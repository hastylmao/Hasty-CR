"""Versioned, append-only manual annotation documents and correction replay."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    CalibrationError,
    NormalizedFrame,
    NormalizedTrace,
    Observability,
    Provenance,
    TraceEvent,
    TrackedEntity,
    Uncertainty,
    canonical_json,
    trace_digest,
    write_trace,
)

ANNOTATION_SCHEMA_VERSION = 1
OPERATION_KINDS = frozenset({"merge", "split", "relabel", "point", "death", "spawn", "queue"})
QUEUE_STATUSES = frozenset({"pending", "in_review", "reviewed", "blocked"})


@dataclass(frozen=True)
class AnnotationFrame:
    frame_id: str
    time_ms: int
    source_frame: int | None = None
    battle_time_ms: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "time_ms": self.time_ms,
            "source_frame": self.source_frame,
            "battle_time_ms": self.battle_time_ms,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnnotationFrame":
        if not value.get("frame_id") or int(value.get("time_ms", -1)) < 0:
            raise CalibrationError("annotation frame requires frame_id and nonnegative time_ms")
        return cls(
            str(value["frame_id"]),
            int(value["time_ms"]),
            None if value.get("source_frame") is None else int(value["source_frame"]),
            None if value.get("battle_time_ms") is None else int(value["battle_time_ms"]),
            dict(value.get("metadata", {})),
        )


@dataclass(frozen=True)
class AnnotationRecord:
    annotation_id: str
    frame_id: str
    time_ms: int
    class_name: str
    team: int | None
    x: float
    y: float
    confidence: float = 1.0
    observability: Observability = Observability.UNKNOWN
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    alive: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "frame_id": self.frame_id,
            "time_ms": self.time_ms,
            "class_name": self.class_name,
            "team": self.team,
            "x": self.x,
            "y": self.y,
            "confidence": self.confidence,
            "observability": self.observability.value,
            "uncertainty": self.uncertainty.to_dict(),
            "alive": self.alive,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnnotationRecord":
        required = ("annotation_id", "frame_id", "time_ms", "class_name", "x", "y")
        missing = [key for key in required if key not in value]
        if missing:
            raise CalibrationError("annotation record missing: " + ", ".join(missing))
        confidence = float(value.get("confidence", 1.0))
        if not 0.0 <= confidence <= 1.0:
            raise CalibrationError("annotation confidence must be between 0 and 1")
        try:
            observability = Observability(value.get("observability", "unknown"))
        except ValueError as exc:
            raise CalibrationError("invalid annotation observability") from exc
        team = None if value.get("team") is None else int(value["team"])
        if team not in (None, -1, 1):
            raise CalibrationError("annotation team must be -1, 1, or null")
        return cls(
            str(value["annotation_id"]), str(value["frame_id"]), int(value["time_ms"]),
            str(value["class_name"]), team, float(value["x"]), float(value["y"]),
            confidence, observability, Uncertainty.from_dict(value.get("uncertainty")),
            bool(value.get("alive", True)), dict(value.get("metadata", {})),
        )


@dataclass(frozen=True)
class AnnotationOperation:
    sequence: int
    operation_id: str
    kind: str
    payload: Mapping[str, Any]
    author: str = "manual"
    reason: str = ""
    confidence: float = 1.0
    uncertainty: Uncertainty = field(default_factory=Uncertainty)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "operation_id": self.operation_id,
            "kind": self.kind,
            "payload": dict(self.payload),
            "author": self.author,
            "reason": self.reason,
            "confidence": self.confidence,
            "uncertainty": self.uncertainty.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnnotationOperation":
        kind = str(value.get("kind", ""))
        if kind not in OPERATION_KINDS:
            raise CalibrationError(f"unsupported annotation operation: {kind}")
        confidence = float(value.get("confidence", 1.0))
        if not 0.0 <= confidence <= 1.0:
            raise CalibrationError("operation confidence must be between 0 and 1")
        payload = value.get("payload")
        if not isinstance(payload, Mapping):
            raise CalibrationError("operation payload must be an object")
        operation = cls(
            int(value.get("sequence", 0)), str(value.get("operation_id", "")), kind,
            dict(payload), str(value.get("author", "manual")), str(value.get("reason", "")),
            confidence, Uncertainty.from_dict(value.get("uncertainty")),
        )
        if operation.sequence <= 0 or not operation.operation_id:
            raise CalibrationError("operation requires positive sequence and operation_id")
        _validate_operation_payload(operation)
        return operation


@dataclass(frozen=True)
class AnnotationDocument:
    document_id: str
    source_trace_id: str
    source_trace_sha256: str
    frames: tuple[AnnotationFrame, ...]
    records: tuple[AnnotationRecord, ...]
    operations: tuple[AnnotationOperation, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = ANNOTATION_SCHEMA_VERSION

    @property
    def revision(self) -> int:
        return len(self.operations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "document_id": self.document_id,
            "revision": self.revision,
            "source_trace_id": self.source_trace_id,
            "source_trace_sha256": self.source_trace_sha256,
            "metadata": dict(self.metadata),
            "frames": [frame.to_dict() for frame in self.frames],
            "records": [record.to_dict() for record in self.records],
            "operations": [operation.to_dict() for operation in self.operations],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AnnotationDocument":
        version = int(value.get("schema_version", 0))
        if version != ANNOTATION_SCHEMA_VERSION:
            raise CalibrationError(f"unsupported annotation schema {version}")
        document = cls(
            str(value.get("document_id", "")), str(value.get("source_trace_id", "")),
            str(value.get("source_trace_sha256", "")),
            tuple(AnnotationFrame.from_dict(item) for item in value.get("frames", ())),
            tuple(AnnotationRecord.from_dict(item) for item in value.get("records", ())),
            tuple(AnnotationOperation.from_dict(item) for item in value.get("operations", ())),
            dict(value.get("metadata", {})), version,
        )
        validate_annotation(document)
        if int(value.get("revision", document.revision)) != document.revision:
            raise CalibrationError("annotation revision does not match operation ledger")
        return document


def annotation_from_trace(trace: NormalizedTrace, *, document_id: str | None = None) -> AnnotationDocument:
    frames = tuple(
        AnnotationFrame(frame.frame_id, frame.time_ms, frame.source_frame, frame.battle_time_ms,
                        {"source_observability": frame.observability.value})
        for frame in trace.frames
    )
    records = tuple(
        AnnotationRecord(
            entity.track_id, frame.frame_id, frame.time_ms, entity.class_name, entity.team,
            entity.x, entity.y, entity.confidence, entity.observability, entity.uncertainty,
            entity.alive, {"source_metadata": dict(entity.metadata)},
        )
        for frame in trace.frames for entity in frame.entities
    )
    source_sha256 = trace_digest(trace)
    identity = document_id or f"annotation-{source_sha256[:16]}"
    return AnnotationDocument(
        identity, trace.trace_id, source_sha256, frames, records,
        metadata={"source_provenance": trace.source.to_dict(), "real_data_claim": False},
    )


def append_operation(
    document: AnnotationDocument,
    kind: str,
    payload: Mapping[str, Any],
    *,
    author: str = "manual",
    reason: str = "",
    confidence: float = 1.0,
    uncertainty: Uncertainty | None = None,
    operation_id: str | None = None,
) -> AnnotationDocument:
    sequence = document.revision + 1
    seed = canonical_json({"document": annotation_digest(document), "sequence": sequence,
                           "kind": kind, "payload": dict(payload)})
    identifier = operation_id or f"op-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:16]}"
    operation = AnnotationOperation.from_dict({
        "sequence": sequence, "operation_id": identifier, "kind": kind,
        "payload": dict(payload), "author": author, "reason": reason,
        "confidence": confidence, "uncertainty": (uncertainty or Uncertainty()).to_dict(),
    })
    updated = replace(document, operations=document.operations + (operation,))
    validate_annotation(updated)
    replay_annotations(updated)
    return updated


def validate_annotation(document: AnnotationDocument) -> dict[str, Any]:
    if not document.document_id or len(document.source_trace_sha256) != 64:
        raise CalibrationError("annotation document identity and source digest are required")
    frame_ids = [frame.frame_id for frame in document.frames]
    if len(frame_ids) != len(set(frame_ids)):
        raise CalibrationError("annotation frame IDs must be unique")
    frame_times = {frame.frame_id: frame.time_ms for frame in document.frames}
    previous_time = -1
    for frame in document.frames:
        if frame.time_ms < previous_time:
            raise CalibrationError("annotation frames must be ordered by time_ms")
        previous_time = frame.time_ms
    for record in document.records:
        if record.frame_id not in frame_times or record.time_ms != frame_times[record.frame_id]:
            raise CalibrationError(f"annotation record references inconsistent frame {record.frame_id}")
    operation_ids: set[str] = set()
    for expected, operation in enumerate(document.operations, 1):
        if operation.sequence != expected:
            raise CalibrationError("annotation operation sequence must be contiguous")
        if operation.operation_id in operation_ids:
            raise CalibrationError("annotation operation IDs must be unique")
        operation_ids.add(operation.operation_id)
    return {
        "status": "PASS", "schema_version": document.schema_version,
        "revision": document.revision, "frames": len(document.frames),
        "base_records": len(document.records), "operations": len(document.operations),
        "queue": annotation_queue(document), "sha256": annotation_digest(document),
    }


def replay_annotations(document: AnnotationDocument) -> NormalizedTrace:
    validate_annotation(document)
    records = list(document.records)
    queue = {frame.frame_id: "pending" for frame in document.frames}
    events: list[tuple[int, TraceEvent]] = []
    for operation in document.operations:
        payload = operation.payload
        known_ids = {record.annotation_id for record in records}
        if operation.kind == "merge":
            source_ids = tuple(str(value) for value in payload["source_ids"])
            if not set(source_ids) <= known_ids:
                raise CalibrationError("merge references an unknown annotation ID")
            target_id = str(payload["target_id"])
            records = [replace(record, annotation_id=target_id,
                               metadata={**record.metadata, "merged_from": list(source_ids)})
                       if record.annotation_id in source_ids else record for record in records]
        elif operation.kind == "split":
            source_id = str(payload["source_id"])
            if source_id not in known_ids:
                raise CalibrationError("split references an unknown annotation ID")
            target_id = str(payload["target_id"])
            at_time_ms = int(payload["at_time_ms"])
            records = [replace(record, annotation_id=target_id,
                               metadata={**record.metadata, "split_from": source_id})
                       if record.annotation_id == source_id and record.time_ms >= at_time_ms else record
                       for record in records]
        elif operation.kind == "relabel":
            annotation_id = str(payload["annotation_id"])
            if annotation_id not in known_ids:
                raise CalibrationError("relabel references an unknown annotation ID")
            from_time_ms = int(payload.get("from_time_ms", 0))
            class_name = str(payload["class_name"])
            records = [replace(record, class_name=class_name,
                               metadata={**record.metadata, "relabel_operation": operation.operation_id})
                       if record.annotation_id == annotation_id and record.time_ms >= from_time_ms else record
                       for record in records]
            events.append((from_time_ms, _operation_event(operation, "annotation_relabel", annotation_id)))
        elif operation.kind == "point":
            annotation_id = str(payload["annotation_id"])
            frame_id = str(payload["frame_id"])
            matches = [record for record in records
                       if record.annotation_id == annotation_id and record.frame_id == frame_id]
            if not matches:
                raise CalibrationError("point correction references an unknown annotation/frame pair")
            records = [replace(record, x=float(payload["x"]), y=float(payload["y"]),
                               confidence=min(record.confidence, operation.confidence),
                               uncertainty=operation.uncertainty,
                               metadata={**record.metadata, "point_operation": operation.operation_id})
                       if record.annotation_id == annotation_id and record.frame_id == frame_id else record
                       for record in records]
        elif operation.kind == "death":
            annotation_id = str(payload["annotation_id"])
            if annotation_id not in known_ids:
                raise CalibrationError("death references an unknown annotation ID")
            time_ms = int(payload["time_ms"])
            records = [record for record in records
                       if not (record.annotation_id == annotation_id and record.time_ms >= time_ms)]
            events.append((time_ms, _operation_event(operation, "death", annotation_id)))
        elif operation.kind == "spawn":
            spawned = AnnotationRecord.from_dict(payload["record"])
            frame = next((item for item in document.frames if item.frame_id == spawned.frame_id), None)
            if frame is None or spawned.time_ms != frame.time_ms:
                raise CalibrationError("spawn record references an unknown or inconsistent frame")
            records.append(spawned)
            events.append((spawned.time_ms, _operation_event(operation, "spawn", spawned.annotation_id,
                                                               actor_class=spawned.class_name,
                                                               team=spawned.team, x=spawned.x, y=spawned.y)))
        elif operation.kind == "queue":
            frame_id = str(payload["frame_id"])
            if frame_id not in queue:
                raise CalibrationError("queue operation references an unknown frame")
            queue[frame_id] = str(payload["status"])
    by_frame: dict[str, list[AnnotationRecord]] = {frame.frame_id: [] for frame in document.frames}
    for record in records:
        by_frame[record.frame_id].append(record)
    normalized_frames: list[NormalizedFrame] = []
    for frame in document.frames:
        collapsed = _collapse_records(by_frame[frame.frame_id])
        entities = tuple(
            TrackedEntity(
                record.annotation_id, record.class_name, record.team, record.x, record.y,
                alive=record.alive, confidence=record.confidence,
                observability=record.observability,
                provenance=Provenance("manual-annotation", (document.document_id,),
                                      "append-only correction replay",
                                      {"revision": document.revision}),
                uncertainty=record.uncertainty, metadata=record.metadata,
            )
            for record in collapsed
        )
        frame_events = tuple(event for event_time, event in events if _event_frame(document.frames, event_time) == frame.frame_id)
        confidence = min((entity.confidence for entity in entities), default=1.0)
        normalized_frames.append(NormalizedFrame(
            frame.time_ms, frame.frame_id, entities=entities, events=frame_events,
            observability=_frame_observability(entities),
            source=Provenance("manual-annotation", (document.document_id,),
                              "append-only correction replay"),
            confidence=confidence, battle_time_ms=frame.battle_time_ms,
            source_frame=frame.source_frame,
            metadata={**frame.metadata, "annotation_revision": document.revision,
                      "annotation_queue_status": queue[frame.frame_id], "real_data_claim": False},
        ))
    return NormalizedTrace(
        tuple(normalized_frames), trace_id=f"{document.source_trace_id}:annotated:r{document.revision}",
        source=Provenance("manual-annotation", (document.document_id,), "deterministic replay"),
        metadata={**document.metadata, "annotation_document": document.document_id,
                  "annotation_revision": document.revision, "real_data_claim": False},
    )


def annotation_queue(document: AnnotationDocument) -> dict[str, Any]:
    statuses = {frame.frame_id: "pending" for frame in document.frames}
    for operation in document.operations:
        if operation.kind == "queue":
            statuses[str(operation.payload["frame_id"])] = str(operation.payload["status"])
    counts = {status: sum(value == status for value in statuses.values()) for status in sorted(QUEUE_STATUSES)}
    next_pending = next((frame.frame_id for frame in document.frames if statuses[frame.frame_id] == "pending"), None)
    return {"counts": counts, "next_pending_frame_id": next_pending}


def annotation_digest(document: AnnotationDocument) -> str:
    return hashlib.sha256(canonical_json(document.to_dict()).encode("utf-8")).hexdigest()


def read_annotation(path: str | Path) -> AnnotationDocument:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"invalid annotation document: {path}") from exc
    if not isinstance(value, Mapping):
        raise CalibrationError("annotation document must be an object")
    return AnnotationDocument.from_dict(value)


def write_annotation(path: str | Path, document: AnnotationDocument) -> None:
    validate_annotation(document)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8")


def materialize_annotation(path: str | Path, document: AnnotationDocument) -> NormalizedTrace:
    trace = replay_annotations(document)
    write_trace(path, trace)
    return trace


def _validate_operation_payload(operation: AnnotationOperation) -> None:
    payload = operation.payload
    required: dict[str, set[str]] = {
        "merge": {"source_ids", "target_id"},
        "split": {"source_id", "target_id", "at_time_ms"},
        "relabel": {"annotation_id", "class_name"},
        "point": {"annotation_id", "frame_id", "x", "y"},
        "death": {"annotation_id", "time_ms"},
        "spawn": {"record"},
        "queue": {"frame_id", "status"},
    }
    missing = required[operation.kind] - set(payload)
    if missing:
        raise CalibrationError(f"{operation.kind} payload missing: {', '.join(sorted(missing))}")
    if operation.kind == "merge":
        source_ids = payload["source_ids"]
        if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)) or len(set(source_ids)) < 2:
            raise CalibrationError("merge source_ids must contain at least two unique IDs")
    if operation.kind == "split" and int(payload["at_time_ms"]) < 0:
        raise CalibrationError("split time must be nonnegative")
    if operation.kind == "death" and int(payload["time_ms"]) < 0:
        raise CalibrationError("death time must be nonnegative")
    if operation.kind == "spawn":
        if not isinstance(payload["record"], Mapping):
            raise CalibrationError("spawn record must be an object")
        AnnotationRecord.from_dict(payload["record"])
    if operation.kind == "queue" and str(payload["status"]) not in QUEUE_STATUSES:
        raise CalibrationError("invalid annotation queue status")


def _collapse_records(records: Sequence[AnnotationRecord]) -> tuple[AnnotationRecord, ...]:
    selected: dict[str, AnnotationRecord] = {}
    for record in sorted(records, key=lambda item: (-item.confidence, item.annotation_id, item.class_name)):
        selected.setdefault(record.annotation_id, record)
    return tuple(selected[key] for key in sorted(selected))


def _operation_event(
    operation: AnnotationOperation, event_type: str, actor_id: str,
    *, actor_class: str | None = None, team: int | None = None,
    x: float | None = None, y: float | None = None,
) -> TraceEvent:
    time_ms = int(operation.payload.get("time_ms", operation.payload.get("at_time_ms", 0)))
    if operation.kind == "relabel":
        time_ms = int(operation.payload.get("from_time_ms", 0))
    return TraceEvent(
        event_type, time_ms, actor_id=actor_id, actor_class=actor_class, team=team, x=x, y=y,
        confidence=operation.confidence, observability=Observability.INFERRED,
        provenance=Provenance("manual-annotation", (operation.operation_id,), operation.kind),
        uncertainty=operation.uncertainty, metadata={"annotation_operation": operation.operation_id},
    )


def _event_frame(frames: Sequence[AnnotationFrame], time_ms: int) -> str:
    candidate = next((frame for frame in frames if frame.time_ms >= time_ms), frames[-1] if frames else None)
    if candidate is None:
        raise CalibrationError("cannot place annotation event without frames")
    return candidate.frame_id


def _frame_observability(entities: Sequence[TrackedEntity]) -> Observability:
    values = {entity.observability for entity in entities}
    if Observability.SIMULATOR_ONLY in values:
        return Observability.SIMULATOR_ONLY
    if Observability.UNKNOWN in values or not values:
        return Observability.UNKNOWN
    if Observability.INFERRED in values:
        return Observability.INFERRED
    return Observability.MEASURED
