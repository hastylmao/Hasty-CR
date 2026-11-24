"""Run with the royalegym interpreter; no emulator or taps required."""
import json
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts'),str(ROOT/'tools')]
import rs_rows as RR
from rs_eval import RSAgent,_unit_names
from gamestate.live_bridge import rs_state_from_frame


class UpgradeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rs,_,_,cls.cat=RR._setup()
        cls.names=_unit_names()
        cls.agent=RSAgent(str(ROOT/'runs/selfplay/sp_v1/it020.pt'))
        cls.meta=cls.agent.torch.load(ROOT/'runs/selfplay/sp_v1/it020.pt',map_location='cpu')['meta']

    def frame(self,name,native):
        towers=[]
        for side,y in [(1,3000),(0,29000)]:
            towers.append([len(towers)+1,0,0,side,9000,y,0,11,5000,5000,'KingTower'])
        u=[123,0,0,0,4500,18000,native,11,896,1200,name]
        return {'t':444,'u':towers+[u],'me':[1,50000,[0,1,2,3],[4,5,6,7]]}

    def state(self,name,native):
        s=rs_state_from_frame(self.frame(name,native),1,list(range(8)),self.names,self.cat,self.rs.SUBTILE_PER_MILLITILE)
        s['players'][1]['deck']=list(range(8))
        return s

    def test_every_checkpoint_unit_keeps_embedding_identity(self):
        for name,token in self.meta['units'].items():
            self.assertEqual(int(self.agent.unit_token_map[self.names.index(name)+2]),token,name)

    def test_supported_ability_units_reach_model_with_real_hp(self):
        cases=[('MusketeerTurret',203000014,'MusketeerTurret'),
               ('TombstoneHero_Monster_Active',203000088,'TombstoneHero_Monster_Active'),
               ('TombstoneHero_Monster_Passive',203000088,'TombstoneHero_Monster_Passive'),
               ('TombstoneHeroSkeleton',203000088,'Skeleton'),
               ('BerserkerHero_BearForm',203000076,'BerserkerHero'),
               ('IceWizardHero',203000023,'IceWizard')]
        for name,native,canonical in cases:
            with self.subTest(name=name):
                s=self.state(name,native)
                self.assertEqual(len(s['entities']),1)
                self.assertEqual(s['entities'][0][7:9],[896,1200])
                row=RR.obs_row(s,0,self.rs.SUBTILE_PER_MILLITILE,
                    {'seen':{0:set(),1:set()},'last':{0:[],1:[]}},444,live=False)
                b=self.agent.batch(row)
                self.assertIn(self.meta['units'][canonical],b['unit_ids'].tolist()[0])
                with self.agent.torch.no_grad():
                    self.agent.model(b,card_ids=b['hand'][:,0].clamp(min=0))
                self.agent.lead_rebuild=True
                self.assertIs(self.agent.ahead(None,s),s)

    def test_normal_board_rebuild_and_prediction(self):
        s=self.state('Ronin',26000106)
        self.agent._team=0;self.agent.lead=26;self.agent.sent=[]
        self.agent.lead_rebuild=True
        rebuilt=self.agent.rebuilt(s,0,self.rs)
        self.assertIsNotNone(rebuilt)
        living=[e for e in json.loads(rebuilt.state_json())['entities'] if e[4]<0 and e[7]>0]
        self.assertEqual(len(living),1)
        self.assertEqual(self.names[living[0][27]],'Ronin')
        future=self.agent.ahead(None,s)
        self.assertEqual(future['tick'],470)
        self.assertEqual(future['players'][0]['tower_max_hp'],s['players'][0]['tower_max_hp'])

    def test_towers_are_buildings_not_crown_towers(self):
        for name,native in [('BombTower',27000004),('InfernoTower',27000003)]:
            s=self.state(name,native)
            self.assertEqual(len(s['entities']),1)
            self.assertEqual(s['entities'][0][2],1)
            self.assertEqual(s['players'][1]['tower_hp'][0],5000)

    def test_crowded_board_reserves_enemy_and_defender_tokens(self):
        s=self.state('Skeleton',26000010)
        prototype=s['entities'][0]
        s['entities']=[]
        for i in range(96):
            e=list(prototype);e[0]=1000+i;e[1]=0 if i<48 else 1
            e[5]=3500*self.rs.SUBTILE_PER_MILLITILE
            e[6]=(5000 if i<48 else 15000)*self.rs.SUBTILE_PER_MILLITILE
            s['entities'].append(e)
        row=RR.obs_row(s,0,self.rs.SUBTILE_PER_MILLITILE,
            {'seen':{0:set(),1:set()},'last':{0:[],1:[]}},444,live=False)
        valid=row['unit_ids']>0;friendly=row['unit_feats'][:,0]>.5
        self.assertEqual(int(valid.sum()),48)
        self.assertGreaterEqual(int((valid & ~friendly).sum()),24)
        self.assertGreaterEqual(int((valid & friendly).sum()),12)

    def test_all_supported_crown_types_stay_out_of_troop_tokens(self):
        for name in ['Cannoneer','DaggerDuchess','ChefTower']:
            f=self.frame(name,159000001)
            f['u'][-1][4:6]=[3500,25500]
            f['u'][-1][8:10]=[2000,3000]
            s=rs_state_from_frame(f,1,list(range(8)),self.names,self.cat,self.rs.SUBTILE_PER_MILLITILE)
            self.assertFalse(s['entities'])
            self.assertEqual(s['players'][1]['tower_hp'][1],2000)


if __name__=='__main__':
    unittest.main()
