"""Print what the bot has learned, best and worst first.

A one-command answer to "is the learning actually finding anything?" without
opening JSON by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "scripts" / "brain"


def load(name: str) -> dict:
    try:
        return json.loads((BRAIN / name).read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    minimum = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    matchups = load("matchups.json")
    rows = [
        (key, value["n"], value["killed"] / value["n"], value["reward"] / value["n"])
        for key, value in matchups.items() if value.get("n", 0) >= minimum
    ]
    rows.sort(key=lambda row: row[3])

    print(f"== matchups with at least {minimum} samples ({len(rows)} of {len(matchups)})")
    for key, count, kill_rate, mean in rows[:6]:
        print(f"  WORST  {key:34s} n={int(count):3d} killed={kill_rate:5.0%} mean={mean:+6.1f}")
    for key, count, kill_rate, mean in rows[-6:]:
        print(f"  BEST   {key:34s} n={int(count):3d} killed={kill_rate:5.0%} mean={mean:+6.1f}")

    learned = load("learned.json")
    print(f"\n== situations ({len(learned)})")
    for situation, cards in sorted(learned.items()):
        best = sorted(cards.items(), key=lambda kv: -kv[1][1])[:3]
        summary = "  ".join(f"{card}({int(n)}):{mean:+.1f}" for card, (n, mean) in best)
        print(f"  {situation:28s} {summary}")

    lessons = BRAIN / "lessons.md"
    if lessons.exists():
        print("\n== current lessons in the advisor prompt")
        for line in lessons.read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
