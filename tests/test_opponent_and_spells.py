"""Opponent cycle tracking, and spell damage against towers.

Both encode numbers taken from the client's own data rather than recalled, and
both replace a guess the bot was previously making badly: "can they answer this
Hog" was inferred from a drifting elixir estimate, and "can this Fireball finish
that tower" was a hand-set threshold that happened to be wrong by threefold.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain import spellinfo  # noqa: E402
from brain.opponent import CYCLE_GAP, OpponentModel  # noqa: E402


# ------------------------------------------------------------------- spells

def test_a_fireball_takes_about_a_twentieth_of_a_tower():
    """700 damage at 25% crown-tower damage is 175 into 3346."""
    assert 0.045 <= spellinfo.tower_fraction("fireball") <= 0.06


def test_a_log_barely_scratches_a_tower():
    assert spellinfo.tower_fraction("the_log") <= 0.02


def test_the_finisher_only_fires_when_it_actually_kills():
    assert spellinfo.can_finish("fireball", 0.04)
    assert not spellinfo.can_finish("fireball", 0.15), \
        "0.15 was the old threshold and leaves the tower alive at ~10%"


def test_inbound_hog_damage_counts_toward_the_finish():
    """Finishing at 8% is right when a Hog mid-swing covers the difference."""
    assert not spellinfo.can_finish("fireball", 0.08)
    assert spellinfo.can_finish("fireball", 0.08, inbound=0.06)


def test_a_dead_tower_is_not_a_finish_target():
    assert not spellinfo.can_finish("fireball", 0.0)


def test_only_fireball_is_worth_chipping_with():
    assert spellinfo.worth_chipping("fireball", elixir=9, cost=4, multiplier=1.0)
    assert not spellinfo.worth_chipping("the_log", elixir=9, cost=2, multiplier=1.0), \
        "a Log is a quarter of the damage per elixir and the only swarm answer"


def test_chipping_needs_spare_elixir_but_less_of_it_in_double():
    assert not spellinfo.worth_chipping("fireball", elixir=5, cost=4, multiplier=1.0)
    assert spellinfo.worth_chipping("fireball", elixir=6, cost=4, multiplier=2.0)


# ----------------------------------------------------------------- opponent

def test_the_deck_is_learned_as_cards_appear():
    model = OpponentModel()
    model.observe(["giant", "musketeer"], now=1.0)
    model.observe(["cannon"], now=2.0)
    assert model.deck == ["giant", "musketeer", "cannon"]
    assert not model.deck_known


def test_spawned_children_are_not_counted_as_cards():
    """Golemites and Lava Pups are produced by a card that was already counted
    when its parent landed, so they carry cost 0 and must not inflate the cycle.

    Note `skeleton` is deliberately *not* in this list: it carries cost 1, and
    because sightings are deduped by name, one Skeletons card bills exactly once
    - which is what both the cycle count and the elixir estimate want.
    """
    model = OpponentModel()
    model.observe(["golemite", "lava_pup", "phoenix_egg"], now=1.0)
    assert model.deck == []


def test_a_card_just_played_cannot_be_back_in_hand():
    model = OpponentModel()
    model.observe(["cannon"], now=1.0)
    assert model.definitely_unavailable("cannon")
    # Four other cards must be played before it returns.
    for index, card in enumerate(["giant", "musketeer", "archer", "knight"]):
        model.observe([card], now=2.0 + index)
    assert not model.definitely_unavailable("cannon")


def test_the_cycle_gap_is_four():
    assert CYCLE_GAP == 4


def test_an_unseen_card_is_never_claimed_unavailable():
    model = OpponentModel()
    assert not model.definitely_unavailable("cannon")


def test_a_hog_is_free_only_once_their_answer_is_provably_away():
    model = OpponentModel()
    # Before seeing any answer, assume they have one - the same caution the
    # elixir estimate failed to apply.
    assert model.answer_ready()

    model.observe(["cannon"], now=1.0)
    assert not model.answer_ready(), "their only seen answer just went down"

    for index, card in enumerate(["giant", "musketeer", "archer", "knight"]):
        model.observe([card], now=2.0 + index)
    assert model.answer_ready(), "it has had time to cycle back"


def test_two_answers_means_both_must_be_away():
    model = OpponentModel()
    model.observe(["cannon"], now=1.0)
    model.observe(["skeletons"], now=2.0)
    assert not model.answer_ready()
    for index, card in enumerate(["giant", "musketeer", "archer", "knight"]):
        model.observe([card], now=3.0 + index)
    assert model.answer_ready()


def test_reset_clears_the_model_between_matches():
    model = OpponentModel()
    model.observe(["cannon", "giant"], now=1.0)
    model.reset()
    assert model.deck == [] and model.plays == 0 and model.answer_ready()
