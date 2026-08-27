"""Ground troops walk at the tower defending their own lane.

A unit deployed on the right walks at the right princess tower, and when that
tower has fallen it walks at the *king*, through the pocket. It does not cross
the arena to the surviving princess tower on the far side. Every Clash Royale
player relies on this without thinking about it: it is what makes taking a
tower worth anything, because the follow-up push goes at the king rather than
wandering back into the lane you already spent elixir opening.

The engine picked the globally nearest enemy tower by straight-line distance,
which gets the *opening* board right by luck and the interesting one wrong.
From the back of the right lane with the right tower down:

    left princess (3.5, 7.5)   -> about 20.7 tiles
    king          (9.5, 3.5)   -> about 22.1 tiles

so the left tower won the arithmetic and a Hog Rider deployed at (14, 25)
walked diagonally across the entire board to it. Reported from live play, and
the walk is unmistakable on screen.

Distance was answering the wrong question. Lane is not a tiebreak on distance,
it is a filter applied before distance is consulted at all.

Buildings are deliberately *not* lane-filtered: a Cannon in the middle is
meant to pull a building-targeter out of either lane, which is the whole point
of the card. That pull stays gated on sight range - see test_building_pull.
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


def arena_with_towers(*, standing=("left", "right")):
    """Returns the battle and the uids it assigned.

    `Battle.add` allocates uids itself and ignores the one passed in, so the
    towers have to be identified by what comes back out.
    """
    battle = Battle()
    towers = {}
    for lane in standing:
        towers[lane] = battle.add(
            make_tower(0, -1, arena.ENEMY_PRINCESS[lane],
                       3052, 109, 800, 7500)).uid
    towers["king"] = battle.add(
        make_tower(0, -1, arena.ENEMY_KING, 3052, 109, 800, 7500,
                   king=True)).uid
    return battle, towers


def deploy(battle: Battle, card: str, tile_x, tile_y):
    unit = battle.add(make_unit(0, CARDS[card].unit, 1,
                                arena.tile(tile_x, tile_y)))
    unit.deploy_remaining_ms = 0
    return unit


def walk_for(battle: Battle, unit, seconds: float):
    for _ in range(int(seconds * 20)):
        battle.step()
        if not unit.alive:
            break
    return unit.target_uid or unit.walk_target_uid


# --------------------------------------------------------------- the geometry

def test_the_centre_band_separates_the_king_from_the_princess_towers():
    """The lane test is positional, so the positions have to actually split."""
    assert arena.is_centre_lane(arena.ENEMY_KING)
    assert arena.is_centre_lane(arena.ALLY_KING)
    for lane in ("left", "right"):
        assert not arena.is_centre_lane(arena.ENEMY_PRINCESS[lane])
        assert not arena.is_centre_lane(arena.ALLY_PRINCESS[lane])


def test_princess_towers_sit_in_the_lane_they_are_named_for():
    assert arena.lane_of(arena.ENEMY_PRINCESS["left"]) == "left"
    assert arena.lane_of(arena.ENEMY_PRINCESS["right"]) == "right"


def test_the_king_is_in_both_lanes():
    right_side = arena.tile(14, 25)
    left_side = arena.tile(3, 25)
    assert arena.same_lane(right_side, arena.ENEMY_KING)
    assert arena.same_lane(left_side, arena.ENEMY_KING)


def test_a_unit_is_not_in_the_far_lane():
    assert not arena.same_lane(arena.tile(14, 25), arena.ENEMY_PRINCESS["left"])
    assert not arena.same_lane(arena.tile(3, 25), arena.ENEMY_PRINCESS["right"])


def test_the_far_tower_really_is_nearer_than_the_king():
    """Without this the fix is untested - distance has to actually disagree.

    If the arena were ever reshaped so the king were the nearest target
    anyway, these tests would pass for a reason that has nothing to do with
    lane commitment, and the bug could come back unnoticed.
    """
    from sim.engine import distance
    corner = arena.tile(14, 25)
    to_far_princess = distance(corner, arena.ENEMY_PRINCESS["left"])
    to_king = distance(corner, arena.ENEMY_KING)
    assert to_far_princess < to_king, "nearest-target would pick the far lane"


# ------------------------------------------------------------- both towers up

@pytest.mark.parametrize("tile_x", [14, 13, 12, 11, 10])
def test_a_hog_on_the_right_walks_at_the_right_tower(tile_x):
    battle, towers = arena_with_towers()
    hog = deploy(battle, "hog_rider", tile_x, 25)
    assert walk_for(battle, hog, 30) == towers["right"]
    assert hog.pos.x > arena.CENTRE_X, "it stayed in its own lane"


@pytest.mark.parametrize("tile_x", [3, 4, 5, 6, 7])
def test_a_hog_on_the_left_walks_at_the_left_tower(tile_x):
    battle, towers = arena_with_towers()
    hog = deploy(battle, "hog_rider", tile_x, 25)
    assert walk_for(battle, hog, 30) == towers["left"]
    assert hog.pos.x < arena.CENTRE_X


# ------------------------------------------------------ the reported failure

def test_a_hog_in_the_right_lane_goes_to_the_king_once_the_right_tower_falls():
    """The reported bug, in the state that produced it."""
    battle, towers = arena_with_towers(standing=("left",))
    hog = deploy(battle, "hog_rider", 14, 25)
    assert walk_for(battle, hog, 30) == towers["king"]
    assert hog.pos.x > 7 * MT, "it must not cross to the left princess tower"


def test_the_mirror_case_holds_too():
    battle, towers = arena_with_towers(standing=("right",))
    hog = deploy(battle, "hog_rider", 3, 25)
    assert walk_for(battle, hog, 30) == towers["king"]
    assert hog.pos.x < 11 * MT


def test_an_ordinary_troop_is_lane_committed_as_well():
    """Not a building-targeter quirk: the fallback is shared."""
    battle, towers = arena_with_towers(standing=("left",))
    knight = deploy(battle, "knight", 14, 25)
    assert walk_for(battle, knight, 40) == towers["king"]


def test_it_crosses_at_its_own_bridge():
    """Going to the king must not mean drifting to the far bridge."""
    battle, _ = arena_with_towers(standing=("left",))
    hog = deploy(battle, "hog_rider", 14, 25)
    crossing_x = None
    for _ in range(20 * 30):
        battle.step()
        if crossing_x is None and hog.pos.y < arena.RIVER_Y:
            crossing_x = hog.pos.x
        if not hog.alive:
            break
    assert crossing_x is not None, "it never crossed the river"
    assert abs(crossing_x - arena.BRIDGE_X[1]) <= arena.BRIDGE_HALF_WIDTH


# --------------------------------------------------- the far lane still works

def test_the_far_tower_is_used_when_nothing_else_is_left():
    """Lane commitment is a preference, not a wall.

    With the king gone too there is exactly one place left to go, and a unit
    that stands still instead is a worse bug than the one being fixed.
    """
    battle = Battle()
    left = battle.add(make_tower(0, -1, arena.ENEMY_PRINCESS["left"],
                                 3052, 109, 800, 7500)).uid
    hog = deploy(battle, "hog_rider", 14, 25)
    assert walk_for(battle, hog, 40) == left


def test_a_cannon_still_pulls_across_the_lane():
    """The building pull is deliberately not lane-filtered.

    Dropping a Cannon in the middle to drag a Hog off its lane is a real
    technique and has to keep working; it is bounded by sight range, not by
    which half of the arena it stands in.
    """
    battle, towers = arena_with_towers()
    cannon = battle.add(make_unit(0, CARDS["cannon"].unit, -1,
                                  arena.tile(9, 18)))
    cannon.deploy_remaining_ms = 0
    assert cannon.is_building and not cannon.is_tower
    hog = deploy(battle, "hog_rider", 12, 20)
    # Read the pull while the Cannon is still standing: given ten seconds the
    # Hog reaches it, kills it, and has moved on to a tower by the time the
    # assertion runs, which looks identical to never having been pulled.
    assert walk_for(battle, hog, 1) == cannon.uid
    assert cannon.alive
