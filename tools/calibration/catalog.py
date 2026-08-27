"""Deterministic scenario catalog generation and validation for sprint task #5."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from .core import CalibrationError, Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[2]
SCENARIO_ROOT = ROOT / "calibration" / "scenarios"
MANIFEST_PATH = ROOT / "calibration" / "catalog.json"
CATEGORIES = (
    "arena", "movement", "targeting", "collisions", "combat_timing", "pathing",
    "building_pull", "projectiles", "knockback", "spawning", "special_mechanics",
)
REQUESTED_CARDS = (
    "knight", "minipekka", "musketeer", "giant", "hog_rider", "balloon",
    "minions", "cannon", "xbow", "fireball", "log", "bowler", "fisherman", "tornado",
)
EVIDENCE_STATUSES = {"synthetic", "unmeasured", "reference-hypothesis"}


def _deck(primary: str, secondary: str) -> list[list[str]]:
    pool = [primary, secondary, "knight", "musketeer", "cannon", "fireball", "log", "minions",
            "giant", "balloon", "bowler", "fisherman"]
    return [list(dict.fromkeys(pool))[:8], ["giant", "hog_rider", "balloon", "bowler", "fisherman", "tornado", "minions", "cannon"]]


def _scenario(index: int, category: str, primary: str, secondary: str, *, special: str = "") -> dict[str, Any]:
    side = 1 if index % 2 else -1
    troop_y = 22 if side == 1 else 9
    opposing_y = 9 if side == 1 else 22
    actions = [
        {"time_ms": 0, "action": "deploy", "side": side, "card": primary, "position": [9, troop_y]},
        {"time_ms": 150, "action": "deploy", "side": -side, "card": secondary, "position": [9, opposing_y]},
    ]
    if category in {"projectiles", "knockback", "special_mechanics", "combat_timing"}:
        actions.append({"time_ms": 300, "action": "spell", "side": side, "card": "fireball", "position": [9, opposing_y]})
    if category == "building_pull":
        actions = [
            {"time_ms": 0, "action": "deploy", "side": side, "card": primary, "position": [9, troop_y]},
            {"time_ms": 100, "action": "building", "side": side, "card": "cannon", "position": [9, 20 if side == 1 else 11]},
        ]
        if special:
            actions[1]["metadata"] = {"sweep_role": special, "map_ready": True}
    return {
        "scenario_id": f"sprint5_{index:03d}_{category}",
        "category": category,
        "tags": ["sprint-5", category, primary, secondary] + ([special] if special else []),
        "split": "validation" if index % 5 == 0 else "train",
        "duration_ms": 1000,
        "dt_ms": 50,
        "seed": 5000 + index,
        "decks": _deck(primary, secondary),
        "actions": actions,
        "observation_windows": [[0, 1000]],
        "measures": [
            {"name": "entity_positions", "category": "position", "tolerance": 0.5, "evidence_ids": [f"SYNTH-S5-{index:03d}"]},
            {"name": "event_order_candidate", "category": category, "tolerance": 250.0, "evidence_ids": [f"SYNTH-S5-{index:03d}"]},
        ],
        "evidence_ids": [f"SYNTH-S5-{index:03d}"],
        "evidence_status": "synthetic",
        "metadata": {
            "provenance": {"source": "generated_synthetic_catalog", "method": "deterministic template", "real_data_claim": False},
            "candidate_thresholds_only": True,
            "implementation_locations": ["tools/calibration/core.py"],
        },
    }


def generate_catalog(root: Path = SCENARIO_ROOT) -> list[dict[str, Any]]:
    root.mkdir(parents=True, exist_ok=True)
    templates = [
        ("arena", "knight", "musketeer"), ("movement", "giant", "knight"),
        ("targeting", "musketeer", "minions"), ("collisions", "knight", "minipekka"),
        ("combat_timing", "minipekka", "knight"), ("pathing", "giant", "hog_rider"),
        ("building_pull", "hog_rider", "cannon"), ("projectiles", "musketeer", "balloon"),
        ("knockback", "bowler", "knight"), ("spawning", "minions", "giant"),
        ("special_mechanics", "fisherman", "tornado"),
    ]
    scenarios: list[dict[str, Any]] = []
    index = 1
    for category, primary, secondary in templates:
        count = 6 if category != "building_pull" else 10
        for variant in range(count):
            special = ""
            if category == "building_pull":
                special = ("hog_cannon_pull_map" if variant % 4 == 0 else
                           "giant_cannon_pull_map" if variant % 4 == 1 else
                           "balloon_cannon_pull_map" if variant % 4 == 2 else "generic_obstacle_pull_map")
                primary = ("hog_rider" if variant % 4 == 0 else "giant" if variant % 4 == 1 else
                           "balloon" if variant % 4 == 2 else "knight")
            item = _scenario(index, category, primary, secondary, special=special)
            path = root / f"{item['scenario_id']}.json"
            path.write_text(json.dumps(item, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            scenarios.append(item)
            index += 1
    return scenarios


def validate_catalog(root: Path = SCENARIO_ROOT) -> dict[str, Any]:
    errors: list[str] = []
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths = sorted(root.rglob("*.json")) if root.exists() else []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            scenario = Scenario.from_dict(raw)
            if scenario.scenario_id in seen:
                errors.append(f"duplicate scenario_id: {scenario.scenario_id}")
            seen.add(scenario.scenario_id)
            if scenario.category not in CATEGORIES:
                errors.append(f"{path}: unsupported category {scenario.category}")
            if raw.get("evidence_status") not in EVIDENCE_STATUSES:
                errors.append(f"{path}: missing/invalid evidence_status")
            if not raw.get("evidence_ids"):
                errors.append(f"{path}: evidence_ids required")
            if raw.get("metadata", {}).get("candidate_thresholds_only") is not True:
                errors.append(f"{path}: thresholds must be marked candidate-only")
            records.append({"scenario_id": scenario.scenario_id, "category": scenario.category,
                            "split": scenario.split, "path": path.relative_to(ROOT).as_posix()})
        except (OSError, json.JSONDecodeError, CalibrationError, TypeError, KeyError) as exc:
            errors.append(f"{path}: {exc}")
    counts = {category: sum(row["category"] == category for row in records) for category in CATEGORIES}
    splits = {split: sum(row["split"] == split for row in records) for split in ("train", "validation", "test")}
    return {"status": "PASS" if not errors else "FAIL", "count": len(records), "categories": counts,
            "splits": splits, "errors": errors, "scenarios": records}


def write_manifest(root: Path = SCENARIO_ROOT, path: Path = MANIFEST_PATH) -> dict[str, Any]:
    report = validate_catalog(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "catalog": "sprint-5", **report}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "validate", "list"))
    parser.add_argument("--root", type=Path, default=SCENARIO_ROOT)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command == "generate":
        generate_catalog(args.root)
    report = validate_catalog(args.root)
    if args.command == "list":
        print(json.dumps({"status": report["status"], "count": report["count"], "categories": report["categories"], "splits": report["splits"]}, indent=2))
    else:
        if args.command == "generate":
            write_manifest(args.root)
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
