"""Keep an autonomous reviewer from re-learning lessons that already cost matches.

Each block review is run by an agent with no memory of the run. Left alone it
will happily re-tighten a knob that was already measured as harmful - which is
exactly what happened: `defend_elixir_ratio` was relaxed to 1.6 after a
ten-match regression, and the next review put it back to 0.9.

`brain/bounds.json` records the safe range for every setting a finding depends
on. This module clamps `config.json` back into those ranges and reports what it
changed, so a review can still tune freely inside the envelope but cannot
silently undo an expensive lesson.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "scripts" / "brain" / "config.json"
BOUNDS = ROOT / "scripts" / "brain" / "bounds.json"


def check(config_path: Path = CONFIG, bounds_path: Path = BOUNDS,
          apply: bool = True) -> List[Tuple[str, float, float]]:
    """Clamp out-of-range values. Returns (key, was, now) for each change."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    bounds = json.loads(bounds_path.read_text(encoding="utf-8"))

    changes: List[Tuple[str, float, float]] = []
    for key, span in bounds.items():
        if key.startswith("_") or not isinstance(span, list) or len(span) != 2:
            continue
        # Dotted keys reach into a nested table: `weights.defend_air`. The
        # scoring weights were unreachable before, and that is exactly where the
        # review loop drifted - it added defend_single and defend_air_weak, and
        # every defensive weight ended up above every Hog weight, so the win
        # condition could not win a scoring contest at any threat level.
        holder, _, leaf = key.rpartition(".")
        table = config
        if holder:
            for part in holder.split("."):
                table = table.get(part) if isinstance(table, dict) else None
                if table is None:
                    break
        if not isinstance(table, dict) or leaf not in table:
            continue
        value = table[leaf]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        low, high = span
        clamped = max(low, min(high, value))
        if clamped != value:
            changes.append((key, value, clamped))
            table[leaf] = clamped

    if changes and apply:
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return changes


def main() -> int:
    changes = check(apply="--check-only" not in sys.argv)
    for key, was, now in changes:
        reason = json.loads(BOUNDS.read_text(encoding="utf-8")).get(f"_{key}", "")
        print(f"GUARD {key}: {was} -> {now}")
        if reason:
            print(f"      {reason}")
    if not changes:
        print("GUARD config within bounds")
    return 1 if changes else 0


if __name__ == "__main__":
    raise SystemExit(main())
