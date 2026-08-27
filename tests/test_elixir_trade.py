"""Scoring the part of the game tower damage cannot see.

Kiting a Musketeer with an Ice Golem, pulling a tank to the centre so both
Princess Towers work on it, answering a five-elixir push with one - none of
these move a tower's hitpoints, and all of them are why one player beats
another. A reward built only on tower fractions is blind to every one.

Scored as elixir they are simply what they are. The signal is net milli-elixir
of enemy bodies destroyed minus our own lost, and it prices the real plays:

    Ice Golem (2) pulls a Musketeer (4) into our towers      +2
    Skeletons (1) distract a Giant (5) so the towers kill it +4
    Knight (3) onto a Musketeer (4)                          +1
    Musketeer (4) onto Skeletons (1)                         -3

Symmetric on purpose: a term counting only enemy losses would pay for throwing
bodies at anything. And off by default, because it is a prior about how to play
- the `RewardWeights` docstring asked that any elixir term be named and
switchable rather than folded into the tower weight.

Death spawns carry no value. A Golem's Golemites were paid for when the Golem
was played, and charging the opponent for them again would make every
death-spawn card look like a bargain.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import TICK_MS                                   # noqa: E402
from sim.env import ClashEnv, RewardWeights                     # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.runner import DECK_26, resolve_deck                    # noqa: E402
from sim.spells import load_spells                              # noqa: E402

RAW = load_gamedata(level=11)
SPELLS = load_spells(level=11)
CARDS = resolve_deck(RAW, sorted(set(DECK_26) | {"musketeer", "ice_golem",
                                                 "skeletons", "giant", "knight"}))


def _trade(theirs, ours, at):
    match = Match(cards=CARDS, decks=(list(DECK_26), list(DECK_26)),
                  seed=6, spells=SPELLS)
    for _ in range(40):
        match.step()
    enemy = match.players[-1]
    enemy.hand[0] = theirs
    enemy.elixir = 10_000
    assert match.play_card(-1, theirs, grid_to_point(3, 20, -1)), theirs
    if ours:
        for _ in range(20):
            match.step()
        player = match.players[1]
        player.hand[0] = ours
        player.elixir = 10_000
        assert match.play_card(1, ours, grid_to_point(at[0], at[1], 1)), ours
    for _ in range(int(40 * 1000 / TICK_MS)):
        match.step()
    destroyed = match.battle.elixir_destroyed
    return (destroyed.get(1, 0) - destroyed.get(-1, 0)) / 1000.0


def test_the_term_is_off_unless_a_run_asks_for_it():
    assert RewardWeights().elixir_traded == 0.0


@pytest.mark.parametrize("theirs,ours,at,expected", [
    ("musketeer", "ice_golem", (14, 22), 2.0),   # 4 answered by 2
    ("giant", "skeletons", (14, 20), 4.0),       # 5 answered by 1
    ("knight", "skeletons", (14, 20), 2.0),      # 3 answered by 1
])
def test_a_good_trade_scores_the_difference(theirs, ours, at, expected):
    assert _trade(theirs, ours, at) == pytest.approx(expected, abs=0.01)


def test_a_bad_trade_scores_negative():
    """Four elixir of Musketeer onto one of Skeletons is -3, and should be."""
    assert _trade("skeletons", "musketeer", (14, 20)) < 0


def test_letting_the_towers_do_it_is_a_trade_too():
    """Spending nothing while the towers kill something is real value.

    Not an oversight: it is the reason a good player does not answer every
    card. The crown and win terms are what stop this becoming pure passivity.
    """
    assert _trade("musketeer", None, (0, 0)) > 0


def test_towers_are_worth_nothing_as_bodies():
    """Otherwise felling a tower would pay twice - once in crowns, once here."""
    match = Match(cards=CARDS, decks=(list(DECK_26), list(DECK_26)),
                  seed=1, spells=SPELLS)
    for entity in match.battle.entities.values():
        if entity.is_tower:
            assert entity.elixir_value == 0


def test_a_death_spawn_is_not_charged_twice():
    """Golemites cost nothing; the Golem already did."""
    from sim.arena import Point
    from sim.entities import make_unit
    from sim.gamedata import load_characters
    table = load_characters(11)
    spawned = make_unit(1, table["Golemite"], 1, Point(9000, 20000))
    assert spawned.elixir_value == 0


def test_a_swarm_splits_its_cost():
    """Three Skeletons are one elixir between them, not one each."""
    match = Match(cards=CARDS, decks=(list(DECK_26), list(DECK_26)),
                  seed=2, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = "skeletons"
    player.elixir = 10_000
    assert match.play_card(1, "skeletons", grid_to_point(9, 22, 1))
    bodies = [e for e in match.battle.entities.values()
              if e.side == 1 and not e.is_tower and e.elixir_value]
    assert bodies, "no skeletons carried a value"
    total = sum(e.elixir_value for e in bodies)
    assert total == pytest.approx(CARDS["skeletons"].cost * 1000, abs=len(bodies))


def test_the_env_pays_the_weight_only_when_it_is_set():
    off = ClashEnv(seed=3, opponent="meta")
    on = ClashEnv(seed=3, opponent="meta",
                  rewards=RewardWeights(elixir_traded=1.0))
    assert off.rewards.elixir_traded == 0.0
    assert on.rewards.elixir_traded == 1.0
