from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tools.calibration.evidence import (
    DEFAULT_PATH,
    EvidenceQuery,
    database_digest,
    export_sqlite,
    query_mechanics,
    read_database,
    render_truth_table,
    summary,
    validate_database,
    write_database,
)


def test_checked_in_mechanics_database_is_valid_and_unmeasured():
    database = read_database()
    result = validate_database(database)
    assert result.status == "PASS", result.errors
    assert result.real_measurements == 0
    assert result.counts["mechanics"] >= 30
    assert result.counts["parameters"] == result.counts["mechanics"]
    assert summary(database)["readiness"] == "NOT_READY"
    assert database["policy"]["cross_implementation_is_truth"] is False


def test_query_filters_are_deterministic_and_join_evidence():
    database = read_database()
    targeting = query_mechanics(database, EvidenceQuery(domain="targeting"))
    assert [row["id"] for row in targeting] == sorted(row["id"] for row in targeting)
    assert {row["id"] for row in targeting} >= {
        "targeting.effective_distance", "targeting.retarget_interval", "targeting.tie_breaking"
    }
    knight = query_mechanics(database, EvidenceQuery(card="knight", status="LEGACY_GUESS"))
    assert {row["id"] for row in knight} == {
        "collision.iterations", "targeting.retarget_interval"
    }
    source = query_mechanics(database, EvidenceQuery(source_id="src-crforge"))
    assert {row["id"] for row in source} >= {
        "events.same_tick_order", "targeting.effective_distance"
    }


def test_database_digest_ignores_volatile_fields_and_round_trips(tmp_path: Path):
    database = read_database()
    digest = database_digest(database)
    changed = dict(database)
    changed["generated_at"] = "volatile"
    changed["sha256"] = "stale"
    assert database_digest(changed) == digest
    path = tmp_path / "mechanics.json"
    assert write_database(path, changed) == digest
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["sha256"] == digest
    assert validate_database(written).status == "PASS"


def test_truth_table_and_sqlite_are_derived_and_queryable(tmp_path: Path):
    database = read_database(DEFAULT_PATH)
    report = render_truth_table(database)
    assert "# Mechanics Truth Table" in report
    assert "## targeting.effective_distance" in report
    assert "Real measured traces: **0**" in report
    path = tmp_path / "mechanics.sqlite"
    export_sqlite(database, path)
    with sqlite3.connect(path) as connection:
        mechanic_count = connection.execute("SELECT COUNT(*) FROM mechanics").fetchone()[0]
        digest = connection.execute("SELECT value FROM metadata WHERE key='sha256'").fetchone()[0]
    assert mechanic_count == len(database["mechanics"])
    assert digest == database_digest(database)
