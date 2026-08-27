"""Compare the simulator against the real matches the bot has actually played.

We cannot replay a real match faithfully - only our own plays are logged, never
the opponent's - so this compares *aggregates* produced by the same policy in
both places: match length, cards played, and the card mix.

If the same policy behaves very differently in the two, the simulator differs
from the real game in ways that matter, and anything tuned in the simulator
will not transfer. That is the failure this project has to avoid, so the
numbers are printed side by side rather than summarised into a single score.

    python -m sim.validate --matches 40
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

MATCH_DIR = ROOT / "tmp" / "live" / "matches"


def live_aggregates(limit: int = 60) -> dict:
    records = []
    for path in sorted(MATCH_DIR.glob("*.json"))[-limit:]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    if not records:
        return {}
    plays = Counter()
    for record in records:
        plays.update(record.get("play_counts", {}))
    total = sum(plays.values()) or 1
    durations = [r.get("duration_s", 0) for r in records]
    mean_duration = sum(durations) / len(durations)
    return {
        "matches": len(records),
        "mean_duration_s": mean_duration,
        "plays_per_match": total / len(records),
        # Plays per match is confounded by how long a match runs, and the two
        # worlds do not agree on that: self-play is evenly matched and goes to
        # overtime far more often than ladder does. Rate is the comparison that
        # is actually about the policy.
        "plays_per_minute": (total / len(records)) / (mean_duration / 60.0)
        if mean_duration else 0.0,
        "mix": {card: 100 * count / total for card, count in plays.items()},
    }


def sim_aggregates(matches: int, level: int = 11) -> dict:
    from sim.gamedata import load_gamedata
    from sim.runner import DECK_26, play_match, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=level), DECK_26)
    spells = load_spells(level=level)
    plays = Counter()
    durations = []
    for index in range(matches):
        match, bottom, _ = play_match(cards, seed=5000 + index, spells=spells,
                                      opponent="brain")
        plays.update(bottom.plays)
        durations.append(match.elapsed_ms / 1000.0)
    total = sum(plays.values()) or 1
    mean_duration = sum(durations) / len(durations)
    return {
        "matches": matches,
        "mean_duration_s": mean_duration,
        "plays_per_match": total / matches,
        "plays_per_minute": (total / matches) / (mean_duration / 60.0)
        if mean_duration else 0.0,
        "mix": {card: 100 * count / total for card, count in plays.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Simulator vs real matches")
    parser.add_argument("--matches", type=int, default=40)
    parser.add_argument("--live", type=int, default=60)
    args = parser.parse_args()

    live = live_aggregates(args.live)
    if not live:
        print("no live match records to compare against")
        return 1
    sim = sim_aggregates(args.matches)

    print(f"{'metric':22s} {'live':>10s} {'sim':>10s} {'delta':>10s}")
    for label, key in (("matches", "matches"),
                       ("mean duration (s)", "mean_duration_s"),
                       ("plays per match", "plays_per_match"),
                       ("plays per minute", "plays_per_minute")):
        a, b = live[key], sim[key]
        print(f"{label:22s} {a:10.1f} {b:10.1f} {b - a:+10.1f}")

    # Say what a duration gap means before someone reads it as a defect.
    gap = sim["mean_duration_s"] - live["mean_duration_s"]
    if abs(gap) > 15:
        longer = "longer" if gap > 0 else "shorter"
        print(f"\nSimulated matches run {abs(gap):.0f}s {longer} than live "
              f"ones. Some of that is expected: self-play is evenly\nmatched "
              f"and goes to overtime far more often than ladder does, which "
              f"inflates plays\nper match without meaning the policy behaves "
              f"differently. Compare plays per minute\nfor that.")

    print(f"\n{'card':14s} {'live %':>8s} {'sim %':>8s} {'delta':>8s}")
    cards = sorted(set(live["mix"]) | set(sim["mix"]))
    worst = None
    for card in cards:
        a = live["mix"].get(card, 0.0)
        b = sim["mix"].get(card, 0.0)
        print(f"{card:14s} {a:8.1f} {b:8.1f} {b - a:+8.1f}")
        if worst is None or abs(b - a) > abs(worst[1]):
            worst = (card, b - a)

    print(f"\nlargest card-mix divergence: {worst[0]} {worst[1]:+.1f} points")
    print("A large divergence means the same policy meets different situations in "
          "the two worlds,\nso anything tuned in the simulator may not transfer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
