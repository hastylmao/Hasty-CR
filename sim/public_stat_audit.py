"""Do the sim's card costs and rarities agree with the public snapshot?

This project's standing rule is that any number which changes behaviour gets
checked against something that can disagree with it.  `card_catalog_audit`
already proves every public card maps to a local row; that is an identity
check and says nothing about the values on the row.

Elixir cost and rarity are the two fields worth checking this way.  Cost drives
the whole economy, so one wrong number changes every affordability decision the
policy makes.  Rarity is worse than it looks: card stats are scaled from
level-1 bases *by rarity*, so a card filed under the wrong rarity has the wrong
hitpoints and damage at every level while still parsing cleanly - the exact
failure mode this codebase keeps hitting.

A disagreement is not automatically a bug. The client files ship ahead of
RoyaleAPI, and the rule is that the game's own files win. Divergences that have
been checked against the client row are recorded in `KNOWN_DIVERGENCES` with
what the client actually says, so a new one stands out instead of being lost
among the explained ones.

    python -m sim.public_stat_audit
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data" / "royaleapi" / "cards.json"

# public key -> (field, snapshot value, local value, why the local value wins)
KNOWN_DIVERGENCES: Dict[str, tuple] = {
    "goblin-hut": (
        "elixir", 5, 4,
        "The client ships the rework: spells_buildings.csv row GoblinHut gives "
        "ManaCost 4, Rarity Rare, character GoblinHut_Rework, icon "
        "goblin_hut_rework_card. The snapshot retrieved 2026-08-19 still "
        "carries the pre-rework cost. The shipped files win.",
    ),
}


def _local_value(spec, spells, name, field):
    if field == "elixir":
        value = getattr(spec, "cost", None)
        if value is None and name in spells:
            value = getattr(spells[name], "cost", None)
        return None if value is None else int(value)
    value = getattr(spec, "rarity", None)
    return None if value is None else str(value).lower()


def report() -> dict:
    from .card_catalog_audit import report as catalog_report
    from .gamedata import load_gamedata
    from .spells import load_spells

    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    snapshot = {card["key"]: card for card in payload["cards"]}
    mapping = catalog_report()["mapped"]
    cards = load_gamedata(level=11)
    spells = load_spells(level=11)

    checked = 0
    unexplained: List[dict] = []
    explained: List[dict] = []
    unchecked: List[str] = []

    for public_key, local_name in sorted(mapping.items()):
        row = snapshot.get(public_key)
        spec = cards.get(local_name)
        if row is None or spec is None:
            unchecked.append(public_key)
            continue
        for field in ("elixir", "rarity"):
            want = row.get(field)
            if want is None:
                continue
            if field == "rarity":
                want = str(want).lower()
            got = _local_value(spec, spells, local_name, field)
            if got is None:
                continue
            checked += 1
            if got == want:
                continue
            finding = {"public_key": public_key, "local_name": local_name,
                       "field": field, "snapshot": want, "sim": got}
            known = KNOWN_DIVERGENCES.get(public_key)
            if known and known[0] == field and known[1] == want and known[2] == got:
                finding["why_the_sim_wins"] = known[3]
                explained.append(finding)
            else:
                unexplained.append(finding)

    return {
        "public_cards": len(snapshot),
        "mapped": len(mapping),
        "values_checked": checked,
        "explained_divergences": explained,
        "unexplained_divergences": unexplained,
        "unchecked": sorted(unchecked),
    }


def main() -> int:
    data = report()
    print(f"public cards: {data['public_cards']}   mapped: {data['mapped']}   "
          f"values checked: {data['values_checked']}")
    for row in data["explained_divergences"]:
        print(f"\nEXPLAINED  {row['local_name']}.{row['field']}: "
              f"snapshot={row['snapshot']} sim={row['sim']}")
        print(f"  {row['why_the_sim_wins']}")
    if data["unexplained_divergences"]:
        print(f"\nUNEXPLAINED: {len(data['unexplained_divergences'])}")
        for row in data["unexplained_divergences"]:
            print(f"  {row['local_name']}.{row['field']}: "
                  f"snapshot={row['snapshot']} sim={row['sim']}")
        print("\nCheck the client row before changing anything. If the shipped "
              "file agrees with the sim, record it in KNOWN_DIVERGENCES with "
              "the row that proves it.")
        return 1
    print("\nno unexplained divergences")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
