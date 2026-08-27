from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.calibration import read_trace, trace_digest
from tools.calibration.synthetic import (corrupt_trace, estimate_time_shift,
                                         estimate_translation, evaluate_identity)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "calibration" / "fixtures"


def test_identity_trace_has_zero_position_and_timing_error():
    trace = read_trace(FIXTURES / "simulator_trace.json")
    assert evaluate_identity(trace) == {"position_error": 0.0, "timing_error_ms": 0.0}


def test_known_shift_and_translation_are_recovered():
    trace = read_trace(FIXTURES / "simulator_trace.json")
    corrupted, _ = corrupt_trace(trace, {"time_shift_ms": 100, "translation": [0.25, -0.15], "seed": 7})
    assert estimate_translation(trace, corrupted) == pytest.approx((0.25, -0.15))
    assert estimate_time_shift(trace, corrupted) == pytest.approx(100)


def test_dropped_tracks_and_bounded_gap_are_deterministic():
    trace = read_trace(FIXTURES / "simulator_trace.json")
    corrupted, truth = corrupt_trace(trace, {"gap_tracks": [trace.frames[1].entities[0].track_id], "gap_start_ms": 50, "gap_end_ms": 150, "seed": 3})
    assert truth["dropped_observations"]
    assert len(corrupted.frames[1].entities) < len(trace.frames[1].entities)
    again, same_truth = corrupt_trace(trace, {"gap_tracks": [trace.frames[1].entities[0].track_id], "gap_start_ms": 50, "gap_end_ms": 150, "seed": 3})
    assert trace_digest(corrupted) == trace_digest(again)
    assert truth == same_truth


def test_fixture_digests_are_checked_in_and_stable():
    expected = json.loads((FIXTURES / "fixture_digests.json").read_text(encoding="utf-8"))
    for name, digest in expected.items():
        assert hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest() == digest
