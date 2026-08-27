from __future__ import annotations

from dataclasses import dataclass

from sim.arena import Point, TICK_MS, distance
from sim.diagnostics import DiagnosticSink
from sim.engine import Battle
from sim.entities import make_unit


@dataclass(frozen=True)
class Spec:
    name: str = "unit"
    hitpoints: int = 300
    damage: int = 100
    hit_speed_ms: int = 200
    load_time_ms: int = 100
    range_mt: int = 1000
    sight_range_mt: int = 6000
    speed_mt_per_sec: int = 60
    collision_radius_mt: int = 500
    mass: int = 5
    deploy_time_ms: int = 0
    attacks_ground: bool = True
    attacks_air: bool = False
    flying: bool = False
    target_only_buildings: bool = False
    splash_radius_mt: int = 0
    projectile_speed_mt_per_sec: int = 0
    projectile_homing: bool = False
    projectile_range_mt: int = 0
    projectile_radius_mt: int = 0
    retarget_after_attack: bool = False


def add(battle: Battle, spec: Spec, side: int, pos: Point):
    entity = battle.add(make_unit(0, spec, side, pos))
    entity.deploy_remaining_ms = 0
    return entity


def fingerprint(battle: Battle) -> tuple:
    return (
        battle.now_ms,
        tuple(battle.damage_log),
        tuple(sorted((e.uid, e.pos, e.hitpoints, e.state, e.target_uid,
                      e.attack_cooldown_ms, e.windup_remaining_ms)
                     for e in battle.entities.values())),
        tuple((row[0], row[1].uid, row[2], row[3]) for row in battle.in_flight),
    )


def make_duel(*, diagnostics: bool) -> Battle:
    battle = Battle(diagnostics=DiagnosticSink() if diagnostics else None)
    add(battle, Spec(name="archer", projectile_speed_mt_per_sec=4000), 1,
        Point(9000, 20000))
    add(battle, Spec(name="target", hitpoints=500, damage=0,
                     speed_mt_per_sec=0), -1, Point(9000, 18000))
    return battle


def test_diagnostics_off_preserves_deterministic_fingerprint():
    disabled = make_duel(diagnostics=False)
    enabled = make_duel(diagnostics=True)
    for _ in range(30):
        disabled.step()
        enabled.step()
    assert fingerprint(disabled) == fingerprint(enabled)
    assert disabled.diagnostics is None


def test_events_have_stable_order_required_fields_and_digest():
    digests = []
    for _ in range(2):
        battle = make_duel(diagnostics=True)
        for _ in range(30):
            battle.step()
        events = battle.diagnostics.events
        assert events
        assert all({"event_type", "time_ms", "tick", "phase", "order",
                    "source_uid", "target_uid", "source_pos", "target_pos",
                    "value", "reason", "state"} <= event.keys()
                   for event in events)
        assert [(e["tick"], e["order"]) for e in events] == sorted(
            (e["tick"], e["order"]) for e in events)
        assert {"target_acquired", "attack_timing", "projectile_launch",
                "projectile_impact", "damage"} <= {
                    e["event_type"] for e in events}
        digests.append(battle.diagnostics.digest())
    assert digests[0] == digests[1]


def test_simultaneous_lethal_damage_death_and_cleanup_order():
    battle = Battle(diagnostics=DiagnosticSink())
    first = add(battle, Spec(name="first", hitpoints=100, damage=100,
                             load_time_ms=0), 1, Point(9000, 20000))
    second = add(battle, Spec(name="second", hitpoints=100, damage=100,
                              load_time_ms=0), -1, Point(9000, 20000))
    battle.step()
    assert not first.alive and not second.alive
    events = battle.diagnostics.events
    assert [e["source_uid"] for e in events if e["event_type"] == "death"] == [1, 2]
    death_orders = [e["order"] for e in events if e["event_type"] == "death"]
    cleanup_orders = [e["order"] for e in events if e["event_type"] == "cleanup"]
    assert all(death < cleanup for death, cleanup in zip(death_orders, cleanup_orders))
    assert all(e["phase"] == "cleanup" for e in events
               if e["event_type"] in {"death", "cleanup"})


