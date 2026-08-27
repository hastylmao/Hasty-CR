"""Replay observation and simulator calibration primitives.

This module deliberately separates perception from mechanics. A future replay
collector only needs to emit :class:`ReplayFrame` records; the event extractor
and simulator comparator remain independent of the source (video, exported
replay, or an authorized API).

The JSON schema is intentionally boring and stable so large datasets can be
streamed as JSON Lines. No external runtime dependency is required.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class UnitObservation:
    """One tracked body observed in a replay frame."""

    track_id: str
    card: str
    side: int
    x: float
    y: float
    hitpoints: float | None = None
    max_hitpoints: float | None = None
    confidence: float = 1.0
    flying: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "UnitObservation":
        return cls(
            track_id=str(value["track_id"]), card=str(value["card"]),
            side=int(value["side"]), x=float(value["x"]), y=float(value["y"]),
            hitpoints=(None if value.get("hitpoints") is None
                       else float(value["hitpoints"])),
            max_hitpoints=(None if value.get("max_hitpoints") is None
                           else float(value["max_hitpoints"])),
            confidence=float(value.get("confidence", 1.0)),
            flying=(None if value.get("flying") is None
                    else bool(value["flying"])),
        )


@dataclass(frozen=True)
class TowerObservation:
    """Tower state as observed in a replay frame."""

    tower_id: str
    side: int
    lane: str
    x: float
    y: float
    hitpoints: float | None = None
    max_hitpoints: float | None = None
    alive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TowerObservation":
        return cls(
            tower_id=str(value["tower_id"]), side=int(value["side"]),
            lane=str(value["lane"]), x=float(value["x"]), y=float(value["y"]),
            hitpoints=(None if value.get("hitpoints") is None
                       else float(value["hitpoints"])),
            max_hitpoints=(None if value.get("max_hitpoints") is None
                           else float(value["max_hitpoints"])),
            alive=bool(value.get("alive", True)),
        )


@dataclass(frozen=True)
class ReplayFrame:
    """Normalized observation at one source timestamp."""

    time_ms: int
    units: tuple[UnitObservation, ...] = ()
    towers: tuple[TowerObservation, ...] = ()
    elixir: float | None = None
    hand: tuple[str, ...] = ()
    source_frame: int | None = None
    source: str = "unknown"
    confidence: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["units"] = [unit.to_dict() for unit in self.units]
        value["towers"] = [tower.to_dict() for tower in self.towers]
        value["hand"] = list(self.hand)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayFrame":
        return cls(
            time_ms=int(value["time_ms"]),
            units=tuple(UnitObservation.from_dict(item)
                        for item in value.get("units", ())),
            towers=tuple(TowerObservation.from_dict(item)
                         for item in value.get("towers", ())),
            elixir=(None if value.get("elixir") is None
                    else float(value["elixir"])),
            hand=tuple(str(item) for item in value.get("hand", ())),
            source_frame=(None if value.get("source_frame") is None
                          else int(value["source_frame"])),
            source=str(value.get("source", "unknown")),
            confidence=float(value.get("confidence", 1.0)),
        )


@dataclass(frozen=True)
class MechanicsEvent:
    """An event inferred from changes between consecutive observations."""

    event_type: str
    time_ms: int
    actor_id: str | None = None
    actor_card: str | None = None
    actor_side: int | None = None
    target_id: str | None = None
    target_card: str | None = None
    x: float | None = None
    y: float | None = None
    previous_x: float | None = None
    previous_y: float | None = None
    value: float | None = None
    confidence: float = 1.0
    source: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EventTolerance:
    """Matching tolerances for observed-vs-simulated event comparison."""

    time_ms: int = 250
    position: float = 0.75
    value: float = 0.15


@dataclass(frozen=True)
class EventMatch:
    observed_index: int
    simulated_index: int
    time_error_ms: int
    position_error: float | None
    value_error: float | None


@dataclass(frozen=True)
class ComparisonReport:
    observed_events: int
    simulated_events: int
    matched_events: int
    unmatched_observed: int
    unmatched_simulated: int
    mean_time_error_ms: float | None
    mean_position_error: float | None
    mean_value_error: float | None
    matches: tuple[EventMatch, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def frame_from_dict(value: Mapping[str, Any]) -> ReplayFrame:
    """Validate and decode one schema-v1 frame."""
    if int(value.get("schema_version", SCHEMA_VERSION)) != SCHEMA_VERSION:
        raise ValueError("unsupported replay observation schema")
    return ReplayFrame.from_dict(value)


def read_frames(path: str | Path) -> Iterator[ReplayFrame]:
    """Stream JSON or JSONL observation files."""
    path = Path(path)
    with path.open(encoding="utf-8") as handle:
        if path.suffix.lower() == ".json":
            payload = json.load(handle)
            values = payload.get("frames", payload) if isinstance(payload, dict) else payload
            if not isinstance(values, list):
                raise ValueError("JSON observations must contain a frame list")
            yield from (frame_from_dict(value) for value in values)
            return
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield frame_from_dict(json.loads(line))
            except (TypeError, ValueError, json.JSONDecodeError) as error:
                if isinstance(error, ValueError) and str(error) == "unsupported replay observation schema":
                    raise
                raise ValueError(f"invalid observation at line {line_number}") from error


def write_frames(path: str | Path, frames: Iterable[ReplayFrame], source: str = "") -> int:
    """Write observations as JSONL and return the number of frames written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for frame in frames:
            record = {"schema_version": SCHEMA_VERSION, **frame.to_dict()}
            if source:
                record["source"] = source
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            count += 1
    return count


