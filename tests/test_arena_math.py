"""Is the integer square root still exact?

`isqrt` was a float estimate with correction loops, and it is now `math.isqrt`.
Both compute floor(sqrt(n)), so no simulated match changes - but the whole
engine is integer arithmetic precisely so that runs are reproducible, and a
distance function that is off by one somewhere would be the kind of fault this
project has repeatedly found the expensive way.

The correction loops are reproduced here as the reference. Testing the new
implementation against the one it replaced is the only comparison that can
actually disagree; testing it against `math.isqrt` would be testing nothing.
"""

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import MT, Point, distance, isqrt                # noqa: E402


def _reference(value: int) -> int:
    """The implementation that was replaced, kept as the thing to disagree."""
    if value <= 0:
        return 0
    root = int(value ** 0.5)
    while root * root > value:
        root -= 1
    while (root + 1) * (root + 1) <= value:
        root += 1
    return root


@pytest.mark.parametrize("value", [0, 1, 2, 3, 4, 8, 9, 10, -1, -7,
                                   10 ** 6, 10 ** 12 - 1, 10 ** 14 + 3])
def test_edge_values_match_the_old_implementation(value):
    assert isqrt(value) == _reference(value)


def test_a_large_random_sample_matches_the_old_implementation():
    rng = random.Random(1)
    for _ in range(20_000):
        value = rng.randrange(0, 10 ** 14)
        assert isqrt(value) == _reference(value), value


def test_distance_is_symmetric_and_exact_on_a_right_triangle():
    """3-4-5 in tiles, so the answer is exact and checkable by eye."""
    a, b = Point(0, 0), Point(3 * MT, 4 * MT)
    assert distance(a, b) == 5 * MT
    assert distance(b, a) == 5 * MT
    assert distance(a, a) == 0


def test_distance_never_overestimates():
    """It floors, so it must never come back above the true distance."""
    rng = random.Random(7)
    for _ in range(5_000):
        a = Point(rng.randrange(0, 18 * MT), rng.randrange(0, 32 * MT))
        b = Point(rng.randrange(0, 18 * MT), rng.randrange(0, 32 * MT))
        got = distance(a, b)
        exact = ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5
        assert got <= exact + 1e-6
        assert got > exact - 1.0
