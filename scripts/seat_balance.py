"""Measure whether a seat, rather than a policy, is winning matches.

Every A/B result this project produces is measured in self-play, which is only
meaningful if the two seats are interchangeable. They were not once before: the
river band sat off-centre, and a mirrored policy won about two thirds of
matches from the bottom seat. `tests/test_board_symmetry.py` now pins the board
itself, but a symmetric board is not the whole story - how the two policies are
interleaved in time is part of the environment too.

    python scripts/seat_balance.py --matches 400
    python scripts/seat_balance.py --matches 250 --policy simple
    python scripts/seat_balance.py --matches 250 --opens top

`--policy simple` puts a seat-agnostic policy on both seats, which separates a
board or scheduling effect from `BrainPolicy` simply playing better from the
seat it was written for. `--opens` chooses which seat takes the first decision
of the match; the runner's alternation otherwise always starts with the bottom.

Interpretation: |z| above about 2 is a real effect, not sampling noise. Draws
are excluded from the share because they carry no seat information, but a high
draw count means low power - the simple policy stalls most matches, so it needs
far more of them to say anything.
"""

from __future__ import annotations

import argparse
import collections
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.runner import (DECIDE_EVERY_MS, DECK_26, BrainPolicy,  # noqa: E402
                        SimpleOpponent, resolve_deck)
from sim.spells import load_spells                              # noqa: E402

MATCH_LIMIT_MS = 310_000


def run(matches: int, policy: str, opens: str, level: int = 11) -> dict:
    full = load_gamedata(level=level)
    cards = resolve_deck(full, DECK_26)
    spells = load_spells(level=level)

    def make(side: int, seed: int):
        if policy == "simple":
            return SimpleOpponent(cards, side=side, seed=seed)
        return BrainPolicy(cards, side=side)

    tally: collections.Counter = collections.Counter()
    crowns = [0, 0]
    started = time.time()
    for seed in range(matches):
        match = Match(cards=cards, decks=(DECK_26, list(DECK_26)), seed=seed,
                      spells=spells)
        # The same seed on both seats, so the only difference between the two
        # policies is which end of the board they sit on.
        bottom, top = make(1, seed + 1), make(-1, seed + 1)
        bottom.reset()
        top.reset()
        next_decision = 0
        turn = 1 if opens == "top" else 0
        while not match.finished and match.elapsed_ms < MATCH_LIMIT_MS:
            match.step()
            if match.elapsed_ms >= next_decision:
                next_decision = match.elapsed_ms + DECIDE_EVERY_MS
                turn += 1
                for actor in ((bottom, top) if turn % 2 else (top, bottom)):
                    actor.act(match)
        ours, theirs = match.crowns_for(1), match.crowns_for(-1)
        crowns[0] += ours
        crowns[1] += theirs
        tally["bottom" if ours > theirs else "top" if theirs > ours else "draw"] += 1
        if (seed + 1) % 25 == 0:
            print(f"  {seed + 1}/{matches}  {dict(tally)}  "
                  f"{time.time() - started:.0f}s", flush=True)

    decided = tally["bottom"] + tally["top"]
    share = tally["bottom"] / decided if decided else None
    error = math.sqrt(0.25 / decided) if decided else None
    return {"tally": dict(tally), "crowns": crowns, "decided": decided,
            "bottom_share": share, "standard_error": error,
            "z": (share - 0.5) / error if decided else None}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=int, default=200)
    parser.add_argument("--policy", choices=("brain", "simple"), default="brain")
    parser.add_argument("--opens", choices=("bottom", "top"), default="bottom",
                        help="which seat takes the first decision of the match")
    parser.add_argument("--level", type=int, default=11)
    args = parser.parse_args()

    data = run(args.matches, args.policy, args.opens, args.level)
    print(f"\n{args.policy} on both seats, {args.opens} opens, "
          f"{args.matches} matches")
    print(" ", data["tally"])
    print("  crowns bottom/top:", data["crowns"])
    if data["decided"]:
        print(f"  bottom share of decided {data['bottom_share']:.3f} "
              f"(even=0.500, 1 s.e.={data['standard_error']:.3f}, "
              f"z={data['z']:+.2f})")
        if abs(data["z"]) > 2:
            print("  -> a real seat effect. Do not read an A/B result of this "
                  "size as a fact about a policy change.")
    else:
        print("  every match drew; no seat information")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
