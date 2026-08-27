"""Executioner's axe comes back, and it hurts on the way back.

Both Executioner and his evolution throw the same boomerang. The simulator
threw it at whatever he was aiming at, dealt damage once, and stopped there -
so a card whose whole job is clearing a line of troops was a single-target hit,
and anything standing behind his target took nothing at all.

His own card screen states the damage as "70 x2":

    [STATS.AxeMan_EV1]
        Value = "damage"
        OverrideIntValue2 = 2
        Unit  = "INTEGER_TIMES_X"

and the geometry is identical on both cards:

    [PROJECTILE.AxeMan_EV1_Projectile_Normal]
        Speed               = 550     # x1000//60 -> 9166 millitiles/sec
        ProjectileRange     = 7000
        ProjectileRadius    = 1000
        PingpongVisualTime  = 1500    # the round trip

Seven tiles out and back at 9166 mt/s is 1527ms against a declared 1500 - two
numbers that were derived independently and agree, which is the only reason
this could be built without a measurement.

The action audit listed this as needing calibration: "ping-pong axe:
Strong/Normal swap at 2000 and 3000 travel". The swap boundary is a detail. The
axe returning is the card, and it was not happening.

What is still simplified: the client declares a hysteresis, strong below 2000
going out and strong again below 3000 coming back. This uses the single
`StrongDamageRange = 2500` band that the card screen displays. That moves where
the boundary sits by half a tile; it does not change whether the axe returns.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import MT, Point, TICK_MS                        # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402

CARDS = load_gamedata(level=11)
BOOMERANG = ["axe_man", "axe_man_ev1"]


def _one_swing(card, distances):
    """A stationary thrower, a row of targets, and exactly one throw."""
    battle = Battle()
    thrower = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 12000)))
    thrower.deploy_remaining_ms = 0
    thrower.speed_mt_per_sec = 0
    thrower.hit_speed_ms = 100_000          # so the second swing never comes
    marks = []
    for index, span in enumerate(distances):
        giant = battle.add(make_unit(10 + index, CARDS["giant"].unit, -1,
                                     Point(9000, 12000 + span)))
        giant.deploy_remaining_ms = 0
        giant.speed_mt_per_sec = 0
        giant.damage = 0
        marks.append((span, giant, giant.hitpoints))
    for _ in range(int(4 * 1000 / TICK_MS)):
        battle.step()
    return {span: before - giant.hitpoints for span, giant, before in marks}


@pytest.mark.parametrize("card", BOOMERANG)
def test_the_declared_geometry_is_read(card):
    unit = CARDS[card].unit
    assert unit.pingpong_range_mt == 7000
    assert unit.pingpong_radius_mt == 1000
    assert unit.pingpong_damage > 0, "the axe would fly and hurt nothing"


def test_only_the_two_executioners_throw_one():
    throwers = {name for name, card in CARDS.items()
                if card.unit is not None
                and getattr(card.unit, "pingpong_range_mt", 0)}
    assert throwers == set(BOOMERANG), sorted(throwers)


@pytest.mark.parametrize("card", BOOMERANG)
def test_it_reaches_past_his_attack_range(card):
    """Range is 4.5 tiles; the axe travels 7.

    A target at six tiles is outside anything he can lock onto and squarely
    inside the axe's flight, which is the whole point of the card.
    """
    lost = _one_swing(card, [2000, 6000])
    assert lost[6000] > 0, (
        "the axe stopped at his target; everything behind it took nothing")


@pytest.mark.parametrize("card", BOOMERANG)
def test_everything_in_the_line_is_hit_exactly_twice(card):
    """Once outbound, once on the return, and not a third time."""
    unit = CARDS[card].unit
    lost = _one_swing(card, [3000, 5000])
    for span in (3000, 5000):
        assert lost[span] == 2 * unit.pingpong_damage, (
            f"{card} dealt {lost[span]} at {span/MT:.1f} tiles against "
            f"{2 * unit.pingpong_damage} for two passes of "
            f"{unit.pingpong_damage}")


def test_the_evolution_hits_harder_close_in():
    """StrongDamage 94 inside 2.5 tiles, Damage 70 beyond it."""
    unit = CARDS["axe_man_ev1"].unit
    assert unit.pingpong_strong_damage > unit.pingpong_damage
    assert unit.pingpong_strong_range_mt == 2500
    lost = _one_swing("axe_man_ev1", [2000, 5000])
    assert lost[2000] == 2 * unit.pingpong_strong_damage
    assert lost[5000] == 2 * unit.pingpong_damage


def test_the_base_card_has_no_strong_band():
    """He throws the same axe; the evolution is what added the strong hit."""
    unit = CARDS["axe_man"].unit
    assert unit.pingpong_strong_damage == 0
    lost = _one_swing("axe_man", [2000, 5000])
    assert lost[2000] == lost[5000] == 2 * unit.pingpong_damage


@pytest.mark.parametrize("card", BOOMERANG)
def test_the_return_leg_lands_after_the_outbound_one(card):
    """Not both at once: the axe has to travel back.

    A card that dealt its double damage instantly would be a different and
    much stronger card - the gap is what lets a unit die to the first pass, or
    walk out of the second.
    """
    battle = Battle()
    thrower = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 12000)))
    thrower.deploy_remaining_ms = 0
    thrower.speed_mt_per_sec = 0
    thrower.hit_speed_ms = 100_000
    giant = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 17000)))
    giant.deploy_remaining_ms = 0
    giant.speed_mt_per_sec = 0
    giant.damage = 0

    first = last = None
    before = giant.hitpoints
    for tick in range(int(4 * 1000 / TICK_MS)):
        battle.step()
        if giant.hitpoints < before:
            if first is None:
                first = tick * TICK_MS
            last = tick * TICK_MS
            before = giant.hitpoints
    assert first is not None and last is not None
    gap = last - first
    assert gap >= 400, f"both passes landed {gap}ms apart, which is one hit"
    # Five tiles out is 545ms; the return passes it at (14000-5000)/9166 = 982ms.
    assert gap <= 1200, f"the passes were {gap}ms apart, too slow for one throw"


@pytest.mark.parametrize("card", BOOMERANG)
def test_it_does_not_hit_units_off_to_the_side(card):
    """A one-tile corridor, not a seven-tile circle."""
    battle = Battle()
    thrower = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 12000)))
    thrower.deploy_remaining_ms = 0
    thrower.speed_mt_per_sec = 0
    inline = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 16000)))
    aside = battle.add(make_unit(3, CARDS["giant"].unit, -1, Point(14000, 16000)))
    for unit in (inline, aside):
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
        unit.damage = 0
    before = aside.hitpoints
    for _ in range(int(3 * 1000 / TICK_MS)):
        battle.step()
    assert aside.hitpoints == before, "the axe hit something five tiles to the side"