def _event_confidence(*values: float) -> float:
    return max(0.0, min(1.0, min(values, default=1.0)))


def extract_events(frames: Iterable[ReplayFrame], movement_threshold: float = 0.08,
                   damage_threshold: float = 0.01) -> list[MechanicsEvent]:
    """Infer conservative, observable events from tracked frame deltas.

    This intentionally does not label attacks from animation guesses. It emits
    only events supported by stable identity, position, health, and presence
    changes; future detectors can add explicit projectile/action annotations.
    """
    ordered = sorted(frames, key=lambda frame: frame.time_ms)
    events: list[MechanicsEvent] = []
    previous_units: dict[str, UnitObservation] = {}
    previous_towers: dict[str, TowerObservation] = {}
    previous_time = None

    for frame in ordered:
        current_units = {unit.track_id: unit for unit in frame.units}
        current_towers = {tower.tower_id: tower for tower in frame.towers}
        if previous_time is not None and frame.time_ms < previous_time:
            raise ValueError("frames must be ordered by nondecreasing time_ms")

        for track_id, unit in current_units.items():
            old = previous_units.get(track_id)
            if old is None:
                events.append(MechanicsEvent(
                    "unit_spawn", frame.time_ms, track_id, unit.card, unit.side,
                    unit.track_id, unit.card, unit.x, unit.y,
                    confidence=_event_confidence(frame.confidence, unit.confidence),
                    source=frame.source))
                continue
            displacement = math.hypot(unit.x - old.x, unit.y - old.y)
            if displacement >= movement_threshold:
                events.append(MechanicsEvent(
                    "unit_move", frame.time_ms, track_id, unit.card, unit.side,
                    x=unit.x, y=unit.y, previous_x=old.x, previous_y=old.y,
                    value=displacement,
                    confidence=_event_confidence(frame.confidence, unit.confidence,
                                                 old.confidence),
                    source=frame.source))
            if (old.hitpoints is not None and unit.hitpoints is not None
                    and old.hitpoints - unit.hitpoints >= damage_threshold):
                events.append(MechanicsEvent(
                    "unit_damage", frame.time_ms, target_id=track_id,
                    target_card=unit.card, x=unit.x, y=unit.y,
                    value=old.hitpoints - unit.hitpoints,
                    confidence=_event_confidence(frame.confidence, unit.confidence,
                                                 old.confidence),
                    source=frame.source))

        for track_id, old in previous_units.items():
            if track_id not in current_units:
                events.append(MechanicsEvent(
                    "unit_despawn", frame.time_ms, track_id, old.card, old.side,
                    target_id=track_id, target_card=old.card,
                    x=old.x, y=old.y, confidence=_event_confidence(
                        frame.confidence, old.confidence), source=frame.source))

        for tower_id, tower in current_towers.items():
            old = previous_towers.get(tower_id)
            if old is None:
                events.append(MechanicsEvent(
                    "tower_seen", frame.time_ms, target_id=tower_id,
                    target_card=tower.lane, x=tower.x, y=tower.y,
                    value=tower.hitpoints, confidence=frame.confidence,
                    source=frame.source))
            elif (old.hitpoints is not None and tower.hitpoints is not None
                  and old.hitpoints - tower.hitpoints >= damage_threshold):
                events.append(MechanicsEvent(
                    "tower_damage", frame.time_ms, target_id=tower_id,
                    target_card=tower.lane, x=tower.x, y=tower.y,
                    value=old.hitpoints - tower.hitpoints,
                    confidence=frame.confidence, source=frame.source))
            if old is not None and old.alive and not tower.alive:
                events.append(MechanicsEvent(
                    "tower_destroyed", frame.time_ms, target_id=tower_id,
                    target_card=tower.lane, x=tower.x, y=tower.y,
                    confidence=frame.confidence, source=frame.source))

        for tower_id, old in previous_towers.items():
            if tower_id not in current_towers and old.alive:
                events.append(MechanicsEvent(
                    "tower_destroyed", frame.time_ms, target_id=tower_id,
                    target_card=old.lane, x=old.x, y=old.y,
                    confidence=_event_confidence(frame.confidence), source=frame.source))

        previous_units, previous_towers, previous_time = (
            current_units, current_towers, frame.time_ms)
    return events


