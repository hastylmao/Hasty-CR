"""Does every evolution the client ships reach the simulator?

Evolution overlays are compact `Base=` blocks rather than full character
sections, and they live in more than one file. The loader read
`characters_evo.toml` and not `buildings_evo.toml`, so Mortar Evolution and
Tesla Evolution had no character data at all: their card rows resolved to
nothing and were dropped, silently, leaving the simulator reporting 40
evolutions where the client ships 42.

That is the same shape as the spell table which named two files that did not
exist, so the simulator ran on two spells while appearing to support four. A
hand-written list of data files is a place for a card to go missing without
anything failing, which is why this counts them from the files instead.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import (GAMEDATA_ROOT, load_characters,  # noqa: E402
                          load_gamedata, to_snake_case)

CARDS = load_gamedata(level=11)
CHARACTERS = load_characters(level=11)
SECTION = re.compile(r"^\[([A-Za-z0-9_]+)\]", re.M)
OVERLAY_FILES = ("characters_evo.toml", "buildings_evo.toml")


def _declared_overlays() -> set:
    """Every `Base=` overlay the shipped evolution files declare."""
    names = set()
    for filename in OVERLAY_FILES:
        path = GAMEDATA_ROOT / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for found in SECTION.finditer(text):
            body = text[found.end():]
            cut = body.find("\n[")
            if "Base" in (body if cut < 0 else body[:cut]):
                names.add(found.group(1))
    return names


def test_every_declared_evolution_overlay_resolves_to_a_character():
    """Characters, not cards.

    Several overlays name the individual member of a swarm - `Barbarian_EV1`
    for the `barbarians_ev1` card - so they are never card keys. What matters
    is that each one produced usable character data, which is exactly what the
    two building evolutions did not.
    """
    declared = _declared_overlays()
    assert declared, "no evolution overlays found at all"
    missing = sorted(name for name in declared
                     if name not in CHARACTERS
                     and to_snake_case(name) not in CHARACTERS)
    assert not missing, missing


def test_the_building_evolutions_specifically_are_present():
    """Named cases, because the sweep would pass if the file vanished."""
    for name in ("mortar_ev1", "tesla_ev1"):
        assert name in CARDS, name
        assert CARDS[name].unit is not None, name


def test_an_evolution_overlay_does_not_leak_into_its_base_card():
    """The risk in merging an overlay onto a base is writing back into it.

    Mortar happens to share its hit speed with its evolution, which would hide
    a leak; Tesla does not, so it is the useful case.
    """
    import re

    shipped = (GAMEDATA_ROOT / "characters" / "tesla.toml").read_text(
        encoding="utf-8", errors="replace")
    declared = int(re.search(r"^\s*Hitpoints\s*=\s*(\d+)", shipped, re.M).group(1))

    base = CARDS["tesla"].unit
    evolved = CARDS["tesla_ev1"].unit
    assert int(base.raw.get("Hitpoints", 0) or 0) == declared
    assert base.name != evolved.name
