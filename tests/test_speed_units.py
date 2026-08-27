"""Is the movement-speed unit still tiles per minute?

This is the bug that cost the project the most. The engine passed every test it
had while being 25% wrong about the movement speed of every unit in the game,
because `Speed` is tiles per *minute* - Slow 45, Medium 60, Fast 90, Very Fast
120 - and the code read it as something else. It was caught by a person putting
one Ice Golem in a real match, not by the suite.

What made it survivable was that no test pinned the unit to a value a human
could recognise. These do: a Medium unit covers exactly one tile per second.

The field is also reused. `Speed` carries walk speeds in the 40-120 band and
projectile speeds in the 300-9999 band, in the same files, so a parser that
reached into the wrong section would pick up a plausible number and make a
Knight sprint. That is asserted separately.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import MT, Point                                # noqa: E402
from sim.entities import make_unit, speed_to_mt_per_sec        # noqa: E402
from sim.gamedata import load_gamedata                         # noqa: E402

CARDS = load_gamedata(level=11)
GAMEDATA = ROOT / "tmp" / "gamedata" / "csv_logic"

# The game's named movement classes, in tiles per minute.
BANDS = {"Slow": 45, "Medium": 60, "Fast": 90, "Very Fast": 120}


@pytest.mark.parametrize("name,tiles_per_minute", sorted(BANDS.items()))
def test_a_named_speed_class_covers_its_tiles_per_minute(name, tiles_per_minute):
    """Medium is one tile a second. If this reads 1.25, the unit is wrong."""
    per_second = speed_to_mt_per_sec(tiles_per_minute) / MT
    assert per_second == pytest.approx(tiles_per_minute / 60.0, abs=1e-3), name


def test_a_medium_unit_crosses_one_tile_per_second():
    """The anchor a person can check in a real match."""
    knight = make_unit(1, CARDS["knight"].unit, 1, Point(0, 0))
    assert knight.speed_mt_per_sec == MT


def test_every_unit_walks_at_a_plausible_pace():
    """No unit should move at a projectile's speed.

    The fastest thing that walks in this game is Very Fast at 2 tiles a
    second. Anything above that means a projectile-band number reached a
    character's walk speed.
    """
    offenders = []
    for name, card in CARDS.items():
        unit = card.unit
        if unit is None:
            continue
        entity = make_unit(1, unit, 1, Point(0, 0))
        tiles_per_second = entity.speed_mt_per_sec / MT
        if tiles_per_second > 2.0:
            offenders.append((name, tiles_per_second))
    assert not offenders, offenders


def test_the_speed_field_really_is_reused_across_two_bands():
    """Guards the premise of the test above rather than the code.

    If the shipped data ever stopped mixing walk and projectile speeds in one
    field, the check above would be guarding nothing and should be revisited
    instead of quietly passing forever.
    """
    values = set()
    for path in GAMEDATA.rglob("*.toml"):
        for found in re.finditer(r"^\s*Speed\s*=\s*(\d+)\s*$",
                                 path.read_text(errors="ignore"), re.M):
            values.add(int(found.group(1)))
    assert values & set(BANDS.values()), "no walk-band speeds found"
    assert {value for value in values if value >= 300}, "no projectile-band speeds found"
