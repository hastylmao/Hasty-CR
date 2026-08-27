from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.calibration import (
    ArenaMapper,
    CalibrationError,
    Detection,
    NormalizedFrame,
    NormalizedTrace,
    Observability,
    Provenance,
    Scenario,
    SimTraceAdapter,
    SimpleGameAwareTracker,
    TimestampSynchronizer,
    TrackedEntity,
    canonical_json,
    from_replay_frames,
    load_scenario,
    read_trace,
    report_markdown,
    trace_digest,
    write_trace,
)


def test_trace_schema_digest_is_metadata_independent(tmp_path: Path):
    entity = TrackedEntity("a", "knight", 1, 2.0, 3.0,
                           observability=Observability.MEASURED,
                           provenance=Provenance("video", details={"path": "volatile.png"}))
    trace = NormalizedTrace((NormalizedFrame(0, "0", (entity,)),), metadata={"path": "one"})
    changed = NormalizedTrace((NormalizedFrame(0, "0", (entity,)),), metadata={"path": "two"})
    assert trace_digest(trace) == trace_digest(changed)
    path = tmp_path / "trace.jsonl"
    assert write_trace(path, trace) == 1
    assert read_trace(path).frames[0].entities[0].track_id == "a"


def test_scenario_validation_and_json_loader(tmp_path: Path):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({
        "scenario_id": "probe", "duration_ms": 200, "dt_ms": 50,
        "decks": [["knight"], ["knight"]],
        "deployments": [{"time_ms": 0, "side": 1, "card": "knight", "position": [9, 22]}],
        "tags": ["combat"], "split": "validation",
    }))
    scenario = load_scenario(path)
    assert scenario.scenario_id == "probe"
    assert scenario.actions[0].action == "deploy"
    with pytest.raises(CalibrationError):
        Scenario.from_dict({"scenario_id": "bad", "duration_ms": 0})


def test_arena_mapper_forward_inverse_and_error():
    image = [(0, 0), (10, 0), (10, 10), (0, 10)]
    arena = [(1, 2), (21, 2), (21, 32), (1, 32)]
    mapping = ArenaMapper.fit(image, arena)
    assert mapping.reprojection_error == pytest.approx(0.0, abs=1e-8)
    assert mapping.forward((5, 5)) == pytest.approx((11, 17))
    assert mapping.inverse_point((11, 17)) == pytest.approx((5, 5))


def test_sync_tracker_and_explicit_unmeasured_report():
    sync = TimestampSynchronizer().fit([0, 100, 200], [25, 125, 225])
    assert sync.offset_ms == pytest.approx(25)
    tracker = SimpleGameAwareTracker(max_distance=1.0)
    first = tracker.update(0, [Detection("hog_rider", 1, 1, 1)])
    second = tracker.update(100, [Detection("hog_rider", 1, 1.2, 1)])
    assert first[0].track_id == second[0].track_id
    assert second[0].velocity_x > 0
    report = report_markdown(__import__("tools.calibration", fromlist=["compare_scenario"]).compare_scenario(
        "empty", NormalizedTrace(()), NormalizedTrace(())))
    assert "UNMEASURED" in report


def test_sim_trace_adapter_is_deterministic(tmp_path: Path):
    scenario = Scenario.from_dict({
        "scenario_id": "deterministic_knight", "duration_ms": 100, "dt_ms": 50, "seed": 3,
        "decks": [["knight"], ["knight"]],
        "actions": [{"time_ms": 0, "action": "deploy", "side": 1,
                     "card": "knight", "position": [9, 22]}],
    })
    adapter = SimTraceAdapter()
    first = adapter.run(scenario)
    second = adapter.run(scenario)
    assert trace_digest(first) == trace_digest(second)
    assert first.frames
    assert any(frame.entities for frame in first.frames)
    output = tmp_path / "sim.json"
    write_trace(output, first)
    assert trace_digest(read_trace(output)) == trace_digest(first)


def test_unsupported_sim_action_fails_clearly():
    scenario = Scenario.from_dict({
        "scenario_id": "unsupported", "duration_ms": 100, "decks": [["knight"], ["knight"]],
        "actions": [{"time_ms": 0, "action": "teleport", "side": 1}],
    })
    with pytest.raises(CalibrationError, match="unsupported"):
        SimTraceAdapter().run(scenario)
