"""Buildings pull building-targeters through sight range, not from anywhere.

A Hog Rider, Giant or Battle Ram walks at buildings, and dropping a Cannon in
the middle to drag one off its lane is a real and central defensive technique.
The range over which that works is the troop's sight range, which is why those
cards are given a longer one than everything else - 9.5 tiles for the Hog
against about 5.5 for a Knight.

What the engine did instead was treat *any* building as a destination at *any*
distance. A Hog deployed at the back of the right lane turned and walked 8.5
tiles across the arena to a Cannon seventeen tiles away in the left one. The
comment above the fallback already described this exact failure for ordinary
troops and fixed it for them; building-targeters kept it.

This matters for training and not only for looks: in a 2.6 mirror both players
hold a Cannon, so every Hog push was answered by a pull no real opponent could
have made, and the simulator's advice was that the win condition is not worth
playing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena                                            # noqa: E402
from sim.arena import MT                                         # noqa: E402
from sim.engine import Battle                                    # noqa: E402
from sim.entities import make_tower, make_unit                   # noqa: E402
from sim.gamedata import load_gamedata                           # noqa: E402

CARDS = load_gamedata(level=11)
PRINCESS_HP, PRINCESS_DAMAGE, PRINCESS_HIT_MS, PRINCESS_RANGE = 3052, 109, 800, 7500


def arena_with_towers() -> Battle:
    """Enemy crown towers present, because they are the default destination."""
    battle = Battle()
    for uid, (lane, pos) in enumerate(arena.ENEMY_PRINCESS.items(), start=100):
        battle.add(make_tower(uid, -1, pos, PRINCESS_HP, PRINCESS_DAMAGE,
                              PRINCESS_HIT_MS, PRINCESS_RANGE))
    battle.add(make_tower(102, -1, arena.ENEMY_KING, PRINCESS_HP,
                          PRINCESS_DAMAGE, PRINCESS_HIT_MS, PRINCESS_RANGE))
    return battle


def deploy(battle: Battle, uid: int, card: str, side: int, tile_x, tile_y):
    unit = battle.add(make_unit(uid, CARDS[card].unit, side,
                                arena.tile(tile_x, tile_y)))
    unit.deploy_remaining_ms = 0
    return unit


def run(battle: Battle, seconds: float) -> None:
    for _ in range(int(seconds * 20)):        # 50ms ticks
        battle.step()


def test_the_pull_radius_matches_the_published_values():
    """The gate is only as good as the number it gates on.

    `sight_range_mt` is the client's own `SightRange` column, not a figure
    anyone here chose, and two independent public claims agree with it:

    * The Clash Royale Wiki puts the Hog Rider at **9.5 tiles**, reduced from
      10 in the March 2016 update, and ties it with Royal Hogs and Princess
      for the longest sight range of any troop.
    * The same source says every building-targeting card is above 6 tiles
      *except Battle Ram and Lava Hound* - and Battle Ram is the one value
      here that sits below 6.

    If a card table update ever moved these, the pull radius would move with
    it silently, so they are pinned.
    """
    hog = CARDS["hog_rider"].unit
    assert hog.sight_range_mt / MT == pytest.approx(9.5)
    assert hog.target_only_buildings

    ram = CARDS["battle_ram"].unit
    assert ram.sight_range_mt / MT < 6.0, "the documented exception"

    for card in ("giant", "royal_giant", "balloon", "golem"):
        unit = CARDS[card].unit
        assert unit.sight_range_mt / MT > 6.0, f"{card} should be above 6 tiles"

    # And the reason building-targeters get a longer leash at all: it is how
    # a building pulls them, so it has to exceed an ordinary troop's.
    knight = CARDS["knight"].unit
    assert hog.sight_range_mt > knight.sight_range_mt


def test_a_hog_ignores_a_cannon_in_the_other_lane():
    """Seventeen tiles away against a 9.5 tile sight range."""
    battle = arena_with_towers()
    hog = deploy(battle, 1, "hog_rider", 1, 14, 26)
    cannon = deploy(battle, 2, "cannon", -1, 3, 13)
    start_x = hog.pos.x

    run(battle, 6.0)

    assert hog.target_uid != cannon.uid
    assert hog.walk_target_uid != cannon.uid
    # It should be heading up its own lane, not across the arena.
    assert (hog.pos.x - start_x) / MT > -1.0, (
        f"hog drifted {(hog.pos.x - start_x) / MT:.1f} tiles toward the "
        "opposite lane")


def test_a_cannon_in_range_still_pulls_the_hog():
    """The technique the card exists for has to keep working."""
    battle = arena_with_towers()
    hog = deploy(battle, 1, "hog_rider", 1, 11, 20)
    cannon = deploy(battle, 2, "cannon", -1, 9, 14)
    gap = ((hog.pos.x - cannon.pos.x) ** 2
           + (hog.pos.y - cannon.pos.y) ** 2) ** 0.5 / MT
    assert gap < hog.sight_range_mt / MT, "probe is not set up inside sight"

    run(battle, 2.0)

    assert cannon.uid in (hog.target_uid, hog.walk_target_uid), (
        "a cannon well inside sight range must pull a hog")


def test_the_sight_range_is_the_boundary_not_an_arbitrary_number():
    """Just inside pulls, well outside does not - same cannon, same hog."""
    inside = arena_with_towers()
    hog_in = deploy(inside, 1, "hog_rider", 1, 9, 22)
    sight = hog_in.sight_range_mt / MT
    cannon_in = deploy(inside, 2, "cannon", -1, 9, 22 - int(sight - 1))
    run(inside, 2.0)
    assert cannon_in.uid in (hog_in.target_uid, hog_in.walk_target_uid)

    # Far enough that two seconds of a Hog's advance cannot close the gap:
    # it covers about three tiles in that time and this is eight clear.
    outside = arena_with_towers()
    hog_out = deploy(outside, 1, "hog_rider", 1, 9, 30)
    cannon_out = deploy(outside, 2, "cannon", -1, 9, 30 - int(sight + 8))
    run(outside, 2.0)
    assert cannon_out.uid not in (hog_out.target_uid, hog_out.walk_target_uid)


def test_a_crown_tower_is_still_reachable_from_anywhere():
    """Towers are the destination of last resort; gating them strands units."""
    battle = arena_with_towers()
    hog = deploy(battle, 1, "hog_rider", 1, 3, 30)     # as far back as it gets
    start = hog.pos.y

    run(battle, 4.0)

    assert hog.target_uid is not None or hog.walk_target_uid is not None, (
        "a unit with no building in sight must still walk at a crown tower")
    assert hog.pos.y < start, "it should be advancing, not standing still"


def test_an_ordinary_troop_is_unaffected_by_the_change():
    """Knights were never pulled by buildings; that must not have changed."""
    battle = arena_with_towers()
    knight = deploy(battle, 1, "knight", 1, 14, 26)
    cannon = deploy(battle, 2, "cannon", -1, 3, 13)
    start_x = knight.pos.x

    run(battle, 6.0)

    assert knight.target_uid != cannon.uid
    assert (knight.pos.x - start_x) / MT > -1.0


def test_with_no_tower_standing_a_distant_building_is_still_a_destination():
    """The sight gate exists to lose a race, not to strand a unit.

    A bare arena has no crown tower to walk at, so gating the only building
    on the field left the unit standing where it was deployed - which is how
    `test_a_musketeer_kills_a_cannon_without_being_touched` caught this.
    """
    battle = Battle()                       # deliberately no towers
    musketeer = deploy(battle, 1, "musketeer", 1, 9, 24)
    cannon = deploy(battle, 2, "cannon", -1, 9, 14)
    gap = (musketeer.pos.y - cannon.pos.y) / MT
    assert gap > musketeer.sight_range_mt / MT, "probe is not set up outside sight"
    start = musketeer.pos.y

    run(battle, 3.0)

    assert musketeer.pos.y < start - 1000, (
        "with nothing else on the field the unit must advance on the building")


@pytest.mark.parametrize("card", ["hog_rider", "giant", "battle_ram"])
def test_every_building_targeter_gets_the_same_rule(card):
    battle = arena_with_towers()
    unit = deploy(battle, 1, card, 1, 14, 27)
    if not unit.target_only_buildings:
        pytest.skip(f"{card} does not target buildings only")
    cannon = deploy(battle, 2, "cannon", -1, 3, 13)
    start_x = unit.pos.x

    run(battle, 5.0)

    assert unit.target_uid != cannon.uid
    assert (unit.pos.x - start_x) / MT > -1.0
