"""Tower damage trace of one card played alone at the bridge.
    unit_hits.py <Card> <form 0|1|2> [level]     (form 1 evolution, 2 hero)"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import realsim

card, form = sys.argv[1], int(sys.argv[2])
lvl = int(sys.argv[3]) if len(sys.argv) > 3 else 11
b = realsim.RealBattle()
names = {r[0]: i for i, r in enumerate(b.cat)}
base = ["HogRider", "Musketeer", "IceGolemite", "IceSpirits", "Skeletons", "Cannon", "Fireball", "Log"]
d = [names[card]] + [names[n] for n in base if n != card][:7]
b.reset(seed=3, decks=[d, d], shuffle=0, forms=[[form] + [0] * 7, [0] * 8], levels=[[lvl] * 8, [lvl] * 8],
        tower_levels=[lvl, lvl])
b.step([], 100)
json.loads(b.state_json())
row = b.step([(0, 0, 3500 * realsim.SUB, 14500 * realsim.SUB)], 1)[0]
trace, last, units = [], None, set()
for _ in range(900):
    b.step([], 1)
    s = json.loads(b.state_json())
    units |= {(o[0], o[4]) for o in b.s["objects"] if o[1] == 0 and "Tower" not in o[0]}
    hp = s["players"][1]["tower_hp"]
    if last is not None and hp != last:
        trace.append([b.eng.t, [a - c for a, c in zip(last, hp)]])
    last = hp
print(json.dumps({"card": card, "form": form, "level": lvl, "deploy_code": row[1], "hits": len(trace),
                  "trace": trace[:12], "tower_hp_end": last, "units_max_hp": sorted({(n, h) for n, h in units})[-4:]}))
