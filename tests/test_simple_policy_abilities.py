from sim.arena import MT, Point
from sim.entities import make_unit
from sim.gamedata import load_gamedata
from sim.match import Match
from sim.runner import SimpleOpponent
from sim.spells import load_spells


def test_generic_policy_presses_golden_knight_dash_when_engaged():
    cards = load_gamedata()
    match = Match(cards={
        "golden_knight": cards["golden_knight"],
        "knight": cards["knight"],
    }, decks=(['golden_knight'] * 8, ['knight'] * 8), spells=load_spells(), seed=2)
    hero = match.battle.add(make_unit(
        1, cards["golden_knight"].unit, 1, Point(8 * MT, 20 * MT), 0))
    target = match.battle.add(make_unit(
        2, cards["knight"].unit, -1, Point(8 * MT, 18 * MT), 0))
    hero.target_uid = target.uid
    hero.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000

    decision = SimpleOpponent(match.cards, side=1, seed=1).act(match)

    assert decision == ("ability", -1, -1, hero.name)
    assert hero.ability_used
    assert hero.ability_dashing
