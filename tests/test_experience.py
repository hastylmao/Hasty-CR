"""The reward signal must reward what actually wins, and be hard to fool.

A sign error here would not crash anything - it would quietly teach the bot to
play worse over hours, which is the most expensive kind of bug this project can
have. Hence the emphasis on directionality and on damping.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain import experience  # noqa: E402
from brain.experience import ExperienceBook  # noqa: E402

COSTS = {"musketeer": 4, "giant": 5, "skeleton": 0, "minion": 3, "hog_rider": 4}


def cost_of(name):
    return COSTS.get(name, 3)


@pytest.fixture
def book(tmp_path):
    return ExperienceBook(learned_path=tmp_path / "learned.json",
                          matchups_path=tmp_path / "matchups.json")


def play(book, card, cost, vs, ids, now=0.0, ally_hp=1.0, enemy_hp=1.0,
         situation="defend|medium"):
    book.record(card=card, cost=cost, tag=f"defend_{card}", situation=situation,
                lane="left", enemy_units=vs, enemy_ids=ids,
                ally_hp=ally_hp, enemy_hp=enemy_hp, now=now)


def test_killing_more_elixir_than_you_spend_is_rewarded(book):
    """One elixir of Skeletons that removes a four elixir Musketeer is the
    trade the deck is built on."""
    play(book, "skeletons", 1, ["musketeer"], [7])
    done = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    assert len(done) == 1
    assert done[0].reward > 0
    assert done[0].killed == ["musketeer"]


def test_spending_a_card_and_killing_nothing_is_punished(book):
    play(book, "musketeer", 4, ["giant"], [7])
    done = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids={7},
                        ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    assert done[0].reward < 0


def test_losing_tower_hp_dominates_the_reward(book):
    """Killing a Musketeer is no consolation for handing over a tower."""
    play(book, "skeletons", 1, ["musketeer"], [7], ally_hp=1.0)
    done = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=0.5, enemy_hp=1.0, unit_cost=cost_of)
    assert done[0].reward < 0


def test_damaging_their_tower_is_rewarded(book):
    play(book, "hog_rider", 4, [], [], enemy_hp=1.0, situation="hog|none")
    done = book.resolve(now=experience.ATTACK_RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=1.0, enemy_hp=0.7, unit_cost=cost_of)
    assert done[0].reward > 0


def test_an_attack_is_judged_only_after_the_hog_has_time_to_connect(book):
    """Judging a Hog at seven seconds scored the win condition at -3.8 over ten
    samples: it was still walking.  The window must outlast the walk."""
    play(book, "hog_rider", 4, [], [], situation="hog|none")
    early = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                         ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    assert early == [], "an attack must not be judged on the defence window"

    late = book.resolve(now=experience.ATTACK_RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=1.0, enemy_hp=0.6, unit_cost=cost_of)
    assert len(late) == 1 and late[0].reward > 0


def test_a_defence_is_still_judged_quickly(book):
    play(book, "skeletons", 1, ["musketeer"], [7], situation="defend|medium")
    done = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    assert len(done) == 1


def test_a_hog_that_connects_is_worth_more_than_it_cost(book):
    """A Hog that lands its hits takes roughly a quarter of a tower, and that
    has to score positive or the bandit learns that chip damage - the entire
    point of the deck - is a mistake.

    A *graze* is a different matter: at this calibration one hit for a tenth of
    a tower is worth 3.5 against a cost of 4, i.e. slightly negative, which is
    the honest answer rather than a flattering one.
    """
    play(book, "hog_rider", 4, [], [], ally_hp=2.0, enemy_hp=2.0, situation="hog|none")
    done = book.resolve(now=experience.ATTACK_RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=2.0, enemy_hp=1.75, unit_cost=cost_of)
    assert done[0].reward > 0

    play(book, "hog_rider", 4, [], [], ally_hp=2.0, enemy_hp=2.0,
         situation="hog|none", now=100.0)
    graze = book.resolve(now=100.0 + experience.ATTACK_RESOLVE_SECONDS + 1,
                         live_ids=set(), ally_hp=2.0, enemy_hp=1.9, unit_cost=cost_of)
    assert graze[0].reward < 0


def test_losing_a_tower_outweighs_taking_one(book):
    """The deck wins by not losing towers, so the reward has to say so."""
    assert experience.TOWER_TAKEN_WEIGHT > experience.TOWER_DEALT_WEIGHT


def test_an_episode_is_not_judged_before_its_window(book):
    play(book, "skeletons", 1, ["musketeer"], [7])
    assert book.resolve(now=1.0, live_ids=set(), ally_hp=1.0, enemy_hp=1.0,
                        unit_cost=cost_of) == []
    assert len(book.pending) == 1


def test_free_spawned_units_do_not_inflate_the_reward(book):
    """Killing three Skeletons is not a four elixir trade."""
    play(book, "the_log", 2, ["skeleton", "skeleton", "skeleton"], [1, 2, 3])
    done = book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                        ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    assert done[0].reward < 0


def test_the_learned_bias_needs_evidence_before_it_counts(book):
    """One good sample must not outweigh a hand-written strategy rule."""
    play(book, "skeletons", 1, ["musketeer"], [7])
    book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                 ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    single = book.bias("defend|medium", "skeletons", scale=1.2, limit=14.0)

    for index in range(9):
        play(book, "skeletons", 1, ["musketeer"], [100 + index],
             now=index * 100.0)
        book.resolve(now=index * 100.0 + experience.RESOLVE_SECONDS + 1,
                     live_ids=set(), ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    many = book.bias("defend|medium", "skeletons", scale=1.2, limit=14.0)
    assert 0 < single < many


def test_the_learned_bias_is_clamped(book):
    for index in range(30):
        play(book, "hog_rider", 4, [], [], now=index * 100.0, situation="hog|none")
        book.resolve(now=index * 100.0 + experience.RESOLVE_SECONDS + 1,
                     live_ids=set(), ally_hp=1.0, enemy_hp=0.0, unit_cost=cost_of)
    assert book.bias("hog|none", "hog_rider", scale=1.2, limit=14.0) <= 14.0


def test_unseen_pairs_have_no_opinion(book):
    assert book.bias("defend|big", "cannon", scale=1.2, limit=14.0) == 0.0


def test_only_units_the_play_engaged_are_credited(book):
    """Pairing a play with everything on the field produced nonsense like
    "hog_rider vs ice_golem: 100% kill rate" - the Hog never fought it."""
    book.record(card="hog_rider", cost=4, tag="push", situation="hog|none",
                lane="left", enemy_units=["ice_golem", "musketeer"],
                enemy_ids=[1, 2], ally_hp=1.0, enemy_hp=1.0, now=0.0,
                engaged=[])
    book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                 ally_hp=1.0, enemy_hp=0.8, unit_cost=cost_of)
    assert book.matchups == {} or all(
        value["n"] == 0 for value in book.matchups.values()
    )


def test_matchups_record_what_beat_what(book):
    play(book, "skeletons", 1, ["musketeer"], [7])
    book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                 ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    rows = dict(book.top_matchups(minimum=1))
    assert "skeletons vs musketeer" in rows
    assert rows["skeletons vs musketeer"]["kill_rate"] == 1.0


def test_situation_keys_generalise_but_stay_specific():
    defend_air = experience.situation_key("defend_air", 12.0, air=True, contained=False)
    defend_ground = experience.situation_key("defend_cannon", 12.0, air=False, contained=False)
    assert defend_air != defend_ground
    # Same family and same threat band should collapse to one key.
    assert experience.situation_key("defend_cannon", 12.0, False, False) == \
           experience.situation_key("defend_kite", 13.0, False, False)


def test_unresolved_episodes_do_not_leak_into_the_next_match():
    """A play awaiting judgement when the match ends must be dropped, not
    scored against the next opponent's towers."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from brain.policy import Brain

    brain = Brain(learn=True)
    brain.book.record(card="hog_rider", cost=4, tag="push", situation="hog|none",
                      lane="left", enemy_units=[], enemy_ids=[],
                      ally_hp=2.0, enemy_hp=0.4, now=0.0, engaged=[])
    assert brain.book.pending
    brain.reset()
    assert not brain.book.pending


def test_learning_survives_a_restart(book, tmp_path):
    play(book, "skeletons", 1, ["musketeer"], [7])
    book.resolve(now=experience.RESOLVE_SECONDS + 1, live_ids=set(),
                 ally_hp=1.0, enemy_hp=1.0, unit_cost=cost_of)
    book.save()

    reloaded = ExperienceBook(learned_path=tmp_path / "learned.json",
                              matchups_path=tmp_path / "matchups.json")
    assert reloaded.bias("defend|medium", "skeletons", scale=1.2, limit=14.0) > 0
