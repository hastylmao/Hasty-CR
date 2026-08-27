"""Arena geometry for the simulator, in the game's own units.

Units and why
-------------
Everything here is **integer millitiles and milliseconds**, because that is what
the client's own data files use: `Range = 800` is 0.8 tiles, `HitSpeed = 1600`
is 1.6 seconds. Converting to floats would mean converting twice - once on the
way in, once on the way out - and inviting exactly the drift that Clash Royale
itself avoids by running fixed-point arithmetic. Integers in, integers out.

Coordinates match `scripts/brain/arena.py` so a policy written against the live
bot runs unchanged in here:

    18 tiles wide, 32 tall, y increasing downward.
    y < 16 is the enemy half, y >= 16 is ours.
    Our princess towers sit at (4, 24) and (14, 24); theirs at (4, 7), (14, 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple
from math import isqrt as _isqrt

MT = 1000                      # millitiles per tile
TILES_W, TILES_H = 18, 32
WIDTH = TILES_W * MT
HEIGHT = TILES_H * MT

RIVER_Y = 16 * MT              # boundary between the halves
# The river straddles the boundary rather than sitting on one side of it. It
# used to run from 15.0 to 16.0 with the boundary at 16.0, so the whole band
# belonged to the top half: measured from each tower to its own near lip, the
# bottom player walked 8.5 tiles and the top player 7.5. That is a free tile
# on every push, and with a mirrored policy on both seats it showed up as the
# bottom seat winning about two thirds of the time - which quietly invalidates
# any A/B comparison run on this board.
RIVER_TOP = 15 * MT + MT // 2      # 15.5
RIVER_BOTTOM = 16 * MT + MT // 2   # 16.5, so the band is centred on RIVER_Y

# Ground units may only cross at the bridges.
BRIDGE_X = (3 * MT + MT // 2, 14 * MT + MT // 2)

# Bridge width is not constant across the game. It is two tiles in Arenas 1-6
# and 8-9, and three tiles in Arena 7 and Arenas 10-23 - so every arena this
# project cares about, Path of Legends included, has the wider bridge. The
# simulator modelled the narrow one, which funnels a push harder than the real
# board does and matters most for exactly the bridge-spam decks it is meant to
# train against.
#
#   https://clashroyale.fandom.com/wiki/Arenas
#
# Expressed as a half-width in millitiles: 1500 spans tiles 2, 3 and 4 around a
# centre of 3.5.
BRIDGE_TILES = 3
BRIDGE_HALF_WIDTH = BRIDGE_TILES * MT // 2

TICK_MS = 50                   # 20 Hz; the client runs faster, this is enough
                               # to resolve a 1.6s hit speed and is 3x cheaper.


@dataclass(frozen=True)
class Point:
    x: int
    y: int

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)


def tile(x: float, y: float) -> Point:
    """Tile coordinates (as used by the policy) -> millitiles at tile centre."""
    return Point(int(x * MT + MT // 2), int(y * MT + MT // 2))


def to_tiles(p: Point) -> Tuple[float, float]:
    return p.x / MT, p.y / MT


def distance(a: Point, b: Point) -> int:
    """Euclidean distance in millitiles.

    Integer sqrt keeps the whole simulation in integers; the error is under one
    millitile, which is a thousandth of a tile and far below anything the game
    resolves.
    """
    # `_isqrt` directly rather than through `isqrt`: a sum of two squares is
    # never negative, so the guard that wrapper exists for cannot fire here,
    # and this is called about two and a half million times a match.
    dx, dy = a.x - b.x, a.y - b.y
    return _isqrt(dx * dx + dy * dy)


def isqrt(value: int) -> int:
    """Exact integer square root.

    This was a float estimate with correction loops, which is the right answer
    written out by hand: `math.isqrt` computes the same floor(sqrt(n)) in C.
    Results are bit-identical, so no simulated match changes - it is the single
    hottest call in the engine at over a million invocations a second, and
    target acquisition is about half of all runtime.
    """
    if value <= 0:
        return 0
    return _isqrt(value)


def is_our_half(p: Point) -> bool:
    return p.y >= RIVER_Y


def crosses_river(a: Point, b: Point) -> bool:
    return (a.y < RIVER_Y) != (b.y < RIVER_Y)


def nearest_bridge_x(x: int) -> int:
    return min(BRIDGE_X, key=lambda bx: abs(bx - x))


def on_bridge(p: Point) -> bool:
    return any(abs(p.x - bx) <= BRIDGE_HALF_WIDTH for bx in BRIDGE_X)


def clamp_to_arena(p: Point) -> Point:
    return Point(max(0, min(WIDTH - 1, p.x)), max(0, min(HEIGHT - 1, p.y)))


def in_arena(p: Point) -> bool:
    """Inside the playable board. Spells are limited by this and nothing else."""
    return 0 <= p.x < WIDTH and 0 <= p.y < HEIGHT


# Tower anchors, in tile coordinates, matching the live policy's convention.
# The left princess tower sat on column 4 while the right sat on 14. With the
# arena 18 wide the mirror line is 9, so that put the left tower 4.5 tiles from
# centre and the right one 5.5 - the board was not mirrored left to right, and
# the left tower did not even line up with its own bridge at 3.5. The live
# bot's arena, calibrated against the real game, has them on columns 3 and 14
# of an 0..17 grid, which is 3.5 and 14.5 here. A top-versus-bottom symmetry
# check cannot see this one, because it is the same on both halves.
ALLY_PRINCESS = {"left": tile(3, 24), "right": tile(14, 24)}
ENEMY_PRINCESS = {"left": tile(3, 7), "right": tile(14, 7)}
ALLY_KING = tile(9, 28)
ENEMY_KING = tile(9, 3)


# The "pocket": taking a princess tower opens ground across the river in front
# of where it stood, and the same happens to you when you lose one.
#
# **These two numbers are an approximation and are not sourced.** The rule is
# real and the client enforces it, but the shipped data does not define it -
# `globals.csv` has no deploy-area key and the arena tile map is not in the
# CSVs - and no published reference states it tile by tile. So the shape here
# is a rectangle around the fallen tower, seven tiles wide and reaching from
# one tile behind it to the river.
#
# What would settle it, stated precisely so a later pass cannot quietly swap a
# guess for a guess: in a real match after taking one princess tower, walk a
# placement along the enemy half and record the outermost accepted x on both
# the arena-edge side and the centre side, and the furthest accepted y behind
# the tower. Three numbers, one match.
#
# Getting the width wrong does not break the rule, it mis-sizes the reward for
# a crown - so it is worth measuring, and it was worth far less than the bug
# it replaced, which was the pocket being unreachable from the action space
# entirely.
POCKET_HALF_WIDTH_MT = 3 * MT     # unverified; see above
POCKET_BEHIND_TOWER_MT = MT       # unverified; see above


def deploy_area_ok(p: Point, side: int, enemy_princess_down: Iterable[str] = ()) -> bool:
    """Whether `side` may deploy a troop at `p`.

    side is +1 for the player at the bottom (ours) and -1 for the top.
    `enemy_princess_down` names the fallen towers of `side`'s opponent, so the
    call is symmetric: passing our own downed towers with side=-1 opens their
    pocket in our half, which is what a lost tower costs you.
    """
    if not (0 <= p.x < WIDTH and 0 <= p.y < HEIGHT):
        return False
    if side > 0:
        if p.y >= RIVER_Y:
            return True
        for lane in enemy_princess_down:
            centre = ENEMY_PRINCESS[lane]
            if (abs(p.x - centre.x) <= POCKET_HALF_WIDTH_MT
                    and p.y >= centre.y - POCKET_BEHIND_TOWER_MT):
                return True
        return False
    if p.y < RIVER_Y:
        return True
    for lane in enemy_princess_down:
        centre = ALLY_PRINCESS[lane]
        if (abs(p.x - centre.x) <= POCKET_HALF_WIDTH_MT
                and p.y <= centre.y + POCKET_BEHIND_TOWER_MT):
            return True
    return False
