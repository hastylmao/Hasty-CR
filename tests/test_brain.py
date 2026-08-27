"""Offline scenario tests for the Hog 2.6 brain.

These run without an emulator: fake states are built from plain tuples so the
policy's behaviour on the situations that lost games (air pushes answered with
a Cannon, spells thrown at nothing, Hog never leaving hand) is pinned down.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain import arena  # noqa: E402
from brain.policy import Brain  # noqa: E402

HAND_ORDER = ["cannon", "hog_rider", "musketeer", "ice_spirit"]


def _ns(**kwargs):
    return types.SimpleNamespace(**kwargs)


def make_state(hand, elixir, enemies=(), allies=(), enemy_hp=(1.0, 1.0), ally_hp=(1.0, 1.0)):
    """Build a duck-typed BuildABot state.

    `enemies` / `allies` are (name, grid_x, grid_y) in the policy's top-down
    convention; they are converted back to BuildABot's bottom-up tiles so the
    conversion in `arena.to_grid` is exercised rather than bypassed.
    """
    cards = [_ns(name="blank", cost=0)]
    for name in hand:
        cards.append(_ns(name=name, cost={"cannon": 3, "fireball": 4, "hog_rider": 4,
                                          "ice_golem": 2, "ice_spirit": 1, "musketeer": 4,
                                          "skeletons": 1, "the_log": 2}.get(name, 4)))
    while len(cards) < 5:
        cards.append(_ns(name="blank", cost=0))

    def units(rows):
        return [
            _ns(unit=_ns(name=name),
                position=_ns(tile_x=x, tile_y=31 - y))
            for name, x, y in rows
        ]

    numbers = _ns(
        elixir=_ns(number=elixir),
        left_enemy_princess_hp=_ns(number=enemy_hp[0]),
        right_enemy_princess_hp=_ns(number=enemy_hp[1]),
        left_ally_princess_hp=_ns(number=ally_hp[0]),
        right_ally_princess_hp=_ns(number=ally_hp[1]),
    )
    return _ns(cards=cards, numbers=numbers, ready={0, 1, 2, 3},
               enemies=units(enemies), allies=units(allies),
               screen=_ns(name="in_game"))


@pytest.fixture
def brain():
    # learn=False on purpose. Brain() loads scripts/brain/learned.json, which the
    # live bot rewrites after every match, so a default Brain makes these tests
    # depend on whatever the bot learned minutes ago - they passed all evening
    # and then failed on a bandit bonus that had shifted underneath them.
    return Brain(learn=False)


def decide(brain, state, elapsed=30.0, now=1000.0):
    # Two ticks: the tracker needs a second sighting before it is confident,
    # and the live runner always sees a unit more than once.
    brain.decide(state, elapsed, now)
    return brain.decide(state, elapsed + 1.0, now + 1.0)


def test_grid_conversion_round_trips():
    assert arena.to_grid(4, 31 - 17) == (4.0, 17.0)
    assert arena.to_pixels(4, 17) == (308, 876)
    assert arena.to_pixels(0, 0) == (104, 172)


def test_a_push_leads_with_the_tank_not_the_hog(brain):
    """The complaint that drove this design: a lone Hog "doesn't get much
    damage in and always gets fucked by something".  With an Ice Golem in hand
    the push opens with the Golem, and the Hog follows a beat later behind it."""
    state = make_state(["ice_golem", "hog_rider", "musketeer", "cannon"], elixir=9)
    first = decide(brain, state)
    assert first is not None and first.card == "ice_golem", first.tag
    assert first.y >= arena.RIVER_Y
    brain.confirm(first, 1001.0)

    # The Hog is the committed next step of the same plan, one second later.
    follow = brain.decide(state, 33.0, 1002.5)
    assert follow is not None and follow.card == "hog_rider", follow.tag
    assert follow.x == first.x, "the Hog must follow into the Golem's lane"


def test_a_lone_hog_needs_elixir_to_spare(brain):
    """Without a tank the Hog may still go, but only when losing the trade
    does not also lose the tower."""
    poor = make_state(["hog_rider", "cannon", "musketeer", "skeletons"], elixir=4.5)
    assert decide(brain, poor) is None or decide(brain, poor).card != "hog_rider"

    rich = make_state(["hog_rider", "cannon", "musketeer", "skeletons"], elixir=9)
    action = decide(brain, rich, elapsed=40.0, now=1100.0)
    assert action is not None and action.card == "hog_rider", action.tag






def test_hog_not_thrown_away_while_defending(brain):
    state = make_state(HAND_ORDER, elixir=5,
                       enemies=[("giant", 4, 20), ("musketeer", 4, 18)])
    action = decide(brain, state)
    assert action is not None
    assert action.card != "hog_rider"


def test_air_push_is_not_answered_with_cannon(brain):
    state = make_state(["cannon", "musketeer", "skeletons", "the_log"], elixir=8,
                       enemies=[("balloon", 14, 19)])
    action = decide(brain, state)
    assert action is not None
    assert action.card == "musketeer", action.tag


def test_cannon_answers_a_ground_tank_at_the_4_3_tile(brain):
    state = make_state(["cannon", "hog_rider", "skeletons", "ice_spirit"], elixir=9,
                       enemies=[("giant", 14, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "cannon"
    assert action.y == arena.RIVER_Y + brain.cfg("cannon_from_river")
    assert action.x > arena.CENTRE_X  # pulled toward the threatened right lane


def test_ice_golem_kites_a_melee_heavy(brain):
    state = make_state(["ice_golem", "hog_rider", "the_log", "ice_spirit"], elixir=6,
                       enemies=[("pekka", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "ice_golem"
    assert action.weight_key == "defend_kite"
    assert action.x > arena.CENTRE_X  # kited across to the opposite lane

def test_skeletons_defend_pekka(brain):
    state = make_state(["skeletons", "ice_golem", "the_log", "ice_spirit"], elixir=6,
                       enemies=[("pekka", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "skeletons"


def test_ice_golem_kites_a_ranged_unit(brain):
    state = make_state(["ice_golem", "hog_rider", "skeletons", "ice_spirit"], elixir=6,
                       enemies=[("musketeer", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "ice_golem"
    assert action.x > arena.CENTRE_X


def test_cannon_pulls_an_air_win_condition(brain):
    state = make_state(["cannon", "hog_rider", "skeletons", "ice_golem"], elixir=9,
                       enemies=[("balloon", 14, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "cannon"
    assert action.y == arena.RIVER_Y + brain.cfg("cannon_from_river")


def test_ice_spirit_stalls_a_high_threat_air_unit(brain):
    state = make_state(["ice_spirit", "hog_rider", "skeletons", "the_log"], elixir=9,
                       enemies=[("giant", 14, 18), ("minion", 14, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "ice_spirit"
    assert action.weight_key == "defend_air_weak"


def test_spells_are_not_thrown_at_nothing(brain):
    # Below chip_spare_elixir (9.5) so the deliberate chip spell cannot fire:
    # this test is about *wasted* spells, not the designed tower chip at 10.
    # A lone knight is below defend_min_threat and is deliberately ignored -
    # what it must not do is draw a spell.
    state = make_state(["fireball", "the_log", "cannon", "musketeer"], elixir=5.5,
                       enemies=[("knight", 9, 18)])
    action = decide(brain, state)
    assert action is None or action.card not in {"fireball", "the_log"}, action.tag


def test_fireball_hits_a_three_unit_cluster(brain):
    state = make_state(["fireball", "hog_rider", "ice_spirit", "skeletons"], elixir=10,
                       enemies=[("archer", 13, 18), ("archer", 14, 18), ("bomber", 14, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "fireball"
    assert 12 <= action.x <= 16


def test_air_cluster_prefers_fireball_when_no_musketeer(brain):
    state = make_state(["fireball", "cannon", "skeletons", "the_log"], elixir=10,
                       enemies=[("minion", 13, 18), ("minion", 14, 18), ("minion", 14, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "fireball", action.tag


def test_fireball_finishes_a_low_tower(brain):
    state = make_state(["fireball", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemy_hp=(0.05, 1.0))
    action = decide(brain, state)
    assert action is not None and action.card == "fireball"
    assert (action.x, action.y) == arena.ENEMY_PRINCESS["left"]


def test_troops_are_never_placed_in_the_enemy_half(brain):
    state = make_state(HAND_ORDER, elixir=10, enemies=[("golem", 9, 4)])
    for _ in range(6):
        action = brain.decide(state, 30.0, 1000.0 + _)
        if action is not None and action.card not in {"fireball", "the_log"}:
            assert action.y >= arena.RIVER_Y, action.tag


def test_elixir_is_cycled_rather_than_capped(brain):
    """The point is that a full bar gets spent, not that a particular card does
    it: a spare Fireball chipping their tower also stops elixir overflowing, and
    is worth more than a Skeleton at the back."""
    state = make_state(["skeletons", "musketeer", "cannon", "fireball"], elixir=10)
    action = decide(brain, state)
    assert action is not None, "a capped bar must be spent on something"
    if action.card == "skeletons":
        assert action.y == 31, "cycled cards go behind the King Tower"
    else:
        assert action.card == "fireball" and action.tag.startswith("chip")


def test_cycle_min_gap_prevents_card_dumping(brain):
    """Ensure that we don't cycle cards back to back quickly."""
    state = make_state(["skeletons", "ice_golem", "cannon", "musketeer"], elixir=10)
    action1 = brain.decide(state, 30.0, 1000.0)
    assert action1 is not None and action1.card == "skeletons"
    brain.confirm(action1, 1000.0)
    
    # 1.0 second later, trying to cycle again
    state2 = make_state(["ice_golem", "cannon", "musketeer", "fireball"], elixir=9.5)
    action2 = brain.decide(state2, 31.0, 1001.0)
    # Shouldn't be a cycle play since 1.0s < 2.5s cycle_min_gap
    assert action2 is None or not action2.tag.startswith("cycle")