def test_projectile_survives_shooter_death_and_reports_homing_target_loss():
    battle = Battle(diagnostics=DiagnosticSink())
    shooter = add(battle, Spec(name="shooter", damage=120, load_time_ms=0,
                               projectile_speed_mt_per_sec=1000,
                               projectile_homing=True), 1, Point(9000, 20000))
    target = add(battle, Spec(name="target", hitpoints=500, damage=0,
                              speed_mt_per_sec=0), -1, Point(9000, 18000))
    for _ in range(20):
        battle.step()
        if battle.in_flight:
            break
    shooter.hitpoints = 0
    battle.step()
    assert battle.in_flight, "launched projectile must outlive its shooter"
    target.hitpoints = 0
    for _ in range(60):
        battle.step()
        if not battle.in_flight:
            break
    lost = [e for e in battle.diagnostics.events
            if e["event_type"] == "projectile_lost"]
    assert lost and lost[-1]["reason"] == "homing_target_lost"


def test_spawn_death_cleanup_and_zero_distance_collision_are_stable():
    battle = Battle(diagnostics=DiagnosticSink())
    first = add(battle, Spec(name="first", damage=0, speed_mt_per_sec=1), 1,
                Point(9000, 20000))
    second = add(battle, Spec(name="second", damage=0, speed_mt_per_sec=1), 1,
                 Point(9000, 20000))
    battle.step()
    assert distance(first.pos, second.pos) >= 998
    collision = next(e for e in battle.diagnostics.events
                     if e["event_type"] == "collision")
    assert collision["reason"] == "zero_distance_normal"
    assert collision["metadata"]["normal"] == (1, 0)
    first.hitpoints = 0
    battle.step()
    kinds = [e["event_type"] for e in battle.diagnostics.events]
    assert kinds.index("spawn") < kinds.index("death") < kinds.index("cleanup")


def test_target_acquisition_explanation_and_windup_phase():
    battle = Battle(diagnostics=DiagnosticSink())
    attacker = add(battle, Spec(name="attacker", load_time_ms=150), 1,
                   Point(9000, 20000))
    target = add(battle, Spec(name="target", damage=0, speed_mt_per_sec=0), -1,
                 Point(9000, 18500))
    for _ in range(5):
        battle.step()
    acquired = next(e for e in battle.diagnostics.events
                    if e["event_type"] == "target_acquired")
    assert acquired["source_uid"] == attacker.uid
    assert acquired["target_uid"] == target.uid
    assert acquired["reason"] == "visible_nearest"
    windup = next(e for e in battle.diagnostics.events
                  if e["event_type"] == "attack_timing"
                  and e["reason"] == "windup")
    assert windup["phase"] == "attack"
    assert windup["value"] == 100


def test_event_order_invariants_hold_each_tick():
    battle = make_duel(diagnostics=True)
    for _ in range(20):
        battle.step(TICK_MS)
    phase_rank = {"external": -1, "tick": 0, "scheduled_effects": 1, "deploy": 2,
                  "targeting": 3, "attack": 4, "movement": 5,
                  "collision": 6, "cleanup": 7}
    by_tick: dict[int, list[dict]] = {}
    for event in battle.diagnostics.events:
        by_tick.setdefault(event["tick"], []).append(event)
    for tick, events in by_tick.items():
        ranks = [phase_rank[event["phase"]] for event in events]
        assert ranks == sorted(ranks)
        if tick == 0:
            assert all(event["event_type"] == "spawn" for event in events)
            continue
        assert events[0]["event_type"] == "tick_start"
        assert events[-1]["event_type"] == "tick_end"


def test_sim_trace_adapter_consumes_normalized_diagnostics():
    from tools.calibration import Scenario, SimTraceAdapter

    scenario = Scenario.from_dict({
        "scenario_id": "diagnostic_adapter",
        "duration_ms": 100,
        "dt_ms": 50,
        "decks": [["knight"], ["knight"]],
        "actions": [{"time_ms": 0, "action": "deploy", "side": 1,
                     "card": "knight", "position": [9, 22]}],
    })
    trace = SimTraceAdapter(trace_diagnostics=True).run(scenario)
    diagnostic_events = [event for frame in trace.frames for event in frame.events
                         if event.provenance.method == "Battle.diagnostics"]
    assert diagnostic_events
    assert all({"tick", "phase", "order", "reason", "state"}
               <= event.metadata.keys() for event in diagnostic_events)
    assert any(event.event_type == "spawn" and event.actor_id is not None
               for event in diagnostic_events)
