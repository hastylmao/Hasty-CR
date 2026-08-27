"""Deterministic longitudinal archaeology over historical cr-csv Git objects.

The tool never checks out a historical revision and never imports historical values
into simulator data. It reads immutable Git objects, emits provenance-rich derived
indexes, and treats every numeric value as study-only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import subprocess
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
PRIMARY_REPOSITORY = ROOT / "_references" / "cr-csv"
WALLE_REPOSITORY = ROOT / "_references" / "walle-cr-csv"
DEFAULT_OUTPUT = ROOT / "research" / "csv_history"

TARGET_TABLES = (
    "characters.csv",
    "buildings.csv",
    "projectiles.csv",
    "spells_characters.csv",
    "spells_buildings.csv",
    "spells_other.csv",
    "area_effect_objects.csv",
    "character_buffs.csv",
    "battle_timelines.csv",
    "game_modes.csv",
    "locations.csv",
)
LOGIC_PREFIX = "assets/csv_logic/"
REPRESENTATIVE_ENTITIES = {
    "characters.csv": ("Knight", "Giant", "HogRider", "Musketeer"),
    "buildings.csv": ("Cannon",),
}
ENTITY_FIELDS = (
    "Speed", "SightRange", "Range", "MinimumRange", "CollisionRadius", "Mass",
    "LoadTime", "HitSpeed", "LoadAfterRetarget", "RetargetEachTick",
    "RetargetAfterAttack", "Projectile", "DeployTime", "SpawnRadius",
    "SpawnNumber", "DeathSpawnCount", "DeathSpawnDeployTime",
)
SPELL_FIELDS = (
    "SummonCharacter", "SummonNumber", "SummonRadius", "SpawnRadius",
    "SpawnNumber", "DeployTime", "DeployDelay", "Projectile", "AreaEffectObject",
)
PROJECTILE_FIELDS = (
    "Speed", "Radius", "Homing", "HomingRadius", "ProjectileRadius",
    "CollisionRadius", "Pushback", "TargetsAir", "TargetsGround",
)

# GitHub release metadata observed through the public API on 2026-08-24. Releases
# are aliases only; the target was the moving branch name `master`, not a commit.
OBSERVED_RELEASES = {
    "smlbiobot/cr-csv": (
        ("2.0.1", "2017-10-11T08:42:07Z"),
        ("2.1.5", "2017-12-12T11:21:30Z"),
        ("3.2.1", "2018-09-26T16:11:52Z"),
        ("2018-10", "2018-10-01T09:33:20Z"),
        ("2019-04", "2019-04-27T16:23:31Z"),
    ),
    "walle-d/cr-csv": (),
}


class ArchaeologyError(RuntimeError):
    """Raised for missing repositories, malformed objects, or stale outputs."""


@dataclass(frozen=True)
class Snapshot:
    order: int
    commit: str
    commit_date: str
    subject: str
    tags: tuple[str, ...]
    probable_version: str
    version_basis: str

    @property
    def snapshot_id(self) -> str:
        return f"s{self.order:03d}-{self.commit[:12]}"


@dataclass(frozen=True)
class TableState:
    path: str
    content: bytes
    headers: tuple[str, ...]
    types: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    rows_by_name: Mapping[str, tuple[tuple[str, ...], ...]]

    @property
    def blob_sha1(self) -> str:
        prefix = f"blob {len(self.content)}\0".encode("ascii")
        return hashlib.sha1(prefix + self.content).hexdigest()

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def schema_sha256(self) -> str:
        payload = json.dumps(
            list(zip(self.headers, self.types)), separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def rowset_sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(sorted(self.rows_by_name), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()


def _git(repository: Path, *arguments: str, binary: bool = False) -> str | bytes:
    if not (repository / ".git").exists():
        raise ArchaeologyError(f"missing Git repository: {repository}")
    result = subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, check=False
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ArchaeologyError(f"git {' '.join(arguments)} failed in {repository}: {message}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict")


def _split_records(text: str) -> list[tuple[str, ...]]:
    return [tuple(record.split("\x1f")) for record in text.split("\x1e") if record.strip()]


def _tags_by_commit(repository: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    tags = str(_git(repository, "tag", "--list")).splitlines()
    for tag in sorted(filter(None, tags)):
        commit = str(_git(repository, "rev-parse", f"{tag}^{{commit}}")).strip()
        result.setdefault(commit, []).append(tag)
    return result


def _infer_version(subject: str, tags: Sequence[str]) -> tuple[str, str]:
    if tags:
        return ";".join(tags), "tag_label_unverified"
    version = re.search(r"(?<!\d)(\d+\.\d+(?:\.\d+)?)(?!\d)", subject)
    if version:
        return version.group(1), "commit_subject_inferred"
    date = re.search(r"(?<!\d)(20\d{2})[- ](\d{2})(?:[- ](\d{2}))?(?!\d)", subject)
    if date:
        value = "-".join(part for part in date.groups() if part)
        return value, "commit_subject_inferred"
    compact = re.search(r"(?<!\d)(20\d{6})(?!\d)", subject)
    if compact:
        value = compact.group(1)
        return f"{value[:4]}-{value[4:6]}-{value[6:]}", "commit_subject_inferred"
    return "unknown", "unknown"


def discover_snapshots(repository: Path = PRIMARY_REPOSITORY) -> list[Snapshot]:
    tags = _tags_by_commit(repository)
    log = str(_git(
        repository, "log", "--reverse", "--format=%H%x1f%cI%x1f%s%x1e", "--", "assets"
    ))
    snapshots = []
    for record in _split_records(log):
        if len(record) != 3:
            raise ArchaeologyError(f"unexpected Git log record: {record!r}")
        commit, commit_date, subject = (part.strip() for part in record)
        commit_tags = tuple(sorted(tags.get(commit, ())))
        probable_version, basis = _infer_version(subject, commit_tags)
        snapshots.append(Snapshot(len(snapshots), commit, commit_date, subject, commit_tags, probable_version, basis))

    known_commits = {snapshot.commit for snapshot in snapshots}
    for commit, commit_tags in tags.items():
        if commit in known_commits:
            continue
        commit_date, subject = str(_git(repository, "show", "-s", "--format=%cI%x1f%s", commit)).strip().split("\x1f", 1)
        probable_version, basis = _infer_version(subject, commit_tags)
        insertion = next(
            (index for index, snapshot in enumerate(snapshots) if snapshot.commit_date > commit_date),
            len(snapshots),
        )
        snapshots.insert(insertion, Snapshot(0, commit, commit_date, subject, tuple(sorted(commit_tags)), probable_version, basis))
    snapshots = [
        Snapshot(order, item.commit, item.commit_date, item.subject, item.tags, item.probable_version, item.version_basis)
        for order, item in enumerate(snapshots)
    ]
    if not snapshots:
        raise ArchaeologyError("no asset-changing commits or tagged snapshots found")
    return snapshots


def _decode_csv(content: bytes, path: str) -> TableState:
    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ArchaeologyError(f"cannot decode {path}")
    parsed = list(csv.reader(io.StringIO(text, newline="")))
    if len(parsed) < 2:
        raise ArchaeologyError(f"{path} lacks header/type rows")
    headers = tuple(parsed[0])
    types = tuple((parsed[1] + [""] * len(headers))[:len(headers)])
    rows = tuple(tuple((row + [""] * len(headers))[:len(headers)]) for row in parsed[2:])
    name_index = headers.index("Name") if "Name" in headers else None
    grouped: dict[str, list[tuple[str, ...]]] = {}
    if name_index is not None:
        for row in rows:
            if row[name_index]:
                grouped.setdefault(row[name_index], []).append(row)
    return TableState(path, content, headers, types, rows, {key: tuple(value) for key, value in grouped.items()})


def _snapshot_archive(repository: Path, commit: str) -> dict[str, TableState]:
    tree = str(_git(repository, "ls-tree", "-r", "--name-only", commit, "--", LOGIC_PREFIX))
    available = set(tree.splitlines())
    paths = [f"{LOGIC_PREFIX}{table}" for table in TARGET_TABLES if f"{LOGIC_PREFIX}{table}" in available]
    if not paths:
        return {}
    result = subprocess.run(
        ["git", "archive", "--format=tar", commit, *paths],
        cwd=repository,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ArchaeologyError(f"git archive failed for {commit}: {message}")
    states: dict[str, TableState] = {}
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive.getmembers():
            if not member.isfile() or not member.name.endswith(".csv"):
                continue
            source = archive.extractfile(member)
            if source is None:
                continue
            table = Path(member.name).name
            states[table] = _decode_csv(source.read(), member.name)
    return states


def _asset_tree(repository: Path, commit: str) -> tuple[int, int, str]:
    listing = str(_git(repository, "ls-tree", "-r", "-l", commit, "--", "assets"))
    records = []
    total_bytes = 0
    csv_count = 0
    pattern = re.compile(r"^\d+ blob ([0-9a-f]+)\s+(\d+)\t(.+)$")
    for line in listing.splitlines():
        match = pattern.match(line)
        if not match:
            continue
        blob, size_text, path = match.groups()
        size = int(size_text)
        total_bytes += size
        if path.lower().endswith(".csv"):
            csv_count += 1
        records.append(f"{path}\0{blob}\0{size}")
    digest = hashlib.sha256("\n".join(records).encode("utf-8")).hexdigest()
    return csv_count, total_bytes, digest


def _row_payloads(state: TableState) -> dict[str, str]:
    result = {}
    for name, rows in state.rows_by_name.items():
        result[name] = json.dumps(rows, separators=(",", ":"), ensure_ascii=False)
    return result


def _column_value(state: TableState, name: str, field: str) -> str | None:
    if field not in state.headers or name not in state.rows_by_name:
        return None
    index = state.headers.index(field)
    return state.rows_by_name[name][0][index]


def _write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _inventory_rows(snapshots: Sequence[Snapshot], repository: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    primary_tags = _tags_by_commit(repository)
    walle_tags = _tags_by_commit(WALLE_REPOSITORY)
    primary_commits = {snapshot.commit for snapshot in snapshots}
    asset_metadata = {snapshot.commit: _asset_tree(repository, snapshot.commit) for snapshot in snapshots}
    for snapshot in snapshots:
        csv_count, asset_bytes, tree_digest = asset_metadata[snapshot.commit]
        rows.append({
            "repository": "smlbiobot/cr-csv", "ref_kind": "asset_commit",
            "ref": snapshot.subject, "peeled_commit": snapshot.commit,
            "commit_date": snapshot.commit_date, "probable_apk_version": snapshot.probable_version,
            "version_basis": snapshot.version_basis,
            "provenance": "decoded APK data claimed by upstream history; not independently authenticated",
            "license_status": "NO_LICENSE_FOUND_STUDY_ONLY",
            "snapshot_id": snapshot.snapshot_id, "canonical_snapshot": "true",
            "duplicate_lineage": "", "csv_file_count": csv_count,
            "asset_bytes": asset_bytes, "asset_tree_sha256": tree_digest,
        })
    for repository_name, tags_by_commit, duplicate_label in (
        ("smlbiobot/cr-csv", primary_tags, ""),
        ("walle-d/cr-csv", walle_tags, "shared_commit_with_smlbiobot/cr-csv"),
    ):
        for commit, tags in sorted(tags_by_commit.items(), key=lambda item: item[1]):
            snapshot = next((item for item in snapshots if item.commit == commit), None)
            for tag in tags:
                rows.append({
                    "repository": repository_name, "ref_kind": "tag", "ref": tag,
                    "peeled_commit": commit, "commit_date": snapshot.commit_date if snapshot else "",
                    "probable_apk_version": tag,
                    "version_basis": "upstream_tag; walle README claims tags match APK versions" if repository_name.startswith("walle") else "upstream_tag_unverified",
                    "provenance": "decoded APK data claimed by upstream README/history; not independently authenticated",
                    "license_status": "NO_LICENSE_FOUND_STUDY_ONLY",
                    "snapshot_id": snapshot.snapshot_id if snapshot else "",
                    "canonical_snapshot": "false", "duplicate_lineage": duplicate_label,
                    "csv_file_count": "", "asset_bytes": "", "asset_tree_sha256": "",
                })
    for repository_name, releases in OBSERVED_RELEASES.items():
        release_tags = primary_tags if repository_name.startswith("smlbiobot") else walle_tags
        for tag, published_at in releases:
            commits = [commit for commit, names in release_tags.items() if tag in names]
            commit = commits[0] if commits else ""
            snapshot = next((item for item in snapshots if item.commit == commit), None)
            rows.append({
                "repository": repository_name, "ref_kind": "release", "ref": tag,
                "peeled_commit": commit, "commit_date": published_at,
                "probable_apk_version": tag,
                "version_basis": "GitHub release alias observed 2026-08-24; target_commitish was master",
                "provenance": "public GitHub release metadata; data origin not independently authenticated",
                "license_status": "NO_LICENSE_FOUND_STUDY_ONLY",
                "snapshot_id": snapshot.snapshot_id if snapshot else "",
                "canonical_snapshot": "false",
                "duplicate_lineage": "alias_of_local_tag" if commit in primary_commits else "unresolved_release_target",
                "csv_file_count": "", "asset_bytes": "", "asset_tree_sha256": "",
            })
    return rows


def _rename_candidates(change_rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for row in change_rows:
        removed = [value for value in str(row["removed_columns"]).split(";") if value]
        added = [value for value in str(row["added_columns"]).split(";") if value]
        for old_name in removed:
            old_tokens = set(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", old_name))
            for new_name in added:
                new_tokens = set(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", new_name))
                overlap = len(old_tokens & new_tokens) / max(len(old_tokens | new_tokens), 1)
                if overlap < 0.5:
                    continue
                candidates.append({
                    "from_snapshot": row["from_snapshot"], "to_snapshot": row["to_snapshot"],
                    "commit": row["commit"], "commit_date": row["commit_date"],
                    "table": row["table"], "removed_column": old_name,
                    "added_column": new_name, "token_similarity": f"{overlap:.3f}",
                    "classification": "POSSIBLE_RENAME_REQUIRES_MANUAL_REVIEW",
                })
    return candidates


def _analyze(repository: Path, snapshots: Sequence[Snapshot]) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    table_rows: list[dict[str, object]] = []
    column_rows: list[dict[str, object]] = []
    change_rows: list[dict[str, object]] = []
    timeline_rows: list[dict[str, object]] = []
    previous: dict[str, TableState] = {}
    previous_snapshot_ids: dict[str, str] = {}
    previous_values: dict[tuple[str, str, str, str], str | None] = {}

    for snapshot in snapshots:
        states = _snapshot_archive(repository, snapshot.commit)
        for table in TARGET_TABLES:
            state = states.get(table)
            if state is None:
                table_rows.append({
                    "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                    "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                    "probable_apk_version": snapshot.probable_version, "table": table,
                    "present": "false", "rows": 0, "named_rows": 0, "columns": 0,
                    "blob_sha1": "", "content_sha256": "", "schema_sha256": "", "rowset_sha256": "",
                })
                continue
            table_rows.append({
                "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                "probable_apk_version": snapshot.probable_version, "table": table,
                "present": "true", "rows": len(state.rows), "named_rows": len(state.rows_by_name),
                "columns": len(state.headers), "blob_sha1": state.blob_sha1,
                "content_sha256": state.content_sha256, "schema_sha256": state.schema_sha256,
                "rowset_sha256": state.rowset_sha256,
            })
            for position, (column, type_name) in enumerate(zip(state.headers, state.types)):
                column_rows.append({
                    "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                    "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                    "table": table, "column_position": position, "column": column, "declared_type": type_name,
                })

            old = previous.get(table)
            if old is not None and old.content_sha256 != state.content_sha256:
                old_columns = dict(zip(old.headers, old.types))
                new_columns = dict(zip(state.headers, state.types))
                old_payloads = _row_payloads(old)
                new_payloads = _row_payloads(state)
                shared_names = sorted(set(old_payloads) & set(new_payloads))
                changed_shared = sum(old_payloads[name] != new_payloads[name] for name in shared_names)
                schema_changed = old.schema_sha256 != state.schema_sha256
                rowset_changed = set(old_payloads) != set(new_payloads)
                value_changed = changed_shared > 0
                if schema_changed:
                    classification = "SCHEMA_CHANGE"
                elif rowset_changed and value_changed:
                    classification = "ROW_AND_VALUE_CHANGE"
                elif rowset_changed:
                    classification = "ROW_SET_CHANGE"
                elif value_changed:
                    classification = "VALUE_OR_BALANCE_CHANGE"
                else:
                    classification = "FORMATTING_OR_DUPLICATE_ROW_CHANGE"
                changed_types = sorted(
                    name for name in set(old_columns) & set(new_columns)
                    if old_columns[name] != new_columns[name]
                )
                change_rows.append({
                    "from_snapshot": previous_snapshot_ids[table],
                    "to_snapshot": snapshot.snapshot_id, "commit": snapshot.commit,
                    "commit_date": snapshot.commit_date, "subject": snapshot.subject,
                    "table": table, "classification": classification,
                    "schema_changed": str(schema_changed).lower(),
                    "row_set_changed": str(rowset_changed).lower(),
                    "shared_values_changed": str(value_changed).lower(),
                    "added_columns": ";".join(sorted(set(new_columns) - set(old_columns))),
                    "removed_columns": ";".join(sorted(set(old_columns) - set(new_columns))),
                    "type_changed_columns": ";".join(changed_types),
                    "added_rows": ";".join(sorted(set(new_payloads) - set(old_payloads))),
                    "removed_rows": ";".join(sorted(set(old_payloads) - set(new_payloads))),
                    "changed_shared_rows": changed_shared,
                })
            previous[table] = state
            previous_snapshot_ids[table] = snapshot.snapshot_id

        for table, names in REPRESENTATIVE_ENTITIES.items():
            state = states.get(table)
            if state is None:
                continue
            for name in names:
                for field in ENTITY_FIELDS:
                    value = _column_value(state, name, field)
                    if value is None:
                        continue
                    key = (table, name, field, "entity")
                    old_value = previous_values.get(key)
                    if key not in previous_values or old_value != value:
                        timeline_rows.append({
                            "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                            "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                            "probable_apk_version": snapshot.probable_version, "subject": snapshot.subject,
                            "record_kind": "entity", "parent_entity": "", "table": table,
                            "name": name, "field": field, "previous_value": "" if old_value is None else old_value,
                            "value": value, "change_kind": "FIRST_OBSERVED" if key not in previous_values else "VALUE_CHANGED",
                        })
                    previous_values[key] = value

                projectile = _column_value(state, name, "Projectile")
                projectile_state = states.get("projectiles.csv")
                if projectile and projectile_state:
                    for field in PROJECTILE_FIELDS:
                        value = _column_value(projectile_state, projectile, field)
                        if value is None:
                            continue
                        key = ("projectiles.csv", f"{name}->{projectile}", field, "projectile")
                        old_value = previous_values.get(key)
                        if key not in previous_values or old_value != value:
                            timeline_rows.append({
                                "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                                "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                                "probable_apk_version": snapshot.probable_version, "subject": snapshot.subject,
                                "record_kind": "linked_projectile", "parent_entity": name,
                                "table": "projectiles.csv", "name": projectile, "field": field,
                                "previous_value": "" if old_value is None else old_value, "value": value,
                                "change_kind": "FIRST_OBSERVED" if key not in previous_values else "VALUE_CHANGED",
                            })
                        previous_values[key] = value

            spell_table = "spells_characters.csv" if table == "characters.csv" else "spells_buildings.csv"
            spell_state = states.get(spell_table)
            if spell_state:
                for name in names:
                    for field in SPELL_FIELDS:
                        value = _column_value(spell_state, name, field)
                        if value is None:
                            continue
                        key = (spell_table, name, field, "spell")
                        old_value = previous_values.get(key)
                        if key not in previous_values or old_value != value:
                            timeline_rows.append({
                                "snapshot_id": snapshot.snapshot_id, "snapshot_order": snapshot.order,
                                "commit": snapshot.commit, "commit_date": snapshot.commit_date,
                                "probable_apk_version": snapshot.probable_version, "subject": snapshot.subject,
                                "record_kind": "spell_metadata", "parent_entity": name, "table": spell_table,
                                "name": name, "field": field,
                                "previous_value": "" if old_value is None else old_value, "value": value,
                                "change_kind": "FIRST_OBSERVED" if key not in previous_values else "VALUE_CHANGED",
                            })
                        previous_values[key] = value

    return table_rows, column_rows, change_rows, timeline_rows


def _render_report(snapshots: Sequence[Snapshot], table_rows: Sequence[Mapping[str, object]], change_rows: Sequence[Mapping[str, object]], timeline_rows: Sequence[Mapping[str, object]], rename_rows: Sequence[Mapping[str, object]]) -> str:
    classifications: dict[str, int] = {}
    for row in change_rows:
        key = str(row["classification"])
        classifications[key] = classifications.get(key, 0) + 1
    first = snapshots[0]
    last = snapshots[-1]
    target_present = sum(row["present"] == "true" for row in table_rows)
    schema_changes = [row for row in change_rows if row["classification"] == "SCHEMA_CHANGE"]
    field_events = sum(bool(row["added_columns"] or row["removed_columns"] or row["type_changed_columns"]) for row in schema_changes)
    lines = [
        "# Longitudinal cr-csv archaeology", "",
        "Generated by `python -m tools.research.csv_history generate`. Historical decoded APK data is unlicensed, unauthenticated, and **study-only**. It is schema evidence and hypothesis input, not current/live truth.", "",
        "## Coverage", "",
        f"- Canonical historical snapshots: **{len(snapshots)}**, covering every asset-changing commit plus any otherwise-missing tagged tree, from `{first.commit[:12]}` ({first.commit_date}) through `{last.commit[:12]}` ({last.commit_date}).",
        f"- Mechanics-relevant tables: **{len(TARGET_TABLES)}**; present table-snapshots: **{target_present}**.",
        f"- Changed table transitions: **{len(change_rows)}**; schema-changing transitions: **{len(schema_changes)}**; transitions with explicit field events: **{field_events}**.",
        f"- Representative parameter change events: **{len(timeline_rows)}** across Knight, Giant, HogRider, Musketeer, Cannon, linked projectiles, and card metadata.",
        f"- Conservative field rename candidates: **{len(rename_rows)}**; these are lexical candidates requiring manual review, never asserted renames.",
        "- `walle-d/cr-csv` shares the same commit objects for its two tags and is represented as duplicate lineage rather than duplicate canonical snapshots.", "",
        "## Change classification", "",
        "The classifier is structural: `SCHEMA_CHANGE` means columns/order/types changed; `ROW_SET_CHANGE` means named rows changed; `VALUE_OR_BALANCE_CHANGE` means shared named row payloads changed with stable schema/row set. A value change may be balance, content, metadata, or formatting—not proven engine behavior.", "",
        "| Class | Table transitions |", "|---|---:|",
    ]
    for key, count in sorted(classifications.items()):
        lines.append(f"| `{key}` | {count} |")
    lines.extend(["", "## Derived datasets", "", "| File | Purpose |", "|---|---|"])
    for name, purpose in (
        ("version_inventory.csv", "All asset-changing commits plus tag/release aliases, provenance, license, lineage, and asset-tree hashes."),
        ("table_evolution.csv", "Per-snapshot target-table presence, shape, Git blob hash, content hash, schema hash, and named-row-set hash."),
        ("column_evolution.csv", "Header position and declared type at every snapshot."),
        ("changes.csv", "Adjacent-snapshot schema/row/value classification with exact added/removed fields and named rows."),
        ("rename_candidates.csv", "Conservative lexical pairs among same-transition removed/added fields; manual review required."),
        ("parameter_timelines.csv", "Change-only historical values for representative entities/card metadata/linked projectiles."),
        ("manifest.json", "Output hashes and source repository pins for deterministic validation."),
    ):
        lines.append(f"| [`{name}`]({name}) | {purpose} |")
    lines.extend([
        "", "## Interpretation limits", "",
        "- Tag names and commit subjects produce only probable version labels. The walle README claims tags/releases match APK versions; no APK files or signatures were independently matched.",
        "- Blank values remain blank. The analysis does not infer zero, false, defaults, inheritance, units, or formulas.",
        "- Column additions reveal candidate concepts, not the client execution path or server authority.",
        "- `Name` is used only as a diff key; duplicate same-name rows are retained as grouped payloads and are not treated as relational uniqueness.",
        "- No historical values are copied into HastyCR runtime data, and real measured Clash traces remain **ZERO**.", "",
        "## High-value conclusions", "",
        "- The broad character/building schema persists while accumulating fields, making field longevity useful for prioritizing semantic investigation.",
        "- Schema, named-row set, and shared-row payload changes are independently observable and must not be collapsed into a generic ‘balance update.’",
        "- Representative timelines show when values or links changed, but do not establish why they changed or whether any snapshot reflects current official behavior.",
        "- Live controlled observation remains required for contact geometry, target transitions, projectile behavior, spawn timing, and event order.", "",
    ])
    return "\n".join(lines)


def _manifest(output: Path, snapshots: Sequence[Snapshot], source_pins: Mapping[str, str]) -> dict[str, object]:
    files = {}
    for path in sorted(output.iterdir(), key=lambda item: item.name):
        if path.is_file() and path.name != "manifest.json":
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    payload: dict[str, object] = {
        "schema_version": 1,
        "generator": "tools.research.csv_history",
        "canonical_snapshot_count": len(snapshots),
        "source_pins": dict(sorted(source_pins.items())),
        "files": files,
        "real_measurements": 0,
        "evidence_class": "HISTORICAL_SCHEMA_STUDY_ONLY",
    }
    digest_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["sha256"] = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    return payload


def generate(output: Path = DEFAULT_OUTPUT, repository: Path = PRIMARY_REPOSITORY) -> dict[str, object]:
    snapshots = discover_snapshots(repository)
    inventory = _inventory_rows(snapshots, repository)
    table_rows, column_rows, change_rows, timeline_rows = _analyze(repository, snapshots)
    rename_rows = _rename_candidates(change_rows)
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "version_inventory.csv", (
        "repository", "ref_kind", "ref", "peeled_commit", "commit_date",
        "probable_apk_version", "version_basis", "provenance", "license_status",
        "snapshot_id", "canonical_snapshot", "duplicate_lineage", "csv_file_count",
        "asset_bytes", "asset_tree_sha256",
    ), inventory)
    _write_csv(output / "table_evolution.csv", (
        "snapshot_id", "snapshot_order", "commit", "commit_date", "probable_apk_version",
        "table", "present", "rows", "named_rows", "columns", "blob_sha1",
        "content_sha256", "schema_sha256", "rowset_sha256",
    ), table_rows)
    _write_csv(output / "column_evolution.csv", (
        "snapshot_id", "snapshot_order", "commit", "commit_date", "table",
        "column_position", "column", "declared_type",
    ), column_rows)
    _write_csv(output / "changes.csv", (
        "from_snapshot", "to_snapshot", "commit", "commit_date", "subject", "table",
        "classification", "schema_changed", "row_set_changed", "shared_values_changed",
        "added_columns", "removed_columns", "type_changed_columns", "added_rows",
        "removed_rows", "changed_shared_rows",
    ), change_rows)
    _write_csv(output / "rename_candidates.csv", (
        "from_snapshot", "to_snapshot", "commit", "commit_date", "table",
        "removed_column", "added_column", "token_similarity", "classification",
    ), rename_rows)
    _write_csv(output / "parameter_timelines.csv", (
        "snapshot_id", "snapshot_order", "commit", "commit_date", "probable_apk_version",
        "subject", "record_kind", "parent_entity", "table", "name", "field",
        "previous_value", "value", "change_kind",
    ), timeline_rows)
    (output / "LONGITUDINAL_SCHEMA_ARCHAEOLOGY.md").write_text(
        _render_report(snapshots, table_rows, change_rows, timeline_rows, rename_rows), encoding="utf-8"
    )
    source_pins = {
        "smlbiobot/cr-csv": str(_git(repository, "rev-parse", "HEAD")).strip(),
        "walle-d/cr-csv": str(_git(WALLE_REPOSITORY, "rev-parse", "HEAD")).strip(),
    }
    manifest = _manifest(output, snapshots, source_pins)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": "PASS", "snapshots": len(snapshots), "inventory_rows": len(inventory),
        "table_snapshots": len(table_rows), "column_records": len(column_rows),
        "changes": len(change_rows), "rename_candidates": len(rename_rows),
        "timeline_events": len(timeline_rows),
        "real_measurements": 0, "sha256": manifest["sha256"], "output": str(output),
    }


def validate(output: Path = DEFAULT_OUTPUT, repository: Path = PRIMARY_REPOSITORY) -> dict[str, object]:
    manifest_path = output / "manifest.json"
    if not manifest_path.exists():
        raise ArchaeologyError(f"missing generated manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    expected_files = set(manifest.get("files", {})) | {"manifest.json"}
    actual_files = {path.name for path in output.iterdir() if path.is_file()}
    if actual_files != expected_files:
        errors.append(f"file set differs: expected {sorted(expected_files)}, found {sorted(actual_files)}")
    for name, expected_digest in sorted(manifest.get("files", {}).items()):
        path = output / name
        if path.exists():
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_digest != expected_digest:
                errors.append(f"hash mismatch for {name}: {actual_digest}")
    digest_payload = {key: value for key, value in manifest.items() if key != "sha256"}
    actual_manifest_digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if actual_manifest_digest != manifest.get("sha256"):
        errors.append("manifest digest mismatch")
    source_pins = {
        "smlbiobot/cr-csv": str(_git(repository, "rev-parse", "HEAD")).strip(),
        "walle-d/cr-csv": str(_git(WALLE_REPOSITORY, "rev-parse", "HEAD")).strip(),
    }
    if source_pins != manifest.get("source_pins"):
        errors.append(f"source pins differ: expected {manifest.get('source_pins')}, found {source_pins}")
    snapshots = discover_snapshots(repository)
    if len(snapshots) != manifest.get("canonical_snapshot_count"):
        errors.append(f"snapshot count differs: expected {manifest.get('canonical_snapshot_count')}, found {len(snapshots)}")
    if manifest.get("real_measurements") != 0:
        errors.append("historical archaeology manifest must contain zero real measurements")
    for name in ("version_inventory.csv", "table_evolution.csv", "column_evolution.csv", "changes.csv", "rename_candidates.csv", "parameter_timelines.csv"):
        path = output / name
        if path.exists():
            with path.open(encoding="utf-8", newline="") as handle:
                list(csv.DictReader(handle))
    return {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "snapshots": len(snapshots), "files": len(manifest.get("files", {})),
        "real_measurements": manifest.get("real_measurements"),
        "sha256": manifest.get("sha256"), "output": str(output),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("generate", "validate"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--repository", type=Path, default=PRIMARY_REPOSITORY)
    arguments = parser.parse_args(list(argv) if argv is not None else None)
    try:
        result = generate(arguments.output, arguments.repository) if arguments.command == "generate" else validate(arguments.output, arguments.repository)
    except ArchaeologyError as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
