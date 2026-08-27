"""Run many simulated matches in parallel worker processes.

`sim.runner` is single-process: a match is CPU-bound and the game-data load is
paid once, so a sequential benchmark leaves every core but one idle. This
module spreads a batch over a process pool:

    python -m sim.batch --matches 200 --workers 8

Two Windows constraints shape the design. The spawn start method re-imports
everything in each child and pickles the work by qualified name, so the worker
function must live at module level (no lambdas or closures) and the entry
point must sit behind `if __name__ == "__main__":`. And because the game-data
load costs more than a match, it happens once per process in the pool
initializer; each child then reuses the resolved cards for every match it is
handed, kept in module globals because pool tasks themselves must stay plain
picklable data.
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
import time
from typing import Dict, Optional, Tuple

from sim.runner import DECK_26, play_match, resolve_deck

# Per-process state, filled by _init_worker once per child and reused by every
# match that child runs. Globals rather than arguments because what crosses
# the pool boundary must pickle.
_CARDS: Optional[dict] = None
_SPELLS: Optional[dict] = None
_OPPONENT: str = "brain"


def _init_worker(level: int, opponent: str) -> None:
    """Pool initializer: load and resolve the game data once per process."""
    global _CARDS, _SPELLS, _OPPONENT
    from sim.gamedata import load_gamedata, scale_stat
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=level), DECK_26)
    missing = [c for c in DECK_26 if c not in cards]
    if missing:
        raise RuntimeError(f"deck cards missing from the game data: {missing}")
    _CARDS = cards
    _SPELLS = load_spells(
        level=level,
        scale=lambda base, rarity, lvl: scale_stat(base, rarity, lvl, {}),
    )
    _OPPONENT = opponent


def _run_one(seed: int) -> Tuple[Optional[str], int, int, Dict[str, int]]:
    """Play one match. Returns plain picklable results, never the Match."""
    match, bottom, _ = play_match(_CARDS, seed=seed, spells=_SPELLS,
                                  opponent=_OPPONENT)
    return (match.result, match.crowns_for(1), match.crowns_for(-1),
            dict(bottom.plays))


def run_batch(matches: int, workers: int = 0, seed: int = 0,
              level: int = 11, opponent: str = "brain") -> dict:
    """Play `matches` matches across `workers` processes. workers=0 means
    os.cpu_count()."""
    if workers <= 0:
        workers = os.cpu_count() or 1
    if matches > 0:
        workers = min(workers, matches)

    # Same per-match seeding as sim.runner (seed + index), so a batch and a
    # sequential run of the same size play identical, reproducible matches.
    seeds = [seed + index for index in range(matches)]

    started = time.monotonic()
    context = multiprocessing.get_context("spawn")
    with context.Pool(processes=workers, initializer=_init_worker,
                      initargs=(level, opponent)) as pool:
        results = pool.map(_run_one, seeds,
                           chunksize=max(1, matches // (workers * 4)))
    elapsed = time.monotonic() - started

    wins = losses = draws = 0
    crowns_for = crowns_against = 0
    card_counts: Dict[str, int] = {}
    for result, cf, ca, plays in results:
        crowns_for += cf
        crowns_against += ca
        if result == "bottom":
            wins += 1
        elif result == "top":
            losses += 1
        else:
            draws += 1
        for card, count in plays.items():
            card_counts[card] = card_counts.get(card, 0) + count

    return {
        "matches": matches,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "crowns_for": crowns_for,
        "crowns_against": crowns_against,
        "elapsed_s": elapsed,
        "matches_per_sec": matches / max(elapsed, 1e-6),
        "card_counts": card_counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run simulated matches in parallel")
    parser.add_argument("--matches", type=int, default=100)
    parser.add_argument("--workers", type=int, default=0,
                        help="worker processes; 0 means os.cpu_count()")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--opponent", choices=["brain", "simple"],
                        default="brain")
    args = parser.parse_args()

    summary = run_batch(matches=args.matches, workers=args.workers,
                        seed=args.seed, level=args.level,
                        opponent=args.opponent)

    total = sum(summary["card_counts"].values()) or 1
    print(f"{summary['matches']} matches in {summary['elapsed_s']:.1f}s "
          f"({summary['matches_per_sec']:.1f} matches/s, "
          f"{args.workers or (os.cpu_count() or 1)} workers)")
    print(f"record {summary['wins']}W {summary['losses']}L "
          f"{summary['draws']}D   crowns "
          f"{summary['crowns_for']}-{summary['crowns_against']}")
    print("card mix: " + "  ".join(
        f"{c} {100 * n / total:.0f}%" for c, n in
        sorted(summary["card_counts"].items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
