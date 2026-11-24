"""Control: an unblocked Hog Rider (level 11) against a level 11 princess tower lands
seven hits (CLAUDE.md, "Measure before concluding"). Run with and without
HASTY_ASSET_ROOT to check that a changed asset tree leaves this untouched.
    .venvs\buildabot\Scripts\python.exe tools/league/controls/hog_hits.py"""
import json
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import realsim

b = realsim.RealBattle()
names = {r[0]: i for i, r in enumerate(b.cat)}
d = [names[n] for n in ["HogRider", "Musketeer", "IceGolemite", "IceSpirits", "Skeletons", "Cannon", "Fireball", "Log"]]
b.reset(seed=3, decks=[d, d], shuffle=0)
b.step([], 100)
json.loads(b.state_json())
row = b.step([(0, 0, 3500 * realsim.SUB, 14500 * realsim.SUB)], 1)[0]
hits, trace, last = 0, [], None
for _ in range(700):
    b.step([], 1)
    s = json.loads(b.state_json())
    hp = s["players"][1]["tower_hp"]
    if last is not None and hp != last:
        hits += 1
        trace.append([b.eng.t, [a - c for a, c in zip(last, hp)]])
    last = hp
print(json.dumps({"deploy_code": row[1], "hits": hits, "trace": trace, "asset_root": os.environ.get("HASTY_ASSET_ROOT", "default")}))
