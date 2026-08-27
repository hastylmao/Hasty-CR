"""Grid pathfinding for the arena.

The engine walked units straight at their target, detouring to a bridge when
the river was in the way. That is fine in an empty lane and wrong everywhere
else: a unit meeting a building simply pressed into it, and the steering patch
that followed only handled one obstacle directly ahead.

This is a breadth-first flow field over the 18x32 tile grid. Cost is one BFS
per distinct goal tile, cached, which is cheap enough to run inside a match:
576 tiles, and every unit heading for the same tower shares one field.

The river is impassable except on the two bridges, which falls out of the grid
rather than being special-cased in the movement code - so a unit that has to
cross finds a bridge because that is the only way through, not because it was
told to go there.
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Tuple

from .arena import (BRIDGE_HALF_WIDTH, BRIDGE_X, MT, RIVER_BOTTOM, RIVER_TOP,
                    TILES_H, TILES_W, Point)

# Eight-way movement: diagonals matter, or units walk in staircases around corners.
_STEPS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))

_FIELD_CACHE: Dict[Tuple[int, int], List[List[int]]] = {}


def walkable(tx: int, ty: int) -> bool:
    """Can a ground unit stand on this tile?

    Everything except the river, and the river is crossable on a bridge.
    """
    if not (0 <= tx < TILES_W and 0 <= ty < TILES_H):
        return False
    centre_mt = ty * MT + MT // 2
    if RIVER_TOP <= centre_mt <= RIVER_BOTTOM:
        x_mt = tx * MT + MT // 2
        return any(abs(x_mt - bx) <= BRIDGE_HALF_WIDTH for bx in BRIDGE_X)
    return True


def distance_field(goal_tx: int, goal_ty: int) -> List[List[int]]:
    """Steps from every tile to the goal, or -1 where there is no route."""
    key = (goal_tx, goal_ty)
    cached = _FIELD_CACHE.get(key)
    if cached is not None:
        return cached

    field = [[-1] * TILES_W for _ in range(TILES_H)]
    if not (0 <= goal_tx < TILES_W and 0 <= goal_ty < TILES_H):
        _FIELD_CACHE[key] = field
        return field

    # The goal itself may be a tower tile, which is not walkable for standing
    # on but is certainly somewhere units path towards, so it seeds the search
    # regardless.
    field[goal_ty][goal_tx] = 0
    queue = deque([(goal_tx, goal_ty)])
    while queue:
        tx, ty = queue.popleft()
        here = field[ty][tx]
        for dx, dy in _STEPS:
            nx, ny = tx + dx, ty + dy
            if not walkable(nx, ny) or field[ny][nx] != -1:
                continue
            field[ny][nx] = here + 1
            queue.append((nx, ny))

    _FIELD_CACHE[key] = field
    return field


def next_step(pos: Point, goal: Point) -> Optional[Point]:
    """The next tile centre to walk towards, following the flow downhill.

    Returns None when the goal is close enough to head for directly, or when
    no route exists - the caller then falls back to walking straight at it,
    which is the right behaviour for a target already in the same open space.
    """
    goal_tx, goal_ty = goal.x // MT, goal.y // MT
    tx, ty = pos.x // MT, pos.y // MT
    if (tx, ty) == (goal_tx, goal_ty):
        return None

    field = distance_field(goal_tx, goal_ty)
    if not (0 <= tx < TILES_W and 0 <= ty < TILES_H):
        return None
    here = field[ty][tx]
    if here <= 1:
        return None                      # adjacent: just walk at it

    best = None
    best_cost = here
    for dx, dy in _STEPS:
        nx, ny = tx + dx, ty + dy
        if not (0 <= nx < TILES_W and 0 <= ny < TILES_H):
            continue
        cost = field[ny][nx]
        if cost == -1 or cost >= best_cost:
            continue
        best_cost = cost
        best = (nx, ny)
    if best is None:
        return None
    return Point(best[0] * MT + MT // 2, best[1] * MT + MT // 2)
