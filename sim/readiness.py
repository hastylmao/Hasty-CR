"""Strict, evidence-based gate for RL training on the headless simulator.

Passing unit tests proves only the scenarios they cover.  A policy trained
against unimplemented client action graphs or uncalibrated contact physics can
learn exploits that cannot transfer to Clash Royale, so this command is
intentionally stricter than the ordinary test suite.

    python -m sim.readiness
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .action_audit import report as action_report
from .card_catalog_audit import report as catalog_report
from .level_audit import report as level_report
from .public_stat_audit import report as stat_report


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "royaleapi" / "combat_rules.json"
CARD_SNAPSHOT = ROOT / "data" / "royaleapi" / "cards.json"
LIVE_PROBES = ROOT / "data" / "validation" / "live_probes.json"
# The level every verified value in combat_rules.json was recorded at, and the
# level the simulator runs at. Training at any other level silently discards
# them; see sim/level_audit.py.
TRAINING_LEVEL = 11
# Only the categories no published dataset can answer. `projectile_timing` and
# `spell_timing` used to be here and were removed on 2026-08-20: RoyaleAPI
# publishes every projectile's speed, its `homing` flag and its
# `check_collisions` flag, and every spell's radius and duration. A shot that
# has left an attacker connects with what it was fired at - check_collisions is
# false - so there is no spatial miss to capture. Demanding a controlled video
# for a value that ships in a file, while accepting the same source for every
# override in combat_rules.json, was inconsistent.
#
# Contact is different: no dataset says how close two bodies stand when they
# meet, or how close a troop gets to a building it walks past.
REQUIRED_PROBE_CATEGORIES = frozenset({
    "map_anchors", "troop_contact", "building_contact",
})
REQUIRED_EVIDENCE_FIELDS = frozenset({
    "capture_id", "start_frame", "end_frame", "cards_and_levels",
    "deployment", "observed_result", "regression_test",
})
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _regression_test_error(reference: object) -> str | None:
    """Return an error unless an evidence record names an executable test.

    A free-form description such as ``"test contact"`` is useful in notes but
    cannot protect a calibrated constant from a later refactor.  Keeping the
    reference in pytest's normal ``path::test_name`` form makes the evidence
    both human-navigable and machine-checkable without running the test suite
    as part of a readiness report.
    """
    if not isinstance(reference, str) or reference.count("::") != 1:
        return "has invalid regression_test (expected tests/path.py::test_name)"
    relative_path, test_name = reference.split("::", 1)
    path = ROOT / relative_path
    if not relative_path.startswith("tests/") or not path.is_file():
        return "names a missing regression-test file"
    if not test_name.startswith("test_"):
        return "names an invalid regression-test function"
    source = path.read_text(encoding="utf-8", errors="replace")
    if f"def {test_name}(" not in source:
        return "names a missing regression-test function"
    return None


def probe_evidence_errors(probes: dict) -> dict[str, list[str]]:
    """Validate evidence provenance before it can claim calibration.

    This is intentionally structural rather than trying to infer physics from a
    video file. A reviewer must state what frames were measured, what was on
    the board and which test protects the resulting simulator behaviour.
    """
    captures = {
        capture.get("id"): capture for capture in probes.get("captures", [])
        if isinstance(capture, dict) and isinstance(capture.get("id"), str)
    }
    errors: dict[str, list[str]] = {}
    for category, entry in probes.get("probes", {}).items():
        if not isinstance(entry, dict) or entry.get("status") != "accepted":
            continue
        category_errors = []
        evidence_items = entry.get("accepted_evidence", [])
        if not isinstance(evidence_items, list) or not evidence_items:
            category_errors.append("no accepted evidence")
        for index, evidence in enumerate(evidence_items if isinstance(evidence_items, list) else []):
            if not isinstance(evidence, dict):
                category_errors.append(f"evidence {index} is not an object")
                continue
            missing = REQUIRED_EVIDENCE_FIELDS - set(evidence)
            if missing:
                category_errors.append(
                    f"evidence {index} missing: {', '.join(sorted(missing))}")
                continue
            capture = captures.get(evidence["capture_id"])
            if capture is None:
                category_errors.append(f"evidence {index} names unknown capture")
            if (not isinstance(evidence["start_frame"], int)
                    or not isinstance(evidence["end_frame"], int)
                    or evidence["start_frame"] < 0
                    or evidence["end_frame"] <= evidence["start_frame"]):
                category_errors.append(f"evidence {index} has invalid frame range")
            for field in ("cards_and_levels", "deployment", "observed_result",
                          "regression_test"):
                if not evidence[field]:
                    category_errors.append(f"evidence {index} has blank {field}")
            test_error = _regression_test_error(evidence["regression_test"])
            if test_error:
                category_errors.append(f"evidence {index} {test_error}")
            if capture is not None:
                if capture.get("classification") != "controlled":
                    category_errors.append(
                        f"evidence {index} capture is not a controlled probe")
                if (not isinstance(capture.get("fps"), (int, float))
                        or capture["fps"] < 50):
                    category_errors.append(
                        f"evidence {index} capture is below the 50 fps minimum")
                if not isinstance(capture.get("source_path"), str) or not capture["source_path"]:
                    category_errors.append(
                        f"evidence {index} capture lacks a source path")
                if (not isinstance(capture.get("sha256"), str)
                        or not SHA256.fullmatch(capture["sha256"])):
                    category_errors.append(
                        f"evidence {index} capture lacks a valid SHA-256")
                frame_count = capture.get("frames")
                if not isinstance(frame_count, int) or frame_count < 2:
                    category_errors.append(
                        f"evidence {index} capture lacks a valid frame count")
                elif (isinstance(evidence["end_frame"], int)
                      and evidence["end_frame"] >= frame_count):
                    category_errors.append(
                        f"evidence {index} frame range exceeds capture length")
        if category_errors:
            errors[category] = category_errors
    return errors


def missing_accepted_probe_categories(probes: dict) -> set[str]:
    """Return categories lacking reviewed, frame-linked live evidence.

    ``completed`` is retained for a human-readable summary, but cannot by
    itself unlock training.  An accepted category must also name at least one
    accepted evidence record.  This prevents an inventory of ordinary gameplay
    recordings from being mistaken for a calibration matrix.
    """
    completed = set(probes.get("completed", ()))
    declared = probes.get("probes", {})
    errors = probe_evidence_errors(probes)
    missing = set()
    for category in REQUIRED_PROBE_CATEGORIES:
        evidence = declared.get(category, {})
        if (category not in completed
                or evidence.get("status") != "accepted"
                or not evidence.get("accepted_evidence")
                or category in errors):
            missing.add(category)
    return missing


def report() -> dict:
    """Return the proof currently available for training readiness."""
    reasons: list[str] = []
    if not CARD_SNAPSHOT.exists():
        reasons.append("no versioned public-card snapshot")
    if not RULES.exists():
        reasons.append("no versioned external combat-rule registry")

    if CARD_SNAPSHOT.exists():
        try:
            catalogue = catalog_report()
            if catalogue["unresolved"] or catalogue["ambiguous"]:
                reasons.append(
                    "public card catalogue does not map uniquely to client data")
        except (OSError, ValueError, json.JSONDecodeError):
            reasons.append("unreadable public-card snapshot")

    if CARD_SNAPSHOT.exists():
        # An identity check proves each public card maps to a local row; it
        # says nothing about the values on that row. Cost and rarity are the
        # two that are silent when wrong - rarity drives level scaling, so a
        # miscategorised card is wrong at every level and still parses.
        try:
            stats = stat_report()
            if stats["unexplained_divergences"]:
                reasons.append(
                    f"{len(stats['unexplained_divergences'])} card values "
                    "disagree with the public snapshot without an explanation")
        except (OSError, ValueError, json.JSONDecodeError):
            reasons.append("unreadable public card stat audit")

    if RULES.exists():
        # Externally verified values are exact only at the level they were
        # verified at; elsewhere they are carried along the client curve, which
        # is an extrapolation. Everything here was verified at 11, which is what
        # the project trains at, so training never runs on an extrapolation.
        try:
            levels = level_report(TRAINING_LEVEL)
            inexact = levels["carried"] + levels["pinned"]
            if inexact:
                reasons.append(
                    f"{levels['values_carried'] + levels['values_pinned']} "
                    f"externally verified values are not exact at level "
                    f"{TRAINING_LEVEL}")
        except (OSError, ValueError, json.JSONDecodeError):
            reasons.append("unreadable external combat-rule registry")

    graphs = action_report()
    graph_count = sum(len(entries) for entries in graphs.values())
    if graph_count:
        gated = len(graphs.get("calibration-gated source graphs", ()))
        unresolved = graph_count - gated
        if unresolved:
            reasons.append(
                f"{unresolved} semantic client source graphs still lack an "
                "implementation/probe disposition")
        if gated:
            # Deliberately still blocking, and deliberately reworded. These
            # started as "the mechanic is missing" and are now "the mechanic
            # works and one named number in it is approximate" - a strong-band
            # boundary, a hit ordering, a flight curve, which logarithm
            # `logX10000` denotes. The bar has not moved; what the number means
            # has, and reading it as eight unimplemented cards is wrong.
            reasons.append(
                f"{gated} source graphs are implemented with a named "
                f"approximation awaiting measurement (see "
                f"CALIBRATION_GATED_FILES for what each one is)")

    if not LIVE_PROBES.exists():
        reasons.append("no recorded live geometry/contact/projectile probe matrix")
    else:
        try:
            probes = json.loads(LIVE_PROBES.read_text(encoding="utf-8"))
            missing = missing_accepted_probe_categories(probes)
            evidence_errors = probe_evidence_errors(probes)
            if missing:
                reasons.append("incomplete live probe matrix: " + ", ".join(sorted(missing)))
            if evidence_errors:
                reasons.append("invalid accepted probe evidence: " + ", ".join(
                    f"{category} ({'; '.join(errors)})"
                    for category, errors in sorted(evidence_errors.items())))
        except (OSError, json.JSONDecodeError):
            reasons.append("unreadable live probe matrix")

    return {
        "ready": not reasons,
        "reasons": reasons,
        "action_graphs": {name: len(entries) for name, entries in graphs.items()},
    }


def main() -> int:
    status = report()
    print("RL READY" if status["ready"] else "RL NOT READY")
    for reason in status["reasons"]:
        print(f"- {reason}")
    return 0 if status["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
