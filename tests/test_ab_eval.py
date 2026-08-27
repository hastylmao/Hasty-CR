"""Does the A/B harness cancel the seat, as it claims to?

`play_match` takes a config per side so a variant can play the baseline, and
the win rate is supposed to be the answer. It is not, on its own: the seat is
worth about ten points here - `BrainPolicy` against itself takes 60.5% of
decided matches from the bottom over 400 matches on a provably symmetric board.
A variant placed on the bottom seat starts ahead of nothing at all.

`scripts/ab_eval.py` plays every seed twice, once with the variant on each
seat. For a change that does nothing, that is not merely approximately even -
it is exactly even, because the two arms are the same matches seen from
opposite ends. Asserting the identity is a real check on the arithmetic: an
off-by-one in which side counts as a win would break it immediately.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from ab_eval import evaluate                                    # noqa: E402


def test_a_change_that_changes_nothing_measures_exactly_even():
    data = evaluate(variant=None, baseline=None, matches=6)
    assert data["decided"] > 0
    assert abs(data["variant_share"] - 0.5) < 1e-9, data["variant_share"]


def test_both_arms_are_played_and_reported_separately():
    """The seat gap is shown rather than averaged away.

    Hiding it would make a large seat effect indistinguishable from a small
    one, and the size is what tells you whether the sample is big enough.
    """
    data = evaluate(variant=None, baseline=None, matches=6)
    assert data["seat_gap"] is not None
    bottom, top = data["bottom_arm"], data["top_arm"]
    assert sum(bottom) == sum(top) == 6
    # With identical configs the two arms are the same matches from opposite
    # ends, so one side's wins are the other's losses.
    assert bottom[0] == top[1] and bottom[1] == top[0], (bottom, top)
