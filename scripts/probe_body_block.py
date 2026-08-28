"""How much does a body block at the bridge actually cost a Hog Rider?

Measured live on 2026-08-28 (tmp/live/studio/clip_20260828_152245.mp4): a Hog
placed at the bridge, with Skeletons dropped in its path about half a second
later, still landed TWO HITS on the tower.

The simulator's body-block cost is not measured - it is a constant somebody
chose - so this replays the same scenario and counts hits. If the simulator
gives fewer than two, cheap bodies are stronger here than in the real game,
and a policy trained in it will correctly learn to spam them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import arena                                            # noqa: E402
from sim.engine import Battle                                    # noqa: E402
from sim.entities import make_tower, make_unit                   # noqa: E402
from sim.gamedata import load_gamedata                           # noqa: E402

CARDS = load_gamedata(level=11)
PRINCESS = (3052, 109, 800, 7500)


def run(delay_s: float, block: str = "skeletons", verbose: bool = False):
    battle = Battle()
    towers = {}
    for lane in ("left", "right"):
        towers[lane] = battle.add(
            make_tower(0, -1, arena.ENEMY_PRINCESS[lane], *PRINCESS)).uid
    king_tower = battle.add(make_tower(0, -1, arena.ENEMY_KING, *PRINCESS,
                                       king=True))
    # make_tower hardcodes target_only_buildings=False, so a king built
    # directly is AWAKE. sim/match.py:190 puts it to sleep at match setup and
    # the engine wakes it when a princess falls or it is damaged. Without this
    # the probe had two towers shooting the hog from the first tick, which
    # killed it after four hits where a real one survives seven.
    king_tower.target_only_buildings = True

    # Hog at the right bridge, the placement the live policy actually makes.
    hog = battle.add(make_unit(0, CARDS["hog_rider"].unit, 1, arena.tile(14, 17)))
    # Deploy time is NOT zeroed. A live card takes ~1s to become active and
    # zeroing it here made the sim's hog arrive a second early, which is a
    # whole hit at a 1.6s hit speed - the exact size of the gap being chased.

    dropped = False
    hits = 0
    first_hit_s = None
    before = battle.entities[towers["right"]].hitpoints
    for tick in range(20 * 60):
        now_s = tick * 0.05
        if not dropped and now_s >= delay_s:
            dropped = True
            card = CARDS[block]
            spec = card.unit
            # The field is summon_number, not summon_count. getattr with a
            # default silently returned 1, so this probe spent three attempts
            # measuring a single Skeleton against a Hog and calling it a body
            # block. A default that cannot be right is worse than a KeyError.
            count = card.summon_number or 1
            offsets = ((0, 0), (1, 0), (0, 1), (1, 1), (2, 0))
            for i in range(count):
                dx, dy = offsets[i % len(offsets)]
                battle.add(make_unit(0, spec, -1, arena.tile(14 + dx, 16 - dy)))
        battle.step()
        tower = battle.entities[towers["right"]]
        if tower.hitpoints < before:
            hits += 1
            if first_hit_s is None:
                first_hit_s = now_s
            before = tower.hitpoints
        if not hog.alive:
            break
    return hits, first_hit_s, hog.alive


def _when(seconds):
    """A hog that never arrives has no first hit, and formatting None throws."""
    return "never" if seconds is None else f"{seconds:.2f}s"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--block", default="skeletons")
    args = ap.parse_args()

    print(f"Live result to match: Hog + {args.block} 0.5s later, both at the "
          f"bridge -> 2 hits on the tower\n")
    for delay in (0.0, 0.25, 0.5, 1.0, 2.0, None):
        if delay is None:
            hits, first, alive = run(9999.0, args.block)
            print(f"  no block at all        -> {hits} hits, "
                  f"first at {_when(first)}")
            continue
        hits, first, alive = run(delay, args.block)
        print(f"  block {delay:>4.2f}s after hog  -> {hits} hits, "
              f"first at {_when(first)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
