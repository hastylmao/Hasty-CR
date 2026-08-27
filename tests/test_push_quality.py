"""The offence changes, tested as behaviour rather than as settings.

The owner's read after watching it play was that defence had become genuinely
good while the push was still "just hog alone" and not converting. These pin the
four things done about that: lane choice that avoids their defenders, a freeze
that arrives with the Hog, overtime aggression, and Fireball chip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain import arena  # noqa: E402
from brain.policy import Brain  # noqa: E402
from tests.test_brain import decide, make_state  # noqa: E402


@pytest.fixture
def brain():
    # learn=False on purpose. Brain() loads scripts/brain/learned.json, which the
    # live bot rewrites after every match, so a default Brain makes these tests
    # depend on whatever the bot learned minutes ago - they passed all evening
    # and then failed on a bandit bonus that had shifted underneath them.
    return Brain(learn=False)


def test_the_hog_goes_to_the_lane_their_defenders_are_not_in(brain):
    """A Hog into the lane they are already holding is a Hog into a prepared
    answer, which is most of why a lone Hog does not convert."""
    state = make_state(["hog_rider", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemies=[("knight", 3, 10), ("musketeer", 4, 9),
                                ("archer", 4, 11)])
    action = decide(brain, state)
    assert action is not None and action.card == "hog_rider", action.tag
    assert action.x > arena.CENTRE_X, "their defence is left, so attack right"


def test_lane_choice_still_prefers_a_weak_tower_over_an_empty_lane(brain):
    """Tower HP outranks board position: a tower at 30% is worth more than a
    marginally emptier lane."""
    state = make_state(["hog_rider", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemy_hp=(0.30, 0.95),
                       enemies=[("knight", 3, 10), ("archer", 4, 11)])
    action = decide(brain, state)
    assert action is not None and action.card == "hog_rider"
    assert action.x < arena.CENTRE_X, "chase the damaged tower"


def test_overtime_lowers_the_bar_for_sending_the_hog(brain):
    """Elixir refills in 0.9s in triple, so holding a full bar back costs more
    than it protects."""
    # Sit just under the single-elixir probe floor and just over the overtime
    # one, so the only thing that differs between the two cases is the clock.
    floor = brain.cfg("probe_min_elixir", 8)
    discount = brain.cfg("overtime_probe_discount", 3)
    elixir = floor - 1
    assert elixir > floor - discount, "test needs a gap between the two floors"

    hand = ["hog_rider", "cannon", "musketeer", "the_log"]
    early = decide(Brain(), make_state(hand, elixir=elixir), elapsed=30.0, now=1000.0)
    assert early is None or early.card != "hog_rider", \
        "below the single-elixir floor it should hold"

    late = decide(Brain(), make_state(hand, elixir=elixir), elapsed=250.0, now=2000.0)
    assert late is not None and late.card == "hog_rider", \
        f"should push in triple elixir, got {getattr(late, 'tag', None)}"


def test_a_spare_fireball_chips_the_tower(brain):
    """5.2% for four elixir is small, but it decides close games and there is
    nothing else to spend a held Fireball on.

    Note the hand deliberately has no Hog: a push is worth far more than a chip,
    and the bot preferring the Hog when it holds one is correct, not a failure.
    """
    state = make_state(["fireball", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemy_hp=(0.60, 0.90))
    action = decide(brain, state)
    assert action is not None and action.card == "fireball", action.tag
    assert action.y < arena.RIVER_Y, "aimed at their tower"
    assert action.tag.startswith("chip")


def test_a_push_outranks_a_chip(brain):
    """With a Hog in hand the Hog goes; the chip is what a spare Fireball does
    when there is no better use for it."""
    state = make_state(["fireball", "cannon", "hog_rider", "skeletons"], elixir=10,
                       enemy_hp=(0.60, 0.90))
    action = decide(brain, state)
    assert action is not None and action.card == "hog_rider", action.tag


def test_the_log_is_never_spent_chipping(brain):
    """A Log is a quarter of the damage per elixir and the deck's only answer
    to a ground swarm."""
    state = make_state(["the_log", "cannon", "musketeer", "hog_rider"], elixir=10,
                       enemy_hp=(0.60, 0.90))
    for tick in range(6):
        action = brain.decide(state, 30.0 + tick, 1000.0 + 3 * tick)
        if action is not None:
            assert not (action.card == "the_log" and action.tag.startswith("chip"))


def test_chip_does_not_pre_empt_a_real_defence(brain):
    """The Fireball is also the answer to a support cluster; chipping must never
    outrank using it on an actual push."""
    state = make_state(["fireball", "cannon", "musketeer", "hog_rider"], elixir=10,
                       enemies=[("archer", 4, 19), ("archer", 5, 19),
                                ("bomber", 4, 20)])
    action = decide(brain, state)
    assert action is not None
    assert not action.tag.startswith("chip"), action.tag
