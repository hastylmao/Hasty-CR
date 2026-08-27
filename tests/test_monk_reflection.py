"""Monk reflects spells back onto the caster's own tower.

Projectile reflection - a troop or a tower shooting a meditating Monk and
getting its own shot back - was already modelled. Spells were not: they ignored
Monk entirely. A Fireball onto a meditating Monk hit him for full and the
caster kept their tower, when the real card turns it into a Fireball on their
*own* tower. That is the whole reason anyone spends the elixir into a spell,
and it is a swing of the spell twice over: they lose the damage and eat it.

Which spells, and what happens to each, is declared outright in
`DeflectBehaviour` on the projectile:

    NoDeflect                 Lightning, Royal Delivery - untouchable
    InvertDirection           the Logs - they roll back the way they came
    (anything else)           Fireball, Rocket, Arrows, Snowball, Goblin
                              Barrel - sent at the caster's own tower
    CheckOnlyTargetPosition   Arrows - he must be near the aim point itself,
                              not merely inside the blast

This was first built by inferring the set - a spell with a projectile speed is
thrown, minus Lightning for declaring `ProjectileStartHeight`, minus Royal
Delivery by name. That reproduced the published list and was still wrong about
The Log, which the inference dropped and the client reflects by reversing.
`DeflectBehaviour` was sitting unread the whole time, found by the sweep in
scripts/unread_fields.py. Reading the field beat reasoning about the data.

Where a reflected spell goes: the caster's nearest own crown tower - so a Monk
defending on the right sends it to their right tower - falling back to the
other if that one is down, and to the king if both are.

  https://clashroyale.fandom.com/wiki/Monk

Reflection also changes *whose* spell it is, not just where it lands. Moving
only the impact point sent the Fireball to the caster's tower and still had it
damage the Monk's side, which did nothing at all.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import TICK_MS                                  # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                             # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
DECK = ["monk", "knight", "archers", "musketeer",
        "cannon", "skeletons", "giant", "hog_rider"]

# Sent at the caster's tower.
REFLECTED = ["fireball", "arrows", "rocket", "goblin_barrel", "snowball"]
# Caught, but reversed rather than redirected. The playable card is `log`;
# `the_log` is a spell-table alias with no card behind it, so casting that name
# is silently refused - which is exactly how an earlier probe of this convinced
# itself The Log was being reflected when nothing had been cast at all.
INVERTED = ["log", "barb_log"]
# Not caught at all - either not thrown, or declared NoDeflect.
PASSES_THROUGH = ["poison", "freeze", "earthquake", "zap", "tornado"]
UNTOUCHABLE = ["lightning", "royal_delivery"]
# Royal Delivery is `deploy_own_side_only`, so an opponent cannot drop it onto
# a Monk defending his own half at all. Its NoDeflect is checked on the data
# rather than in play.
UNTOUCHABLE_IN_PLAY = ["lightning"]


def _meditating_monk(column=14, destroy_columns=()):
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = "monk"
    player.elixir = 10_000
    assert match.play_card(1, "monk", grid_to_point(column, 22, 1))
    for _ in range(80):
        match.step()
    monk = next(e for e in match.battle.entities.values() if e.name == "monk")
    player.elixir = 10_000
    assert match.activate_ability(1, monk.uid), "Monk would not meditate"
    for _ in range(30):
        match.step()
    assert monk.deflect_from_ms <= match.battle.now_ms < monk.deflect_until_ms

    for entity in list(match.battle.entities.values()):
        if (entity.is_tower and entity.side == -1
                and entity.name != "king_tower"
                and entity.pos.x // 1000 in destroy_columns):
            entity.hitpoints = 0
    return match, monk


def _throw(match, monk, spell):
    """Returns (damage the Monk took, {tower name+column: damage})."""
    before = {e.uid: (e.name, e.pos.x // 1000, e.hitpoints)
              for e in match.battle.entities.values()
              if e.is_tower and e.side == -1}
    monk_before = monk.hitpoints
    enemy = match.players[-1]
    enemy.hand[0] = spell
    enemy.elixir = 10_000
    assert match.play_card(-1, spell, monk.pos), f"{spell} was refused"
    for _ in range(80):
        match.step()
    hit = {}
    for uid, (name, column, hp) in before.items():
        now = match.battle.entities.get(uid)
        if now is not None and now.hitpoints < hp:
            hit[f"{name}@{column}"] = hp - now.hitpoints
    return monk_before - monk.hitpoints, hit


def test_the_client_states_which_spells_he_catches():
    for name in REFLECTED + INVERTED:
        assert "NoDeflect" not in SPELLS[name].deflect_behaviour, name
        assert SPELLS[name].projectile_speed_mt_per_sec > 0, name
    for name in UNTOUCHABLE:
        assert "NoDeflect" in SPELLS[name].deflect_behaviour, (
            f"{name} is declared NoDeflect and should be untouchable")
    for name in PASSES_THROUGH:
        assert SPELLS[name].projectile_speed_mt_per_sec == 0, (
            f"{name} is not thrown, so there is nothing to catch")


def test_the_logs_are_the_ones_that_reverse():
    inverting = {name for name, spec in SPELLS.items()
                 if "InvertDirection" in spec.deflect_behaviour}
    assert inverting == {"log", "the_log", "barb_log", "barb_log_hero"}, sorted(inverting)


def test_arrows_are_checked_against_the_aim_point_alone():
    """`CheckOnlyTargetPosition`, which is why Arrows need a closer landing."""
    assert "CheckOnlyTargetPosition" in SPELLS["arrows"].deflect_behaviour
    assert "CheckOnlyTargetPosition" not in SPELLS["fireball"].deflect_behaviour


@pytest.mark.parametrize("spell", REFLECTED)
def test_a_thrown_spell_lands_on_the_casters_own_tower(spell):
    match, monk = _meditating_monk()
    took, towers = _throw(match, monk, spell)
    assert took == 0, f"{spell} hurt the meditating Monk for {took}"
    assert towers, f"{spell} was deflected off the Monk and hit nothing"


@pytest.mark.parametrize("spell", INVERTED)
def test_a_log_is_caught_but_reversed_rather_than_redirected(spell):
    """It rolls back the way it came; roll direction follows the owning side."""
    match, monk = _meditating_monk()
    took, towers = _throw(match, monk, spell)
    assert took == 0, f"{spell} rolled over the meditating Monk for {took}"
    assert not towers, f"{spell} was sent to a tower instead of reversed"


@pytest.mark.parametrize("spell", UNTOUCHABLE_IN_PLAY)
def test_a_nodeflect_spell_goes_straight_through_him(spell):
    match, monk = _meditating_monk()
    _took, towers = _throw(match, monk, spell)
    assert not towers, f"{spell} declares NoDeflect and was reflected anyway"


@pytest.mark.parametrize("spell", PASSES_THROUGH)
def test_a_spell_that_is_not_thrown_hits_him_normally(spell):
    match, monk = _meditating_monk()
    took, towers = _throw(match, monk, spell)
    assert took > 0, f"{spell} should not be reflected and did nothing to him"
    assert not towers, f"{spell} was reflected onto {towers} and should not be"


@pytest.mark.parametrize("column,expected", [(14, 14), (3, 3)])
def test_it_goes_to_the_tower_on_the_side_he_is_standing(column, expected):
    """Nearest opposing crown tower, which is the side he is defending."""
    match, monk = _meditating_monk(column=column)
    _took, towers = _throw(match, monk, "fireball")
    assert list(towers) == [f"princess_tower@{expected}"], towers


def test_with_that_tower_down_it_goes_to_the_other_one():
    match, monk = _meditating_monk(column=14, destroy_columns=(14,))
    _took, towers = _throw(match, monk, "fireball")
    assert list(towers) == ["princess_tower@3"], towers


def test_with_both_princess_towers_down_it_goes_to_the_king():
    match, monk = _meditating_monk(column=14, destroy_columns=(3, 14))
    _took, towers = _throw(match, monk, "fireball")
    assert list(towers) == ["king_tower@9"], towers


def test_a_monk_who_is_not_meditating_reflects_nothing():
    """The ability is the mechanic; he is an ordinary troop without it."""
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = "monk"
    player.elixir = 10_000
    assert match.play_card(1, "monk", grid_to_point(14, 22, 1))
    for _ in range(80):
        match.step()
    monk = next(e for e in match.battle.entities.values() if e.name == "monk")
    took, towers = _throw(match, monk, "fireball")
    assert took > 0, "he took nothing without having activated anything"
    assert not towers


def test_a_spell_thrown_well_away_from_him_is_not_caught():
    """His reach is 1.5 tiles, not the whole lane."""
    match, monk = _meditating_monk(column=14)
    enemy = match.players[-1]
    enemy.hand[0] = "fireball"
    enemy.elixir = 10_000
    far = grid_to_point(3, 22, 1)
    before = {e.uid: e.hitpoints for e in match.battle.entities.values()
              if e.is_tower and e.side == -1}
    assert match.play_card(-1, "fireball", far)
    for _ in range(80):
        match.step()
    assert all(match.battle.entities[uid].hitpoints == hp
               for uid, hp in before.items()
               if uid in match.battle.entities), (
        "a Fireball eleven tiles away was reflected")


def test_deflecting_a_firecracker_shot_costs_him():
    """`ActionOnDeflector`: catching her fireworks is not free.

    Her projectile declares an `ActionDealDamage` of 25 aimed at whoever sends
    the shot back. It was the last unresolved action node in the client and it
    is a Monk interaction, which is why it turned up here rather than in
    anything about Firecracker.
    """
    unit = CARDS["firecracker"].unit
    assert unit.projectile_deflector_damage > 0

    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    enemy = match.players[-1]
    enemy.hand[0] = "firecracker"
    enemy.elixir = 10_000
    assert match.play_card(-1, "firecracker", grid_to_point(9, 17, -1))
    player = match.players[1]
    player.hand[0] = "monk"
    player.elixir = 10_000
    assert match.play_card(1, "monk", grid_to_point(9, 18, 1))
    for _ in range(80):
        match.step()
    monk = next(e for e in match.battle.entities.values() if e.name == "monk")
    player.elixir = 10_000
    assert match.activate_ability(1, monk.uid)

    before = monk.hitpoints
    for _ in range(int(4 * 1000 / TICK_MS)):
        match.step()
        if not monk.alive:
            break
    assert monk.hitpoints < before, (
        "he deflected her shots and paid nothing for it")


def test_only_firecracker_charges_for_being_deflected():
    charging = {name for name, card in CARDS.items()
                if card.unit is not None
                and getattr(card.unit, "projectile_deflector_damage", 0)}
    assert charging == {"firecracker"}, sorted(charging)
