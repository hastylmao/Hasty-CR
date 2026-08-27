"""Play random public decks against each other and report anything that breaks.

The fixed decks exercise about thirty cards. Everything else in the catalogue
is reached only by a random-deck run, which is where an interaction between two
cards nobody has put together shows up.

It found one on 2026-08-20, in about one match in fifteen: `RamRider`
snake-cases onto the `ram_rider` card, whose unit is the Ram, which declares
`RamRider` as its attachment - so `Battle.add` recursed until the stack ran
out. Hog 2.6 contains no attachment card, so no fixed-deck test could have seen
it, and the viewer would have looked frozen rather than reporting a traceback.

    python scripts/soak.py --matches 300

Failures are grouped by kind, because one broken interaction usually shows up
as many identical tracebacks and the count matters less than the shape.
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.deck_builder import random_public_deck                 # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.runner import DECIDE_EVERY_MS, SimpleOpponent          # noqa: E402
from sim.spells import load_spells                              # noqa: E402

MATCH_LIMIT_MS = 310_000


def run(matches: int, level: int = 11) -> dict:
    cards = load_gamedata(level=level)
    spells = load_spells(level=level)
    failures = []
    missing_spawns: collections.Counter = collections.Counter()
    started = time.time()

    for seed in range(matches):
        try:
            rng = random.Random(seed)
            decks = (list(random_public_deck(cards, spells, rng)),
                     list(random_public_deck(cards, spells, rng)))
            match = Match(cards=cards, decks=decks, seed=seed, spells=spells)
            bottom = SimpleOpponent(cards, side=1, seed=seed)
            top = SimpleOpponent(cards, side=-1, seed=seed + 1)
            bottom.reset()
            top.reset()
            next_decision = 0
            turn = 0
            while not match.finished and match.elapsed_ms < MATCH_LIMIT_MS:
                match.step()
                if match.elapsed_ms >= next_decision:
                    next_decision = match.elapsed_ms + DECIDE_EVERY_MS
                    turn += 1
                    for actor in ((bottom, top) if turn % 2 else (top, bottom)):
                        actor.act(match)
            # A spawn the engine could not resolve is a silent hole in a card's
            # behaviour rather than a crash, so it is collected too.
            missing_spawns.update(match.missing_spawns)
        except Exception as error:                              # noqa: BLE001
            failures.append({"seed": seed, "kind": type(error).__name__,
                             "message": str(error)[:160],
                             "traceback": traceback.format_exc()})
        if (seed + 1) % 25 == 0:
            print(f"  {seed + 1}/{matches}  failures={len(failures)}  "
                  f"{time.time() - started:.0f}s", flush=True)

    return {"matches": matches, "failures": failures,
            "missing_spawns": dict(missing_spawns)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matches", type=int, default=150)
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--verbose", action="store_true",
                        help="print a full traceback for each distinct failure")
    args = parser.parse_args()

    data = run(args.matches, args.level)
    print(f"\nSOAK: {data['matches']} random-deck matches, "
          f"{len(data['failures'])} failures")

    if data["missing_spawns"]:
        print("\nspawns the engine could not resolve (not crashes, but holes):")
        for name, count in sorted(data["missing_spawns"].items()):
            print(f"    {name}  x{count}")

    grouped: dict = {}
    for failure in data["failures"]:
        grouped.setdefault((failure["kind"], failure["message"]), []).append(failure)
    for (kind, message), items in grouped.items():
        print(f"\n  {kind}: {message}")
        print(f"    {len(items)} matches, first at seed {items[0]['seed']}")
        if args.verbose:
            print("    " + items[0]["traceback"].replace("\n", "\n    "))

    return 1 if data["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
