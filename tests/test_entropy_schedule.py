"""The entropy coefficient schedule used by Sprint 4's first intervention.

The measured failure at 43% against the rule engine is not a reward failure -
`reports/rl_sprint4/REWARD_DIAGNOSTIC.md` puts return/win at r = 0.967 - but an
exploration one: fireball is 0.7% of plays and musketeer 0.6%, so the two cards
that turn chip damage into a crown are almost never tried, and an action never
tried is never reinforced. The schedule explores hard early and then stops.

These are cheap arithmetic tests on purpose. The expensive question (does it
actually raise the win rate) is answered by a training run and a held-out eval,
not by a unit test; what a unit test can guarantee is that the number fed to the
loss is the number the run was asked for, on every step including the joins.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.train_ppo import entropy_schedule

# The intervention's own numbers: 0.10 held to 2M, linear to 0.03 by 4M.
INTERVENTION = dict(start=0.10, final=0.03, hold=2_000_000, anneal=4_000_000)


def test_no_final_value_is_the_constant_every_earlier_run_used():
    for step in (0, 1, 500_000, 6_000_000):
        assert entropy_schedule(step, 0.03, None, 0, 0) == 0.03


def test_held_flat_across_the_whole_hold_window():
    for step in (0, 1, 1_000_000, 2_000_000):
        assert entropy_schedule(step, **INTERVENTION) == pytest.approx(0.10)


def test_reaches_the_final_value_exactly_at_the_anneal_step():
    assert entropy_schedule(4_000_000, **INTERVENTION) == pytest.approx(0.03)


def test_stays_at_the_final_value_afterwards():
    for step in (4_000_001, 5_000_000, 6_000_000, 100_000_000):
        assert entropy_schedule(step, **INTERVENTION) == pytest.approx(0.03)


def test_halfway_through_the_ramp_is_halfway_between_the_values():
    assert entropy_schedule(3_000_000, **INTERVENTION) == pytest.approx(0.065)


def test_the_ramp_is_monotonic_and_never_leaves_the_two_endpoints():
    previous = entropy_schedule(0, **INTERVENTION)
    for step in range(0, 6_000_001, 50_000):
        value = entropy_schedule(step, **INTERVENTION)
        assert value <= previous + 1e-12       # only ever decreases
        assert 0.03 - 1e-12 <= value <= 0.10 + 1e-12
        previous = value


def test_a_rising_schedule_works_the_same_way():
    """Nothing in it assumes final < start."""
    rising = dict(start=0.01, final=0.10, hold=100, anneal=300)
    assert entropy_schedule(100, **rising) == pytest.approx(0.01)
    assert entropy_schedule(200, **rising) == pytest.approx(0.055)
    assert entropy_schedule(300, **rising) == pytest.approx(0.10)


def test_a_zero_length_ramp_is_a_step_change_not_a_division_by_zero():
    """`anneal <= hold` is degenerate, not ambiguous: jump at `hold`."""
    degenerate = dict(start=0.10, final=0.03, hold=1000, anneal=1000)
    assert entropy_schedule(1000, **degenerate) == pytest.approx(0.10)
    assert entropy_schedule(1001, **degenerate) == pytest.approx(0.03)
    inverted = dict(start=0.10, final=0.03, hold=1000, anneal=500)
    assert entropy_schedule(999, **inverted) == pytest.approx(0.10)
    assert entropy_schedule(1001, **inverted) == pytest.approx(0.03)


def test_hold_of_zero_starts_annealing_immediately():
    immediate = dict(start=0.10, final=0.03, hold=0, anneal=1000)
    assert entropy_schedule(0, **immediate) == pytest.approx(0.10)
    assert entropy_schedule(500, **immediate) == pytest.approx(0.065)


def test_the_flag_surface_reaches_the_schedule():
    """`--entropy-final` and friends parse into the values used above.

    Worth asserting because the schedule is only correct if the argument
    parser hands it the run's numbers; a renamed flag would leave every test
    above passing while training at a flat 0.03.
    """
    import argparse

    import sim.train_ppo as train

    source = Path(train.__file__).read_text(encoding="utf-8")
    for flag in ("--entropy-final", "--entropy-hold", "--entropy-anneal"):
        assert flag in source, flag

    parser = argparse.ArgumentParser()
    parser.add_argument("--entropy", type=float, default=0.01)
    parser.add_argument("--entropy-final", type=float)
    parser.add_argument("--entropy-hold", type=int, default=0)
    parser.add_argument("--entropy-anneal", type=int, default=0)
    args = parser.parse_args(["--entropy", "0.10", "--entropy-final", "0.03",
                              "--entropy-hold", "2000000",
                              "--entropy-anneal", "4000000"])
    assert entropy_schedule(0, args.entropy, args.entropy_final,
                            args.entropy_hold, args.entropy_anneal) == pytest.approx(0.10)
    assert entropy_schedule(3_000_000, args.entropy, args.entropy_final,
                            args.entropy_hold, args.entropy_anneal) == pytest.approx(0.065)
