"""Bounded-memory, resumable local replay rebuild and staged imitation.

No emulator access. Each source parquet batch is committed independently.
The existing match hash split is retained; unsupported ability events cut trust.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import time
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
DATA = ROOT / 'data/policy_v2'
RUN = ROOT / 'runs/policy_v2'
COLS = ('unit_ids','unit_feats','towers','scalars','hand','next','opp_seen',
        'opp_last','opp_last_age','outcome','won','act_card','act_x','act_y')


def save_json(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2), encoding='utf-8')
    tmp.replace(path)


def rebuild(args):
    import pyarrow.parquet as pq
    import rs_rows as rr
    ctx = rr._setup(); rs, names, _, cat = ctx
    DATA.mkdir(parents=True, exist_ok=True)
    units = json.loads(rs.Battle(card_names=None,slot_of_k=[[0,1,2],[0,1,2]]).unit_types_json())
    save_json(DATA/'vocab.json',dict(n_cards=len(cat)+2,n_units=len(units)+2,
        cards={r[0]:i+2 for i,r in enumerate(cat)},units={n:i+2 for i,n in enumerate(units)},
        engine='royalesim',version=getattr(rs,'__version__','?'),memory_observation=True))
    from royalesim_redrive import CORPUS, base_key
    assert CORPUS.resolve().is_relative_to(ROOT.resolve()), 'Only repository replays are authorised'
    done = json.loads((DATA/'progress.json').read_text()) if (DATA/'progress.json').exists() else {}
    processed = 0
    for part in sorted((CORPUS/'replays').glob('part-*.parquet')):
        for batch_id, batch in enumerate(pq.ParquetFile(part).iter_batches(batch_size=20,
                         columns=['replay_tag','game_mode','payload_json'])):
            key=f'{part.stem}-{batch_id:04d}'
            if key in done: continue
            if shutil.disk_usage(ROOT).free < 4*1024**3:
                raise RuntimeError('Less than 4 GiB disk free; stopped safely. Resume after freeing space.')
            rows=[]; rejected={}; counts={'source':len(batch),'accepted':0,'rows':0,'trusted':0,'hog':0}
            for r in batch.to_pylist():
                try:
                    if r['game_mode'] not in rr.MODES: raise ValueError('mode')
                    p=json.loads(r['payload_json']); tag=r['replay_tag']
                    p.setdefault('source',{})['replay_tag']=tag
                    for side in ('team','opponent'):
                        players=p['battle'][side]['players']
                        if len(players)!=1: raise ValueError('not 1v1')
                        if any(names.get(base_key(c['card_key'])[0]) is None for c in players[0]['deck']):
                            raise ValueError('unmapped card')
                    built, why=rr.rows_for(p,ctx)
                    if not built: raise ValueError(why)
                    # The redrive currently ignores ability commands. Never label
                    # its later board as an expert's trustworthy observation.
                    ability=min((int(e['replay_tick_20hz']) for e in p['events']
                        if 'ability' in e['kind'].lower()),default=10**9)
                    for row in built:
                        row['trusted'] &= row['tick']+rr.HORIZON < ability
                        row['unit_feats'][:,6]=0 # memory cannot observe deploy timers
                        row['match']=tag;row['split']=rr.split_of(tag)
                        a=row['action'];row['act_card'],row['act_x'],row['act_y']=a
                    counts['accepted']+=1;counts['rows']+=len(built)
                    counts['trusted']+=sum(bool(x['trusted']) for x in built)
                    counts['hog']+=sum(bool(x['trusted'] and x['hog']) for x in built)
                    rows.extend(built)
                except Exception as exc:
                    why=str(exc);rejected[why]=rejected.get(why,0)+1
            path=DATA/f'shard-{key}.npz'
            if rows:
                fields=COLS+('tick','trusted','hog','match','split')
                values={k:np.stack([np.asarray(r[k]) for r in rows]) for k in fields}
                tmp=path.with_suffix('.tmp.npz');np.savez_compressed(tmp,**values);tmp.replace(path)
            done[key]={**counts,'rejected':rejected}
            save_json(DATA/'progress.json',done)
            processed+=1
            if processed%10==0: print(json.dumps({'stage':'rebuild','batches':len(done),
                'source_replays':sum(v['source'] for v in done.values()),
                'trusted_rows':sum(v['trusted'] for v in done.values())}),flush=True)
            if args.limit_batches and processed>=args.limit_batches:return


def read_rows(path, split, rng, wait_keep=.25):
    with np.load(path) as z:
        mask=(z['split']==split)&z['trusted']
        act=z['act_card'];mask &= (act!=0)|(rng.random(len(act))<wait_keep)
        if not mask.any():return None
        return {k:z[k][mask] for k in COLS+('hog',)}


def initialise(torch, meta, path, device):
    from sim.model_tokens import TokenPolicy
    blob=torch.load(path,map_location='cpu',weights_only=False)
    old=blob['meta'];meta={**meta,**{k:old[k] for k in ('d','layers','heads')}}
    model=TokenPolicy(meta['n_cards'],meta['n_units'],d=meta['d'],layers=meta['layers'],heads=meta['heads'])
    weights=model.state_dict()
    for key,v in blob['model'].items():
        if key in ('card_emb.weight','unit_emb.weight'):
            names='cards' if key.startswith('card') else 'units'
            weights[key][:2]=v[:2]
            for name,idx in meta[names].items():
                if name in old[names]:weights[key][idx]=v[old[names][name]]
        else:weights[key]=v
    model.load_state_dict(weights)
    return model.to(device),meta


def row_batches(data, size, rng, hog=False, balance=False):
    from sim.train_tokens import phase_of
    n=len(data['act_card']); indices=np.arange(n)
    if hog:
        hi=indices[data['hog']];gi=indices[~data['hog']]
        if not len(hi):return
        n=max(size,len(hi))
        indices=np.concatenate([rng.choice(hi,int(n*.8),replace=True),
            rng.choice(gi if len(gi) else hi,n-int(n*.8),replace=True)])
    if balance:
        ph=phase_of(data)[indices];counts=np.bincount(ph,minlength=12)
        weight=np.minimum(20,np.sqrt(len(ph)/np.maximum(counts[ph],1)))
        indices=rng.choice(indices,len(indices),replace=True,p=weight/weight.sum())
    else:rng.shuffle(indices)
    for start in range(0,len(indices),size):
        ix=indices[start:start+size]
        yield {k:np.ascontiguousarray(data[k][ix]) for k in COLS}


def train(args):
    import torch
    from sim.model_tokens import losses
    torch.set_num_threads(1);torch.manual_seed(20261012)
    dev='cuda' if torch.cuda.is_available() else 'cpu'
    if dev=='cuda':torch.cuda.set_per_process_memory_fraction(.20)
    folder=RUN/args.stage;folder.mkdir(parents=True,exist_ok=True)
    meta=json.loads((DATA/'vocab.json').read_text())
    model,meta=initialise(torch,meta,args.init,dev)
    opt=torch.optim.AdamW(model.parameters(),lr=args.lr)
    paths=sorted(DATA.glob('shard-*.npz'));assert paths,'No rebuilt rows'
    rng=np.random.default_rng(20261012);best=float('inf');start=0
    resume=folder/'resume.pt'
    if resume.exists():
        b=torch.load(resume,map_location='cpu',weights_only=False)
        model.load_state_dict(b['model']);opt.load_state_dict(b['optimizer'])
        start=b['epoch']+1;best=b['best'];rng.bit_generator.state=b['rng']
    save_json(folder/'args.json',dict(wait_keep=.25,stage=args.stage,lr=args.lr,
        epochs=args.epochs,seed=20261012,data=str(DATA),init=str(args.init),delay=26,
        tactical_guards=False,expert_mix=.2 if args.stage=='hog' else 0))
    def tensor(b):
        return {k:torch.as_tensor(v,dtype=torch.long if v.dtype.kind in 'iu' else torch.float32,device=dev)
                for k,v in b.items()}
    def checkpoint(value,path):
        tmp=path.with_suffix('.tmp.pt');torch.save(value,tmp);tmp.replace(path)
    def evaluate():
        model.eval();total={};count=0;vrng=np.random.default_rng(11)
        with torch.no_grad():
            for path in paths:
                data=read_rows(path,'val',vrng)
                if data is None:continue
                if args.stage=='hog':data={k:v[data['hog']] for k,v in data.items()}
                if not len(data['act_card']):continue
                for b in row_batches(data,args.batch,vrng):
                    with torch.autocast(dev,dtype=torch.bfloat16,enabled=dev=='cuda'):
                        loss,stats=losses(model,tensor(b),beta=0)
                    n=len(b['act_card']);count+=n
                    for k,v in {'loss':float(loss),**stats}.items():total[k]=total.get(k,0)+v*n
        assert count,'No held-out validation rows'
        return dict(rows=count,**{k:v/count for k,v in total.items()})
    if start==0:
        save_json(folder/'baseline.json',evaluate())
    for epoch in range(start,args.epochs):
        model.train();order=rng.permutation(len(paths));steps=0;total=0;nrows=0;t=time.time()
        for j in order:
            data=read_rows(paths[j],'train',rng)
            if data is None:continue
            for b in row_batches(data,args.batch,rng,hog=args.stage=='hog',balance=True):
                with torch.autocast(dev,dtype=torch.bfloat16,enabled=dev=='cuda'):
                    loss,_=losses(model,tensor(b),beta=0)
                opt.zero_grad(set_to_none=True);loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(),1);opt.step()
                steps+=1;n=len(b['act_card']);total+=float(loss)*n;nrows+=n
                if steps%500==0:print(json.dumps(dict(stage=args.stage,epoch=epoch,steps=steps,
                    rows=nrows,loss=total/nrows,seconds=round(time.time()-t))),flush=True)
        metrics=evaluate();score=metrics['loss'];improved=score<best;best=min(best,score)
        blob=dict(model={k:v.detach().cpu() for k,v in model.state_dict().items()},meta=meta,epoch=epoch)
        checkpoint(blob,folder/'last.pt')
        if improved:checkpoint(blob,folder/'best.pt')
        checkpoint(dict(**blob,optimizer=opt.state_dict(),best=best,rng=rng.bit_generator.state),resume)
        rec=dict(stage=args.stage,epoch=epoch,train_rows=nrows,validation=metrics,seconds=time.time()-t)
        with (folder/'log.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
        print(json.dumps(rec),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['rebuild','train'])
    p.add_argument('--limit-batches',type=int,default=0)
    p.add_argument('--stage',choices=['general','hog'],default='general')
    p.add_argument('--init',type=Path,default=ROOT/'runs/tokens/rs_big/best.pt')
    p.add_argument('--epochs',type=int,default=2);p.add_argument('--batch',type=int,default=32)
    p.add_argument('--lr',type=float,default=1e-5)
    a=p.parse_args();return rebuild(a) if a.mode=='rebuild' else train(a)


if __name__=='__main__':main()
