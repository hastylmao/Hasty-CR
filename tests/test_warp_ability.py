"""Mega Minion Hero's warp, which was filed as needing a live measurement.

The action audit listed this graph as "accelerating warp path, arrival contact
and target acquisition" - three things that sound like they need video. Every
one of them is declared in the shipped file:

    [ACTION.MegaMinion_hero_teleport_action]
        ClassType = "ActionWarpCharacter"
        Speed = 1500
        Acceleration = 400
        TargetResolver = "MegaMinion_hero_target_resolver"

    [TARGET_RESOLVER.MegaMinion_hero_target_resolver]
        Filter = "default_targets_no_towers"
        StrategyList = ["RESOLVER_STRATEGY_LOWEST_MAX_HP",
                        "RESOLVER_STRATEGY_FURTHEST_TARGET"]
        Shape = "MegaMinion_hero_shape"   # ClassType = "Global"

So: warp onto the frailest thing on the board, ties broken by distance, towers
excluded, anywhere in the arena. The loader had never parsed `TARGET_RESOLVER`
sections at all, which is why the target half looked unknowable - the speed was
readable and the destination was not.

What is genuinely not modelled is the shape of the flight: `Acceleration = 400`
describes a curve, and the engine places the unit at its destination after
distance/speed. That affects when it arrives, not where.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import MT, TICK_MS, distance                     # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
DECK = ["mega_minion_hero", "knight", "archers", "musketeer",
        "cannon", "skeletons", "giant", "hog_rider"]


def _match_with_hero():
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    enemy = match.players[-1]
    enemy.hand[0] = "skeletons"
    enemy.elixir = 10_000
    assert match.play_card(-1, "skeletons", grid_to_point(9, 26, -1))
    enemy.hand[0] = "giant"
    enemy.elixir = 10_000
    assert match.play_card(-1, "giant", grid_to_point(9, 20, -1))
    ours = match.players[1]
    ours.hand[0] = "mega_minion_hero"
    ours.elixir = 10_000
    assert match.play_card(1, "mega_minion_hero", grid_to_point(9, 22, 1))
    for _ in range(60):
        match.step()
    hero = next(e for e in match.battle.entities.values()
                if e.name == "mega_minion_hero")
    return match, hero


def test_the_declared_values_are_read_from_the_client():
    unit = CARDS["mega_minion_hero"].unit
    assert unit.ability_warp_to_target_speed == 1500
    assert "LOWEST_MAX_HP" in unit.ability_warp_to_target_strategy
    assert "FURTHEST_TARGET" in unit.ability_warp_to_target_strategy


def test_the_resolver_picks_the_frailest_target_not_the_nearest():
    """The whole point of the strategy list.

    A Giant sits closer than the Skeletons. Picking by distance - which is what
    an unread resolver falls back to - would take the Giant, and the ability is
    declared to take the Skeleton.
    """
    match, hero = _match_with_hero()
    picked = match.battle.resolve_warp_target(hero)
    assert picked is not None
    others = [e for e in match.battle.entities.values()
              if e.alive and e.side == -1 and not e.is_tower]
    assert picked.max_hitpoints == min(e.max_hitpoints for e in others)
    assert picked.name != "giant"


def test_ties_on_hitpoints_are_broken_by_distance():
    match, hero = _match_with_hero()
    picked = match.battle.resolve_warp_target(hero)
    tied = [e for e in match.battle.entities.values()
            if e.alive and e.side == -1 and not e.is_tower
            and e.max_hitpoints == picked.max_hitpoints]
    furthest = max(distance(hero.pos, e.pos) for e in tied)
    assert distance(hero.pos, picked.pos) == furthest


def test_towers_are_excluded():
    match, hero = _match_with_hero()
    picked = match.battle.resolve_warp_target(hero)
    assert not picked.is_tower


def test_the_ability_is_available_and_moves_the_hero_onto_its_target():
    match, hero = _match_with_hero()
    picked = match.battle.resolve_warp_target(hero)
    start = hero.pos
    match.players[1].elixir = 10_000

    assert match.can_activate_ability(1, hero.uid), (
        "the warp is declared but the ability gate does not offer it")
    assert match.activate_ability(1, hero.uid)
    for _ in range(int(3 * 1000 / TICK_MS)):
        match.step()

    travelled = distance(start, hero.pos)
    assert travelled > 5 * MT, f"the hero barely moved ({travelled / MT:.1f} tiles)"


def test_a_warp_with_nothing_to_warp_to_is_refused_and_refunds():
    """No target means no ability, and no elixir spent."""
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=2, spells=SPELLS)
    for _ in range(40):
        match.step()
    ours = match.players[1]
    ours.hand[0] = "mega_minion_hero"
    ours.elixir = 10_000
    assert match.play_card(1, "mega_minion_hero", grid_to_point(9, 22, 1))
    for _ in range(40):
        match.step()
    hero = next(e for e in match.battle.entities.values()
                if e.name == "mega_minion_hero")
    # Towers are excluded by the filter, and they are all that is on the board.
    assert match.battle.resolve_warp_target(hero) is None
    ours.elixir = 6_000
    before = ours.elixir
    assert not match.activate_ability(1, hero.uid)
    assert ours.elixir == before
