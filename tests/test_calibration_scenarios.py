from __future__ import annotations

import json
from pathlib import Path

from tools.calibration.catalog import CATEGORIES, validate_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_count_coverage_and_splits():
    report = validate_catalog(ROOT / "calibration" / "scenarios")
    assert report["status"] == "PASS"
    assert report["count"] >= 55
    assert all(report["categories"][category] > 0 for category in CATEGORIES)
    assert report["splits"]["train"] > report["splits"]["validation"] > 0


def test_catalog_records_have_required_candidate_evidence_fields():
    paths = sorted((ROOT / "calibration" / "scenarios").glob("*.json"))
    assert paths
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        assert value["scenario_id"]
        assert len(value["decks"]) == 2
        assert value["actions"] == sorted(value["actions"], key=lambda action: action["time_ms"])
        assert value["evidence_status"] in {"synthetic", "unmeasured", "reference-hypothesis"}
        assert value["metadata"]["candidate_thresholds_only"] is True


def test_registries_and_readiness_schema():
    required = {"status", "confidence", "provenance", "evidence_ids", "tested_range",
                "implementation_locations", "legacy_default", "promotion_rules"}
    for name in ("mechanics.json", "shared_physics.json"):
        registry = json.loads((ROOT / "calibration" / "registry" / name).read_text(encoding="utf-8"))
        assert registry["game_version"]
        assert registry["entries"]
        assert all(required <= entry.keys() for entry in registry["entries"])
    gates = json.loads((ROOT / "calibration" / "readiness_gates.json").read_text(encoding="utf-8"))
    assert gates["scalar_accuracy_claim"] is False
    assert gates["current_status"] == "NOT_READY"
    assert set(CATEGORIES) == set(gates["required_category_evidence"])
    assert gates["regression_health"]["required"] is True
