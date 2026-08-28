"""Does the missing next-card one-hot explain the live collapse?

The live bridge left the last eight scalars at zero for every match while the
simulator always set one. If that is what made a 94% policy play like a
spammer against a person, then blanking the same eight scalars *in the
simulator* should reproduce it - same weights, same opponents, same seeds,
one input removed.

Run it both ways and compare. This is cheaper than another human match and it
answers the question the human match would.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sim.env as env_mod                                        # noqa: E402
from sim.env import DECK_26, NUM_SLOTS                           # noqa: E402

TAIL = 3 + 4 + NUM_SLOTS * len(DECK_26)          # where the next-card one-hot starts


def blank_next_card():
    """Wrap sim.env.observe so the next-card block is always zero."""
    original = env_mod.observe

    def patched(match, side: int = 1):
        out = original(match, side)
        out["scalars"][TAIL:] = 0.0
        return out

    env_mod.observe = patched
    return original


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ckpt", required=True, type=Path)
    ap.add_argument("--episodes", type=int, default=60)
    ap.add_argument("--seed", type=int, default=8000)
    ap.add_argument("--opponents", nargs="+", default=["brain", "meta", "mirror"])
    args = ap.parse_args()

    from scripts.evaluate_pilot import evaluate_one

    for label, ablate in (("intact", False), ("next-card blanked", True)):
        if ablate:
            blank_next_card()
        print(f"\n=== {label} ===")
        for opp in args.opponents:
            r = evaluate_one(args.ckpt, opp, args.episodes, args.seed)
            print(f"  vs {opp:7s} win={r['win_rate']:6.1%}  "
                  f"hog={r['hog_share']:.0%}  plays={r['plays_per_match']:.0f}  "
                  f"crown={r['crown_diff']:+.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
