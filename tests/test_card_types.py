"""Does the simulator agree with the public snapshot about what a card *is*?

Cost and rarity are checked elsewhere. Card type is the third field the public
snapshot carries, and it is the one with the largest behavioural reach: whether
something is a building decides whether a Hog Rider walks past it or into it,
whether troops path around it, and whether it holds still.

The simulator inferred it from `Speed == 0`. That is true of most buildings and
was never true by definition, and two cards broke it: the reworked Furnace and
Goblin Drill both carry a real Speed in their character section, so they were
classed as troops and *walked up the lane* - six and ten tiles in ten seconds -
drawing no building-targeted aggro and standing solid to nothing.

The client answers this itself: the card is declared in `spells_buildings.csv`.
That is now what `from_building_card` records, and it agrees with the snapshot
on all 120 public cards.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import MT, Point, TICK_MS                      # noqa: E402
from sim.card_catalog_audit import report as catalog_report   # noqa: E402
from sim.engine import Battle                                 # noqa: E402
from sim.entities import make_unit                            # noqa: E402
from sim.gamedata import load_gamedata                        # noqa: E402

SNAPSHOT = json.loads(
    (ROOT / "data" / "royaleapi" / "cards.json").read_text(encoding="utf-8"))
PUBLIC = {card["key"]: card for card in SNAPSHOT["cards"]}
CARDS = load_gamedata(level=11)
MAPPING = catalog_report()["mapped"]


def _sim_type(local_name: str):
    spec = CARDS.get(local_name)
    if spec is None or spec.unit is None:
        return None
    entity = make_unit(1, spec.unit, 1, Point(0, 0))
    return "Building" if entity.is_building else "Troop"


def test_the_sim_and_the_snapshot_agree_on_every_card_type():
    mismatches = []
    checked = 0
    for public_key, local_name in sorted(MAPPING.items()):
        want = PUBLIC[public_key]["type"]
        if want not in ("Building", "Troop"):
            continue
        got = _sim_type(local_name)
        if got is None:
            continue
        checked += 1
        if got != want:
            mismatches.append(f"{local_name}: snapshot={want} sim={got}")
    assert checked > 80, checked
    assert not mismatches, mismatches


@pytest.mark.parametrize("card", ["firespirit_hut", "goblin_drill"])
def test_a_building_that_carries_a_speed_is_still_a_building(card):
    """The two cards the Speed == 0 inference got wrong.

    Kept as named cases rather than folded into the sweep above, because the
    sweep would still pass if the client stopped shipping them.
    """
    entity = make_unit(1, CARDS[card].unit, 1, Point(0, 0))
    assert entity.is_building, card


def test_the_stationary_buildings_did_not_start_moving():
    """The fix must not have been bought by making everything a building."""
    battle = Battle()
    placed = []
    for index, name in enumerate(("cannon", "tesla", "tombstone")):
        entity = battle.add(make_unit(index + 1, CARDS[name].unit, 1,
                                      Point(3000 + index * 2000, 20000)))
        entity.deploy_remaining_ms = 0
        placed.append((name, entity, entity.pos))
    for _ in range(int(8 * 1000 / TICK_MS)):
        battle.step()
    for name, entity, start in placed:
        moved = abs(entity.pos.x - start.x) + abs(entity.pos.y - start.y)
        assert moved == 0, (name, moved / MT)
