"""Compare two policy configs without the seat deciding the answer.

`play_match` takes a config per side so a variant can play the baseline, and
the win rate is supposed to be the answer. It is not, on its own: the seat is
worth about ten points. Measured on 2026-08-20, `BrainPolicy` against itself -
same config, same deck, on a board that is provably symmetric - takes 60.5% of
decided matches from the bottom seat over 400 matches (z=+3.69). A variant put
on the bottom seat starts ten points ahead of nothing.

So every match is played twice, once with the variant on each seat, over the
same seeds. Averaging the two arms cancels the seat exactly, and the gap
between the arms tells you how large the seat effect was in this pairing, which
is worth seeing rather than hiding.

    python scripts/ab_eval.py --variant brain/config_variant.json
    python scripts/ab_eval.py --variant a.json --baseline b.json --matches 200

A result inside about two standard errors is not a result. With 200 matches per
arm that is roughly five points, which is larger than most config changes are
worth - so a null here usually means "measure more", not "no difference".
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.gamedata import load_gamedata                          # noqa: E402
from sim.runner import DECK_26, play_match, resolve_deck        # noqa: E402
from sim.spells import load_spells                              # noqa: E402


def _arm(cards, spells, matches: int, variant, baseline, variant_on_bottom: bool):
    """Play one arm and return (variant wins, baseline wins, draws)."""
    wins = losses = draws = 0
    for seed in range(matches):
        bottom = variant if variant_on_bottom else baseline
        top = baseline if variant_on_bottom else variant
        match, _, _ = play_match(cards, seed=seed, spells=spells,
                                 opponent="brain",
                                 bottom_config=bottom, top_config=top)
        result = match.result
        if result == "draw" or result is None:
            draws += 1
        elif (result == "bottom") == variant_on_bottom:
            wins += 1
        else:
            losses += 1
    return wins, losses, draws


def evaluate(variant, baseline, matches: int, level: int = 11) -> dict:
    cards = resolve_deck(load_gamedata(level=level), DECK_26)
    spells = load_spells(level=level)

    started = time.time()
    bottom_arm = _arm(cards, spells, matches, variant, baseline, True)
    print(f"  variant on bottom: {bottom_arm[0]}W {bottom_arm[1]}L "
          f"{bottom_arm[2]}D  ({time.time() - started:.0f}s)", flush=True)
    top_arm = _arm(cards, spells, matches, variant, baseline, False)
    print(f"  variant on top:    {top_arm[0]}W {top_arm[1]}L "
          f"{top_arm[2]}D  ({time.time() - started:.0f}s)", flush=True)

    def share(arm):
        decided = arm[0] + arm[1]
        return (arm[0] / decided) if decided else None

    bottom_share, top_share = share(bottom_arm), share(top_arm)
    decided = sum(arm[0] + arm[1] for arm in (bottom_arm, top_arm))
    overall = ((bottom_arm[0] + top_arm[0]) / decided) if decided else None
    error = math.sqrt(0.25 / decided) if decided else None
    seat_gap = (bottom_share - top_share
                if bottom_share is not None and top_share is not None else None)
    return {"bottom_arm": bottom_arm, "top_arm": top_arm,
            "bottom_share": bottom_share, "top_share": top_share,
            "decided": decided, "variant_share": overall,
            "standard_error": error, "seat_gap": seat_gap,
            "z": ((overall - 0.5) / error) if decided else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", type=Path, default=None,
                        help="config for the policy under test (default: baseline)")
    parser.add_argument("--baseline", type=Path, default=None,
                        help="config to compare against (default: shipped)")
    parser.add_argument("--matches", type=int, default=100,
                        help="matches per arm; total played is twice this")
    parser.add_argument("--level", type=int, default=11)
    args = parser.parse_args()

    print(f"{args.matches} matches per arm, both seats, same seeds")
    data = evaluate(args.variant, args.baseline, args.matches, args.level)
    if not data["decided"]:
        print("every match drew; nothing to compare")
        return 1

    print(f"\nvariant share of decided matches: {data['variant_share']:.3f} "
          f"(even=0.500, 1 s.e.={data['standard_error']:.3f}, "
          f"z={data['z']:+.2f})")
    print(f"seat effect in this pairing: {data['seat_gap']:+.3f} "
          f"(bottom arm {data['bottom_share']:.3f} vs top arm "
          f"{data['top_share']:.3f})")
    if abs(data["z"]) < 2:
        print("\nNot a result. Inside two standard errors, which at this sample "
              "size is\nwider than most config changes are worth - measure more "
              "rather than concluding.")
    else:
        better = "better" if data["variant_share"] > 0.5 else "worse"
        print(f"\nThe variant is {better} than the baseline, and it survives "
              f"swapping seats.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
