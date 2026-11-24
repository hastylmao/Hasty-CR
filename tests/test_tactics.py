import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('tactics',Path(__file__).resolve().parents[1]/'scripts/gamestate/tactics.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)


def state(flying=False,unknown=False):
    ents=[]
    for i in range(8):
        e=[0]*28;e[0]=i;e[1]=1;e[4]=-1;e[5]=3500;e[6]=10000;e[7]=100;e[10]=flying;ents.append(e)
    p={'hand':[0,1,2,3],'hand_costs':[2,4,1,4],'tower_hp':[5000,3000,3000],'tower_max_hp':[5000,3000,3000]}
    s={'entities':ents,'players':[dict(p),dict(p)]}
    if unknown:
        s['entities']=[];s['unknown_units']=[{'uid':1,'team':1,'x':3500,'y':10000,'hp':1800}]
    return s


CAT=[['Log'],['Fireball'],['IceSpirits'],['Musketeer']]


def test_ground_cluster_gets_affordable_splash():
    plan=t.defence_plan(state(),0,1,CAT,set(),2000)
    assert plan['card']=='Log' and plan['count']==8


def test_air_and_unknown_never_assumed_log_targets():
    assert t.defence_plan(state(True),0,1,CAT,set(),4000)['card']=='Fireball'
    assert t.defence_plan(state(unknown=True),0,1,CAT,set(),4000)['card']=='Musketeer'


def test_affordability_and_pending_slots():
    assert t.defence_plan(state(),0,1,CAT,{0,2},2000) is None
    assert t.defence_plan(state(),0,1,CAT,set(),500) is None


def test_supported_defence_does_not_overspend():
    s=state();e=list(s['entities'][0]);e[0]=99;e[1]=0;e[3]=3;e[7]=3000;s['entities'].append(e)
    assert t.defence_plan(s,0,1,CAT,set(),8000) is None


def test_hog_guard_keeps_king_finish_and_full_towers():
    class Check:
        def check_deploy(self,*args):return 0
    s=state();order=list(range(576))
    assert t.hog_order(order,s,0,1,0,Check())[1] is None
    s['players'][1]['tower_hp']=[500,0,3000]
    assert t.hog_order(order,s,0,1,0,Check())[1] is None


def test_hog_considers_surviving_tower_and_legal_pocket():
    class Check:
        def check_deploy(self,team,slot,x,y):return 0 if x<9000 and y>18000 else 1
    s=state();s['players'][1]['tower_hp']=[5000,0,3000]
    order,reason=t.hog_order(list(range(576)),s,0,1,0,Check())
    assert reason=='surviving-princess'
    x,y=(order[0]%18)*1000+500,(order[0]//18)*1000+500
    assert Check().check_deploy(0,0,x,32000-y)==0
    assert y<16000


def test_fireball_keeps_nearby_forward_aim_not_wrong_lane():
    plan={'tiles':[(3,21)],'card':'Fireball','centre':(3500,21500)}
    assert t.defence_order(plan,[24*18+3])[0]==24*18+3
    assert t.defence_order(plan,[24*18+14])[0]==21*18+3


def test_ground_only_defender_does_not_cover_air_swarm():
    s=state(True);e=list(s['entities'][0]);e[0]=99;e[1]=0;e[3]=0;e[7]=3000
    s['entities'].append(e)
    assert t.defence_plan(s,0,1,CAT,set(),4000) is not None
