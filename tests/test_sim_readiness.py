from sim.readiness import (missing_accepted_probe_categories,
                           probe_evidence_errors)


CONTROLLED_CAPTURE = {
    "id": "clip-a",
    "frames": 10,
    "fps": 60,
    "classification": "controlled",
    "source_path": "C:/captures/clip-a.mp4",
    "sha256": "a" * 64,
}


def test_contextual_recordings_cannot_unlock_live_probe_categories():
    matrix = {
        "completed": ["map_anchors"],
        "probes": {
            "map_anchors": {
                "status": "pending",
                "accepted_evidence": [],
            },
        },
    }
    # projectile_timing and spell_timing are no longer required: every
    # projectile's speed, homing and check_collisions flag, and every spell's
    # radius and duration, are published. Contact is not.
    assert missing_accepted_probe_categories(matrix) == {
        "map_anchors", "troop_contact", "building_contact",
    }


def test_reviewed_frame_linked_evidence_satisfies_the_matrix_gate():
    categories = ("map_anchors", "troop_contact", "building_contact",
                  "projectile_timing", "spell_timing")
    matrix = {
        "completed": list(categories),
        "captures": [CONTROLLED_CAPTURE],
        "probes": {
            category: {
                "status": "accepted",
                "accepted_evidence": [{
                    "capture_id": "clip-a",
                    "start_frame": 1,
                    "end_frame": 2,
                    "cards_and_levels": "Knight level 11",
                    "deployment": "bottom King Tower centre",
                    "observed_result": "Knight moves left",
                    "regression_test": (
                        "tests/test_sim_readiness.py::"
                        "test_reviewed_frame_linked_evidence_satisfies_the_matrix_gate"),
                }],
            }
            for category in categories
        },
    }
    assert missing_accepted_probe_categories(matrix) == set()
    assert probe_evidence_errors(matrix) == {}


def test_claimed_evidence_without_a_frame_link_cannot_unlock_readiness():
    matrix = {
        "captures": [{"id": "clip-a"}],
        "probes": {
            "troop_contact": {
                "status": "accepted",
                "accepted_evidence": [{"capture_id": "clip-a"}],
            },
        },
    }
    assert "troop_contact" in probe_evidence_errors(matrix)
    assert "troop_contact" in missing_accepted_probe_categories(matrix)


def test_probe_evidence_must_name_a_real_test_and_fit_the_capture():
    matrix = {
        "captures": [CONTROLLED_CAPTURE],
        "probes": {
            "troop_contact": {
                "status": "accepted",
                "accepted_evidence": [{
                    "capture_id": "clip-a",
                    "start_frame": 8,
                    "end_frame": 12,
                    "cards_and_levels": "Knight level 11",
                    "deployment": "bottom King Tower centre",
                    "observed_result": "Knight moves left",
                    "regression_test": "contact test",
                }],
            },
        },
    }
    errors = probe_evidence_errors(matrix)["troop_contact"]
    assert any("invalid regression_test" in error for error in errors)
    assert any("exceeds capture length" in error for error in errors)


def test_contextual_or_low_fps_capture_cannot_be_promoted_to_calibration():
    matrix = {
        "captures": [{**CONTROLLED_CAPTURE,
                      "classification": "contextual_only", "fps": 30}],
        "probes": {
            "troop_contact": {
                "status": "accepted",
                "accepted_evidence": [{
                    "capture_id": "clip-a",
                    "start_frame": 1,
                    "end_frame": 2,
                    "cards_and_levels": "Knight level 11",
                    "deployment": "bottom King Tower centre",
                    "observed_result": "Knight moves left",
                    "regression_test": (
                        "tests/test_sim_readiness.py::"
                        "test_contextual_or_low_fps_capture_cannot_be_promoted_to_calibration"),
                }],
            },
        },
    }
    errors = probe_evidence_errors(matrix)["troop_contact"]
    assert any("not a controlled" in error for error in errors)
    assert any("below the 50 fps" in error for error in errors)
