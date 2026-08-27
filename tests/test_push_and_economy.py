"""Push plans, enemy elixir, and the advisor's contract with the policy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain import push  # noqa: E402
from brain.advisor import Advice, Advisor  # noqa: E402
from brain.economy import EnemyEconomy  # noqa: E402


# ------------------------------------------------------------------ economy

def test_enemy_elixir_regenerates_at_the_verified_rate():
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.tick(now=2.8, multiplier=1.0)
    assert abs(economy.elixir - 6.0) < 0.01
    economy.tick(now=2.8 + 1.4, multiplier=2.0)
    assert abs(economy.elixir - 7.0) < 0.01


def test_enemy_elixir_is_charged_for_what_they_play():
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.observe_spawns([("giant", 5, 6.0)], now=0.1)
    assert abs(economy.elixir - 0.0) < 0.01
    assert economy.is_committed


def test_a_multi_unit_card_is_charged_once():
    """Three Barbarians are one five-elixir card, not fifteen elixir."""
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    for _ in range(3):
        economy.observe_spawns([("barbarian", 5, 6.0)], now=0.1)
    assert abs(economy.elixir - 0.0) < 0.01
    assert economy.spent == 5


def test_a_unit_reacquired_in_our_half_is_not_a_new_card():
    """The tracker loses and re-finds units mid-fight.  Billing those pinned
    the estimate at zero for a whole match, so the bot believed every moment
    was a punish window."""
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.observe_spawns([("giant", 5, 24.0)], now=1.0)   # deep in our half
    assert economy.elixir == 5.0
    assert economy.spent == 0


def test_the_same_card_is_not_billed_twice_on_a_flickering_track():
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.observe_spawns([("musketeer", 4, 8.0)], now=1.0)
    economy.observe_spawns([("musketeer", 4, 9.0)], now=4.0)
    assert economy.spent == 4


def test_a_unit_that_never_left_the_field_is_billed_once_however_long_it_lives():
    """The live failure this fixes: `enemy_elixir` read 0.0-1.3 on every logged
    play of an entire block.  `tracker.STALE_SECONDS` is 2.5, so a unit the
    detector loses for three seconds in a fight returns as a fresh track, and
    the six-second dedupe window expires under any fight lasting longer than it.
    Passing `visible` keeps the timer alive while the unit is still on screen.
    """
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    # A Musketeer lands and then survives a thirty-second fight, flickering out
    # of the detector's view repeatedly on the way.
    economy.observe_spawns([("musketeer", 4, 8.0)], now=1.0, visible=["musketeer"])
    for t in range(2, 32):
        seen = [("musketeer", 4, 12.0)] if t % 4 == 0 else []   # re-acquired
        economy.observe_spawns(seen, now=float(t), visible=["musketeer"])
    assert economy.spent == 4, "one card, one charge"

    # Once it dies and the dedupe window passes, a genuinely new one bills again.
    economy.observe_spawns([("musketeer", 4, 8.0)], now=40.0, visible=["musketeer"])
    assert economy.spent == 8


def test_recent_spend_is_the_punish_signal_not_the_running_estimate():
    """The integrated estimate drifts low, so "their bar is empty" was true
    nearly always and every moment looked like a punish window."""
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    assert economy.recent_spend(now=1.0) == 0
    economy.observe_spawns([("golem", 8, 5.0)], now=10.0)
    assert economy.recent_spend(now=11.0) == 8
    assert economy.recent_spend(now=20.0) == 0, "the window must expire"


def test_spawned_children_are_free():
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.observe_spawns([("skeleton", 0, 6.0), ("golemite", 0, 6.0)], now=0.1)
    assert economy.elixir == 5.0


def test_elixir_never_leaves_its_range():
    economy = EnemyEconomy()
    economy.reset(now=0.0)
    economy.tick(now=999.0, multiplier=1.0)
    assert economy.elixir == 10.0
    economy.observe_spawns([("golem", 8, 5.0)], now=999.1)
    economy.observe_spawns([("pekka", 7, 5.0)], now=1005.0)
    assert economy.elixir >= 0.0


# --------------------------------------------------------------------- push

def test_the_default_push_leads_with_the_tank():
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    assert [step.card for step in plan.steps] == ["ice_golem", "hog_rider", "ice_spirit"]
    assert plan.steps[1].delay == 1.0, "Hog follows about a second behind the Golem"
    assert plan.steps[2].role == "freeze" and plan.steps[2].optional
    # `total_cost` is what the push must be able to pay for to be worth
    # starting, so the optional freeze is excluded. Requiring all seven up front
    # meant the push rarely started at all.
    assert plan.total_cost == 6


def test_the_freeze_follows_close_enough_to_matter():
    """Ice Spirit and Hog Rider share `Speed = 120`, so any delay is pure
    lateness. At 1.2s the freeze landed after the defence had engaged."""
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    assert plan.steps[2].delay <= 0.5


def test_an_unaffordable_optional_step_is_skipped_not_waited_on():
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    plan.advance(now=1.0)      # golem played
    plan.advance(now=2.0)      # hog played
    assert plan.current.card == "ice_spirit"
    plan.skip(now=2.5)
    assert plan.done, "skipping the last optional step completes the push"


def test_a_plan_is_not_built_from_cards_we_do_not_hold():
    assert push.build_plan("golem_hog", "left", {"hog_rider": 0}, now=0.0) is None
    assert push.build_plan("punish", "left", {"ice_golem": 0}, now=0.0) is None


def test_steps_wait_for_their_delay():
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    assert plan.ready(0.0)                 # first step goes immediately
    plan.advance(now=10.0)
    assert not plan.ready(10.5)            # too soon for the Hog
    assert plan.ready(11.1)


def test_a_plan_expires_so_it_cannot_haunt_a_later_fight():
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    assert not push.expired(plan, now=1.0)
    assert push.expired(plan, now=push.PLAN_EXPIRY_SECONDS + 1)


def test_remaining_cost_shrinks_as_the_push_is_paid_for():
    plan = push.build_plan("golem_hog", "left", {"ice_golem": 0, "hog_rider": 1}, now=0.0)
    # remaining_cost counts every step left, optional included; total_cost
    # counts only what starting the push commits to.
    assert plan.remaining_cost == 7
    assert plan.total_cost == 6
    plan.advance(now=1.0)
    assert plan.remaining_cost == 5


# ------------------------------------------------------------------ advisor

def test_advice_goes_stale():
    advice = Advice("push", "hog_rider", "left", "bridge", at=100.0)
    assert advice.fresh(now=101.0, max_age=3.0)
    assert not advice.fresh(now=110.0, max_age=3.0)


def test_the_prompt_carries_the_state_the_model_needs():
    advisor = Advisor()
    prompt = advisor.build_prompt({
        "elixir": 7.0, "enemy_elixir": 2.0, "multiplier": 1.0, "elapsed": 42,
        "ally_hp": [1.0, 0.5], "enemy_hp": [0.3, 1.0],
        "hand": ["hog_rider", "ice_golem"],
        "enemies": [{"name": "giant", "lane": "left", "depth": 3}],
    })
    for needle in ("7.0", "2.0", "hog_rider", "giant", "left"):
        assert needle in prompt, needle


def test_a_dead_ollama_yields_no_advice_rather_than_an_exception():
    advisor = Advisor(url="http://127.0.0.1:9/none", timeout=0.2)
    assert advisor._ask({
        "elixir": 5.0, "enemy_elixir": 5.0, "multiplier": 1.0, "elapsed": 1,
        "ally_hp": [1.0, 1.0], "enemy_hp": [1.0, 1.0], "hand": [], "enemies": [],
    }) is None
    assert advisor.failures == 1
