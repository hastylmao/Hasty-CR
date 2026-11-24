"""Self-play reinforcement learning in RoyaleSim, starting from imitation.

Everything up to now copied pros. This lets the Hog model learn from its own
results: it plays full RoyaleSim battles under the live configuration (21-tick
command delay, decisions on a board rebuilt from public information and run
21 ticks ahead) against a frozen reactive opponent playing the real
opponents' decks from IL_Replay's train split, and is pushed toward the
decisions of the battles it won.

Two halves, because the engine and the GPU live in different environments:

  collect  (.venvs/royalegym, CPU, engine)  - N battles -> one .npz of decisions
  train    (.venvs/buildabot, CUDA)         - one PPO update on that .npz

and a driver that alternates them and evaluates every few iterations:

  .venvs\\royalegym\\Scripts\\python.exe tools\\rs_selfplay.py loop --iters 40

The policy being trained is exactly the one the live bot runs: the gate's
wait / play probabilities with the evaluator's wait correction and its
p_wait ** (DECIDE / 20) cadence, a slot among the affordable cards, and a tile
among the legal ones. Here the slot and tile are SAMPLED (the evaluator takes
the argmax), so the policy can find out what else works; that is what the
log-probabilities below describe.

Update: PPO (clipped ratio) on advantage = result - value, where result is
1 / 0.5 / 0 for win / draw / loss and value is the model's own win head at that
moment, plus a KL penalty to the imitation model so it cannot wander off into
play no pro would recognise. The value head is trained on the results too.

Nothing here touches the emulator or the game.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

RUNS = ROOT / "runs" / "selfplay"
KEYS = ("unit_ids", "unit_feats", "towers", "scalars", "hand", "opp_seen", "opp_last", "opp_last_age")
DECIDE = 10
TOP_TILES = 8          # tiles sampled among the model's best legal ones
EXTRA_TILES = 8        # plus this many random legal tiles from anywhere
EXPLORE = 0.15         # share of the tile choice spread evenly over all candidates
TILE_TEMP = 1.0
# Why the extra tiles: sampling only the model's 8 best legal tiles never once
# tried a pocket Hog after a princess tower fell - the bridge row alone holds
# 16 legal tiles, so all 8 were bridge tiles - and what is never tried cannot
# be learned (2026-10-10).
CANDS = TOP_TILES + EXTRA_TILES


# ----------------------------------------------------------------------------
# collect (royalegym env)
# ----------------------------------------------------------------------------

def _sampling_agent():
    import rs_eval
    import rs_rows as RR

    class SPAgent(rs_eval.RSAgent):
        """RSAgent.act with a sampled slot and tile, recording every decision."""

        def __init__(self, ckpt, seed=0, wait_keep=0.35):
            super().__init__(ckpt, seed=seed, wait_keep=wait_keep)
            self.records = []

        def act(self, battle, state, team, mem, tick, sub, royalesim):
            torch = self.torch
            self._team = team
            view = self.ahead(battle, state)
            row = RR.obs_row(view, team, sub, mem, tick + self.lead, live=self.live)
            b = self.batch(row)
            with torch.no_grad():
                gate, _, value = self.model(b, card_ids=b["hand"][:, 0].clamp(min=0))
            g = gate[0].float().numpy().astype(np.float64)
            g[0] += self.wait_bias
            p = state["players"][team]
            pending_cost = int(p.get("pending_cost", 0) or 0)
            mask = np.ones(5, bool)
            for slot in range(4):
                cost = p["hand_costs"][slot] if slot < len(p["hand_costs"]) else 99
                if (slot >= len(p["hand"]) or p["elixir_milli"] - pending_cost * 1000 < cost * 1000
                        or p["hand"][slot] < 0):
                    mask[1 + slot] = False
            if not mask[1:].any():
                return None
            q = gate_probs(g, mask)
            a = int(self.rng.choice(5, p=q))
            rec = {k: np.asarray(row[k]) for k in KEYS}
            # Rollout storage feeds the checkpoint directly during PPO updates.
            # Store the embedding IDs used for inference, not engine indices.
            rec['unit_ids'] = b['unit_ids'][0].cpu().numpy().astype(np.int16)
            rec.update(next=int(row["next"]), mask=mask, gate_a=a, logq_gate=float(math.log(q[a])),
                       v=float(1 / (1 + math.exp(-float(value[0, 1])))), tile_a=-1, logq_tile=0.0,
                       tile_cands=np.full(CANDS, -1, np.int16), tick=tick)
            if a == 0:
                self.records.append(rec)
                return None
            slot = a - 1
            with torch.no_grad():
                _, tile, _ = self.model(b, card_ids=b["hand"][:, slot])
            logits = tile[0].float().numpy().astype(np.float64)

            def legal_at(t):
                tx, ty = int(t % 18), int(t // 18)
                wx, wy = rs_eval.to_world(tx * 1000 + 500, ty * 1000 + 500, team)
                ok = battle.check_deploy(team, slot, wx * sub, wy * sub) == 0
                return ok, wx, wy

            legal, seen = [], set()
            for t in np.argsort(-logits)[:60]:
                ok, wx, wy = legal_at(t)
                seen.add(int(t))
                if ok:
                    legal.append((int(t), wx, wy))
                    if len(legal) == TOP_TILES:
                        break
            if not legal:
                return None
            for t in self.rng.permutation(len(logits))[:120]:
                if len(legal) == CANDS:
                    break
                if int(t) in seen:
                    continue
                seen.add(int(t))
                ok, wx, wy = legal_at(t)
                if ok:
                    legal.append((int(t), wx, wy))
            pt = tile_probs(np.array([logits[t] for t, _, _ in legal]))
            k = int(self.rng.choice(len(legal), p=pt))
            t, wx, wy = legal[k]
            cands = np.full(CANDS, -1, np.int16)
            cands[:len(legal)] = [c for c, _, _ in legal]
            rec.update(tile_a=k, logq_tile=float(math.log(pt[k])), tile_cands=cands)
            self.records.append(rec)
            return (team, slot, wx * sub, wy * sub)

    return SPAgent


def tile_probs(lg):
    """Tile choice among the candidates: (1 - EXPLORE) x the model's softmax
    + EXPLORE spread evenly, so every candidate keeps a real chance."""
    p = np.exp((lg - lg.max()) / TILE_TEMP)
    p /= p.sum()
    return (1 - EXPLORE) * p + EXPLORE / len(lg)


def gate_probs(g, mask):
    """The live / evaluator gate as a distribution over wait + 4 slots.

    Evaluator: wait with probability p_wait ** (DECIDE / 20), where p_wait is
    the softmax wait share; otherwise play. Here the slot played is drawn in
    proportion to the slot softmax, among affordable slots only.
    """
    g = np.where(mask, g, -1e9)
    pr = np.exp(g - g.max())
    pr /= pr.sum()
    qw = float(pr[0]) ** (DECIDE / 20)
    s = pr[1:].sum()
    q = np.zeros(5)
    q[0] = qw
    q[1:] = (1 - qw) * pr[1:] / max(s, 1e-12)
    q = np.where(mask, q, 0.0)
    return q / q.sum()


def _collect_one(task):
    import rs_eval
    rs_eval.AGENT_CLASS = _sampling_agent()
    out = rs_eval.play(task)
    if not out or not out.get("records"):
        return None
    r = {"win": 1.0, "draw": 0.5, "loss": 0.0}[out["result"]]
    return out["result"], out["crowns"], r, out["records"]


def _curriculum_one(task):
    """Full defensive sequences with a reactive opponent, never rule teachers.

    Boundary-state spawns deliberately oversample pushes and a fallen tower.
    These are simulator stress scenarios, not reconstructed live matches.
    """
    ckpt, opponent_ckpt, seed, delay = task
    import royalesim as rs
    import rs_rows as rr
    import rs_eval
    rng=np.random.default_rng(seed)
    rr._setup()
    b=rs.Battle(card_names=None,slot_of_k=[[0,1,2],[0,1,2]])
    cat=json.loads(b.catalogue_json());ids={c[0]:i for i,c in enumerate(cat)}
    hog=['Cannon','Skeletons','IceSpirits','IceGolemite','Musketeer','Log','Fireball','HogRider']
    target=['MiniPekka','Skeletons','Goblins','Bats','IceSpirits','MinionHorde'][seed%6]
    enemies=[target]+[x for x in ['Giant','Witch','Fireball','Zap','MiniPekka','Goblins','Bats','HogRider'] if x!=target][:7]
    amount=1 if target in ('MiniPekka','MinionHorde') else int(rng.choice([2,3,4]))
    x=int(rng.choice([3500,14500]));sub=rs.SUBTILE_PER_MILLITILE
    spawns=[(1,ids[target],(x+i*200)*sub,(14500+i*150)*sub,-1) for i in range(amount)]
    hp=[[4824,3052,3052],[4824,3052,3052]]
    if seed%3==0:hp[1][1+seed%2]=0
    clock=int(rng.choice([800,2600,4200]));mana=int(rng.choice([2000,4000,8000,10000]))
    # In overtime an unequal crown count would already have ended the match.
    # Post-tower overtime scenarios must therefore start tied on crowns.
    if clock>=3600 and 0 in hp[1][1:]:hp[0][1+(seed+1)%2]=0
    hero=target=='MiniPekka' # alternate base/hero in adjacent seed banks below
    hero=hero and (seed//6)%2==0
    forms=[[0]*8,[2 if c=='MiniPekka' and hero else 0 for c in enemies]]
    b.reset(seed=seed,decks=[[ids[c] for c in hog],[ids[c] for c in enemies]],shuffle=0,
        start_tick=clock-60 if hero else clock,elixir_milli=[mana,8000],tower_hp=hp,
        spawns=[] if hero else spawns,forms=forms)
    b.set_command_delay_ticks(delay,delay)
    if hero:
        # Scenario spawns always make base characters. A real deployment is
        # needed to materialise the hero form and its initial runtime state.
        result=b.step([(1,0,x*sub,17500*sub)],60)
        assert all(rs.DEPLOY_REASONS[r[1]]=='OK' for r in result),result
    agent=_sampling_agent()(ckpt,seed=seed,wait_keep=.25)
    agent.lead=delay;agent.lead_rebuild=True
    opponent=rs_eval.RSAgent(opponent_ckpt,seed=seed+7)
    mem={'seen':{0:set(),1:set()},'last':{0:[],1:[]}}
    initial=json.loads(b.state_json());tick=initial['tick']
    names=json.loads(b.unit_types_json())
    initial_enemies=[e for e in initial['entities'] if e[4]<0 and e[1]==1 and e[7]>0]
    assert initial_enemies,'Stress scenario must contain a living push'
    if hero:assert any(names[e[27]]=='MiniPekkaHero' for e in initial_enemies),'Missing hero form'
    while tick<min(clock+1600,6200):
        state=json.loads(b.state_json())
        if state['game_over']:break
        commands=[]
        for team,a in [(0,agent),(1,opponent)]:
            cmd=a.act(b,state,team,mem,tick,rs.SUBTILE_PER_MILLITILE,rs)
            if cmd:
                card=state['players'][team]['hand'][cmd[1]];commands.append(cmd)
                a.sent=getattr(a,'sent',[])+[(tick+delay,card,cmd[2],cmd[3])]
                mem['seen'][team].add(card+2);mem['last'][team].append((card+2,tick))
        b.step(commands,DECIDE);tick+=DECIDE
    end=json.loads(b.state_json());losses=[]
    for t in (0,1):
        losses.append(sum(initial['players'][t]['tower_hp'])-sum(end['players'][t]['tower_hp']))
    # Dense episode return based on actual damage, bounded for the win head.
    # Training heuristic, not an assertion about live optimal strategy.
    result=.5+.5*np.tanh((losses[1]-losses[0])/3052)
    if end['players'][0]['tower_hp'][0]<=0:result=0.
    elif end['players'][1]['tower_hp'][0]<=0:result=1.
    label='win' if result>.55 else 'loss' if result<.45 else 'draw'
    units=json.loads(b.unit_types_json())
    return label,[0,0],float(result),agent.records,dict(seed=seed,target=target,
        starting_units=[units[e[27]] for e in initial['entities'] if e[4]<0 and e[1]==1],
        clock=clock,mana=mana,fallen_tower=hp[1][1:]==[0,3052] or hp[1][1:]==[3052,0],
        own_damage=losses[0],enemy_damage=losses[1])


def pick_matches(n, seed, split="train"):
    """Hog 2.6 matches from IL_Replay (train split by default), shuffled by seed."""
    import random
    import pyarrow.parquet as pq
    import rs_rows as RR
    from royalesim_redrive import CORPUS, base_key
    _, names, _, _ = RR._setup()
    parts = sorted((CORPUS / "replays").glob("part-*.parquet"))
    rnd = random.Random(seed)
    rnd.shuffle(parts)
    picked = []
    for part in parts:
        rows = pq.read_table(part, columns=["replay_tag", "game_mode", "payload_json"]).to_pylist()
        rnd.shuffle(rows)
        for r in rows:
            if r["game_mode"] not in RR.MODES or RR.split_of(r["replay_tag"]) != split:
                continue
            p = json.loads(r["payload_json"])
            try:
                sides = [frozenset(names.get(base_key(c["card_key"])[0])
                                   for c in p["battle"][s]["players"][0]["deck"]) for s in ("team", "opponent")]
            except (KeyError, IndexError):
                continue
            if any(None in s for s in sides) or RR.HOG26 not in sides or sides[0] == sides[1]:
                continue
            p.setdefault("source", {})["replay_tag"] = r["replay_tag"]
            picked.append(json.dumps(p))
            if len(picked) >= n:
                return picked
    return picked


def collect(args):
    from concurrent.futures import ProcessPoolExecutor
    curriculum_n=round(args.matches*args.curriculum_fraction)
    picked = pick_matches(args.matches-curriculum_n, args.seed) if args.matches>curriculum_n else []
    tasks = [(t, args.ckpt, "agent", args.seed * 1000 + k, args.opponent, args.delay, -args.delay, False, False, False)
             for k, t in enumerate(picked)]
    t0 = time.time()
    recs, results = [], []
    with ProcessPoolExecutor(args.workers) as pool:
        collected=list(pool.map(_collect_one, tasks))
        collected.extend(pool.map(_curriculum_one,[(args.ckpt,args.opponent,args.seed*1000+k,args.delay)
                                                  for k in range(curriculum_n)]))
        for res in collected:
            if res is None:
                continue
            outcome, crowns, r, rows = res[:4]
            results.append(outcome)
            for row in rows:
                row["ret"] = r
                recs.append(row)
    if not recs:raise RuntimeError('No valid simulator rollouts')
    out = {k: np.stack([x[k] for x in recs]) for k in recs[0]}
    np.savez_compressed(args.out, **out)
    w = results.count("win") / max(1, len(results))
    print(json.dumps({"matches": len(results), "decisions": len(recs), "win_rate": round(w, 3),
                      "seconds": round(time.time() - t0)}), flush=True)


# ----------------------------------------------------------------------------
# train (buildabot env, CUDA)
# ----------------------------------------------------------------------------

def train(args):
    import torch
    import torch.nn.functional as F
    from sim.model_tokens import TokenPolicy
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(1)
    if dev == 'cuda':torch.cuda.set_per_process_memory_fraction(.20)

    def load(path):
        blob = torch.load(path, map_location="cpu")
        m = blob["meta"]
        net = TokenPolicy(m["n_cards"], m["n_units"], d=m.get("d", 192),
                          layers=m.get("layers", 4), heads=m.get("heads", 6))
        net.load_state_dict(blob["model"])
        return net.to(dev), blob

    model, blob = load(args.ckpt)
    # No dropout: the probabilities trained on must be the ones the agent
    # sampled from (with dropout on, ratios were off by 4% at learning rate 0).
    model.eval()
    ref, _ = load(args.ref)
    ref.eval()
    wait_bias = math.log(1 / float(args.wait_keep))
    # Materialise once. Repeated NPZ key access re-decompresses the entire
    # rollout at every minibatch, wasting CPU and memory.
    with np.load(args.data) as archive:
        d = {k:archive[k] for k in archive.files}
    n = len(d["gate_a"])
    adv_all = d["ret"] - d["v"]
    adv_all = (adv_all - adv_all.mean()) / (adv_all.std() + 1e-6)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.0)
    stats = []
    expert_paths=sorted(Path(args.expert_data).glob('shard-*.npz')) if args.expert_data else []
    expert=None
    if expert_paths:
        from train_policy_v2 import read_rows, COLS
        from sim.model_tokens import losses as expert_losses
        expert_rng=np.random.default_rng(100)
    for epoch in range(args.epochs):
        perm = np.random.permutation(n)
        for i in range(0, n, args.batch):
            idx = perm[i:i + args.batch]
            b = {k: torch.as_tensor(d[k][idx]).to(dev) for k in KEYS}
            for k in ("unit_ids", "hand", "opp_seen", "opp_last"):
                b[k] = b[k].long()
            b["unit_feats"] = b["unit_feats"].float()
            b["opp_last_age"] = b["opp_last_age"].float()
            b["next"] = torch.as_tensor(d["next"][idx]).long().to(dev)
            mask = torch.as_tensor(d["mask"][idx]).to(dev)
            a = torch.as_tensor(d["gate_a"][idx]).long().to(dev)
            old = torch.as_tensor(d["logq_gate"][idx] + d["logq_tile"][idx]).float().to(dev)
            adv = torch.as_tensor(adv_all[idx]).float().to(dev)
            ret = torch.as_tensor(d["ret"][idx]).float().to(dev)
            hand = b["hand"]
            slot = (a - 1).clamp(min=0)
            card = hand.gather(1, slot[:, None])[:, 0].clamp(min=0)
            gate, tile, value = model(b, card_ids=card)
            with torch.no_grad():
                rgate, rtile, _ = ref(b, card_ids=card)

            def gate_logq(gl):
                gl = gl.float().clone()
                gl[:, 0] = gl[:, 0] + wait_bias
                gl = gl.masked_fill(~mask, -1e9)
                lp = F.log_softmax(gl, 1)
                lw = lp[:, 0] * (DECIDE / 20)                      # log q_wait = log p_wait ** 0.5
                q_play = (1 - lw.exp()).clamp(min=1e-6)
                ls = F.log_softmax(gl[:, 1:], 1)                   # slot share among playable
                lq = torch.cat([lw[:, None], q_play.log()[:, None] + ls], 1)
                return lq

            lq = gate_logq(gate)
            lq_ref = gate_logq(rgate)
            new = lq.gather(1, a[:, None])[:, 0]
            # tile: log-softmax over the recorded legal candidates
            cands = torch.as_tensor(d["tile_cands"][idx]).long().to(dev)
            played = a > 0
            cmask = cands >= 0
            tl = tile.float().gather(1, cands.clamp(min=0)) / TILE_TEMP
            tl = tl.masked_fill(~cmask, -1e9)
            ncand = cmask.float().sum(1, keepdim=True).clamp(min=1)
            ptile = (1 - EXPLORE) * F.softmax(tl, 1) + EXPLORE / ncand
            ltile = ptile.clamp(min=1e-12).log().masked_fill(~cmask, -1e9)
            ta = torch.as_tensor(d["tile_a"][idx]).long().to(dev).clamp(min=0)
            new = new + torch.where(played, ltile.gather(1, ta[:, None])[:, 0], torch.zeros_like(new))
            ratio = (new - old).exp()
            pg = -torch.min(ratio * adv, ratio.clamp(1 - args.clip, 1 + args.clip) * adv).mean()
            # keep near the imitation policy (gate distribution, and tile on plays)
            kl_gate = (lq.exp() * (lq - lq_ref)).sum(1).mean()
            rtl = rtile.float().gather(1, cands.clamp(min=0)).masked_fill(~cmask, -1e9)
            # the reference under the same exploration mixture, or the brake
            # would push against the exploration itself
            pref = (1 - EXPLORE) * F.softmax(rtl / TILE_TEMP, 1) + EXPLORE / ncand
            lref_tile = pref.clamp(min=1e-12).log().masked_fill(~cmask, -1e9)
            kl_tile = ((ltile.exp() * (ltile - lref_tile)).masked_fill(~cmask, 0).sum(1)
                       * played.float()).sum() / played.float().sum().clamp(min=1)
            v_loss = F.binary_cross_entropy_with_logits(value[:, 1].float(), ret)
            loss = pg + args.kl * (kl_gate + kl_tile) + 0.5 * v_loss
            if expert_paths:
                if expert is None or i % (args.batch*20)==0:
                    for _ in range(len(expert_paths)):
                        candidate=read_rows(expert_paths[int(expert_rng.integers(len(expert_paths)))],
                                            'train',expert_rng)
                        if candidate is not None:expert=candidate;break
                if expert is not None:
                    ix=expert_rng.integers(len(expert['act_card']),size=min(16,len(idx)))
                    eb={k:torch.as_tensor(np.ascontiguousarray(expert[k][ix]),device=dev,
                        dtype=torch.long if expert[k].dtype.kind in 'iu' else torch.float32) for k in COLS}
                    il,_=expert_losses(model,eb,beta=0)
                    loss=loss+args.expert_weight*il
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            stats.append((pg.item(), kl_gate.item(), kl_tile.item(), v_loss.item(),
                          (ratio - 1).abs().mean().item()))
    s = np.mean(stats, 0)
    blob["model"] = {k: v.cpu() for k, v in model.state_dict().items()}
    torch.save(blob, args.out)
    print(json.dumps({"rows": n, "pg": round(s[0], 4), "kl_gate": round(s[1], 4),
                      "kl_tile": round(s[2], 4), "value_bce": round(s[3], 4),
                      "ratio_dev": round(s[4], 4)}), flush=True)


# ----------------------------------------------------------------------------
# loop (royalegym env drives both)
# ----------------------------------------------------------------------------

def loop(args):
    run = RUNS / args.name
    run.mkdir(parents=True, exist_ok=True)
    (run / "args.json").write_text(json.dumps(vars(args), default=str))
    rg = ROOT / ".venvs" / "royalegym" / "Scripts" / "python.exe"
    bb = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
    me = str(Path(__file__).resolve())
    # args.json next to each checkpoint so RSAgent reads the right wait_keep
    init_args = Path(args.ref or args.init).with_name("args.json")
    wait_keep = json.loads(init_args.read_text())["wait_keep"] if init_args.exists() else "0.25"
    ckpt = run / "it000.pt"
    if not ckpt.exists():
        import shutil
        shutil.copy(args.init, ckpt)
    (run / "args.json").write_text(json.dumps({**vars(args), "wait_keep": wait_keep}, default=str))
    log = run / "log.jsonl"
    start = max([int(p.stem[2:]) for p in run.glob("it*.pt")])
    for it in range(start, args.iters):
        ckpt = run / f"it{it:03d}.pt"
        data = run / f"it{it:03d}.npz"
        t0 = time.time()
        opponents = args.opponents or [args.opponent]
        selected_opponent = opponents[it % len(opponents)]
        c = subprocess.run([str(rg), me, "collect", "--ckpt", str(ckpt), "--opponent", selected_opponent,
                            "--matches", str(args.matches), "--workers", str(args.workers),
                            "--delay", str(args.delay), "--curriculum-fraction", str(args.curriculum_fraction),
                            "--seed", str(it + 1), "--out", str(data)],
                           capture_output=True, text=True)
        if c.returncode != 0:
            print(c.stderr[-2000:], flush=True)
            return 1
        col = json.loads(c.stdout.strip().splitlines()[-1])
        nxt = run / f"it{it + 1:03d}.pt"
        t = subprocess.run([str(bb), me, "train", "--ckpt", str(ckpt), "--ref", args.ref or args.init,
                            "--data", str(data), "--out", str(nxt), "--lr", str(args.lr),
                            "--kl", str(args.kl), "--batch", str(args.batch),
                            "--expert-data",args.expert_data,"--expert-weight",str(args.expert_weight),
                            "--wait-keep", str(wait_keep)],
                           capture_output=True, text=True)
        if t.returncode != 0:
            print(t.stderr[-2000:], flush=True)
            return 1
        tr = json.loads(t.stdout.strip().splitlines()[-1])
        data.unlink(missing_ok=True)                    # rollouts are cheap to regenerate
        rec = {"iter": it, **{f"collect_{k}": v for k, v in col.items()}, **tr,
               "seconds": round(time.time() - t0)}
        if args.eval_every and (it + 1) % args.eval_every == 0:
            e = subprocess.run([str(rg), str(ROOT / "tools" / "rs_eval.py"), "--ckpt", str(nxt),
                                "--opponent-ckpt", args.eval_opponent, "--matches", str(args.eval_matches),
                                "--workers", str(args.workers), "--delay", str(args.delay), "--lead", str(-args.delay)],
                               capture_output=True, text=True)
            line = [l for l in e.stdout.splitlines() if " wins (" in l]
            rec["eval"] = line[-1] if line else e.stderr[-300:]
        with log.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    c = sp.add_parser("collect")
    c.add_argument("--ckpt", required=True)
    c.add_argument("--opponent", required=True)
    c.add_argument("--matches", type=int, default=48)
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--seed", type=int, default=1)
    c.add_argument("--out", required=True)
    c.add_argument('--delay',type=int,default=26)
    c.add_argument('--curriculum-fraction',type=float,default=0.)
    t = sp.add_parser("train")
    t.add_argument("--ckpt", required=True)
    t.add_argument("--ref", required=True)
    t.add_argument("--data", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--lr", type=float, default=1e-5)
    t.add_argument("--kl", type=float, default=0.05)
    t.add_argument("--clip", type=float, default=0.2)
    t.add_argument("--epochs", type=int, default=2)
    t.add_argument("--batch", type=int, default=256)
    t.add_argument("--wait-keep", default="0.25")
    t.add_argument('--expert-data',default='')
    t.add_argument('--expert-weight',type=float,default=.2)
    lp = sp.add_parser("loop")
    lp.add_argument("--name", default="sp_v1")
    lp.add_argument("--init", default=str(ROOT / "runs" / "tokens" / "rs_big_hog" / "best.pt"))
    lp.add_argument("--ref", default="",
                    help="model the KL brake pulls toward (default: --init). Set it to the "
                         "imitation model when --init is already a self-play checkpoint")
    lp.add_argument("--opponent", default=str(ROOT / "runs" / "tokens" / "rs_big" / "best.pt"),
                    help="frozen reactive opponent playing the real opponent's deck")
    lp.add_argument("--iters", type=int, default=40)
    lp.add_argument("--matches", type=int, default=48)
    lp.add_argument("--workers", type=int, default=4)
    lp.add_argument('--delay',type=int,default=26)
    lp.add_argument('--batch',type=int,default=32)
    lp.add_argument('--opponents',nargs='+',default=None)
    lp.add_argument('--curriculum-fraction',type=float,default=.5)
    lp.add_argument('--expert-data',default='')
    lp.add_argument('--expert-weight',type=float,default=.2)
    lp.add_argument("--lr", type=float, default=1e-5)
    lp.add_argument("--kl", type=float, default=0.05)
    lp.add_argument("--eval-every", type=int, default=5)
    lp.add_argument("--eval-matches", type=int, default=300)
    lp.add_argument("--eval-opponent", default=str(ROOT / "runs" / "tokens" / "rs_bc" / "ep1.pt"),
                    help="the reference every earlier number was measured against")
    args = ap.parse_args()
    return {"collect": collect, "train": train, "loop": loop}[args.cmd](args) or 0


if __name__ == "__main__":
    sys.exit(main())
