"""Evolved Princess's ice arrow, which she was never firing.

Her evolution is the slow field. She fired her ordinary arrow every time, so
the evolution was a Princess with a slightly larger splash on paper and no slow
at all - and every stat on the card was correct, which is why nothing caught it.

The field is declared: attack sequence index 1 carries
`Princess_EV1_FreezeProjectile`, whose `SpawnAreaEffectObject` is a three-tile
area lasting 5500ms applying `IceWizardSlowDown` at -30% move and hit speed.

One number is not shipped. The cadence lives in
`Princess_EV1_attack_count % Princess_EV1_reload_frequency == 0`, and
`Princess_EV1_reload_frequency` is declared as an empty `[VARIABLE.…]` section
with no value anywhere in the client. The published behaviour supplies it -
every third attack, starting with the first - and it is recorded in
combat_rules.json with its source rather than guessed inline.

  https://royaleapi.com/blog/princess-evolution-june-2026?lang=en

Not this: her *death* freeze, a separate 3.5-second area that also carries 66
damage, which was already modelled. The arrow's field carries no damage at all
- `Princess_EV1_projectile_aeo` sets `SpawnAreaEffectObject = ""`, so the 66
belongs only to the death version. Reading the two as one would have handed her
free damage on every third shot.
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
from sim.gamedata import load_buffs, load_gamedata              # noqa: E402

CARDS = load_gamedata(level=11)


def test_the_declared_field_is_read():
    unit = CARDS["princess_ev1"].unit
    assert unit.special_attack_every == 3
    assert unit.special_attack_radius_mt == 3000
    assert unit.special_area_duration_ms == 5500
    assert unit.special_area_buff == "IceWizardSlowDown"
    assert load_buffs()["IceWizardSlowDown"][:2] == (-30, -30)


def test_the_field_is_wider_than_her_ordinary_splash():
    """2.5 tiles normally, 3.0 with the ice arrow."""
    unit = CARDS["princess_ev1"].unit
    assert unit.splash_radius_mt == 2500
    assert unit.special_attack_radius_mt == 3000


def test_only_the_evolution_fires_one():
    special = {name for name, card in CARDS.items()
               if card.unit is not None
               and getattr(card.unit, "special_attack_every", 0)}
    assert special == {"princess_ev1"}, sorted(special)


def _shoot_for(card, seconds=12):
    battle = Battle()
    princess = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 24000)))
    princess.deploy_remaining_ms = 0
    princess.speed_mt_per_sec = 0
    giant = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 19000)))
    giant.deploy_remaining_ms = 0
    giant.damage = 0
    slowed = 0
    fields = 0
    for _ in range(int(seconds * 1000 / TICK_MS)):
        battle.step()
        fields = max(fields, len(battle.areas))
        if giant.alive and giant.buffed(battle.now_ms) and giant.buff_speed_pct < 0:
            slowed += 1
    return fields, slowed, giant


def test_the_evolution_slows_what_it_shoots():
    fields, slowed, _giant = _shoot_for("princess_ev1")
    assert fields > 0, "no ice field was ever created"
    assert slowed > 0, "the field was created and slowed nothing"


def test_the_base_card_does_not():
    fields, slowed, _giant = _shoot_for("princess")
    assert fields == 0
    assert slowed == 0


def test_the_first_shot_is_the_special_one():
    """(1st, 4th, 7th) - so the field is up before she has fired three times."""
    battle = Battle()
    princess = battle.add(make_unit(1, CARDS["princess_ev1"].unit, 1,
                                    Point(9000, 24000)))
    princess.deploy_remaining_ms = 0
    princess.speed_mt_per_sec = 0
    giant = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 19000)))
    giant.deploy_remaining_ms = 0
    giant.damage = 0

    hit_speed = CARDS["princess_ev1"].unit.hit_speed_ms
    for _ in range(int((hit_speed + 1500) / TICK_MS)):
        battle.step()
        if battle.areas:
            return
    pytest.fail("no field after her first attack; the cadence starts at one")


def test_the_field_lingers_rather_than_only_hitting_on_impact():
    """A slow that only touched what was standing there is a splash.

    Something that walks in afterwards has to be caught too, which is the
    whole reason the area has a 5500ms life.
    """
    battle = Battle()
    princess = battle.add(make_unit(1, CARDS["princess_ev1"].unit, 1,
                                    Point(9000, 24000)))
    princess.deploy_remaining_ms = 0
    princess.speed_mt_per_sec = 0
    giant = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 19000)))
    giant.deploy_remaining_ms = 0
    giant.damage = 0

    # Wait for a field to exist, then walk a fresh unit into it.
    for _ in range(int(6 * 1000 / TICK_MS)):
        battle.step()
        if battle.areas:
            break
    assert battle.areas, "no field to walk into"
    centre = battle.areas[0][1]

    latecomer = battle.add(make_unit(3, CARDS["knight"].unit, -1, centre))
    latecomer.deploy_remaining_ms = 0
    latecomer.speed_mt_per_sec = 0
    latecomer.damage = 0
    for _ in range(int(1 * 1000 / TICK_MS)):
        battle.step()
    assert latecomer.buffed(battle.now_ms) and latecomer.buff_speed_pct < 0, (
        "a unit that walked into the field afterwards was not slowed")


def test_the_arrow_field_carries_no_damage_of_its_own():
    """The 66 belongs to her death freeze, not to the arrow.

    `Princess_EV1_projectile_aeo` blanks `SpawnAreaEffectObject`; reading the
    two areas as one would give her free damage every third shot.
    """
    battle = Battle()
    princess = battle.add(make_unit(1, CARDS["princess_ev1"].unit, 1,
                                    Point(9000, 24000)))
    princess.deploy_remaining_ms = 0
    princess.speed_mt_per_sec = 0
    giant = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 19000)))
    giant.deploy_remaining_ms = 0
    giant.damage = 0          # she needs something to shoot at
    for _ in range(int(6 * 1000 / TICK_MS)):
        battle.step()
        if battle.areas:
            break
    assert battle.areas
    spec = battle.areas[0][0]
    assert spec.damage == 0
    assert spec.damage_per_second == 0


def test_her_death_freeze_is_still_its_own_thing():
    unit = CARDS["princess_ev1"].unit
    assert unit.death_area_damage > 0
    assert unit.death_area_duration_ms == 3500
    assert unit.death_area_speed_pct == -30
