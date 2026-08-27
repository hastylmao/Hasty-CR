"""Does every card that shoots actually hurt what it shoots?

A card that fires and deals nothing is the worst kind of wrong: it looks like
it is working, it costs elixir, it draws aggro, and every measurement taken
with it is quietly meaningless. Twenty-five of them were in that state at once
because non-homing shots were held back from resolving.

Damage is not always on the character. The client hangs it wherever the card
needs it, and each of these shapes had to be followed:

    Cannon, Musketeer      on the projectile the character names
    Princess               on `CustomFirstProjectile`; `Projectile` is a
                           decorative arrow with no damage at all
    Firecracker            on the projectile that the projectile spawns
    Evolved Princess       on a projectile named inside AttackSequenceList,
                           while the top level blanks CustomFirstProjectile
    Evolved Executioner    on the action the projectile starts - the axe row
                           says Damage 0 and the controller says 70

So the loader follows the declared chain rather than reading one field, and
this test is the check that the chain still reaches everything.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import Point, TICK_MS                            # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402

CARDS = load_gamedata(level=11)

# Super Archers is a party-mode card and the shipped data simply does not carry
# its damage: not on the character row, not on `SuperArcherChargeArrow`, not on
# the area effect that projectile spawns (which is a pull, not a hit), and not
# in RoyaleAPI's published stats either - they have its hitpoints per level and
# no damage at all. Inventing a number for it is the one thing not to do, so it
# is named here instead. Remove it if a source ever states the value.
UNDECLARED_DAMAGE = {"super_archer"}

RANGED = sorted(
    name for name, card in CARDS.items()
    if card.unit is not None
    and int(getattr(card.unit, "projectile_speed_mt_per_sec", 0) or 0) > 0)


def test_there_are_ranged_cards_to_check():
    assert len(RANGED) > 40, len(RANGED)


@pytest.mark.parametrize("card", [n for n in RANGED if n not in UNDECLARED_DAMAGE])
def test_a_ranged_card_declares_damage(card):
    assert CARDS[card].unit.damage > 0, (
        f"{card} fires a projectile and deals nothing; follow its declared "
        f"chain - projectile, CustomFirstProjectile, SpawnProjectile, "
        f"AttackSequenceList, OnStartingAction")


def test_the_undeclared_list_has_not_quietly_grown():
    """The allowance is for cards with no source, not for new regressions."""
    silent = {name for name in RANGED if CARDS[name].unit.damage <= 0}
    assert silent == UNDECLARED_DAMAGE, (
        f"zero-damage ranged cards changed: {sorted(silent)}")


@pytest.mark.parametrize("card", ["princess", "princess_ev1", "firecracker",
                                  "axe_man_ev1", "bomber", "mortar"])
def test_the_awkward_chains_land_damage_in_a_real_fight(card):
    """Declaring damage is not the same as dealing it."""
    battle = Battle()
    shooter = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    shooter.deploy_remaining_ms = 0
    shooter.speed_mt_per_sec = 0
    target = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 16000)))
    target.deploy_remaining_ms = 0
    target.speed_mt_per_sec = 0
    target.damage = 0
    before = target.hitpoints
    for _ in range(int(10 * 1000 / TICK_MS)):
        battle.step()
    assert target.hitpoints < before, f"{card} fired for ten seconds and did nothing"
