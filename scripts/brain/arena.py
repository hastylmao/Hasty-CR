"""Arena geometry and the single source of truth for coordinate conventions.

Every other module in `brain` speaks the "grid" convention defined here, so the
bottom-up/top-down confusion that produced placements like (-2, 33) upstream
cannot reappear in more than one place.

Grid convention
---------------
    18 columns (x, 0 = far left) x 32 rows (y, 0 = enemy back line).
    y  < 16   enemy half        (only spells may be placed here)
    y >= 16   our half          (troops must be placed here)
    y == 16   the first row on our side of the river, i.e. "at the bridge"

BuildABot reports unit tiles bottom-up, so a detection's grid row is
`31 - tile_y`.  That conversion lives in `to_grid` and nowhere else.
"""

from __future__ import annotations

from typing import Iterable, NamedTuple, Tuple

GRID_W = 18
GRID_H = 32

RIVER_Y = 16
CENTRE_X = 8.5

# Tower anchors, matching the tokens the perception layer emits.
ENEMY_KING = (9, 3)
ENEMY_PRINCESS = {"left": (3, 7), "right": (14, 7)}
ALLY_PRINCESS = {"left": (3, 24), "right": (14, 24)}
ALLY_KING = (9, 28)

# Bridge columns.  Troops walk to the nearest bridge, so a "bridge push" is
# placed on the bridge column rather than on the princess-tower column.
BRIDGE_X = {"left": 3, "right": 14}

# MuMu 1080x1920 pixel mapping, measured against the live emulator.
_X0, _XS = 103.5, 51.0
_Y0, _YS = 171.9, 41.4


class Cell(NamedTuple):
    x: float
    y: float


def to_grid(tile_x: float, tile_y: float) -> Cell:
    """Convert a BuildABot detection tile to the grid convention."""
    return Cell(float(tile_x), 31.0 - float(tile_y))


def clamp(x: int, y: int) -> Tuple[int, int]:
    return max(0, min(GRID_W - 1, int(x))), max(0, min(GRID_H - 1, int(y)))


def to_pixels(x: int, y: int) -> Tuple[int, int]:
    """Grid cell -> MuMu screen pixel."""
    x, y = clamp(x, y)
    return round(_X0 + _XS * x), round(_Y0 + _YS * y)


def mirror_x(x: int) -> int:
    """Column `x` reflected across the arena's centre line.

    The grid has an *even* number of columns, so `CENTRE_X` is 8.5 and there is
    no middle column: the mirror of column x is `GRID_W - 1 - x`, which is what
    makes 3 and 14 (the princess-tower columns) a matched pair.

    Any right-lane tile derived as `round(CENTRE_X + offset)` instead of as the
    mirror of its left-lane twin is off by one - at offset 3, `round(8.5 - 3)`
    is 6 and sits 2.5 columns from the centre while `round(8.5 + 3)` is 12 and
    sits 3.5. Mirror the left tile instead of re-deriving the right one.
    """
    return GRID_W - 1 - int(x)


def side_of(x: float) -> str:
    return "left" if x < CENTRE_X else "right"


def our_half(cell: Cell) -> bool:
    return cell.y >= RIVER_Y


def distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def centroid(cells: Iterable[Tuple[float, float]]) -> Cell:
    cells = list(cells)
    if not cells:
        return Cell(CENTRE_X, 20.0)
    return Cell(
        sum(c[0] for c in cells) / len(cells),
        sum(c[1] for c in cells) / len(cells),
    )


def densest_cluster(cells, radius: float, minimum: int):
    """Centre of the largest group of >= `minimum` cells within `radius`.

    Returns (cell, count) or None.  Used for spell aiming, where hitting the
    most units matters more than hitting any particular one.
    """
    best = None
    best_count = minimum - 1
    for cx, cy in cells:
        group = [c for c in cells if distance(c, (cx, cy)) <= radius]
        if len(group) > best_count:
            best_count = len(group)
            best = centroid(group)
    if best is None:
        return None
    return best, best_count
