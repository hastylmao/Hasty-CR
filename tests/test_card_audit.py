import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('card_audit',
    Path(__file__).resolve().parents[1]/'scripts/gamestate/card_audit.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def audit(path,expected=''):
    return module.CardAudit(path,[['Skeletons'],['Log']],['Skeleton'],
                            {'1':{'rs_id':0},'2':{'rs_id':1}},lambda n,c:-1,expected)


def unit(addr,name='Skeleton',card=1,hp=100):
    return [addr,0,0,0,1000,1000,card,11,hp,hp,name]


def test_persists_and_deduplicates_across_restarts(tmp_path):
    path=tmp_path/'coverage.json'
    a=audit(path,'Skeletons,Log')
    f={'t':10,'u':[unit(1),unit(2)]}
    a.observe(f,1,{'entities':[[1],[2]]})
    assert len(a.data['observations'])==1
    contents=path.read_bytes()
    a.observe(f,1,{'entities':[[1],[2]]})
    assert path.read_bytes()==contents
    b=audit(path)
    assert len(b.data['observations'])==1
    assert b.data['expected']==['Skeletons','Log']
    assert 'Log' in path.with_suffix('.txt').read_text()


def test_distinguishes_unknown_body_from_effect(tmp_path):
    a=audit(tmp_path/'coverage.json')
    a.observe({'t':1,'u':[unit(1,'NewHero',99),unit(2,'LogProjectile',2,0)]},1,{'entities':[]})
    stages={r['unit']:r['stage'] for r in a.data['observations'].values()}
    assert stages=={'NewHero':'dropped','LogProjectile':'effect'}
    assert 'UNKNOWN / NewHero' in a.path.with_suffix('.txt').read_text()


def test_model_records_enemy_only_and_once(tmp_path):
    a=audit(tmp_path/'coverage.json')
    row={'unit_ids':[2,2,3,0],'unit_feats':[[0],[0],[1],[0]]}
    a.model(row,True,1)
    a.model(row,True,2)
    records=list(json.loads(a.path.read_text())['observations'].values())
    assert len(records)==1
    assert records[0]['card']=='Skeletons'