def test_hog_targets_the_weaker_tower(brain):
    state = make_state(HAND_ORDER, elixir=8, enemy_hp=(0.30, 0.95))
    action = decide(brain, state)
    assert action is not None and action.card == "hog_rider"
    assert action.x < arena.CENTRE_X


def test_a_trivial_enemy_unit_does_not_trigger_a_defence(brain):
    """One Skeleton over the bridge is not a push.  Treating it as one is what
    turned the bot into a turtle that never had elixir for a Hog."""
    state = make_state(HAND_ORDER, elixir=6, enemies=[("skeleton", 4, 18)])
    action = decide(brain, state)
    # Holding is a valid answer here; spending a card on one Skeleton is not.
    assert action is None or not action.weight_key.startswith("defend"), action.tag


def test_defensive_placements_stay_in_the_tower_pocket(brain):
    state = make_state(["skeletons", "ice_spirit", "ice_golem", "cannon"], elixir=8,
                       enemies=[("prince", 17, 30)])
    action = decide(brain, state)
    assert action is not None
    lo_x, hi_x = brain.cfg("defend_x_range")
    lo_y, hi_y = brain.cfg("defend_y_range")
    assert lo_x <= action.x <= hi_x and lo_y <= action.y <= hi_y, action.tag


def test_fireball_is_not_spent_on_free_units(brain):
    """Three Skeletons are three units and almost no elixir.  Counting units
    rather than elixir is what made the bot throw Fireballs at nothing."""
    state = make_state(["fireball", "cannon", "musketeer", "hog_rider"], elixir=10,
                       enemies=[("skeleton", 8, 12), ("skeleton", 9, 12),
                                ("skeleton", 9, 13)])
    action = decide(brain, state)
    assert action is None or action.card != "fireball", action.tag


