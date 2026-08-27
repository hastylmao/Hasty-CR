"""Versioned mechanics evidence database, validation, queries, and reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .core import CalibrationError, canonical_json

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / "data" / "fidelity" / "mechanics.json"
DEFAULT_REPORT = ROOT / "reports" / "MECHANICS_TRUTH_TABLE.md"

STATUSES = {
    "VERIFIED_CURRENT_DATA", "VERIFIED_OBSERVATION", "HISTORICAL_DIRECT_DATA",
    "CROSS_IMPLEMENTATION_AGREEMENT", "SINGLE_IMPLEMENTATION",
    "PRIVATE_SERVER_DATA", "HYPOTHESIS", "LEGACY_GUESS", "UNKNOWN",
}
CONFIDENCES = {"NONE", "LOW", "MEDIUM", "HIGH"}
SOURCE_TYPES = {
    "CURRENT_CLIENT_DATA", "CURRENT_PUBLIC_DATA", "CONTROLLED_OBSERVATION",
    "HISTORICAL_DATA", "PRIVATE_SERVER_DATA", "SIMULATOR_IMPLEMENTATION",
    "SIMULATOR_COMPARISON", "WEB_CLAIM", "SYNTHETIC_SCENARIO",
    "IMPLEMENTATION_REVIEW",
}
COLLECTIONS = (
    "game_versions", "sources", "implementations", "cards", "scenarios",
    "mechanics", "parameters", "evidence", "disagreements", "measurements",
)


@dataclass(frozen=True)
class EvidenceQuery:
    domain: str | None = None
    status: str | None = None
    card: str | None = None
    source_id: str | None = None
    confidence: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...]
    counts: Mapping[str, int]
    real_measurements: int
    digest: str

    @property
    def status(self) -> str:
        return "PASS" if not self.errors else "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": list(self.errors),
            "counts": dict(self.counts),
            "real_measurements": self.real_measurements,
            "sha256": self.digest,
        }


def read_database(path: str | Path = DEFAULT_PATH) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot read evidence database {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationError("evidence database must be a JSON object")
    return value


def database_digest(database: Mapping[str, Any]) -> str:
    payload = {key: value for key, value in database.items() if key not in {"generated_at", "sha256"}}
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def write_database(path: str | Path, database: Mapping[str, Any]) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(database)
    payload["sha256"] = database_digest(payload)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload["sha256"]


def _indexed(rows: Any, collection: str, errors: list[str]) -> dict[str, Mapping[str, Any]]:
    if not isinstance(rows, list):
        errors.append(f"{collection} must be a list")
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{collection}[{index}] must be an object")
            continue
        row_id = row.get("id")
        if not isinstance(row_id, str) or not row_id:
            errors.append(f"{collection}[{index}].id is required")
        elif row_id in result:
            errors.append(f"duplicate {collection} id: {row_id}")
        else:
            result[row_id] = row
    return result


def _references(row: Mapping[str, Any], field: str, valid: set[str], label: str,
                errors: list[str]) -> None:
    values = row.get(field, [])
    if not isinstance(values, list):
        errors.append(f"{label}.{field} must be a list")
        return
    missing = sorted(value for value in values if value not in valid)
    if missing:
        errors.append(f"{label}.{field} has unknown ids: {missing}")


def validate_database(database: Mapping[str, Any]) -> ValidationResult:
    errors: list[str] = []
    if database.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    indexes = {name: _indexed(database.get(name), name, errors) for name in COLLECTIONS}
    source_ids = set(indexes["sources"])
    implementation_ids = set(indexes["implementations"])
    card_ids = set(indexes["cards"])
    scenario_ids = set(indexes["scenarios"])
    mechanic_ids = set(indexes["mechanics"])
    parameter_ids = set(indexes["parameters"])
    evidence_ids = set(indexes["evidence"])
    version_ids = set(indexes["game_versions"])

    for mechanic_id, mechanic in indexes["mechanics"].items():
        label = f"mechanics.{mechanic_id}"
        status = mechanic.get("status")
        confidence = mechanic.get("confidence")
        if status not in STATUSES:
            errors.append(f"{label}.status invalid: {status}")
        if confidence not in CONFIDENCES:
            errors.append(f"{label}.confidence invalid: {confidence}")
        _references(mechanic, "parameter_ids", parameter_ids, label, errors)
        _references(mechanic, "evidence_ids", evidence_ids, label, errors)
        _references(mechanic, "scenario_ids", scenario_ids, label, errors)
        _references(mechanic, "affected_cards", card_ids, label, errors)
        _references(mechanic, "implementation_ids", implementation_ids, label, errors)

    for parameter_id, parameter in indexes["parameters"].items():
        label = f"parameters.{parameter_id}"
        if parameter.get("mechanic_id") not in mechanic_ids:
            errors.append(f"{label}.mechanic_id is unknown")
        if parameter.get("status") not in STATUSES:
            errors.append(f"{label}.status invalid: {parameter.get('status')}")
        if parameter.get("confidence") not in CONFIDENCES:
            errors.append(f"{label}.confidence invalid: {parameter.get('confidence')}")
        version_id = parameter.get("game_version_id")
        if version_id is not None and version_id not in version_ids:
            errors.append(f"{label}.game_version_id is unknown")
        _references(parameter, "source_ids", source_ids, label, errors)
        _references(parameter, "scenario_ids", scenario_ids, label, errors)
        _references(parameter, "affected_cards", card_ids, label, errors)

    for evidence_id, evidence in indexes["evidence"].items():
        label = f"evidence.{evidence_id}"
        if evidence.get("source_id") not in source_ids:
            errors.append(f"{label}.source_id is unknown")
        if evidence.get("source_type") not in SOURCE_TYPES:
            errors.append(f"{label}.source_type invalid: {evidence.get('source_type')}")
        if evidence.get("status") not in STATUSES:
            errors.append(f"{label}.status invalid: {evidence.get('status')}")
        if evidence.get("confidence") not in CONFIDENCES:
            errors.append(f"{label}.confidence invalid: {evidence.get('confidence')}")
        _references(evidence, "mechanic_ids", mechanic_ids, label, errors)
        if evidence.get("real_game_measurement") and evidence.get("source_type") != "CONTROLLED_OBSERVATION":
            errors.append(f"{label} real measurement must be CONTROLLED_OBSERVATION")

    for disagreement_id, disagreement in indexes["disagreements"].items():
        label = f"disagreements.{disagreement_id}"
        if disagreement.get("mechanic_id") not in mechanic_ids:
            errors.append(f"{label}.mechanic_id is unknown")
        _references(disagreement, "source_ids", source_ids, label, errors)
        values = disagreement.get("implementation_values")
        if not isinstance(values, list) or len(values) < 2:
            errors.append(f"{label}.implementation_values needs at least two entries")

    for measurement_id, measurement in indexes["measurements"].items():
        label = f"measurements.{measurement_id}"
        if measurement.get("mechanic_id") not in mechanic_ids:
            errors.append(f"{label}.mechanic_id is unknown")
        if measurement.get("scenario_id") not in scenario_ids:
            errors.append(f"{label}.scenario_id is unknown")
        if measurement.get("source_id") not in source_ids:
            errors.append(f"{label}.source_id is unknown")

    real_measurements = sum(bool(row.get("real_game_measurement")) for row in indexes["measurements"].values())
    real_measurements += sum(bool(row.get("real_game_measurement")) for row in indexes["evidence"].values())
    return ValidationResult(tuple(errors), {name: len(indexes[name]) for name in COLLECTIONS},
                            real_measurements, database_digest(database))


def query_mechanics(database: Mapping[str, Any], query: EvidenceQuery) -> list[dict[str, Any]]:
    evidence = {row["id"]: row for row in database.get("evidence", [])}
    rows: list[dict[str, Any]] = []
    for mechanic in database.get("mechanics", []):
        if query.domain and mechanic.get("domain") != query.domain:
            continue
        if query.status and mechanic.get("status") != query.status:
            continue
        if query.confidence and mechanic.get("confidence") != query.confidence:
            continue
        if query.card and query.card not in mechanic.get("affected_cards", []):
            continue
        linked = [evidence[item] for item in mechanic.get("evidence_ids", []) if item in evidence]
        if query.source_id and not any(row.get("source_id") == query.source_id for row in linked):
            continue
        if query.text:
            blob = canonical_json({"mechanic": mechanic, "evidence": linked}).lower()
            if query.text.lower() not in blob:
                continue
        rows.append(dict(mechanic))
    return sorted(rows, key=lambda row: row["id"])


def summary(database: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_database(database)
    statuses: dict[str, int] = {}
    domains: dict[str, int] = {}
    for mechanic in database.get("mechanics", []):
        statuses[mechanic["status"]] = statuses.get(mechanic["status"], 0) + 1
        domains[mechanic["domain"]] = domains.get(mechanic["domain"], 0) + 1
    return {
        **validation.to_dict(),
        "statuses": dict(sorted(statuses.items())),
        "domains": dict(sorted(domains.items())),
        "readiness": "NOT_READY" if validation.real_measurements == 0 else "EVIDENCE_PRESENT_NOT_PROMOTED",
    }


def render_truth_table(database: Mapping[str, Any]) -> str:
    sources = {row["id"]: row for row in database.get("sources", [])}
    evidence = {row["id"]: row for row in database.get("evidence", [])}
    disagreements = {}
    for row in database.get("disagreements", []):
        disagreements.setdefault(row["mechanic_id"], []).append(row)
    lines = [
        "# Mechanics Truth Table", "",
        "Generated from `data/fidelity/mechanics.json`. `VERIFIED` is reserved for current direct data or controlled observation; cross-simulator agreement is not truth.", "",
    ]
    for mechanic in sorted(database.get("mechanics", []), key=lambda row: row["id"]):
        linked = [evidence[item] for item in mechanic.get("evidence_ids", []) if item in evidence]
        lines.extend([
            f"## {mechanic['id']}", "",
            f"- **Current HastyCR:** {mechanic['current_hastycr']}",
            f"- **Status:** `{mechanic['status']}`; confidence `{mechanic['confidence']}`; measurement `{mechanic['measurement_status']}`.",
            f"- **Affected cards:** {', '.join(mechanic.get('affected_cards', [])) or 'shared/all applicable cards'}.",
            f"- **Implementation:** {', '.join(mechanic.get('implementation_locations', []))}.",
        ])
        for item in linked:
            source = sources.get(item["source_id"], {})
            lines.append(f"- **Evidence `{item['id']}`:** {item['claim']} Source: {source.get('title', item['source_id'])}; `{item['status']}` / `{item['confidence']}`.")
        for item in disagreements.get(mechanic["id"], []):
            values = "; ".join(f"{value['implementation']}: {value['value']}" for value in item["implementation_values"])
            lines.append(f"- **Disagreement:** {values}. Severity `{item['severity']}`, RL impact `{item['rl_impact']}`.")
        lines.extend([
            f"- **Conclusion:** {mechanic['conclusion']}",
            f"- **Needed experiment:** {mechanic['needed_experiment']}", "",
        ])
    validation = validate_database(database)
    lines.extend([
        "## Database checkpoint", "",
        f"- Mechanics: {validation.counts['mechanics']}",
        f"- Parameters: {validation.counts['parameters']}",
        f"- Evidence records: {validation.counts['evidence']}",
        f"- Disagreements: {validation.counts['disagreements']}",
        f"- Real measured traces: **{validation.real_measurements}**", "",
    ])
    return "\n".join(lines)


def export_sqlite(database: Mapping[str, Any], path: str | Path) -> None:
    result = validate_database(database)
    if result.errors:
        raise CalibrationError("invalid evidence database: " + "; ".join(result.errors))
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    connection = sqlite3.connect(target)
    try:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata VALUES (?, ?)", ("sha256", result.digest))
        for collection in COLLECTIONS:
            connection.execute(f"CREATE TABLE {collection} (id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
            connection.executemany(
                f"INSERT INTO {collection} VALUES (?, ?)",
                [(row["id"], canonical_json(row)) for row in database[collection]],
            )
        connection.commit()
    finally:
        connection.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "summary", "query", "report", "sqlite"))
    parser.add_argument("--database", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--domain")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--confidence", choices=sorted(CONFIDENCES))
    parser.add_argument("--card")
    parser.add_argument("--source")
    parser.add_argument("--text")
    args = parser.parse_args(list(argv) if argv is not None else None)
    database = read_database(args.database)
    validation = validate_database(database)
    if args.command == "validate":
        print(json.dumps(validation.to_dict(), indent=2, sort_keys=True))
    elif args.command == "summary":
        print(json.dumps(summary(database), indent=2, sort_keys=True))
    elif args.command == "query":
        rows = query_mechanics(database, EvidenceQuery(args.domain, args.status, args.card,
                                                        args.source, args.confidence, args.text))
        print(json.dumps({"count": len(rows), "mechanics": rows}, indent=2, sort_keys=True))
    elif args.command == "report":
        output = args.output or DEFAULT_REPORT
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(render_truth_table(database) + "\n", encoding="utf-8")
        print(json.dumps({"status": "PASS", "output": str(output), "sha256": validation.digest}))
    else:
        output = args.output or args.database.with_suffix(".sqlite")
        export_sqlite(database, output)
        print(json.dumps({"status": "PASS", "output": str(output), "sha256": validation.digest}))
    return 0 if validation.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
