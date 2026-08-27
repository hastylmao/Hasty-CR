"""Projectile impacts retain their declared trajectory after target loss."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import Point, TICK_MS  # noqa: E402
from sim.engine import Battle  # noqa: E402
from sim.entities import make_unit  # noqa: E402
from sim.gamedata import load_gamedata  # noqa: E402

CARDS = load_gamedata(level=11)


def _ready(battle: Battle, uid: int, card: str, side: int, point: Point):
    unit = battle.add(make_unit(uid, CARDS[card].unit, side, point))
    unit.deploy_remaining_ms = 0
    unit.speed_mt_per_sec = 0
    return unit


def test_non_homing_splash_lands_at_its_original_aim_when_target_dies():
    """A Bomber blast should still hit a nearby survivor after its mark dies."""
    battle = Battle()
    bomber = _ready(battle, 1, "bomber", 1, Point(9000, 20000))
    primary = _ready(battle, 2, "knight", -1, Point(9000, 16000))
    neighbour = _ready(battle, 3, "knight", -1, Point(9600, 16000))
    primary.speed_mt_per_sec = neighbour.speed_mt_per_sec = 0
    primary.hitpoints = 1
    neighbour.damage = 0

    for _ in range(400):
        battle.step()
        if any(shot[2] == primary.uid for shot in battle.in_flight):
            primary.hitpoints = 0
            break
    else:
        raise AssertionError("Bomber never launched a projectile")

    before = neighbour.hitpoints
    for _ in range(100):
        battle.step()
        if neighbour.hitpoints < before:
            break

    assert not primary.alive
    assert neighbour.hitpoints < before
    assert any(entry[1] == bomber.uid and entry[2] == neighbour.uid
               for entry in battle.damage_log)


def test_homing_projectile_is_wasted_when_its_target_dies():
    """A tower-style homing shot must not become an invented area attack."""
    battle = Battle()
    musketeer = _ready(battle, 1, "musketeer", 1, Point(9000, 20000))
    primary = _ready(battle, 2, "knight", -1, Point(9000, 16000))
    primary.hitpoints = 1
    musketeer.projectile_homing = True

    for _ in range(400):
        battle.step()
        if any(shot[2] == primary.uid for shot in battle.in_flight):
            primary.hitpoints = 0
            break
    else:
        raise AssertionError("Musketeer never launched a projectile")

    for _ in range(100):
        battle.step()

    assert not [entry for entry in battle.damage_log
                if entry[0] > 0 and entry[1] == musketeer.uid
                and entry[2] == primary.uid]
