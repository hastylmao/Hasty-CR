"""Client-derived evolution catalogue.

This module records availability edges. Cycle counts are materialized on each
evolved ``CardSpec`` from the evolved-card row's ``DarkElixirCost`` field and
are enforced only for variants explicitly equipped in ``Match.evolution_slots``.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .gamedata import parse_toml_file, to_snake_case


ROOT = Path(__file__).resolve().parents[1] / "tmp" / "gamedata" / "csv_logic"


def _variants(value: str | list[str]) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(to_snake_case(str(part)) for part in value if str(part))
    value = (value or "").strip().strip("[]")
    if not value:
        return ()
    return tuple(to_snake_case(part.strip().strip('"'))
                 for part in value.split(",") if part.strip())


def catalogue(root: Path = ROOT) -> dict[str, tuple[str, ...]]:
    """Return base-card -> client-declared evolved spell variants.

    Only variants that exist in the client evolved-card table are retained;
    hidden or stale references therefore cannot enter an RL deck accidentally.
    """
    evolved: set[str] = set()
    evo_file = root / "spells_evolved.csv"
    if evo_file.exists():
        with evo_file.open(encoding="utf-8", newline="") as stream:
            for row in list(csv.DictReader(stream))[1:]:  # type annotation row
                name = row.get("Name", "")
                if name:
                    evolved.add(to_snake_case(name))

    result: dict[str, tuple[str, ...]] = {}
    for filename in ("spells_characters.csv", "spells_buildings.csv",
                     "spells_other.csv"):
        path = root / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        # The extracted client CSV includes a type-description row directly
        # below its header.  Ignore it rather than treating `string` as a card.
        for row in rows[1:]:
            name = row.get("Name", "")
            variants = tuple(v for v in _variants(row.get("EvolvedSpells", ""))
                             if v in evolved)
            if name and variants:
                result[to_snake_case(name)] = variants
    # Hero-form files can augment a base card's evolution list (for example
    # Knight exposes both its normal evolution and hero form in this graph).
    # Merge only actual evolved-card variants; the hero-form edge itself is
    # intentionally not misclassified as an evolution.
    hero_dir = root / "characters" / "hero_form"
    if hero_dir.exists():
        for path in hero_dir.glob("*_spell.toml"):
            try:
                data = parse_toml_file(path)
            except Exception:
                continue
            for name, spell in data.get("SPELL_CHARACTER", {}).items():
                if not isinstance(spell, dict):
                    continue
                extra = tuple(v for v in _variants(spell.get("EvolvedSpells", ""))
                              if v in evolved)
                if extra:
                    key = to_snake_case(name)
                    result[key] = tuple(dict.fromkeys(result.get(key, ()) + extra))
    return result
