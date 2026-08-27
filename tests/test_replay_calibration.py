from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.replay_calibration import (
    EventTolerance,
    MechanicsEvent,
    ReplayFrame,
    TowerObservation,
    UnitObservation,
    compare_events,
    extract_events,
    read_frames,
    simulator_snapshot,
    write_frames,
)


def unit(track_id: str, x: float, *, hitpoints: float = 100.0) -> UnitObservation:
    return UnitObservation(track_id, "hog_rider", 1, x, 20.0,
                            hitpoints=hitpoints, max_hitpoints=100.0,
                            confidence=0.95)


def test_frame_jsonl_round_trip_preserves_nested_observations(tmp_path: Path):
    path = tmp_path / "frames.jsonl"
    frames = [ReplayFrame(0, (unit("a", 4.0),), source="synthetic"),
              ReplayFrame(100, (unit("a", 4.2),), elixir=7, hand=("cannon",),
                          source="synthetic")]

    assert write_frames(path, frames) == 2
    loaded = list(read_frames(path))
    assert loaded == frames


def test_extract_events_reports_spawn_move_damage_and_despawn():
    frames = [
        ReplayFrame(0, (unit("a", 4.0),), source="synthetic"),
        ReplayFrame(100, (unit("a", 4.2, hitpoints=80.0),), source="synthetic"),
        ReplayFrame(200, (), source="synthetic"),
    ]

    events = extract_events(frames, movement_threshold=0.1)
    assert [event.event_type for event in events] == [
        "unit_spawn", "unit_move", "unit_damage", "unit_despawn"]
    assert events[1].value == pytest.approx(0.2)
    assert events[2].value == pytest.approx(20.0)
    assert events[3].time_ms == 200


def test_extract_events_reports_tower_damage_and_destroyed():
    tower = lambda hp, alive=True: TowerObservation(
        "enemy-left", -1, "left", 3.5, 7.5, hp, 3000, alive)
    events = extract_events([
        ReplayFrame(0, towers=(tower(3000),)),
        ReplayFrame(100, towers=(tower(2500),)),
        ReplayFrame(200, towers=(tower(0, False),)),
    ])

    assert [event.event_type for event in events] == [
        "tower_seen", "tower_damage", "tower_damage", "tower_destroyed"]
    assert events[1].value == pytest.approx(500)
    assert events[-1].target_id == "enemy-left"


def test_compare_events_matches_by_type_identity_and_tolerance():
    observed = [MechanicsEvent("unit_move", 100, "1", "hog_rider", 1,
                               x=4.0, y=20.0, value=0.5)]
    simulated = [MechanicsEvent("unit_move", 180, "2", "hog_rider", 1,
                                x=4.2, y=20.1, value=0.52)]

    report = compare_events(observed, simulated,
                            EventTolerance(time_ms=100, position=0.3, value=0.1))
    assert report.matched_events == 1
    assert report.unmatched_observed == 0
    assert report.mean_time_error_ms == pytest.approx(80)
    assert report.mean_position_error == pytest.approx(0.223606, rel=1e-4)


def test_compare_events_rejects_out_of_tolerance_events():
    event = MechanicsEvent("tower_damage", 0, target_id="tower", value=100)
    report = compare_events(
        [event], [MechanicsEvent("tower_damage", 1000, target_id="tower", value=100)],
        EventTolerance(time_ms=100))
    assert report.matched_events == 0
    assert report.unmatched_observed == 1
    assert report.unmatched_simulated == 1


def test_simulator_snapshot_projects_living_entities():
    from sim.arena import tile
    from sim.engine import Battle
    from sim.entities import make_unit

    battle = Battle()
    entity = battle.add(make_unit(1, type("Spec", (), {
        "name": "probe", "hitpoints": 100, "damage": 10,
        "hit_speed_ms": 1000, "load_time_ms": 0, "range_mt": 500,
        "sight_range_mt": 5000, "speed_mt_per_sec": 0,
        "collision_radius_mt": 400, "mass": 1, "deploy_time_ms": 0,
        "attacks_ground": True, "attacks_air": False, "flying": False,
        "target_only_buildings": False, "target_only_troops": False,
        "splash_radius_mt": 0, "jump_enabled": False,
    })(), 1, tile(4, 20)))
    entity.deploy_remaining_ms = 0

    snapshots = simulator_snapshot(battle)
    assert len(snapshots) == 1
    assert snapshots[0].event_type == "unit_state"
    assert snapshots[0].actor_id == str(entity.uid)
    assert snapshots[0].x == pytest.approx(4.5)


def test_json_reader_rejects_unknown_schema(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps({"schema_version": 99, "time_ms": 0}) + "\n")
    with pytest.raises(ValueError, match="unsupported"):
        list(read_frames(path))
