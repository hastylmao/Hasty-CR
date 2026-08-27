"""Is the board the same board from either seat?

The river band once sat entirely on one side of the halfway line, so one player
walked an extra tile on every push. With a mirrored policy on both seats the
bottom seat won about two thirds of matches, which invalidates any A/B result
measured on that board - the change under test and the seat are confounded, and
the seat is worth more.

Win rates are a slow and blunt way to find that. These check the board itself:
the deploy zones, the river, the tower anchors, walkability and the actual path
costs all have to mirror exactly about the halfway line. Each runs in
milliseconds and fails on the specific tile that broke, rather than on a
distribution that needs hundreds of matches to separate from noise.

Note what this does NOT claim. A symmetric board does not make mirror self-play
even; `BrainPolicy` is written for the bottom seat and measurably wins more
from it. See docs/SIM_MECHANICS.md - a seat effect of that size must not be
read as a result about a policy change.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena as A                                     # noqa: E402
from sim import pathfind as P                                  # noqa: E402
from sim.arena import MT, Point                                # noqa: E402

HEIGHT = 32 * MT
MIDLINE = 16 * MT


def _mirror(point: Point) -> Point:
    return Point(point.x, HEIGHT - point.y)


def test_the_river_is_centred_on_the_halfway_line():
    """The original bug, asserted directly."""
    above = MIDLINE - A.RIVER_TOP
    below = A.RIVER_BOTTOM - MIDLINE
    assert above == below, (A.RIVER_TOP, A.RIVER_BOTTOM, MIDLINE)


def test_the_towers_stand_in_mirrored_places():
    for lane in ("left", "right"):
        ally, enemy = A.ALLY_PRINCESS[lane], A.ENEMY_PRINCESS[lane]
        assert ally.x == enemy.x, lane
        assert ally.y + enemy.y == HEIGHT, lane
    assert A.ALLY_KING.x == A.ENEMY_KING.x
    assert A.ALLY_KING.y + A.ENEMY_KING.y == HEIGHT


def test_both_seats_may_deploy_on_mirrored_tiles():
    offenders = []
    for tx in range(18):
        for ty in range(32):
            point = Point(tx * MT + MT // 2, ty * MT + MT // 2)
            if A.deploy_area_ok(point, 1) != A.deploy_area_ok(_mirror(point), -1):
                offenders.append((tx, ty))
    assert not offenders, offenders[:20]


def test_the_walkable_grid_is_mirrored():
    offenders = [(tx, ty) for tx in range(18) for ty in range(32)
                 if P.walkable(tx, ty) != P.walkable(tx, 31 - ty)]
    assert not offenders, offenders[:20]


def test_a_push_costs_the_same_from_either_end():
    """The measurement that matters: walking cost, not just the map.

    A board can be drawn symmetrically and still path asymmetrically if the
    flow field breaks a tie one way, which is exactly how an extra tile per
    push hides.
    """
    ours = P.distance_field(9, 3)      # our units heading for the enemy king
    theirs = P.distance_field(9, 28)   # theirs heading for ours
    offenders = [(tx, ty, ours[ty][tx], theirs[31 - ty][tx])
                 for tx in range(18) for ty in range(32)
                 if ours[ty][tx] != theirs[31 - ty][tx]]
    assert not offenders, offenders[:20]
