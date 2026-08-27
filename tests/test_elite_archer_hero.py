"""Elite Archer Hero's ability, which was offered and then refused.

Unlike Skeleton King - whose ability the gate never offered at all - this one
passed the capability check on its 100ms buff and then failed to schedule,
because none of the three things it actually does had been read. He spent two
elixir on nothing, which is the harder version of the same bug: it looks like
it works right up to the point where it does not.

All three are declared, and each was hidden behind a different indirection:

  * **A decoy.** `ActionSpawnToLocation` puts `EliteArcherHero_Dummy` where he
    stands. The loader only knew the `ActionSpawnGuard` shape.
  * **A seven-second life on it.** The decoy is killed by its own graph - an
    `ActionInterval` of 7000 into an `ActionKill` - and nothing read that, so
    a permanent decoy would have been a much better card than a temporary one.
  * **Three arrows abreast.** `ProjectileCount = 2` beside the ordinary shot,
    `ProjectileDistance = 1500`, each carrying Damage 19 down a 13500 line.
    This hangs off the *projectile* of attack sequence index 1, not off the
    ability, so walking the ability graph finds nothing - and the attack
    sequence itself lives on the CHARACTER row and does not survive the EXT
    overlay that defines the hero. It has to be found by scanning his
    projectile tables, and exactly one card in the client declares parallel
    projectiles, so that scan cannot pick up anyone else's.

Separately, he had lost the trait that defines Magic Archer. `pierces` is
recorded per card name in combat_rules.json rather than read from the client,
the hero form had no entry, and his arrows stopped at the first enemy despite
firing the identical `EliteArcherArrow`.

Still approximate: ordering along each line. Arrows are resolved by distance
rather than swept, which is the same treatment the ordinary pierce already
gets, and is what the action audit still gates.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import MT, Point, TICK_MS                        # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_characters, load_gamedata         # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
TABLE = load_characters(11)
SPELLS = load_spells(level=11)
DECK = ["elite_archer_hero", "knight", "archers", "musketeer",
        "cannon", "skeletons", "giant", "hog_rider"]


def test_the_declared_numbers_are_read():
    unit = CARDS["elite_archer_hero"].unit
    assert unit.ability_deploy_character == "EliteArcherHero_Dummy"
    assert unit.ability_extra_projectiles == 2
    assert unit.ability_extra_projectile_spacing_mt == 1500
    assert unit.ability_shot_window_ms == 7000
    assert unit.ability_shot_damage > 0
    assert unit.ability_shot_range_mt == 13500


def test_he_is_still_a_magic_archer():
    """The hero form fires the identical arrow and had stopped piercing."""
    assert CARDS["elite_archer"].unit.pierces
    assert CARDS["elite_archer_hero"].unit.pierces


def test_only_this_card_fires_in_parallel():
    """One card in the client declares it, so the loader's scan is safe."""
    parallel = {name for name, card in CARDS.items()
                if card.unit is not None
                and getattr(card.unit, "ability_extra_projectiles", 0)}
    assert parallel == {"elite_archer_hero"}, sorted(parallel)


def test_the_decoy_lives_the_declared_seven_seconds():
    unit = TABLE["EliteArcherHero_Dummy"]
    assert unit.lifetime_ms == 7000
    assert unit.hitpoints > 0


def _hero_in_a_match():
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    enemy = match.players[-1]
    enemy.hand[0] = "giant"
    enemy.elixir = 10_000
    assert match.play_card(-1, "giant", grid_to_point(9, 20, -1))
    player = match.players[1]
    player.hand[0] = "elite_archer_hero"
    player.elixir = 10_000
    assert match.play_card(1, "elite_archer_hero", grid_to_point(9, 22, 1))
    for _ in range(80):
        match.step()
    hero = next(e for e in match.battle.entities.values()
                if "elite_archer" in e.name and "dummy" not in e.name)
    return match, hero


def test_the_ability_is_offered_and_accepted():
    """It used to be offered and then refused, which is worse than refused."""
    match, hero = _hero_in_a_match()
    match.players[1].elixir = 10_000
    assert match.can_activate_ability(1, hero.uid)
    assert match.activate_ability(1, hero.uid), (
        "the ability was offered and then would not schedule")


def _decoys(match):
    return [e for e in match.battle.entities.values()
            if e.alive and "dummy" in e.name.lower()]


def test_activating_leaves_a_decoy_that_expires():
    match, hero = _hero_in_a_match()
    match.players[1].elixir = 10_000
    assert match.activate_ability(1, hero.uid)

    for _ in range(int(1 * 1000 / TICK_MS)):
        match.step()
    assert _decoys(match), "no decoy was left behind"

    for _ in range(int(8 * 1000 / TICK_MS)):
        match.step()
    assert not _decoys(match), "the decoy outlived its declared seven seconds"


def _lane_damage(window: bool):
    """Damage to three targets: straight ahead and one in each side lane."""
    battle = Battle()
    hero = battle.add(make_unit(1, CARDS["elite_archer_hero"].unit, 1,
                                Point(9000, 24000)))
    hero.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = 0
    if window:
        hero.ability_shots_until_ms = 999_999
    lanes = {}
    for index, (offset, label) in enumerate(
            ((0, "centre"), (-1500, "left"), (1500, "right"))):
        giant = battle.add(make_unit(10 + index, CARDS["giant"].unit, -1,
                                     Point(9000 + offset, 19000)))
        giant.deploy_remaining_ms = 0
        giant.speed_mt_per_sec = 0
        giant.damage = 0
        lanes[label] = (giant, giant.hitpoints)
    for _ in range(int(4 * 1000 / TICK_MS)):
        battle.step()
    return {label: before - giant.hitpoints
            for label, (giant, before) in lanes.items()}


def test_without_the_ability_only_what_he_aims_at_is_hit():
    lost = _lane_damage(window=False)
    assert lost["centre"] > 0
    assert lost["left"] == 0 and lost["right"] == 0


def test_with_the_ability_all_three_lanes_are_hit():
    """The spread is the ability - three shots at one target would be pointless."""
    lost = _lane_damage(window=True)
    for label in ("centre", "left", "right"):
        assert lost[label] > 0, f"the {label} lane took nothing"


def test_the_spread_trades_single_target_damage_for_width():
    """Each arrow is weaker than his ordinary shot; there are simply three."""
    unit = CARDS["elite_archer_hero"].unit
    assert unit.ability_shot_damage < unit.damage
    off = _lane_damage(window=False)
    on = _lane_damage(window=True)
    assert on["centre"] < off["centre"], (
        "the ability made his aimed shot stronger as well as wider")
    assert sum(on.values()) > off["centre"], (
        "three lanes should be worth more in total than one")


def test_the_window_ends():
    match, hero = _hero_in_a_match()
    match.players[1].elixir = 10_000
    assert match.activate_ability(1, hero.uid)
    assert hero.ability_shots_until_ms > match.battle.now_ms
    for _ in range(int(9 * 1000 / TICK_MS)):
        match.step()
        if not hero.alive:
            pytest.skip("he died before the window closed")
    assert match.battle.now_ms >= hero.ability_shots_until_ms, (
        "the seven-second window never expired")
