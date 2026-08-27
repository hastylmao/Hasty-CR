"""Engine behaviour, using hand-made specs so these do not depend on the loader.

These pin the parts of the tick that a trained policy would otherwise be free
to exploit: that damage matches the stated hit speed, that range is measured
edge-to-edge, that ground units cannot walk over the river, that building-only
attackers ignore troops, and that splash hits neighbours.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import arena  # noqa: E402
from sim.arena import MT, Point  # noqa: E402
from sim.engine import Battle  # noqa: E402
from sim.entities import make_tower, make_unit  # noqa: E402


@dataclass(frozen=True)
class Spec:
    name: str = "test"
    hitpoints: int = 1000
    damage: int = 100
    hit_speed_ms: int = 1000
    load_time_ms: int = 0
    range_mt: int = 800
    sight_range_mt: int = 6000
    speed_mt_per_sec: int = 1000
    collision_radius_mt: int = 500
    mass: int = 5
    deploy_time_ms: int = 0
    attacks_ground: bool = True
    attacks_air: bool = False
    flying: bool = False
    target_only_buildings: bool = False
    splash_radius_mt: int = 0
    jump_enabled: bool = False
    jump_speed_mt_per_sec: int = 0
    retarget_after_attack: bool = False
    spawn_number: int = 1
    raw: dict = None


def run(battle: Battle, ms: int) -> None:
    for _ in range(ms // arena.TICK_MS):
        battle.step()


def test_a_unit_kills_a_target_on_its_stated_hit_speed():
    battle = Battle()
    attacker = battle.add(make_unit(0, Spec(damage=100, hit_speed_ms=1000),
                                    1, arena.tile(9, 20)))
    victim = battle.add(make_unit(0, Spec(name="victim", hitpoints=300, speed_mt_per_sec=0),
                                  -1, arena.tile(9, 20)))
    run(battle, 3200)          # three hits' worth
    assert not victim.alive
    assert attacker.damage_dealt >= 300


def test_deploy_time_delays_the_first_action():
    battle = Battle()
    battle.add(make_unit(0, Spec(deploy_time_ms=1000), 1, arena.tile(9, 20)))
    victim = battle.add(make_unit(0, Spec(name="v", hitpoints=1000, speed_mt_per_sec=0),
                                  -1, arena.tile(9, 20)))
    run(battle, 900)
    assert victim.hitpoints == 1000, "a unit must not act while deploying"
    run(battle, 1500)
    assert victim.hitpoints < 1000


def test_range_is_measured_to_the_edge_not_the_centre():
    """A big target is reachable from further away, which is why a Giant can be
    hit before a Skeleton standing on the same tile."""
    battle = Battle()
    attacker = battle.add(make_unit(0, Spec(range_mt=1000, speed_mt_per_sec=0),
                                    1, arena.tile(9, 20)))
    # Two tiles apart: out of reach centre-to-centre, in reach edge-to-edge.
    far = battle.add(make_unit(0, Spec(name="big", collision_radius_mt=1500,
                                       speed_mt_per_sec=0, hitpoints=5000),
                               -1, arena.tile(9, 18)))
    run(battle, 1200)
    assert far.hitpoints < 5000
    assert attacker.target_uid == far.uid


def test_a_ground_unit_uses_a_bridge_to_cross():
    battle = Battle()
    walker = battle.add(make_unit(0, Spec(speed_mt_per_sec=1200, range_mt=200),
                                  1, arena.tile(9, 22)))
    battle.add(make_tower(0, -1, arena.tile(9, 3), 5000, 50, 1000, 7000, king=True))

    # The x at the moment of crossing is what matters. Checking the final
    # position instead reports where it walked to *afterwards*, which is
    # legitimately back toward the tower in the middle of the map.
    crossing_x = None
    for _ in range(12000 // arena.TICK_MS):
        was_our_side = walker.pos.y >= arena.RIVER_Y
        battle.step()
        if was_our_side and walker.pos.y < arena.RIVER_Y and crossing_x is None:
            crossing_x = walker.pos.x

    assert crossing_x is not None, "should have crossed by now"
    assert any(abs(crossing_x - bx) <= 2 * MT for bx in arena.BRIDGE_X), \
        f"crossed off-bridge at x={crossing_x}"


def test_a_flying_unit_ignores_the_bridges():
    battle = Battle()
    flyer = battle.add(make_unit(0, Spec(name="fly", flying=True, speed_mt_per_sec=1200,
                                         range_mt=200),
                                 1, arena.tile(9, 22)))
    battle.add(make_tower(0, -1, arena.tile(9, 3), 5000, 50, 1000, 7000, king=True))
    run(battle, 6000)
    assert flyer.pos.y < arena.RIVER_Y
    assert abs(flyer.pos.x - arena.tile(9, 0).x) < 2 * MT, "should fly straight"


def test_a_building_targeter_walks_past_troops():
    battle = Battle()
    hog = battle.add(make_unit(0, Spec(name="hog", target_only_buildings=True,
                                       speed_mt_per_sec=1200, range_mt=800),
                               1, arena.tile(4, 18)))
    # A real troop, not a zero-speed one: speed 0 is how the engine recognises
    # a building, and a "building" is exactly what this test must not use.
    bait = battle.add(make_unit(0, Spec(name="bait", hitpoints=2000,
                                        speed_mt_per_sec=300),
                                -1, arena.tile(4, 16)))
    tower = battle.add(make_tower(0, -1, arena.tile(4, 7), 3000, 50, 1000, 7000))
    run(battle, 4000)
    assert hog.target_uid == tower.uid, "a building-targeter must ignore troops"
    assert bait.hitpoints == 2000, "and must not damage them"


def test_ground_attackers_cannot_hit_air():
    battle = Battle()
    battle.add(make_unit(0, Spec(attacks_air=False, speed_mt_per_sec=0), 1, arena.tile(9, 20)))
    flyer = battle.add(make_unit(0, Spec(name="balloon", flying=True, hitpoints=800,
                                         speed_mt_per_sec=0),
                                 -1, arena.tile(9, 20)))
    run(battle, 3000)
    assert flyer.hitpoints == 800


def test_splash_hits_the_neighbours_of_its_target():
    battle = Battle()
    battle.add(make_unit(0, Spec(name="bomber", splash_radius_mt=1200,
                                 speed_mt_per_sec=0, damage=200),
                         1, arena.tile(9, 20)))
    victims = [battle.add(make_unit(0, Spec(name=f"v{i}", hitpoints=500,
                                            speed_mt_per_sec=0),
                                    -1, arena.tile(9 + i * 0.5, 19)))
               for i in range(3)]
    run(battle, 1200)
    hurt = [v for v in victims if not v.alive or v.hitpoints < 500]
    assert len(hurt) >= 2, "splash should reach more than the primary target"


def test_the_king_tower_sleeps_until_it_is_woken():
    from sim.match import Match
    match = Match(cards={}, decks=(["hog_rider"], ["hog_rider"]))
    king = match.towers[1]["king"]
    assert king.target_only_buildings, "king starts asleep"
    match.towers[1]["left"].hitpoints = 0
    match.step()
    assert not king.target_only_buildings, "losing a princess wakes the king"


def test_units_do_not_stack_on_one_point():
    """Swarm cards spawn several units on nearly the same spot, so exactly
    coincident positions are the common case, not an edge case. Buildings are
    excluded deliberately - they do not shove each other."""
    battle = Battle()
    a = battle.add(make_unit(0, Spec(name="a", speed_mt_per_sec=600), 1, arena.tile(9, 20)))
    b = battle.add(make_unit(0, Spec(name="b", speed_mt_per_sec=600), 1, arena.tile(9, 20)))
    run(battle, 500)
    assert arena.distance(a.pos, b.pos) > 0, "same-side units must push apart"


def test_spells_reach_the_enemy_half_but_troops_do_not():
    """Spells land anywhere; troops are restricted to your own half.

    Gating spells by the deploy area meant every Fireball aimed at a tower
    silently failed, so chip damage and the finisher were untestable here and
    every offence measurement was taken with the main tool disabled.
    """
    from sim.adapter import grid_to_point
    from sim.gamedata import load_gamedata
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=11), DECK_26)
    spells = load_spells(level=11)

    def fresh():
        match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=5,
                      spells=spells)
        match.players[1].hand = ["fireball", "hog_rider", "cannon", "skeletons"]
        match.players[1].elixir = 10_000
        return match

    # (4, 7) is the enemy left princess tower in the policy's grid convention.
    assert fresh().play_card(1, "fireball", grid_to_point(4, 7, 1))
    assert fresh().play_card(1, "fireball", grid_to_point(4, 24, 1))
    assert not fresh().play_card(1, "hog_rider", grid_to_point(4, 7, 1))
    assert fresh().play_card(1, "hog_rider", grid_to_point(4, 17, 1))


def test_jump_enabled_ground_units_still_cross_at_a_bridge():
    """Jump-enabled attacks do not grant unrestricted river traversal."""
    from sim.gamedata import load_gamedata

    cards = load_gamedata(level=11)
    battle = Battle()
    hog = battle.add(make_unit(
        1, cards["hog_rider"].unit, 1, arena.tile(9, 22)))
    tower = battle.add(make_tower(
        2, -1, arena.tile(9, 3), 5000, 0, 1000, 7000, king=True))
    hog.deploy_remaining_ms = 0
    crossing_x = None
    for _ in range(12000 // arena.TICK_MS):
        was_our_side = hog.pos.y >= arena.RIVER_Y
        battle.step()
        if was_our_side and hog.pos.y < arena.RIVER_Y:
            crossing_x = hog.pos.x
            break

    assert tower.alive
    assert crossing_x is not None
    assert any(abs(crossing_x - bridge_x) <= 2 * MT
               for bridge_x in arena.BRIDGE_X)
