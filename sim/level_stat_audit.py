"""Compare every card's stats, at every level, against the published tables.

The simulator computes a stat by scaling a level-1 base from the client files
through the rarity multiplier table. RoyaleAPI publishes the actual value at
every level - `hitpoints_per_level`, `damage_per_level` - which is an
independent source that can disagree, and disagreement is the only thing worth
having a second source for.

Index convention: an array's length tells you where it starts. Common cards
have nineteen entries, Rare seventeen, Epic fourteen, Legendary eleven,
Champion nine, matching each rarity's `RelativeLevel`. So the offset is
`19 - len(table)` and never needs the card's rarity, which matters because a
character row's rarity is not always the card row's.

Differences are bucketed rather than totalled, because they are not one
phenomenon:

  exact        the two agree
  within 1%    rounding path - the sim compounds rounded steps, the table is
               published rounded once. Not worth chasing.
  1-5%         worth a look
  over 5%      a real disagreement: usually the simulator scaling a card at
               the wrong rarity, or resolving it to the wrong character
               section entirely

This reports. It deliberately does not overwrite the simulator's values from
the published table: the shipped client files are sometimes ahead of RoyaleAPI
(the Goblin Hut rework is the standing example), so which source wins is a
judgement per card, not a blanket rule.

    python -m sim.level_stat_audit
    python -m sim.level_stat_audit --level 9 --verbose
    python -m sim.level_stat_audit --all-levels
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "royaleapi"
COMMON_TABLE_LENGTH = 19


def _published() -> Dict[str, dict]:
    """Character rows that carry a per-level table, by normalized name."""
    from .card_catalog_audit import canonical

    path = DATA / "cards_stats_characters.json"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing; run scripts/sync_royaleapi_full.py")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {canonical(row["name"]): row for row in rows
            if isinstance(row, dict) and row.get("name")
            and row.get("hitpoints_per_level")}


def _index_for(table: List[int], level: int) -> int | None:
    offset = COMMON_TABLE_LENGTH - len(table)
    index = level - 1 - offset
    return index if 0 <= index < len(table) else None


def report(level: int = 11) -> dict:
    from .card_catalog_audit import canonical
    from .gamedata import load_gamedata

    published = _published()
    cards = load_gamedata(level=level)

    exact, within_one, small, large, unmatched = [], [], [], [], []
    for name, card in sorted(cards.items()):
        unit = card.unit
        if unit is None:
            continue
        row = (published.get(canonical(unit.name))
               or published.get(canonical(name)))
        if row is None:
            unmatched.append(name)
            continue
        table = row["hitpoints_per_level"]
        index = _index_for(table, level)
        if index is None:
            continue
        want, got = int(table[index]), int(unit.hitpoints)
        entry = {"card": name, "published": want, "sim": got,
                 "delta": got - want,
                 "percent": (100.0 * (got - want) / want) if want else 0.0,
                 "table_length": len(table)}
        if got == want:
            exact.append(entry)
        elif abs(entry["percent"]) <= 1.0:
            within_one.append(entry)
        elif abs(entry["percent"]) <= 5.0:
            small.append(entry)
        else:
            large.append(entry)

    return {"level": level, "exact": exact, "within_one_percent": within_one,
            "one_to_five_percent": small, "over_five_percent": large,
            "unmatched": unmatched,
            "checked": len(exact) + len(within_one) + len(small) + len(large)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Per-level stats against RoyaleAPI")
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--all-levels", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    levels = range(1, 16) if args.all_levels else [args.level]
    worst = 0
    for level in levels:
        data = report(level)
        if not data["checked"]:
            continue
        print(f"level {level:2d}: checked {data['checked']:3d}  "
              f"exact {len(data['exact']):3d}  "
              f"within1% {len(data['within_one_percent']):3d}  "
              f"1-5% {len(data['one_to_five_percent']):3d}  "
              f">5% {len(data['over_five_percent']):3d}")
        worst = max(worst, len(data["over_five_percent"]))
        if (args.verbose or not args.all_levels) and data["over_five_percent"]:
            for row in sorted(data["over_five_percent"],
                              key=lambda r: -abs(r["percent"])):
                print(f"     {row['card']:24s} published={row['published']:6d} "
                      f"sim={row['sim']:6d}  {row['percent']:+7.1f}%")
    if worst:
        print("\nOver 5% is not rounding. The usual causes are the simulator "
              "scaling a card\nat the wrong rarity, or resolving it to a "
              "different character section than the\none the published row "
              "describes. Check the client row before changing either.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
