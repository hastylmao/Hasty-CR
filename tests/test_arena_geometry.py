"""The board's published dimensions, checked against the ones we simulate.

Arena geometry is not in the shipped data - `arenas.csv` is trophy and
progression metadata, and the playfield is identical in every arena, so it
lives in the engine binary. That binary is packed: `libg.so` is 28MB, stripped,
with its strings encrypted into 8-character noise, and `base.apk` ships an
encrypted `.text.ecc` section decrypted at runtime. Reading the constants out
of it is a reverse-engineering project, not an afternoon.

The dimensions are published, though, and that is enough to check them.

  https://clashroyale.fandom.com/wiki/Arenas

This caught a real error. Bridges are two tiles wide in Arenas 1-6 and 8-9, and
*three* tiles wide in Arena 7 and Arenas 10-23 - which is every arena this
project cares about, Path of Legends included. The simulator modelled the
narrow bridge, funnelling a push harder than the real board does, and it
matters most for the bridge-spam decks the opponent pool is full of.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena                                          # noqa: E402


def test_the_board_is_the_published_size():
    """32 tiles long, 18 wide."""
    assert (arena.TILES_W, arena.TILES_H) == (18, 32)


def test_the_bridges_are_the_wide_kind():
    """Three tiles, which is Arena 7 and 10-23 - everything that matters."""
    assert arena.BRIDGE_TILES == 3
    assert arena.BRIDGE_HALF_WIDTH == 3 * arena.MT // 2


def test_each_bridge_spans_three_whole_tiles():
    for centre in arena.BRIDGE_X:
        low = centre - arena.BRIDGE_HALF_WIDTH
        high = centre + arena.BRIDGE_HALF_WIDTH
        assert (high - low) == arena.BRIDGE_TILES * arena.MT
        # Whole tiles, not a strip straddling two halves.
        assert low % arena.MT == 0 and high % arena.MT == 0


def test_there_are_two_bridges_and_they_are_symmetric():
    assert len(arena.BRIDGE_X) == 2
    left, right = sorted(arena.BRIDGE_X)
    assert left + right == arena.WIDTH, (left, right, arena.WIDTH)


def test_the_river_band_is_centred_on_the_halfway_line():
    """An offset band once cost one seat a whole tile per push."""
    assert arena.RIVER_TOP < arena.RIVER_Y < arena.RIVER_BOTTOM
    assert arena.RIVER_Y - arena.RIVER_TOP == arena.RIVER_BOTTOM - arena.RIVER_Y
    assert arena.RIVER_Y * 2 == arena.HEIGHT


def test_the_towers_mirror_across_the_river():
    for lane in ("left", "right"):
        ours = arena.ALLY_PRINCESS[lane]
        theirs = arena.ENEMY_PRINCESS[lane]
        assert ours.x == theirs.x, lane
        assert ours.y + theirs.y == arena.HEIGHT, lane
    assert arena.ALLY_KING.x == arena.ENEMY_KING.x
    assert arena.ALLY_KING.y + arena.ENEMY_KING.y == arena.HEIGHT


def test_a_unit_on_the_bridge_can_cross_and_one_beside_it_cannot():
    from sim.arena import Point
    for centre in arena.BRIDGE_X:
        assert arena.on_bridge(Point(centre, arena.RIVER_Y))
        # A tile and a half out is the edge; two tiles out is the river.
        assert not arena.on_bridge(Point(centre + 2 * arena.MT, arena.RIVER_Y))
