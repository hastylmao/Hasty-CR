"""Which externally verified values are exact here, and which are extrapolated?

`combat_rules.json` is where this project records numbers it could not derive
from the shipped files - balance changes read off Supercell's own blog and
RoyaleAPI, each with a source URL and a verification date. Every one is stamped
with the level it was observed at, and every one was observed at level 11.

The loader used to apply such a value *only* at that exact level, so every
other level fell back to raw client scaling without a word. That was reachable
in ordinary play, not just by typing `--level`: Mirror resolves cards one level
up, and a mirrored Evolved Witch came out at 922 hitpoints against the 1451 she
is verified at - weaker for being played higher.

`gamedata.carry_verified` now carries a verified value along the client's own
scaling curve, holding its ratio to `scale_stat` constant. At the level it was
verified at it is returned exactly; elsewhere it moves the way every other stat
on that card moves. That is an extrapolation, not a measurement, and this
report is what says which is which.

    python -m sim.level_audit             level 11: everything exact
    python -m sim.level_audit --level 12  what Mirror resolves against
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "royaleapi" / "combat_rules.json"

OVERRIDE_SUFFIX = "_override"

# Overrides the loader carries across levels. The rest are either non-numeric
# (a spawned character's name) or counts that do not scale with level, and are
# reported as level-pinned so nobody assumes more than is true.
CARRIED_FIELDS = frozenset({
    "hitpoints_override", "damage_override", "variable_damage2_override",
    "variable_damage3_override", "shield_lost_damage_override",
    "far_attack_damage_override", "projectile_area_damage_override",
    "ground_landing_damage_override", "dash_damage_override",
})


def _rules() -> Dict[str, dict]:
    payload = json.loads(RULES.read_text(encoding="utf-8"))
    rules = payload.get("rules", {})
    return {name: rule for name, rule in rules.items() if isinstance(rule, dict)}


def report(level: int = 11) -> dict:
    """Split verified overrides into exact, extrapolated, and level-pinned."""
    exact: List[dict] = []
    carried: List[dict] = []
    pinned: List[dict] = []
    unpinned: List[dict] = []

    for name, rule in sorted(_rules().items()):
        fields = sorted(key for key in rule if key.endswith(OVERRIDE_SUFFIX))
        if not fields:
            continue
        recorded = rule.get("level")
        entry = {"card": name, "fields": fields, "recorded_level": recorded,
                 "source": rule.get("source") or (rule.get("sources") or [None])[0],
                 "verified_at": rule.get("verified_at")}
        if recorded is None:
            unpinned.append(entry)
            continue
        if int(recorded) == level:
            exact.append(entry)
            continue
        movable = sorted(set(fields) & CARRIED_FIELDS)
        fixed = sorted(set(fields) - CARRIED_FIELDS)
        if movable:
            carried.append({**entry, "fields": movable})
        if fixed:
            pinned.append({**entry, "fields": fixed})

    return {
        "level": level,
        "rules_with_overrides": len({row["card"] for row in
                                     exact + carried + pinned + unpinned}),
        "exact": exact,
        "carried": carried,
        "pinned": pinned,
        "unpinned": unpinned,
        "values_carried": sum(len(row["fields"]) for row in carried),
        "values_pinned": sum(len(row["fields"]) for row in pinned),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verified-override coverage by level")
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    data = report(args.level)
    print(f"level {data['level']}: {len(data['exact'])} of "
          f"{data['rules_with_overrides']} rules with verified overrides are "
          f"exact here")
    if data["unpinned"]:
        print(f"  {len(data['unpinned'])} carry no recorded level and apply "
              f"everywhere")
    if not data["carried"] and not data["pinned"]:
        print("  every verified value is used as measured")
        return 0

    if data["carried"]:
        print(f"\n  EXTRAPOLATED: {data['values_carried']} values on "
              f"{len(data['carried'])} rules")
        print("  Carried along the client scaling curve from the level they "
              "were verified at.")
        print("  Sound enough to play against; re-verify before quoting one.")
        for row in data["carried"] if args.verbose else data["carried"][:10]:
            print(f"    {row['card']:26s} verified at level "
                  f"{row['recorded_level']}  {', '.join(row['fields'])}")
        if not args.verbose and len(data["carried"]) > 10:
            print(f"    ... and {len(data['carried']) - 10} more (--verbose)")

    if data["pinned"]:
        print(f"\n  STILL LEVEL-PINNED: {data['values_pinned']} values on "
              f"{len(data['pinned'])} rules")
        print("  These do not scale with level (counts, spawned character "
              "names) or have no carrying rule, so they apply only at the "
              "level they were verified at.")
        for row in data["pinned"] if args.verbose else data["pinned"][:10]:
            print(f"    {row['card']:26s} verified at level "
                  f"{row['recorded_level']}  {', '.join(row['fields'])}")
        if not args.verbose and len(data["pinned"]) > 10:
            print(f"    ... and {len(data['pinned']) - 10} more (--verbose)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