def compare_events(observed: Sequence[MechanicsEvent],
                   simulated: Sequence[MechanicsEvent],
                   tolerance: EventTolerance = EventTolerance()) -> ComparisonReport:
    """Greedily align events by type/identity and report calibration error."""
    candidates = sorted(enumerate(simulated), key=lambda item: item[1].time_ms)
    used: set[int] = set()
    matches: list[EventMatch] = []
    for observed_index, expected in sorted(enumerate(observed), key=lambda item: item[1].time_ms):
        best: tuple[float, int, MechanicsEvent] | None = None
        for simulated_index, actual in candidates:
            if simulated_index in used or actual.event_type != expected.event_type:
                continue
            if expected.actor_card and actual.actor_card != expected.actor_card:
                continue
            if expected.target_card and actual.target_card != expected.target_card:
                continue
            time_error = abs(actual.time_ms - expected.time_ms)
            if time_error > tolerance.time_ms:
                continue
            position_error = None
            if expected.x is not None and expected.y is not None and actual.x is not None and actual.y is not None:
                position_error = math.hypot(actual.x - expected.x, actual.y - expected.y)
                if position_error > tolerance.position:
                    continue
            value_error = None
            if expected.value is not None and actual.value is not None:
                scale = max(abs(expected.value), 1.0)
                value_error = abs(actual.value - expected.value) / scale
                if value_error > tolerance.value:
                    continue
            score = time_error / max(tolerance.time_ms, 1)
            if position_error is not None:
                score += position_error / max(tolerance.position, 1e-9)
            if value_error is not None:
                score += value_error / max(tolerance.value, 1e-9)
            if best is None or score < best[0]:
                best = (score, simulated_index, actual)
        if best is None:
            continue
        _, simulated_index, actual = best
        used.add(simulated_index)
        position_error = (None if expected.x is None or expected.y is None
                          or actual.x is None or actual.y is None else
                          math.hypot(actual.x - expected.x, actual.y - expected.y))
        value_error = (None if expected.value is None or actual.value is None else
                       abs(actual.value - expected.value) / max(abs(expected.value), 1.0))
        matches.append(EventMatch(
            observed_index, simulated_index,
            abs(actual.time_ms - expected.time_ms), position_error, value_error))

    time_errors = [match.time_error_ms for match in matches]
    position_errors = [match.position_error for match in matches if match.position_error is not None]
    value_errors = [match.value_error for match in matches if match.value_error is not None]
    return ComparisonReport(
        observed_events=len(observed), simulated_events=len(simulated),
        matched_events=len(matches), unmatched_observed=len(observed) - len(matches),
        unmatched_simulated=len(simulated) - len(matches),
        mean_time_error_ms=(sum(time_errors) / len(time_errors) if time_errors else None),
        mean_position_error=(sum(position_errors) / len(position_errors)
                             if position_errors else None),
        mean_value_error=(sum(value_errors) / len(value_errors) if value_errors else None),
        matches=tuple(matches))


def simulator_snapshot(battle: Any) -> list[MechanicsEvent]:
    """Project the current HastyCR Battle state into observation-like events."""
    events: list[MechanicsEvent] = []
    for entity in battle.living():
        events.append(MechanicsEvent(
            "unit_state", int(battle.now_ms), actor_id=str(entity.uid),
            actor_card=entity.name, actor_side=entity.side, x=entity.pos.x / 1000,
            y=entity.pos.y / 1000, value=float(entity.hitpoints), source="simulator"))
    return events
