"""Is the simulator-versus-live comparison measuring what it claims to?

`sim.validate` exists to notice when the same policy meets different situations
in the two worlds, because anything tuned in the simulator would then fail to
transfer. It compared plays per *match*, which is confounded by how long a
match runs - and the two worlds genuinely disagree about that, since self-play
is evenly matched and reaches overtime far more often than ladder does.

Measured on 2026-08-20: matches ran 51s longer in the simulator and carried
15.9 more plays each, which reads as a large behavioural divergence. Per minute
the same numbers are 13.3 against 14.5, a 9% difference. The rate is the
comparison that is about the policy; the per-match figure is mostly about the
clock.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.validate import sim_aggregates                        # noqa: E402


def test_aggregates_report_a_duration_normalised_rate():
    data = sim_aggregates(matches=2)
    for key in ("matches", "mean_duration_s", "plays_per_match",
                "plays_per_minute", "mix"):
        assert key in data, key
    assert data["mean_duration_s"] > 0
    assert data["plays_per_minute"] > 0


def test_the_rate_is_consistent_with_the_two_numbers_it_comes_from():
    data = sim_aggregates(matches=2)
    expected = data["plays_per_match"] / (data["mean_duration_s"] / 60.0)
    assert abs(data["plays_per_minute"] - expected) < 1e-6


def test_the_card_mix_sums_to_a_hundred_percent():
    """The mix is the other half of the comparison and is a share, not a count."""
    data = sim_aggregates(matches=2)
    assert data["mix"]
    assert abs(sum(data["mix"].values()) - 100.0) < 1e-6
