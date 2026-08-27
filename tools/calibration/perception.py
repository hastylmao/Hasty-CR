"""Frame-source, detector, mapping, tracking, event, and trace orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence

from .core import (
    ArenaMapping,
    CalibrationError,
    Detection,
    Detector,
    Metric,
    NormalizedFrame,
    NormalizedTrace,
    Observability,
    Provenance,
    ResultStatus,
    SimpleGameAwareTracker,
    TraceEvent,
    TrackedEntity,
    Uncertainty,
)

FRAME_PACKET_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FramePacket:
    frame_id: str
    time_ms: int
    frame: Any
    source_frame: int | None = None
    battle_time_ms: int | None = None
    source: Provenance = field(default_factory=Provenance)
    confidence: float = 1.0
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = FRAME_PACKET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != FRAME_PACKET_SCHEMA_VERSION:
            raise CalibrationError(f"unsupported frame packet schema {self.schema_version}")
        if not self.frame_id or self.time_ms < 0:
            raise CalibrationError("frame packet requires frame_id and nonnegative time_ms")
        if not 0.0 <= self.confidence <= 1.0:
            raise CalibrationError("frame packet confidence must be between 0 and 1")


class PacketSource(Protocol):
    def frames(self) -> Iterable[FramePacket]: ...


class IterableFrameSource:
    """Normalize predecoded frames without imposing an image dependency."""

    def __init__(
        self,
        frames: Iterable[Any],
        *,
        interval_ms: int,
        source: str = "iterable",
        start_time_ms: int = 0,
        frame_id_prefix: str = "frame",
    ) -> None:
        if interval_ms <= 0 or start_time_ms < 0:
            raise CalibrationError("frame source timing must be positive and nonnegative")
        self._frames = frames
        self.interval_ms = interval_ms
        self.source = source
        self.start_time_ms = start_time_ms
        self.frame_id_prefix = frame_id_prefix

    def frames(self) -> Iterator[FramePacket]:
        for index, frame in enumerate(self._frames):
            yield FramePacket(
                f"{self.frame_id_prefix}-{index:06d}", self.start_time_ms + index * self.interval_ms,
                frame, source_frame=index,
                source=Provenance(self.source, method="IterableFrameSource"),
            )


class CaptureIndexFrameSource:
    """Read emulator capture indexes while leaving image decoding to a callback."""

    def __init__(self, session_dir: str | Path, decoder: Callable[[Path], Any]) -> None:
        self.session_dir = Path(session_dir)
        self.decoder = decoder

    def frames(self) -> Iterator[FramePacket]:
        session_path = self.session_dir / "session.json"
        try:
            session = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"invalid capture session: {session_path}") from exc
        devices = session.get("devices", ())
        if not isinstance(devices, list) or not devices:
            raise CalibrationError("capture session contains no devices")
        for device in sorted(str(item) for item in devices):
            index_path = self.session_dir / device.replace(":", "_") / "frames.jsonl"
            for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise CalibrationError(f"invalid capture index row {index_path}:{line_number}") from exc
                if row.get("error"):
                    continue
                relative_path = row.get("path")
                elapsed = row.get("elapsed_seconds")
                if not isinstance(relative_path, str) or elapsed is None:
                    raise CalibrationError(f"capture row missing path/time at {index_path}:{line_number}")
                image_path = self.session_dir / relative_path
                index = int(row.get("frame_index", line_number - 1))
                yield FramePacket(
                    f"{device}:{index}", round(float(elapsed) * 1000), self.decoder(image_path),
                    source_frame=index,
                    source=Provenance("emulator-capture", method="frames.jsonl",
                                      details={"device": device}),
                    metadata={"device": device, "sha256_pixels": row.get("sha256_pixels")},
                )


class CallableDetectorAdapter:
    """Adapt detector callables and structured rows to the core Detection protocol."""

    def __init__(self, detect: Callable[[Any], Sequence[Any]],
                 convert: Callable[[Any], Detection] | None = None) -> None:
        self._detect = detect
        self._convert = convert or detection_from_mapping

    def detect(self, frame: Any) -> tuple[Detection, ...]:
        return tuple(self._convert(item) for item in self._detect(frame))


class MappedDetector:
    """Map detector points from image coordinates into arena coordinates."""

    def __init__(
        self,
        detector: Detector,
        mapping: ArenaMapping,
        *,
        contact_estimator: Callable[[Detection], tuple[float, float] | None] | None = None,
    ) -> None:
        self.detector = detector
        self.mapping = mapping
        self.contact_estimator = contact_estimator

    def detect(self, frame: Any) -> tuple[Detection, ...]:
        mapped = []
        for detection in self.detector.detect(frame):
            point = self.contact_estimator(detection) if self.contact_estimator else (detection.x, detection.y)
            if point is None:
                continue
            x, y = self.mapping.forward(point)
            sigma = detection.uncertainty.sigma
            mapping_sigma = self.mapping.reprojection_error
            uncertainty = replace(
                detection.uncertainty,
                sigma=max(sigma or 0.0, mapping_sigma),
                reason="; ".join(filter(None, (detection.uncertainty.reason, "arena reprojection"))),
            )
            mapped.append(replace(detection, x=x, y=y, uncertainty=uncertainty))
        return tuple(mapped)


class TrackerAdapter:
    """Normalize third-party tracker rows to TrackedEntity without copying internals."""

    def __init__(self, update: Callable[[int, Sequence[Detection]], Sequence[Any]],
                 convert: Callable[[Any], TrackedEntity]) -> None:
        self._update = update
        self._convert = convert

    def update(self, time_ms: int, detections: Sequence[Detection]) -> tuple[TrackedEntity, ...]:
        return tuple(self._convert(item) for item in self._update(time_ms, detections))


class EventDeriver:
    """Derive conservative spawn/death/relabel events from track transitions."""

    def __init__(self, *, max_gap_frames: int = 1) -> None:
        if max_gap_frames < 0:
            raise CalibrationError("event max gap must be nonnegative")
        self.max_gap_frames = max_gap_frames
        self._previous: dict[str, TrackedEntity] = {}
        self._missing: dict[str, int] = {}

    def update(self, time_ms: int, entities: Sequence[TrackedEntity]) -> tuple[TraceEvent, ...]:
        current = {entity.track_id: entity for entity in entities}
        events: list[TraceEvent] = []
        for track_id, entity in sorted(current.items()):
            previous = self._previous.get(track_id)
            if previous is None:
                events.append(_entity_event("spawn", time_ms, entity))
            elif previous.class_name != entity.class_name or previous.team != entity.team:
                events.append(_entity_event(
                    "track_relabel", time_ms, entity,
                    metadata={"previous_class": previous.class_name, "previous_team": previous.team},
                ))
            self._missing.pop(track_id, None)
        for track_id, previous in sorted(self._previous.items()):
            if track_id in current:
                continue
            count = self._missing.get(track_id, 0) + 1
            if count > self.max_gap_frames:
                events.append(_entity_event("death_inferred", time_ms, previous))
                self._missing.pop(track_id, None)
            else:
                self._missing[track_id] = count
                current[track_id] = previous
        self._previous = current
        return tuple(events)


class PerceptionTraceBuilder:
    def __init__(self, detector: Detector, tracker: Any | None = None,
                 event_deriver: EventDeriver | None = None) -> None:
        self.detector = detector
        self.tracker = tracker or SimpleGameAwareTracker()
        self.event_deriver = event_deriver or EventDeriver()

    def build(self, source: PacketSource | Iterable[FramePacket], *, trace_id: str,
              metadata: Mapping[str, Any] | None = None) -> NormalizedTrace:
        packets = source.frames() if hasattr(source, "frames") else source
        normalized: list[NormalizedFrame] = []
        previous_time = -1
        for packet in packets:
            if packet.time_ms < previous_time:
                raise CalibrationError("perception frame packets must be time ordered")
            previous_time = packet.time_ms
            detections = tuple(self.detector.detect(packet.frame))
            entities = tuple(self.tracker.update(packet.time_ms, detections))
            events = self.event_deriver.update(packet.time_ms, entities)
            confidence = _combined_confidence(packet.confidence, entities)
            normalized.append(NormalizedFrame(
                packet.time_ms, packet.frame_id, entities=entities, events=events,
                observability=_observability(entities), source=packet.source,
                confidence=confidence, uncertainty=packet.uncertainty,
                battle_time_ms=packet.battle_time_ms, source_frame=packet.source_frame,
                metadata={**packet.metadata, "detections": len(detections)},
            ))
        return NormalizedTrace(
            tuple(normalized), trace_id=trace_id,
            source=Provenance("perception", method="PerceptionTraceBuilder"),
            metadata={**dict(metadata or {}), "frame_packet_schema": FRAME_PACKET_SCHEMA_VERSION},
        )


def compare_traces_weighted(
    observed: NormalizedTrace,
    simulated: NormalizedTrace,
    *,
    position_tolerance: float = 0.5,
    time_tolerance_ms: float = 250.0,
    uncertainty_floor: float = 0.05,
) -> tuple[Metric, ...]:
    """Compare matched IDs/events using confidence and inverse-variance weights."""
    if uncertainty_floor <= 0:
        raise CalibrationError("uncertainty_floor must be positive")
    simulated_by_time = {frame.time_ms: frame for frame in simulated.frames}
    position_rows: list[tuple[float, float]] = []
    for frame in observed.frames:
        key = frame.battle_time_ms if frame.battle_time_ms is not None else frame.time_ms
        other_frame = simulated_by_time.get(key)
        if other_frame is None:
            continue
        entities = {entity.track_id: entity for entity in other_frame.entities}
        for entity in frame.entities:
            other = entities.get(entity.track_id)
            if other is None:
                continue
            error = ((entity.x - other.x) ** 2 + (entity.y - other.y) ** 2) ** 0.5
            sigma = max(entity.uncertainty.sigma or uncertainty_floor,
                        other.uncertainty.sigma or uncertainty_floor, uncertainty_floor)
            weight = max(0.0, entity.confidence * other.confidence) / (sigma * sigma)
            if weight:
                position_rows.append((error, weight))
    metrics = [_weighted_metric("position.weighted_mean_error", "position", position_rows,
                                position_tolerance, fail=True)]
    observed_events = [event for frame in observed.frames for event in frame.events]
    simulated_events = [event for frame in simulated.frames for event in frame.events]
    timing_rows: list[tuple[float, float]] = []
    for event in observed_events:
        candidates = [item for item in simulated_events
                      if item.event_type == event.event_type
                      and (event.actor_id is None or item.actor_id == event.actor_id)]
        if not candidates:
            continue
        candidate = min(candidates, key=lambda item: abs(item.time_ms - event.time_ms))
        sigma = max(event.uncertainty.sigma or uncertainty_floor,
                    candidate.uncertainty.sigma or uncertainty_floor, uncertainty_floor)
        weight = max(0.0, event.confidence * candidate.confidence) / (sigma * sigma)
        if weight:
            timing_rows.append((abs(candidate.time_ms - event.time_ms), weight))
    metrics.append(_weighted_metric("timing.weighted_event_error", "timing", timing_rows,
                                    time_tolerance_ms, fail=False))
    metrics.append(Metric(
        "coverage.weighted_comparison", "coverage",
        ResultStatus.PASS if position_rows or timing_rows else ResultStatus.UNMEASURED,
        len(position_rows) + len(timing_rows),
        details={"position_pairs": len(position_rows), "event_pairs": len(timing_rows),
                 "weighting": "confidence_product / max(sigma,floor)^2",
                 "uncertainty_floor": uncertainty_floor},
    ))
    return tuple(metrics)


def perception_manifest(trace: NormalizedTrace, weighted_metrics: Sequence[Metric] = ()) -> dict[str, Any]:
    from .core import trace_digest
    payload = {
        "schema_version": 1,
        "status": "SYNTHETIC_ONLY" if (
            trace.source.source == "perception"
            and any(frame.source.source == "synthetic-fixture" for frame in trace.frames)
        ) else "UNMEASURED",
        "trace_id": trace.trace_id,
        "frames": len(trace.frames),
        "entity_observations": sum(len(frame.entities) for frame in trace.frames),
        "events": sum(len(frame.events) for frame in trace.frames),
        "trace_sha256": trace_digest(trace),
        "weighted_metrics": [metric.to_dict() for metric in weighted_metrics],
        "real_measurements": 0,
        "performance_claim": None,
    }
    return payload


def detection_from_mapping(value: Any) -> Detection:
    if isinstance(value, Detection):
        return value
    if not isinstance(value, Mapping):
        raise CalibrationError("detector row must be a Detection or object")
    team = None if value.get("team") is None else int(value["team"])
    uncertainty = Uncertainty.from_dict(value.get("uncertainty"))
    return Detection(
        str(value["class_name"]), team, float(value["x"]), float(value["y"]),
        float(value.get("confidence", 1.0)),
        None if value.get("flying") is None else bool(value["flying"]),
        None if value.get("hitpoints") is None else float(value["hitpoints"]), uncertainty,
    )


def frame_packet_digest(packet: FramePacket) -> str:
    payload = {
        "schema_version": packet.schema_version, "frame_id": packet.frame_id,
        "time_ms": packet.time_ms, "source_frame": packet.source_frame,
        "battle_time_ms": packet.battle_time_ms, "source": packet.source.to_dict(),
        "confidence": packet.confidence, "uncertainty": packet.uncertainty.to_dict(),
        "metadata": dict(packet.metadata),
    }
    from .core import canonical_json
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _entity_event(event_type: str, time_ms: int, entity: TrackedEntity,
                  metadata: Mapping[str, Any] | None = None) -> TraceEvent:
    return TraceEvent(
        event_type, time_ms, actor_id=entity.track_id, actor_class=entity.class_name,
        team=entity.team, x=entity.x, y=entity.y,
        confidence=entity.confidence, observability=entity.observability,
        provenance=entity.provenance, uncertainty=entity.uncertainty,
        metadata=dict(metadata or {}),
    )


def _combined_confidence(frame_confidence: float, entities: Sequence[TrackedEntity]) -> float:
    if not entities:
        return frame_confidence
    return min(frame_confidence, sum(entity.confidence for entity in entities) / len(entities))


def _observability(entities: Sequence[TrackedEntity]) -> Observability:
    values = {entity.observability for entity in entities}
    if Observability.SIMULATOR_ONLY in values:
        return Observability.SIMULATOR_ONLY
    if Observability.UNKNOWN in values or not values:
        return Observability.UNKNOWN
    if Observability.INFERRED in values:
        return Observability.INFERRED
    return Observability.MEASURED


def _weighted_metric(name: str, category: str, rows: Sequence[tuple[float, float]],
                     tolerance: float, *, fail: bool) -> Metric:
    if not rows:
        return Metric(name, category, ResultStatus.UNMEASURED, 0, None, tolerance)
    total_weight = sum(weight for _, weight in rows)
    value = sum(error * weight for error, weight in rows) / total_weight
    if value <= tolerance:
        status = ResultStatus.PASS
    else:
        status = ResultStatus.FAIL if fail else ResultStatus.WARN
    return Metric(name, category, status, len(rows), value, tolerance,
                  {"total_weight": total_weight})