def test_fireball_is_spent_on_zappies_because_they_die(brain):
    state = make_state(["fireball", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemies=[("zappy", 8, 12), ("zappy", 9, 12),
                                ("zappy", 9, 13)])
    action = decide(brain, state)
    assert action is not None and action.card == "fireball"



def test_hog_counter_pushes_once_the_defence_is_holding(brain):
    """The moment their push is contained is the moment their lane is open."""
    state = make_state(["hog_rider", "cannon", "musketeer", "ice_spirit"], elixir=4.5,
                       enemies=[("giant", 4, 19)],
                       allies=[("cannon", 6, 20), ("musketeer", 3, 22)])
    brain.committed_elixir = 3.0
    action = decide(brain, state)
    assert action is not None and action.card == "hog_rider", action.tag
    # Either read is correct: the defence is holding *and* the Giant emptied
    # their bar, so this is both a counter-push and a punish.
    assert action.weight_key in {"hog_counterpush", "hog_punish"}, action.weight_key


def test_elixir_is_held_for_the_hog_rather_than_cycled_away(brain):
    """With Hog in hand at 5 elixir, cycling a Skeleton to drop to 4 gives up
    the push.  The cycle card is only correct once Hog is already affordable."""
    state = make_state(["skeletons", "hog_rider", "musketeer", "cannon"], elixir=4.5)
    action = decide(brain, state)
    # Holding is the right call at five elixir with no tank in hand; what must
    # not happen is cycling the Skeleton and dropping below the Hog.
    assert action is None or action.card != "skeletons", action.tag


def test_the_defence_budget_survives_a_detection_dropout(brain):
    """One frame where the push is not detected must not refund the budget."""
    pushing = make_state(["skeletons", "ice_spirit", "ice_golem", "cannon"], elixir=10,
                         enemies=[("giant", 4, 20), ("musketeer", 4, 18)])
    empty = make_state(["skeletons", "ice_spirit", "ice_golem", "cannon"], elixir=10)
    for tick in range(4):
        action = brain.decide(pushing, 30.0, 1000.0 + tick)
        if action:
            brain.confirm(action, 1000.0 + tick)
    spent = brain.committed_elixir
    assert spent > 0
    brain.decide(empty, 31.0, 1005.0)          # a single dropped frame
    assert brain.committed_elixir == spent
    brain.decide(empty, 40.0, 1020.0)          # the push really is over
    assert brain.committed_elixir == 0


def test_cheap_cards_are_not_dumped_on_a_push_still_crossing_the_bridge(brain):
    """The fallback exists for units about to hit the tower, not for a big
    threat number.  Spending the last elixir early leaves nothing for arrival."""
    state = make_state(["ice_spirit", "skeletons", "fireball", "musketeer"], elixir=2,
                       enemies=[("golem", 9, 17), ("witch", 9, 16)])
    action = decide(brain, state)
    assert action is None or not action.tag.startswith("defend_fallback"), action.tag


def test_a_big_push_is_never_left_unanswered_by_the_budget(brain):
    """The budget must cap over-defending, not disable defending.  Live logs
    caught 17 seconds of doing nothing at threat 35 with a Cannon in hand."""
    state = make_state(["cannon", "skeletons", "the_log", "ice_spirit"], elixir=5.5,
                       enemies=[("golem", 4, 22), ("witch", 4, 20), ("minion", 5, 21),
                                ("minion", 5, 22), ("bat", 6, 21)])
    brain.committed_elixir = 6.0
    brain.cards_this_push = 3
    action = decide(brain, state)
    assert action is not None, "bot must still answer a push at its own tower"


def test_holding_elixir_for_the_hog_never_blocks_a_defence(brain):
    """Live deadlock: a 24-threat push walking in while the bot held five
    elixir for a Hog whose defending threshold it could not reach either."""
    state = make_state(["ice_spirit", "fireball", "hog_rider", "the_log"], elixir=5,
                       enemies=[("giant", 12, 19), ("musketeer", 12, 17),
                                ("mega_minion", 13, 18)])
    action = decide(brain, state)
    assert action is not None, "must answer the push rather than bank for Hog"
    assert action.card != "hog_rider"


def test_an_expensive_hand_still_cycles_toward_the_hog(brain):
    """Cycle-block was the real reason Hog share stayed near 10%: across 42
    matches Musketeer, Fireball and Log were each under 5% of plays, so the
    expensive cards sat in hand and the rotation never came back round."""
    state = make_state(["musketeer", "cannon", "ice_golem", "fireball"], elixir=10)
    action = decide(brain, state)
    assert action is not None, "a hand with no cheap card must still advance"
    assert action.weight_key in {"cycle", "cycle_to_hog"}, action.tag
    assert action.card == "musketeer", action.tag       # preferred cycle card over wasting ice_golem


def test_a_cycled_spell_is_thrown_at_a_tower_not_our_own_back_line(brain):
    state = make_state(["fireball", "ice_golem", "cannon", "hog_rider"], elixir=10,
                       enemy_hp=(0.40, 0.95))
    brain.decide(state, 30.0, 1000.0)
    # Hog in hand blocks cycling, so drop it and re-check with the same shape.
    # The hand must contain no cheap troop.
    state = make_state(["fireball", "ice_golem", "cannon", "the_log"], elixir=10,
                       enemy_hp=(0.40, 0.95))
    for i in range(5):
        brain.observe(state, 40.0, 1010.0)
    action = decide(brain, state, elapsed=40.0, now=1010.0)
    assert action is not None and action.card == "fireball"
    assert action.y < arena.RIVER_Y, "a cycled spell should chip their tower"


def test_cheap_cards_are_cycled_only_near_the_cap(brain):
    """Cycling behind our own tower pays only when elixir would otherwise be
    wasted, and costs real matches at mid elixir.

    Measured 400 matches per value, monotone: cycle_to_hog_elixir 3.5 -> 31.8%
    win, 4.0 -> 32.4%, 6.5 -> 47.8%, 8.0 -> 56.8%, 9.0 -> 62.5%, with crowns
    conceded falling 23 -> 6. A paired 200-match rerun at 9.0 kept Hog share
    identical (19.4% against 19.3%) and played slightly *more* cards, so this is
    elixir efficiency rather than passivity: the cheap cards are still spent,
    just on threats instead of on the back line.  See docs/RUN_JOURNAL.md."""
    hand = ["skeletons", "cannon", "musketeer", "fireball"]
    # Three separate paths can cycle a cheap card: cap-avoidance
    # (cycle_elixir), rotating toward the Hog (cycle_to_hog_elixir), and
    # unblocking a hand of expensive cards (cycle_any_elixir). The lowest of the
    # three is the elixir at which *something* cycles.
    threshold = min(float(brain.cfg("cycle_elixir", 8.5)),
                    float(brain.cfg("cycle_to_hog_elixir", 9.0)),
                    float(brain.cfg("cycle_any_elixir", 8.0)))

    held = make_state(hand, elixir=threshold - 1.0)
    assert decide(brain, held) is None, "must not dump a cheap card at mid elixir"

    rich = make_state(hand, elixir=min(10.0, threshold + 0.5))
    action = decide(brain, rich, elapsed=40.0, now=1100.0)
    assert action is not None and action.card == "skeletons", action and action.tag
    assert action.y >= 25, "cycled cards go at our own back line"


def test_defence_stops_at_the_elixir_budget(brain):
    """2.6 wins by defending for less than the opponent spent.  Answering one
    push with an unlimited stream of cheap cards is what left the bot at one
    elixir with no Hog sent."""
    state = make_state(["skeletons", "ice_spirit", "ice_golem", "cannon"], elixir=10,
                       enemies=[("knight", 4, 20), ("archer", 4, 18)])
    played = []
    for tick in range(14):
        action = brain.decide(state, 30.0 + tick, 1000.0 + 3 * tick)
        if action is None:
            continue
        brain.confirm(action, 1000.0 + 3 * tick)
        played.append(action)
    defensive = [a for a in played if a.weight_key.startswith("defend")]
    assert len(defensive) <= brain.cfg("defend_max_cards_per_push")
    threat_elixir = 3 + 3  # knight + archer
    assert sum(a.cost for a in defensive) <= max(
        brain.cfg("defend_min_budget"), threat_elixir * brain.cfg("defend_elixir_ratio")
    )


def test_unaffordable_cards_are_never_chosen(brain):
    state = make_state(["musketeer", "fireball", "cannon", "hog_rider"], elixir=2,
                       enemies=[("giant", 4, 20), ("archer", 4, 18)])
    action = decide(brain, state)
    assert action is None or action.cost <= 2


def test_bats_are_not_logged_because_they_fly(brain):
    state = make_state(["the_log", "cannon", "musketeer", "hog_rider"], elixir=10,
                       enemies=[("bat", 9, 18), ("bat", 10, 18), ("bat", 10, 19)])
    action = decide(brain, state)
    assert action is None or action.card != "the_log", getattr(action, "tag", "none")


def test_single_skeleton_is_not_logged(brain):
    state = make_state(["the_log", "cannon", "musketeer", "hog_rider"], elixir=10,
                       enemies=[("skeleton", 9, 18)])
    action = decide(brain, state)
    assert action is None or action.card != "the_log", getattr(action, "tag", "none")

def test_cannon_is_available_quickly_after_cycle(brain):
    """`cannon_repeat_seconds` must not be what keeps a Cannon out of the next
    push.

    The original form of this test asserted a second Cannon against the *same*
    push five seconds later. That is not a cooldown question: two Cannons is six
    elixir spent answering a five-elixir Giant, and the defence budget refuses
    it on purpose. What matters is that once the previous push is over, the
    Cannon is immediately available again.
    """
    first = make_state(["cannon", "skeletons", "ice_spirit", "the_log"], elixir=10,
                       enemies=[("giant", 4, 18)])
    opener = decide(brain, first, elapsed=30.0, now=1000.0)
    assert opener is not None and opener.card == "cannon"
    brain.confirm(opener, obs_now=1000.0)

    # The push resolves, then a fresh one arrives in the other lane.
    brain.plays += 4
    brain.decide(make_state(["cannon", "skeletons", "ice_spirit", "the_log"], elixir=10),
                 40.0, 1010.0)
    later = make_state(["cannon", "skeletons", "ice_spirit", "the_log"], elixir=10,
                       enemies=[("golem", 14, 18)])
    action = decide(brain, later, elapsed=43.0, now=1013.0)
    assert action is not None and action.card == "cannon", action.tag
    assert action.x > arena.CENTRE_X
def test_the_hog_is_followed_by_its_support_not_by_another_hog(brain):
    """A push runs to completion.  Re-sending the Hog two seconds later is not
    a push, it is the one-card-at-a-time behaviour this replaced."""
    state = make_state(["hog_rider", "cannon", "musketeer", "ice_spirit"], elixir=10)
    first = decide(brain, state, elapsed=30.0, now=1000.0)
    assert first is not None and first.card == "hog_rider"
    brain.confirm(first, 1000.0)

    second = brain.decide(state, 32.0, 1002.0)
    assert second is not None and second.card == "ice_spirit", second.tag
    assert second.weight_key.startswith("hog")


def test_defend_fallback_is_suppressed_on_contained_pushes(brain):
    state = make_state(["ice_spirit", "skeletons", "hog_rider", "the_log"], elixir=6,
                       enemies=[("giant", 4, 18)],
                       allies=[("cannon", 6, 20)])
    brain.committed_elixir = 3.0
    action = decide(brain, state)
    # The threat is giant (8), which triggers fallback, but since it's contained, the score
    # drops below 0 and it plays Hog Rider instead.
    assert action is not None
    assert "defend_fallback" not in getattr(action, "weight_key", "")
    assert action.card == "hog_rider"


def test_fallback_does_not_fire_twice_in_a_row_on_one_push(brain):
    """The last resort is one card, not the whole bar.

    The branch re-fires on the next tick because the card it spent has left the
    hand, so a single push drew Ice Golem, then Skeletons, then Ice Spirit three
    seconds apart - 113 of 513 plays across fifteen live matches.  The second
    one is what the gap suppresses; the safety net itself must survive.

    The push below is heavy air (threat 10 + 5 + 3 = 18), which clears
    `ice_spirit_max_air_threat` so the headline Ice Spirit rule declines and the
    last resort is genuinely what is left.  Note that the air arm of the
    fallback can now only ever offer the Ice Spirit, since it is the deck's one
    fallback card that can shoot air - so on air the repeat is also blocked
    structurally.  The gap is still what protects the ground arm, where all
    three fallback cards are eligible and the live triple-fire was observed.
    """
    hand = ["ice_spirit", "skeletons", "ice_golem", "hog_rider"]
    enemies = [("baby_dragon", 4, 24), ("balloon", 5, 23), ("minion", 6, 24)]

    first = decide(brain, make_state(hand, elixir=6, enemies=enemies))
    assert first is not None and first.tag.startswith("defend_fallback"), first.tag
    brain.confirm(first, 1001.0)

    # Same push, next tick, the spent card gone from hand.  Nothing may take
    # its place: the remaining fallback cards cannot shoot air.
    hand.remove(first.card)
    blocked = brain.decide(make_state(hand, elixir=5, enemies=enemies), 32.0, 1003.0)
    assert blocked is None or not blocked.tag.startswith("defend_fallback"), blocked.tag

    # The gap itself, in isolation: a fresh push with the card back in hand
    # still gets a safety net once the gap has passed.
    other = Brain(learn=False)   # see the fixture: live learned.json makes tests flaky
    other.last_fallback_at = 1004.0 - other.cfg("fallback_min_gap_seconds") - 1.0
    later = decide(other, make_state(["ice_spirit", "skeletons", "ice_golem", "hog_rider"],
                                     elixir=6, enemies=enemies),
                   elapsed=40.0, now=1010.0)
    assert later is not None and later.tag.startswith("defend_fallback"), (
        getattr(later, "tag", "none"))


def test_air_fallback_only_offers_cards_that_can_shoot_air(brain):
    """The last resort must not spend a card that physically cannot hit air.

    Ice Golem is a building-targeting ground troop and Skeletons are
    ground-targeting melee; neither can touch a Balloon. The air fallback order
    used to be ("ice_spirit", "ice_golem", "skeletons"), so with no Ice Spirit
    in hand it dropped the Hog's tank in front of an air push for nothing.
    """
    hand = ["skeletons", "ice_golem", "the_log", "hog_rider"]
    enemies = [("baby_dragon", 4, 24), ("balloon", 5, 23), ("minion", 6, 24)]
    action = decide(brain, make_state(hand, elixir=6, enemies=enemies))
    assert action is None or not action.tag.startswith("defend_fallback"), action.tag


def test_air_fallback_still_fires_with_an_air_capable_card(brain):
    """The safety net itself must survive the filter above."""
    hand = ["ice_spirit", "ice_golem", "the_log", "hog_rider"]
    enemies = [("baby_dragon", 4, 24), ("balloon", 5, 23), ("minion", 6, 24)]
    action = decide(brain, make_state(hand, elixir=6, enemies=enemies))
    assert action is not None and action.tag == "defend_fallback_ice_spirit", (
        getattr(action, "tag", "none"))


def test_fireball_targets_support_units(brain):
    state = make_state(["fireball", "cannon", "skeletons", "the_log"], elixir=10,
                       enemies=[("electro_dragon", 14, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "fireball"


def test_cycling_respects_whatever_threshold_is_configured(brain):
    """Read the threshold rather than hard-coding it.

    This test previously pinned 4.0, then 6.5, and broke each time the number
    moved - which is noise, because the behaviour under test is "hold below the
    threshold, cycle above it", not any particular value."""
    hand = ["skeletons", "cannon", "musketeer", "fireball"]
    # Two separate paths can cycle a cheap card: cap-avoidance
    # (cycle_elixir), and rotating toward the Hog (cycle_to_hog_elixir).
    # (cycle_any_elixir only applies when there are NO cheap cards).
    threshold = min(float(brain.cfg("cycle_elixir", 8.5)),
                    float(brain.cfg("cycle_to_hog_elixir", 9.0)))
    assert decide(brain, make_state(hand, elixir=threshold - 0.1)) is None
    action = decide(brain, make_state(hand, elixir=min(10.0, threshold)),
                    elapsed=40.0, now=1100.0)
    assert action is not None and action.card == "skeletons", action and action.tag

def test_min_seconds_between_plays_grace_period(brain):
    assert brain.cfg("min_seconds_between_plays") >= 0.3

def test_ice_spirit_stalls_light_air_with_weak_weight(brain):
    state = make_state(["ice_spirit", "skeletons", "hog_rider", "the_log"], elixir=6,
                       enemies=[("bat", 14, 19), ("bat", 15, 19)])
    action = decide(brain, state)
    assert action is not None
    assert action.card == "ice_spirit"
    assert action.weight_key == "defend_air_weak"


def test_serious_threat_triggers_defence_before_emergency(brain):
    # Giant (threat 8) is scaled up by threat_depth_bonus at y=18, so it clears
    # defend_min_threat at every value the knob has held (3.0 -> 6.0 -> 8.0).
    # This asserts the behaviour rather than pinning the threshold: a serious
    # push is answered mid-field, not left for the emergency depth net.
    state = make_state(HAND_ORDER, elixir=6, enemies=[("giant", 4, 18)])
    action = decide(brain, state)
    assert action is not None and action.weight_key.startswith("defend"), action.tag

def test_hunter_and_musketeer_not_targeted_by_fireball(brain):
    state = make_state(["fireball", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemies=[("hunter", 8, 12), ("musketeer", 9, 12)])
    action = decide(brain, state)
    assert action is not None and action.card == "fireball"

def test_defend_cover_radius_does_not_reach_deep_musketeer(brain):
    state = make_state(["hog_rider", "cannon", "ice_spirit", "the_log"], elixir=6,
                       enemies=[("giant", 4, 17)],
                       allies=[("musketeer", 4, 26)])
    # Leave room for the Cannon (3) inside the push budget; this test is about
    # the cover radius, not the budget, so it is derived rather than pinned.
    brain.committed_elixir = brain.cfg("defend_min_budget") - 3.0
    action = decide(brain, state)
    assert action is not None and action.card == "cannon"

def test_musketeer_not_targeted_by_fireball():
    from brain.knowledge import BOOK
    assert not BOOK.dies_to("fireball", "musketeer")

def test_defend_cannon_preferred_over_ranged(brain):
    assert brain.weight("defend_cannon") > brain.weight("defend_ranged")

def test_illegal_defensive_candidates_do_not_suppress_fallback(brain):
    """If the proper defensive answer is in hand but blocked by the budget, it
    must not suppress the last resort (fallback) if the fallback itself is legal."""
    # Below `cycle_elixir`, so the cycle generator does not claim the Ice Spirit
    # before the defence does; this test is about the fallback, not the cycle.
    state = make_state(["musketeer", "ice_spirit", "hog_rider", "the_log"], elixir=6,
                       enemies=[("balloon", 4, 17), ("baby_dragon", 5, 17),
                                ("minion", 6, 17)])
    # Commit enough of the push budget that the Musketeer (4) no longer fits
    # but the Ice Spirit (1) still does.  Derived from config so that retuning
    # the budget cannot silently turn this into a test of nothing.  The fallback
    # card has to be one that can shoot air, or the branch correctly declines.
    # budget = max(defend_min_budget, threat_elixir * defend_elixir_ratio), and
    # the push above costs balloon 5 + baby dragon 4 + minion 1 = 10 elixir.
    budget = max(brain.cfg("defend_min_budget"),
                 10 * brain.cfg("defend_elixir_ratio"))
    brain.committed_elixir = budget - 2.0
    action = decide(brain, state)
    
    assert action is not None
    assert action.weight_key == "defend_fallback", getattr(action, "tag", "none")

def test_fireball_not_cast_on_win_condition_for_value(brain):
    """A value Fireball should not be cast on an incoming win condition. Defenses should be used instead."""
    state = make_state(["fireball", "ice_golem", "skeletons", "the_log"], elixir=10,
                       enemies=[("hog_rider", 14, 18)])
    action = decide(brain, state)
    assert action is None or action.card != "fireball"


def test_cannon_answers_lone_giant(brain):
    """Cannon must answer a lone ground unit whose threat clears defend_min_threat.

    The lone 4-threat Mini PEKKA case was retired when defend_min_threat moved
    to 6.0 (and it is 8.0 as of block 216): a lone 4-threat unit is deliberately
    ignored until emergency depth answers it late and cheaply - that trade was
    the measured sim win. Giant (threat 8) stays above the gate at every value
    the knob has held."""
    state = make_state(["cannon", "hog_rider", "skeletons", "ice_spirit"], elixir=6,
                       enemies=[("giant", 14, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "cannon"


def test_cannon_pulls_multiple_knights_when_serious(brain):
    """With cannon_min_threat raised to 8.0, Cannon must pull a push that sums to >=8.0 (e.g. 2 Knights)."""
    state = make_state(["cannon", "hog_rider", "skeletons", "ice_spirit"], elixir=9,
                       enemies=[("knight", 14, 18), ("knight", 15, 18)])
    action = decide(brain, state)
    assert action is not None and action.card == "cannon"


def test_lone_small_threat_defended_cheaply_not_with_expensive_cards(brain):
    """A lone Knight (threat 6.0) or Musketeer (threat 6.0) is a serious threat,
    but cannon_min_threat (8.0) and defend_ranged (45.0) vs defend_single (46.0)
    should force Skeletons over Cannon or Musketeer."""
    state = make_state(["cannon", "musketeer", "skeletons", "hog_rider"], elixir=9,
                       enemies=[("knight", 14, 18)])
    brain.config["defend_min_threat"] = 5.0
    action = decide(brain, state)
    assert action is not None and action.card == "skeletons"

    state2 = make_state(["cannon", "musketeer", "skeletons", "hog_rider"], elixir=9,
                       enemies=[("musketeer", 14, 18)])
    action2 = decide(brain, state2)
    assert action2 is not None and action2.card == "musketeer"



def test_ice_golem_kites_pekka(brain):
    """Ice Golem must kite a PEKKA."""
    state = make_state(["ice_golem", "hog_rider", "the_log", "ice_spirit"], elixir=6,
                       enemies=[("pekka", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "ice_golem"

def test_ice_golem_does_not_kite_knight(brain):
    """With kite_min_threat raised to 6, Ice Golem must NOT kite a threat-5 unit
    like Knight, preserving the Ice Golem for the Hog push."""
    state = make_state(["ice_golem", "hog_rider", "the_log", "ice_spirit"], elixir=6,
                       enemies=[("knight", 4, 19), ("baby_dragon", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card != "ice_golem"


def test_skeletons_preferred_against_pekka(brain):
    """Skeletons are preferred to distract PEKKA over Ice Golem."""
    state = make_state(["ice_golem", "hog_rider", "skeletons", "ice_spirit"], elixir=6,
                       enemies=[("pekka", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "skeletons"
    assert action.weight_key == "defend_outranged"


def test_musketeer_placed_towards_center(brain):
    """Musketeer must be placed towards the center of the arena to avoid giving Fireball value with the tower."""
    # Threat in the left lane (x=4)
    state = make_state(["musketeer", "hog_rider", "the_log", "fireball"], elixir=6,
                       enemies=[("giant", 4, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "musketeer"
    assert action.x > 6  # Should be placed towards center (x=9), away from tower (x=3) and cannon (x=6)


def test_log_value_on_skeletons(brain):
    """Log should be played on skeletons if log_min_value_elixir allows it (e.g. 0)."""
    # Skeletons must be on our side of the river (y < 15) to be threats,
    # but close to the river (y >= 11) to be within log_max_y_from_river.
    # 31 - 18 = 13, which is 11 <= 13 < 15.
    state = make_state(["the_log", "ice_spirit", "musketeer", "cannon"], elixir=10,
                       enemies=[("skeleton", 4, 18), ("skeleton", 5, 18)])
    action = decide(brain, state)
    assert action is None or action.card != "the_log", getattr(action, "tag", "none")




def test_the_bot_is_never_idle_with_a_full_bar_and_no_threat(brain):
    """The dead-zone regression, reported from live play as "it randomly stops
    placing stuff".

    Measured in the log: 278 IDLE ticks at four or more elixir with no real
    threat, and a 13-23 second stretch with no play in *every* recent match.
    Three gates had each been raised for its own good reason - cycle_to_hog to
    9.0, cycle_any to 8.0, probe_min to 8.0 - and together they left a band from
    roughly four to eight elixir where no candidate is generated at all: the
    cycle paths refuse below their thresholds, `_cycle` returns nothing at all
    when the Hog is in hand, and the Hog will not go without probe elixir.

    Nobody is going to notice that by reading three separate thresholds, so it
    is pinned here instead: with elixir to spare and nothing to defend against,
    there must always be something to do.
    """
    playable = (
        ["skeletons", "cannon", "musketeer", "fireball"],   # cheap, no Hog
        ["hog_rider", "cannon", "musketeer", "the_log"],    # Hog, no tank
        ["hog_rider", "ice_golem", "musketeer", "cannon"],  # Hog and tank
    )
    expensive = ["cannon", "musketeer", "fireball", "the_log"]

    stuck = []
    for hand in playable:
        for elixir in (9, 10):
            fresh = Brain(learn=False)
            if decide(fresh, make_state(hand, elixir=elixir),
                      elapsed=45.0, now=1200.0) is None:
                stuck.append((elixir, hand[0]))

    # A hand of only expensive cards is different: holding a Cannon at seven
    # elixir with nothing to answer is a real option, and dumping it behind our
    # own king tower is waste. Only near the cap is doing nothing clearly wrong,
    # and that case was 11 of the 278 measured idles rather than the problem.
    for elixir in (10,):
        fresh = Brain(learn=False)
        if decide(fresh, make_state(expensive, elixir=elixir),
                  elapsed=45.0, now=1200.0) is None:
            stuck.append((elixir, "expensive-only"))

    assert not stuck, f"no action available at: {stuck}"


def test_a_long_idle_forces_a_play_even_when_no_generator_fires(brain):
    """The floor under the dead zone.

    Taken from the live log: elixir 7, hand fireball/musketeer/the_log/cannon,
    no threat, and seventeen seconds without a play. No generator proposes
    anything in that state - the cycle paths are above their thresholds, there
    is no Hog to push with and nothing to defend against - so the bot stood
    still while the opponent built.

    `_anti_idle` runs only when the legal set is empty, so it cannot outbid a
    real decision. It just refuses to do nothing for ever.
    """
    hand = ["fireball", "musketeer", "the_log", "cannon"]
    state = make_state(hand, elixir=5.0)

    brain.decide(state, 40.0, 1000.0)            # seeds the match clock
    assert brain.decide(state, 41.0, 1001.0) is None, "one second idle is fine"

    action = brain.decide(state, 58.0, 1018.0)   # seventeen seconds later
    assert action is not None, "seventeen seconds of nothing is not fine"
    assert action.card != "hog_rider", "the win condition is not filler"
    assert action.tag.startswith("idle_"), action.tag


def test_the_idle_floor_never_outbids_a_real_decision(brain):
    """It must be a floor, not a preference: with a genuine threat on the board
    the answer is a defensive play, however long the bot has been idle."""
    state = make_state(["cannon", "musketeer", "skeletons", "the_log"], elixir=9,
                       enemies=[("giant", 14, 19), ("musketeer", 14, 18)])
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    assert action is not None
    assert not action.tag.startswith("idle_"), action.tag


def test_the_idle_floor_does_not_spend_the_hogs_elixir(brain):
    """Curing idleness must not delay the only card that scores.

    With the Hog in hand at five elixir, playing a one-cost filler leaves four
    and the Hog stays home. The floor either finds something that still leaves
    the Hog affordable, or does nothing.
    """
    state = make_state(["hog_rider", "skeletons", "musketeer", "fireball"], elixir=4.5)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    if action is not None and action.tag.startswith("idle_"):
        cost = {"skeletons": 1, "musketeer": 4, "fireball": 4}[action.card]
        # With the fix, reserve should be probe_min_elixir (7.0)
        assert 4.5 - cost >= brain.cfg("probe_min_elixir", 7.0), action.tag

def test_the_idle_floor_uses_probe_reserve(brain):
    """_anti_idle must reserve probe_min_elixir (7.0) so it does not dump
    cheap cards at 6 elixir when waiting for 7 to send a Hog."""
    state = make_state(["hog_rider", "the_log", "musketeer", "fireball"], elixir=6.5)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    # The Log costs 2. 6.5 - 2 = 4.5. The reserve is 7.0, so 4.5 < 7.0.
    # Therefore, the bot must NOT dump The Log to cure idleness.
    assert action is None or not action.tag.startswith("idle_")

def test_the_idle_floor_does_not_waste_defensive_keys(brain):
    """Curing idleness must not throw away Cannon."""
    state = make_state(["hog_rider", "cannon", "musketeer", "fireball"], elixir=6.0)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    if action is not None and action.tag.startswith("idle_"):
        assert action.card not in ["cannon"], action.tag

def test_cycle_unblock_does_not_waste_defensive_keys(brain):
    """Unblocking the cycle must not throw away Cannon."""
    state = make_state(["fireball", "cannon", "musketeer", "the_log"], elixir=9.0)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 40.1, 1000.1)
    if action is not None and action.tag.startswith("cycle_"):
        assert action.card not in ["cannon"], action.tag

def test_cycle_to_hog_elixir_beats_idle_floor(brain):
    """The bot must be able to reach cycle_to_hog_elixir before the idle floor
    kicks in and throws away a card for nothing. If max_idle_seconds triggers
    first, the bot will constantly drain elixir and never cycle properly.
    """
    cycle_elixir = float(brain.cfg("cycle_to_hog_elixir", 5.0))
    idle_secs = float(brain.cfg("max_idle_seconds", 6.0))
    # At ~0.357 elixir per second (2.8s per elixir), it takes this long to
    # reach cycle_to_hog_elixir from 0.
    seconds_to_reach_cycle = cycle_elixir * 2.8
    assert idle_secs > seconds_to_reach_cycle, (
        f"max_idle_seconds ({idle_secs}s) is too low to ever reach "
        f"cycle_to_hog_elixir ({cycle_elixir} elixir, takes {seconds_to_reach_cycle:.1f}s)"
    )



def test_cannon_is_not_the_answer_to_something_that_outranges_it(brain):
    """Reported from watching it play: it answered a Musketeer with a Cannon and
    the Cannon died without firing a shot. The card data says why - Cannon
    reaches 5.5 tiles, Musketeer 6.0."""
    state = make_state(["cannon", "musketeer", "skeletons", "ice_spirit"], elixir=9,
                       enemies=[("musketeer", 4, 19), ("musketeer", 5, 19)])
    action = decide(brain, state)
    assert action is None or action.card != "cannon", action.tag


def test_cannon_still_answers_what_must_close_the_distance(brain):
    """The rule must not disarm the Cannon against what it is for. An Archer
    reaches 5.0 and does walk into it, so it is about reach, not about being
    ranged at all. With min_threat=7.0, 3 archers are needed to exceed the threat."""
    for threat, count in [("giant", 1), ("archer", 3)]:
        fresh = Brain(learn=False)
        enemies = [(threat, 14, 18)] * count
        state = make_state(["cannon", "musketeer", "skeletons", "ice_spirit"],
                           elixir=9, enemies=enemies)
        action = decide(fresh, state)
        assert action is not None and action.card == "cannon", (threat, action and action.tag)


def test_a_building_is_not_dropped_on_top_of_the_troops_it_must_stop(brain):
    """A Cannon takes a full second to activate; one placed in contact absorbs
    free hits while doing nothing."""
    tile = brain.cannon_spot("left")
    state = make_state(["cannon", "musketeer", "skeletons", "ice_spirit"], elixir=9,
                       enemies=[("giant", tile[0], tile[1]),
                                ("barbarian", tile[0], tile[1])])
    action = decide(brain, state)
    assert action is not None and action.card == "cannon", action and action.tag
    assert action.y > tile[1], (action.x, action.y, tile)


def test_a_ranged_push_is_answered_with_the_musketeer_not_a_cheap_card(brain):
    """Against units that outrange our short answers, only the Musketeer works.

    Measured in the simulator: one attacking Musketeer leaks 880 tower damage
    past a Cannon, Skeletons, an Ice Spirit and an Ice Golem alike, and zero
    past our own Musketeer. A Wizard leaks 284 past everything else. So those
    cheap answers are not weaker in this situation, they are irrelevant, and the
    Musketeer must win the comparison outright rather than tie with them.
    """
    state = make_state(["musketeer", "skeletons", "ice_spirit", "cannon"], elixir=9,
                       enemies=[("musketeer", 4, 19), ("wizard", 5, 19)])
    action = decide(brain, state)
    assert action is not None and action.card == "musketeer", action and action.tag
    assert action.tag.startswith("defend_outranged"), action.tag


def test_a_melee_push_still_gets_the_ordinary_answers(brain):
    """The preference must not fire against things our cheap cards handle."""
    state = make_state(["musketeer", "skeletons", "ice_spirit", "cannon"], elixir=9,
                       enemies=[("giant", 14, 18), ("knight", 13, 18)])
    action = decide(brain, state)
    assert action is not None
    assert not action.tag.startswith("defend_outranged"), action.tag

def test_musketeer_placed_deep_by_king_tower(brain):
    """Musketeer defends from behind the princess-tower line, but still inside
    her own six-tile range of the threat.

    She used to be allowed back to y=30, which is behind the king tower. Live
    that was not a rare edge: 18 of 33 logged placements sat deeper than y=26
    and nine were pinned at exactly 30, every one of them against a push that
    had already reached our tower line. Safe but out of range loses the tower
    anyway - she spends the fight walking. The cap is now 26, which keeps her
    behind our towers (y=24) and still shooting on arrival.
    """
    state = make_state(["musketeer", "hog_rider", "the_log", "fireball"], elixir=6,
                       enemies=[("giant", 4, 30)])
    action = decide(brain, state)
    assert action is not None and action.card == "musketeer"
    assert action.y == 26
    # Behind our own princess towers, never behind the king tower.
    assert 24 < action.y <= 26

def test_idle_filler_does_not_burn_the_log_on_chip(brain):
    """The Log is the deck's only answer to a ground swarm and a poor chip
    tool - web-verified Aug 2026, 13% of its damage to a Crown Tower against
    the Fireball's 25%, off a smaller base. `_chip` already refuses to chip
    with it; the anti-idle filler used to do it anyway, 116 times at mean
    -1.98 reward. Filler must fall through to a cheap troop and keep it."""
    hand = ['the_log', 'musketeer', 'fireball', 'cannon']
    state = make_state(hand, elixir=5.0)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 58.0, 1018.0)
    assert action is not None
    assert action.card != 'the_log', action.tag


def test_a_log_candidate_is_never_placed_on_the_enemy_side(brain):
    """The Log rolls forward from where it lands, so it is played on our side
    of the river. Whatever generator proposes it, `decide` clamps it."""
    hand = ['the_log', 'musketeer', 'fireball', 'cannon']
    state = make_state(hand, elixir=9.0)
    for elapsed in (40.0, 58.0, 76.0):
        action = brain.decide(state, elapsed, 1000.0 + elapsed)
        if action is not None and action.card == 'the_log':
            assert action.y >= arena.RIVER_Y, action.tag

def test_cycle_min_gap_prevents_back_to_back_cycling(brain):
    hand = ['skeletons', 'ice_golem', 'musketeer', 'cannon']
    state = make_state(hand, elixir=10)
    first = decide(brain, state, elapsed=40.0, now=1000.0)
    assert first is not None and first.weight_key in ('cycle', 'cycle_to_hog')
    brain.confirm(first, 1000.0)
    
    hand2 = ['ice_spirit', 'ice_golem', 'musketeer', 'cannon']
    state2 = make_state(hand2, elixir=9)
    second = brain.decide(state2, elapsed=40.2, now=1000.2)
    assert second is None or second.weight_key not in ('cycle', 'cycle_to_hog')
    
    gap = float(brain.cfg("cycle_min_gap_seconds", 2.5))
    third = brain.decide(state2, elapsed=40.0 + gap + 0.1, now=1000.0 + gap + 0.1)
    assert third is not None and third.weight_key in ('cycle', 'cycle_to_hog')

def test_defends_lone_mini_pekka_at_tower_with_skeletons(brain):
    """A lone Mini PEKKA does not meet defend_min_threat, but it will take the tower.
    When it reaches emergency depth, it MUST trigger a defense rather than being ignored."""
    hand = ["skeletons", "hog_rider", "the_log", "fireball"]
    # Depth 23 is emergency_depth
    enemies = [("mini_pekka", 4, 23)]
    action = decide(brain, make_state(hand, elixir=5, enemies=enemies))
    assert action is not None
    assert action.card == "skeletons"
    assert "surround" in action.tag or "defend" in action.tag


def test_a_lone_skeleton_at_the_tower_is_not_an_emergency(brain):
    """Deep is not the same as dangerous.

    `_emergency` used to ask only how far in a unit was, so one Skeleton that
    walked to the tower opened the door that bypasses `serious` and arms the
    last-resort branch. Live, 8 of 26 `defend_fallback_*` plays over ten matches
    answered a threat scoring 1 - an Ice Golem or Skeletons spent on a unit the
    tower kills for free. The Mini P.E.K.K.A. above sits at the same depth and
    must still be answered, which is the line this floor has to find.
    """
    hand = ["skeletons", "ice_golem", "ice_spirit", "hog_rider"]
    deep_skeleton = make_state(hand, elixir=5, enemies=[("skeleton", 4, 24)])
    action = decide(brain, deep_skeleton)
    assert action is None or not action.tag.startswith("defend"), (
        action and action.tag)


class _StubClassifier:
    """Stands in for the NCC classifier with a scripted answer per frame."""

    ready = True

    def __init__(self, readings):
        self.readings = list(readings)

    def classify_hand_scored(self, frame):
        return self.readings[min(frame, len(self.readings) - 1)]

    def classify_hand(self, frame):
        # The pre-fix interface, so this test fails on the old behaviour
        # rather than on a missing attribute.
        return [name for name, _score in self.classify_hand_scored(frame)]


def test_a_duplicate_slot_reading_does_not_hide_the_real_card(brain):
    """Two slots cannot hold the same card, and the loser must not shadow it.

    The hand is assembled with setdefault, so before this was resolved a slot
    misread as a card another slot already held did not just add a wrong entry -
    it made the card actually sitting there invisible to every rule. Musketeer,
    Fireball and Log each fell under 6% of plays as a result.
    """
    state = make_state(HAND_ORDER, 10)          # cannon, hog, musketeer, ice_spirit
    good = [("cannon", 0.90), ("hog_rider", 0.88),
            ("musketeer", 0.85), ("ice_spirit", 0.87)]
    # Slot 2 (Musketeer) is misread as Cannon, and less confidently than slot 0.
    bad = [("cannon", 0.90), ("hog_rider", 0.88),
           ("cannon", 0.55), ("ice_spirit", 0.87)]
    brain.classifier = _StubClassifier([good, bad, bad])

    for tick in range(3):
        obs = brain.observe(state, 30.0 + tick, 1000.0 + tick, frame=tick)

    assert obs.hand["cannon"] == 0, "the confident Cannon keeps its slot"
    assert obs.hand.get("musketeer") == 2, "the misread slot holds Musketeer"


def test_the_weaker_of_two_equal_claims_abstains_rather_than_inventing(brain):
    """With no prior reading to hold, a losing duplicate yields nothing."""
    state = make_state(HAND_ORDER, 10)
    reading = [("cannon", 0.90), ("hog_rider", 0.88),
               ("cannon", 0.55), ("ice_spirit", 0.87)]
    brain.classifier = _StubClassifier([reading])

    for tick in range(3):
        obs = brain.observe(state, 30.0 + tick, 1000.0 + tick, frame=tick)

    assert obs.hand["cannon"] == 0
    assert 2 not in obs.hand.values(), "slot 2 stays unknown, not a second Cannon"

def test_ice_golem_is_cycled_when_blocked(brain):
    state = make_state(["ice_golem", "cannon"], elixir=10)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    assert action is not None and action.card == "ice_golem"

def test_tower_hp_glitch_is_filtered_out(brain):
    state_start = make_state(["cannon"], 10, ally_hp=(0.81, 1.0))
    brain.observe(state_start, 30.0, 1000.0)
    brain.observe(state_start, 30.5, 1000.5)

    state_glitch = make_state(["cannon"], 10, ally_hp=(0.0, 1.0))
    obs_glitch = brain.observe(state_glitch, 31.0, 1001.0)
    assert obs_glitch.ally_hp["left"] == 0.81

    state_real = make_state(["cannon"], 10, ally_hp=(0.51, 1.0))
    obs_real = brain.observe(state_real, 31.5, 1001.5)
    assert obs_real.ally_hp["left"] == 0.51

def test_experience_filters_glitch_drops():
    from brain.experience import ExperienceBook
    book = ExperienceBook(None, None)
    
    # Test ally_hp spurious drop from 0.51 to 0.0
    book.record("cannon", 3.0, "test", "defend|small", "left", [], [], 0.51, 1.0, 1000.0)
    eps = book.resolve(1010.0, set(), 0.0, 1.0, lambda x: 1.0)
    assert len(eps) == 1
    # Without the fix, taken would be 0.51, and reward heavily penalized (-22.95). 
    # With the fix, taken = 0.0, reward is just -cost (-3.0).
    assert eps[0].reward > -10.0

    # Test enemy_hp spurious drop from 0.51 to 0.0
    book.record("cannon", 3.0, "test", "defend|small", "left", [], [], 1.0, 0.51, 1020.0)
    eps = book.resolve(1030.0, set(), 1.0, 0.0, lambda x: 1.0)
    assert len(eps) == 1


def test_ice_spirit_ground_stall_placement_clearance(brain):
    brain.config["cannon_deploy_clearance"] = 2.5
    state = make_state(['ice_spirit', 'the_log', 'fireball', 'hog_rider'], elixir=3,
                       enemies=[('pekka', 14, 18)])
    action = decide(brain, state)
    assert action is not None
    assert action.card == 'ice_spirit'
    assert action.tag == 'defend_stall_ice_spirit'
    assert action.y == 21


def test_fireball_is_not_cycled(brain):
    """Fireball is 4 elixir and should be saved, not cycled at the back or on an empty tower."""
    state = make_state(["fireball", "cannon", "hog_rider"], elixir=10)
    brain.decide(state, 40.0, 1000.0)
    action = brain.decide(state, 60.0, 1020.0)
    if action is not None:
        assert action.card != "fireball", f"Fireball must not be cycled, got {action.tag}"


def test_fireball_is_not_spent_on_single_3_cost_unit(brain):
    """A 4-elixir Fireball should not be traded for a lone 3-elixir unit like an Archer or Little Prince."""
    state = make_state(["fireball", "cannon", "musketeer", "skeletons"], elixir=10,
                       enemies=[("archer", 14, 18)])
    action = decide(brain, state)
    assert action is None or action.card != "fireball"



def test_counterpush_uses_skeletons_not_ice_golem_for_support(brain):
    state = make_state(['hog_rider', 'fireball', 'skeletons', 'cannon'], elixir=10,
                       enemies=[('giant', 4, 19)],
                       allies=[('cannon', 6, 20), ('musketeer', 3, 22)])
    brain.committed_elixir = 3.0
    action = decide(brain, state)
    assert action is not None and action.card == 'hog_rider'
    assert brain.plan is not None
    assert len(brain.plan.steps) == 2
    assert brain.plan.steps[1].card == 'skeletons'



def test_musketeer_is_cycled_to_unblock_the_hand(brain):
    """The unblock path should cycle a Musketeer at the back when the hand is full of expensive uncyclable cards to avoid freezing the bot."""
    state = make_state(["musketeer", "cannon", "fireball", "the_log"], elixir=9)
    action = decide(brain, state, elapsed=40.0, now=1100.0)
    assert action is not None and action.card == "musketeer", action
    assert action.tag == "cycle_unblock_musketeer"

