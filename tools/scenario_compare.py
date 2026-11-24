"""Play the same fixed scenarios in RoyaleSim and in the real engine (realsim)
and compare what happens: tower hitpoints over time and which units are alive.

Each scenario places units with `spawns` at reset (free, no hand), then lets the
battle run with no further plays. Both sides use the same deck and levels, so
any difference comes from the simulation itself.

    .venvs/buildabot/Scripts/python.exe tools/scenario_compare.py [--only NAME]

A third column (the engine inside the game on MuMu instance 7, FirstLight) can
be added once that instance is running.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "league"))
import royalesim  # noqa: E402
import realsim  # noqa: E402

SUB = royalesim.SUBTILE_PER_MILLITILE
DECK = ["Knight", "Archer", "Goblins", "Giant", "Musketeer", "Fireball", "Arrows", "Cannon"]
START = 200          # after the start delay
TICKS = 700          # 35 s per scenario
EVERY = 50           # sample every 2.5 s

# (team, card, x, y) in game units; team 0 is at the bottom (y < 16000)
SCENARIOS = {
    "hog_alone": [(0, "HogRider", 14500, 15000)],
    "giant_alone": [(0, "Giant", 14500, 14000)],
    "golem_alone": [(0, "Golem", 14500, 13000)],
    "knight_vs_knight": [(0, "Knight", 14500, 13000), (1, "Knight", 14500, 19000)],
    "hog_vs_cannon": [(0, "HogRider", 14500, 15000), (1, "Cannon", 9500, 22500)],
    "musketeer_vs_giant": [(0, "Giant", 14500, 14000), (1, "Musketeer", 14500, 24000)],
    "minipekka_vs_hog": [(0, "HogRider", 14500, 15000), (1, "MiniPekka", 14500, 23000)],
    "skarmy_vs_knight": [(0, "Knight", 3500, 14000), (1, "SkeletonArmy", 3500, 20000)],
    "balloon_alone": [(0, "Balloon", 14500, 14000)],
    "valk_vs_barbs": [(0, "Valkyrie", 3500, 13000), (1, "Barbarians", 3500, 19000)],
}


def run(battle, ids, spawns, levels):
    battle.set_command_delay_ticks(26, 26)
    battle.reset(seed=1, decks=[[ids[c] for c in DECK]] * 2, shuffle=0, start_tick=START,
                 elixir_milli=[0, 0], tower_hp=None,
                 spawns=[(t, ids[c], x * SUB, y * SUB, -1) for t, c, x, y in spawns],
                 forms=[[0] * 8, [0] * 8], levels=[[levels] * 8] * 2, tower_levels=[levels, levels])
    names = json.loads(battle.unit_types_json())
    out = []
    for _ in range(TICKS // EVERY):
        battle.step([], EVERY)
        s = json.loads(battle.state_json())
        units = sorted(f"{e[1]}:{names[e[27]] if 0 <= e[27] < len(names) else '?'}"
                       for e in s["entities"] if e[4] < 0 and e[7] > 0)
        out.append((s["tick"], [p["tower_hp"] for p in s["players"]], units))
        if s["game_over"]:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--level", type=int, default=11)
    a = ap.parse_args()
    rs = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    cat = json.loads(rs.catalogue_json())
    ids = {row[0]: i for i, row in enumerate(cat)}
    real = realsim.RealBattle()
    report = {}
    for name, spawns in SCENARIOS.items():
        if a.only and name != a.only:
            continue
        missing = [c for _, c, _, _ in spawns if c not in ids]
        if missing:
            print(f"{name}: skipped, not in catalogue: {missing}")
            continue
        r1 = run(rs, ids, spawns, a.level)
        r2 = run(real, ids, spawns, a.level)
        print(f"\n== {name}")
        print(f"{'tick':>5}  {'RoyaleSim towers (ours | theirs)':40s}  {'real engine towers':40s}")
        for (t, h1, u1), (_, h2, u2) in zip(r1, r2):
            mark = "" if h1 == h2 else "  <-"
            print(f"{t:5d}  {str(h1):40s}  {str(h2):40s}{mark}")
        end1, end2 = r1[-1], r2[-1]
        print(f"  units at end  RoyaleSim: {end1[2]}")
        print(f"                real:      {end2[2]}")
        dmg = lambda r: [sum(r[0][1][s]) - sum(r[-1][1][s]) for s in (0, 1)]
        report[name] = {"royalesim_damage": dmg(r1), "real_damage": dmg(r2)}
    real.close()
    print("\nTower damage taken over the scenario [team 0, team 1]:")
    for name, d in report.items():
        print(f"  {name:20s} RoyaleSim {d['royalesim_damage']}   real {d['real_damage']}")
    out = ROOT / "reports" / "scenario_compare.json"
    out.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
