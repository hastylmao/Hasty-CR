"""Stdlib-first normalized calibration core for HastyCR."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Iterator, Mapping, Protocol, Sequence

SCHEMA_VERSION = 2


class CalibrationError(ValueError):
    pass


class Observability(str, Enum):
    MEASURED = "measured"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    SIMULATOR_ONLY = "simulator-only"


class ResultStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    UNMEASURED = "UNMEASURED"


@dataclass(frozen=True)
class Provenance:
    source: str = "unknown"
    evidence_ids: tuple[str, ...] = ()
    method: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "evidence_ids": list(self.evidence_ids),
                "method": self.method, "details": dict(self.details)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "Provenance":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise CalibrationError("provenance must be an object")
        return cls(str(value.get("source", "unknown")),
                   tuple(str(x) for x in value.get("evidence_ids", ())),
                   str(value.get("method", "")),
                   dict(value.get("details", {})))


@dataclass(frozen=True)
class Uncertainty:
    sigma: float | None = None
    lower: float | None = None
    upper: float | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"sigma": self.sigma, "lower": self.lower,
                "upper": self.upper, "reason": self.reason}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "Uncertainty":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise CalibrationError("uncertainty must be an object")
        result = cls(_optional_float(value.get("sigma")),
                     _optional_float(value.get("lower")),
                     _optional_float(value.get("upper")),
                     str(value.get("reason", "")))
        if result.lower is not None and result.upper is not None and result.lower > result.upper:
            raise CalibrationError("uncertainty lower exceeds upper")
        return result


@dataclass(frozen=True)
class TrackedEntity:
    track_id: str
    class_name: str
    team: int | None
    x: float
    y: float
    z: float | None = None
    hitpoints: float | None = None
    max_hitpoints: float | None = None
    alive: bool = True
    flying: bool | None = None
    velocity_x: float | None = None
    velocity_y: float | None = None
    confidence: float = 1.0
    observability: Observability = Observability.UNKNOWN
    provenance: Provenance = field(default_factory=Provenance)
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.track_id or not self.class_name:
            raise CalibrationError("entity identity is required")
        _finite(self.x, "entity.x")
        _finite(self.y, "entity.y")
        _bounded(self.confidence, 0.0, 1.0, "entity.confidence")
        if self.team not in (None, -1, 1):
            raise CalibrationError("entity.team must be -1, 1, or null")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observability"] = self.observability.value
        value["provenance"] = self.provenance.to_dict()
        value["uncertainty"] = self.uncertainty.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TrackedEntity":
        _object(value, "entity")
        required = ("track_id", "class_name", "x", "y")
        _required(value, required, "entity")
        try:
            observability = Observability(value.get("observability", "unknown"))
        except ValueError as exc:
            raise CalibrationError("invalid entity observability") from exc
        return cls(str(value["track_id"]), str(value["class_name"]),
                   None if value.get("team") is None else int(value["team"]),
                   float(value["x"]), float(value["y"]),
                   _optional_float(value.get("z")),
                   _optional_float(value.get("hitpoints")),
                   _optional_float(value.get("max_hitpoints")),
                   bool(value.get("alive", True)),
                   None if value.get("flying") is None else bool(value["flying"]),
                   _optional_float(value.get("velocity_x")),
                   _optional_float(value.get("velocity_y")),
                   float(value.get("confidence", 1.0)), observability,
                   Provenance.from_dict(value.get("provenance")),
                   Uncertainty.from_dict(value.get("uncertainty")),
                   dict(value.get("metadata", {})))


@dataclass(frozen=True)
class TowerState:
    tower_id: str
    team: int
    lane: str
    x: float
    y: float
    hitpoints: float | None = None
    max_hitpoints: float | None = None
    alive: bool = True
    confidence: float = 1.0
    observability: Observability = Observability.UNKNOWN
    provenance: Provenance = field(default_factory=Provenance)
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observability"] = self.observability.value
        value["provenance"] = self.provenance.to_dict()
        value["uncertainty"] = self.uncertainty.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TowerState":
        _object(value, "tower")
        _required(value, ("tower_id", "team", "lane", "x", "y"), "tower")
        try:
            obs = Observability(value.get("observability", "unknown"))
        except ValueError as exc:
            raise CalibrationError("invalid tower observability") from exc
        return cls(str(value["tower_id"]), int(value["team"]), str(value["lane"]),
                   float(value["x"]), float(value["y"]),
                   _optional_float(value.get("hitpoints")),
                   _optional_float(value.get("max_hitpoints")),
                   bool(value.get("alive", True)), float(value.get("confidence", 1.0)), obs,
                   Provenance.from_dict(value.get("provenance")),
                   Uncertainty.from_dict(value.get("uncertainty")),
                   dict(value.get("metadata", {})))


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    time_ms: int
    actor_id: str | None = None
    target_id: str | None = None
    actor_class: str | None = None
    target_class: str | None = None
    team: int | None = None
    x: float | None = None
    y: float | None = None
    value: float | None = None
    confidence: float = 1.0
    observability: Observability = Observability.UNKNOWN
    provenance: Provenance = field(default_factory=Provenance)
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_type or self.time_ms < 0:
            raise CalibrationError("event type and nonnegative time_ms are required")
        _bounded(self.confidence, 0.0, 1.0, "event.confidence")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["observability"] = self.observability.value
        value["provenance"] = self.provenance.to_dict()
        value["uncertainty"] = self.uncertainty.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TraceEvent":
        _object(value, "event")
        _required(value, ("event_type", "time_ms"), "event")
        try:
            obs = Observability(value.get("observability", "unknown"))
        except ValueError as exc:
            raise CalibrationError("invalid event observability") from exc
        return cls(str(value["event_type"]), int(value["time_ms"]),
                   _optional_str(value.get("actor_id")), _optional_str(value.get("target_id")),
                   _optional_str(value.get("actor_class")), _optional_str(value.get("target_class")),
                   None if value.get("team") is None else int(value["team"]),
                   _optional_float(value.get("x")), _optional_float(value.get("y")),
                   _optional_float(value.get("value")), float(value.get("confidence", 1.0)), obs,
                   Provenance.from_dict(value.get("provenance")),
                   Uncertainty.from_dict(value.get("uncertainty")), dict(value.get("metadata", {})))


@dataclass(frozen=True)
class NormalizedFrame:
    time_ms: int
    frame_id: str
    entities: tuple[TrackedEntity, ...] = ()
    towers: tuple[TowerState, ...] = ()
    events: tuple[TraceEvent, ...] = ()
    observability: Observability = Observability.UNKNOWN
    source: Provenance = field(default_factory=Provenance)
    confidence: float = 1.0
    uncertainty: Uncertainty = field(default_factory=Uncertainty)
    battle_time_ms: int | None = None
    source_frame: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.time_ms < 0 or not self.frame_id:
            raise CalibrationError("frame_id and nonnegative time_ms are required")
        _bounded(self.confidence, 0.0, 1.0, "frame.confidence")
        ids = [x.track_id for x in self.entities]
        if len(ids) != len(set(ids)):
            raise CalibrationError("duplicate entity track_id in frame")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["entities"] = [x.to_dict() for x in self.entities]
        value["towers"] = [x.to_dict() for x in self.towers]
        value["events"] = [x.to_dict() for x in self.events]
        value["observability"] = self.observability.value
        value["source"] = self.source.to_dict()
        value["uncertainty"] = self.uncertainty.to_dict()
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedFrame":
        _object(value, "frame")
        _required(value, ("time_ms", "frame_id"), "frame")
        try:
            obs = Observability(value.get("observability", "unknown"))
        except ValueError as exc:
            raise CalibrationError("invalid frame observability") from exc
        return cls(int(value["time_ms"]), str(value["frame_id"]),
                   tuple(TrackedEntity.from_dict(x) for x in value.get("entities", ())),
                   tuple(TowerState.from_dict(x) for x in value.get("towers", ())),
                   tuple(TraceEvent.from_dict(x) for x in value.get("events", ())), obs,
                   Provenance.from_dict(value.get("source")), float(value.get("confidence", 1.0)),
                   Uncertainty.from_dict(value.get("uncertainty")),
                   None if value.get("battle_time_ms") is None else int(value["battle_time_ms"]),
                   None if value.get("source_frame") is None else int(value["source_frame"]),
                   dict(value.get("metadata", {})))


@dataclass(frozen=True)
class NormalizedTrace:
    frames: tuple[NormalizedFrame, ...]
    trace_id: str = ""
    source: Provenance = field(default_factory=Provenance)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise CalibrationError(f"unsupported normalized trace schema {self.schema_version}")
        previous = -1
        for frame in self.frames:
            if frame.time_ms < previous:
                raise CalibrationError("trace frames must be ordered by time_ms")
            previous = frame.time_ms

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "trace_id": self.trace_id,
                "source": self.source.to_dict(), "metadata": dict(self.metadata),
                "frames": [x.to_dict() for x in self.frames]}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NormalizedTrace":
        _object(value, "trace")
        version = int(value.get("schema_version", SCHEMA_VERSION))
        if version != SCHEMA_VERSION:
            raise CalibrationError(f"unsupported normalized trace schema {version}")
        frames = value.get("frames")
        if not isinstance(frames, list):
            raise CalibrationError("trace.frames must be a list")
        return cls(tuple(NormalizedFrame.from_dict(x) for x in frames),
                   str(value.get("trace_id", "")), Provenance.from_dict(value.get("source")),
                   dict(value.get("metadata", {})), version)


def write_trace(path: str | Path, trace: NormalizedTrace, *, jsonl: bool = False) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if jsonl or path.suffix.lower() in {".jsonl", ".ndjson"}:
            for frame in trace.frames:
                handle.write(json.dumps({"schema_version": SCHEMA_VERSION,
                                         "trace_id": trace.trace_id, **frame.to_dict()},
                                        separators=(",", ":"), allow_nan=False) + "\n")
            return len(trace.frames)
        handle.write(json.dumps(trace.to_dict(), indent=2, allow_nan=False) + "\n")
    return len(trace.frames)


def read_trace(path: str | Path) -> NormalizedTrace:
    path = Path(path)
    if path.suffix.lower() not in {".jsonl", ".ndjson"}:
        try:
            return NormalizedTrace.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise CalibrationError(f"invalid trace JSON: {path}") from exc
    frames: list[NormalizedFrame] = []
    trace_id = ""
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise TypeError("frame is not an object")
                trace_id = str(value.get("trace_id", trace_id))
                frames.append(NormalizedFrame.from_dict(value))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise CalibrationError(f"invalid normalized trace at line {line_number}") from exc
    return NormalizedTrace(tuple(frames), trace_id=trace_id)


_VOLATILE_KEYS = frozenset({"captured_at_utc", "capture_started_at", "capture_ended_at",
                            "path", "file", "file_path", "source_file", "run_id",
                            "session_id", "volatile", "capture_metadata"})


def canonical_payload(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): canonical_payload(v) for k, v in sorted(value.items(), key=lambda p: str(p[0]))
                if str(k) not in _VOLATILE_KEYS}
    if isinstance(value, (list, tuple)):
        return [canonical_payload(v) for v in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CalibrationError("non-finite float cannot be serialized")
        if value == 0:
            return 0
        normalized = float(format(value, ".12g"))
        return int(normalized) if normalized.is_integer() else normalized
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(canonical_payload(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def trace_digest(trace: NormalizedTrace) -> str:
    return hashlib.sha256(canonical_json(trace.to_dict()).encode("utf-8")).hexdigest()


# Replay calibration schema-v1 compatibility.
def from_replay_frames(frames: Iterable[Any], *, source: str = "replay_calibration") -> NormalizedTrace:
    normalized = []
    for index, frame in enumerate(frames):
        entities = tuple(TrackedEntity(str(unit.track_id), str(unit.card), int(unit.side),
                                       float(unit.x), float(unit.y), hitpoints=unit.hitpoints,
                                       max_hitpoints=unit.max_hitpoints, flying=unit.flying,
                                       confidence=float(unit.confidence),
                                       observability=Observability.MEASURED,
                                       provenance=Provenance(source=source))
                         for unit in frame.units)
        towers = tuple(TowerState(str(tower.tower_id), int(tower.side), str(tower.lane),
                                  float(tower.x), float(tower.y), tower.hitpoints,
                                  tower.max_hitpoints, tower.alive,
                                  provenance=Provenance(source=source),
                                  observability=Observability.MEASURED)
                       for tower in frame.towers)
        normalized.append(NormalizedFrame(int(frame.time_ms), str(frame.source_frame if frame.source_frame is not None else index),
                                          entities, towers, source=Provenance(source=str(frame.source)),
                                          confidence=float(frame.confidence), source_frame=frame.source_frame,
                                          metadata={"elixir": frame.elixir, "hand": list(frame.hand)}))
    return NormalizedTrace(tuple(normalized), source=Provenance(source=source))


def to_replay_frames(trace: NormalizedTrace) -> list[Any]:
    from tools.replay_calibration import ReplayFrame, TowerObservation, UnitObservation
    result = []
    for frame in trace.frames:
        units = tuple(UnitObservation(entity.track_id, entity.class_name, int(entity.team or 0),
                                      entity.x, entity.y, entity.hitpoints, entity.max_hitpoints,
                                      entity.confidence, entity.flying)
                      for entity in frame.entities if entity.team is not None)
        towers = tuple(TowerObservation(tower.tower_id, tower.team, tower.lane, tower.x, tower.y,
                                        tower.hitpoints, tower.max_hitpoints, tower.alive)
                       for tower in frame.towers)
        result.append(ReplayFrame(frame.time_ms, units, towers,
                                  frame.metadata.get("elixir"), tuple(frame.metadata.get("hand", ())),
                                  frame.source_frame, frame.source.source, frame.confidence))
    return result


@dataclass(frozen=True)
class ScenarioAction:
    time_ms: int
    action: str
    side: int
    card: str | None = None
    x: float | None = None
    y: float | None = None
    uid: int | None = None
    actor_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], default_action: str = "deploy") -> "ScenarioAction":
        _object(value, "scenario action")
        position = value.get("position", value.get("at"))
        x = value.get("x")
        y = value.get("y")
        if position is not None:
            if not isinstance(position, (list, tuple)) or len(position) != 2:
                raise CalibrationError("scenario position must contain x and y")
            x, y = position
        side = int(value.get("side", 1))
        if side not in (-1, 1):
            raise CalibrationError("scenario action side must be -1 or 1")
        return cls(int(value.get("time_ms", value.get("time", 0))),
                   str(value.get("action", default_action)), side,
                   None if value.get("card") is None else str(value["card"]),
                   None if x is None else float(x), None if y is None else float(y),
                   None if value.get("uid") is None else int(value["uid"]),
                   _optional_str(value.get("actor_id")),
                   dict(value.get("metadata", {})))


@dataclass(frozen=True)
class MeasureSpec:
    name: str
    category: str
    tolerance: float | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    duration_ms: int
    dt_ms: int = 50
    seed: int = 0
    decks: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    actions: tuple[ScenarioAction, ...] = ()
    observation_windows: tuple[tuple[int, int], ...] = ()
    measures: tuple[MeasureSpec, ...] = ()
    tags: tuple[str, ...] = ()
    category: str = "uncategorized"
    split: str = "train"
    evidence_ids: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.scenario_id:
            errors.append("scenario_id is required")
        if self.duration_ms <= 0:
            errors.append("duration_ms must be positive")
        if self.dt_ms <= 0:
            errors.append("dt_ms must be positive")
        if self.split not in {"train", "validation", "test"}:
            errors.append("split must be train, validation, or test")
        if len(self.decks) != 2:
            errors.append("decks must contain two sides")
        previous = -1
        for action in self.actions:
            if action.time_ms < 0 or action.time_ms > self.duration_ms:
                errors.append(f"action time outside scenario: {action.time_ms}")
            if action.time_ms < previous:
                errors.append("actions must be ordered by time_ms")
            previous = action.time_ms
            if action.action in {"deploy", "spell", "building"} and not action.card:
                errors.append("card action requires card")
            if action.action in {"deploy", "spell", "building"} and (action.x is None or action.y is None):
                errors.append("card action requires position")
            if action.action == "ability" and action.uid is None and not action.actor_id and not action.card:
                errors.append("ability requires uid, actor_id, or card")
        for start, end in self.observation_windows:
            if start < 0 or end < start or end > self.duration_ms:
                errors.append("invalid observation window")
        return errors

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Scenario":
        _object(value, "scenario")
        decks_value = value.get("decks", ((), ()))
        if isinstance(decks_value, Mapping):
            decks_value = (decks_value.get("1", decks_value.get(1, ())),
                           decks_value.get("-1", decks_value.get(-1, ())))
        if not isinstance(decks_value, (list, tuple)) or len(decks_value) != 2:
            raise CalibrationError("scenario.decks must contain two lists")
        actions: list[ScenarioAction] = []
        for key in ("actions", "deployments", "spells", "buildings", "ability_activations"):
            if key not in value or value[key] is None:
                continue
            values = value[key]
            if not isinstance(values, list):
                raise CalibrationError(f"scenario.{key} must be a list")
            default = "ability" if key == "ability_activations" else {
                "deployments": "deploy", "spells": "spell", "buildings": "building"
            }.get(key, "deploy")
            actions.extend(ScenarioAction.from_dict(item, default) for item in values)
        actions.sort(key=lambda item: item.time_ms)
        measures = tuple(MeasureSpec(str(item["name"]), str(item.get("category", "uncategorized")),
                                    _optional_float(item.get("tolerance")),
                                    tuple(str(x) for x in item.get("evidence_ids", ())))
                       for item in value.get("measures", ()))
        windows = tuple((int(item[0]), int(item[1])) for item in value.get("observation_windows", ()))
        scenario = cls(str(value.get("scenario_id", value.get("id", ""))),
                       int(value.get("duration_ms", value.get("duration", 0))),
                       int(value.get("dt_ms", value.get("dt", 50))), int(value.get("seed", 0)),
                       (tuple(str(x) for x in decks_value[0]), tuple(str(x) for x in decks_value[1])),
                       tuple(actions), windows, measures,
                       tuple(str(x) for x in value.get("tags", ())), str(value.get("category", "uncategorized")),
                       str(value.get("split", "train")), tuple(str(x) for x in value.get("evidence_ids", ())),
                       dict(value.get("metadata", {})))
        errors = scenario.validate()
        if errors:
            raise CalibrationError("invalid scenario: " + "; ".join(errors))
        return scenario


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise CalibrationError("YAML input requires an already-installed PyYAML; use JSON") from exc
        value = yaml.safe_load(text)
    else:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CalibrationError(f"invalid scenario JSON: {path}") from exc
    return Scenario.from_dict(value)


class SimTraceAdapter:
    """Run controlled actions through public Match APIs and emit a trace."""
    def __init__(self, *, level: int = 11, trace_diagnostics: bool = False):
        self.level = level
        self.trace_diagnostics = trace_diagnostics

    def run(self, scenario: Scenario) -> NormalizedTrace:
        from sim.gamedata import load_gamedata
        from sim.match import Match
        from sim.spells import load_spells
        from sim.arena import Point
        cards = load_gamedata(level=self.level)
        needed = set(scenario.decks[0]) | set(scenario.decks[1]) | {
            x.card for x in scenario.actions if x.card}
        missing = sorted(x for x in needed if x not in cards)
        if missing:
            raise CalibrationError("scenario references unavailable cards: " + ", ".join(missing))
        decks = (list(scenario.decks[0] or tuple(needed)), list(scenario.decks[1] or tuple(needed)))
        spells = load_spells(self.level)
        match = Match(cards={name: cards[name] for name in needed}, decks=decks,
                      seed=scenario.seed, spells=spells)
        diagnostic_cursor = 0
        if self.trace_diagnostics:
            from sim.diagnostics import DiagnosticSink
            match.battle.diagnostics = DiagnosticSink()
            match.battle.trace_contacts = True
        actions = list(scenario.actions)
        action_index = 0
        frames: list[NormalizedFrame] = []
        previous_ids: set[int] = set()
        previous_damage = 0
        previous_ids, previous_damage, diagnostic_cursor = self._append_frame(
            frames, match, previous_ids, previous_damage,
            diagnostic_cursor, scenario, "0")
        while match.elapsed_ms < scenario.duration_ms and not match.finished:
            while action_index < len(actions) and actions[action_index].time_ms <= match.elapsed_ms:
                self._apply_action(match, actions[action_index])
                action_index += 1
            match.step(scenario.dt_ms)
            previous_ids, previous_damage, diagnostic_cursor = self._append_frame(
                frames, match, previous_ids, previous_damage, diagnostic_cursor,
                scenario, str(len(frames)))
        return NormalizedTrace(tuple(frames), trace_id=scenario.scenario_id,
                               source=Provenance("simulator", method="SimTraceAdapter"),
                               metadata={"scenario_id": scenario.scenario_id, "seed": scenario.seed,
                                         "duration_ms": scenario.duration_ms, "dt_ms": scenario.dt_ms})

    def _apply_action(self, match: Any, action: ScenarioAction) -> None:
        from sim.arena import Point
        if action.action in {"deploy", "spell", "building"}:
            if action.card is None or action.x is None or action.y is None:
                raise CalibrationError("card action requires card and position")
            player = match.players[action.side]
            if action.card not in player.hand:
                if not player.hand:
                    player.hand.append(action.card)
                else:
                    player.hand[0] = action.card
            player.elixir = max(player.elixir, 10000)
            if not match.play_card(action.side, action.card, Point(round(action.x * 1000), round(action.y * 1000))):
                raise CalibrationError(f"simulator rejected action {action.action}:{action.card} at {action.time_ms}ms")
            return
        if action.action == "ability":
            uid = action.uid
            if uid is None and action.actor_id:
                try:
                    uid = int(action.actor_id)
                except ValueError:
                    uid = next((entity.uid for entity in match.battle.living(action.side)
                                if str(entity.name) == action.actor_id), None)
            if uid is None and action.card:
                uid = next((entity.uid for entity in match.battle.living(action.side)
                            if entity.name == action.card), None)
            if uid is None:
                raise CalibrationError("ability actor could not be resolved")
            match.players[action.side].elixir = max(match.players[action.side].elixir, 10000)
            if not match.activate_ability(action.side, uid):
                raise CalibrationError(f"simulator rejected ability uid {uid} at {action.time_ms}ms")
            return
        raise CalibrationError(f"unsupported scenario action: {action.action}")

    def _append_frame(self, frames: list[NormalizedFrame], match: Any, previous_ids: set[int],
                      previous_damage: int, diagnostic_cursor: int,
                      scenario: Scenario, frame_id: str) -> tuple[set[int], int, int]:
        entities = []
        towers = []
        living = list(match.battle.living())
        current_ids = {entity.uid for entity in living}
        events: list[TraceEvent] = []
        for entity in sorted(living, key=lambda item: item.uid):
            if entity.is_tower:
                lane = next((name for side_towers in match.towers.values() for name, tower in side_towers.items()
                             if tower.uid == entity.uid), "unknown")
                towers.append(TowerState(str(entity.uid), entity.side, lane, entity.pos.x / 1000,
                                         entity.pos.y / 1000, entity.hitpoints, entity.max_hitpoints,
                                         entity.alive, 1.0, Observability.SIMULATOR_ONLY,
                                         Provenance("simulator", method="Match.towers")))
            else:
                entities.append(TrackedEntity(str(entity.uid), entity.name, entity.side,
                                              entity.pos.x / 1000, entity.pos.y / 1000,
                                              hitpoints=entity.hitpoints, max_hitpoints=entity.max_hitpoints,
                                              alive=entity.alive, flying=entity.flying, confidence=1.0,
                                              observability=Observability.SIMULATOR_ONLY,
                                              provenance=Provenance("simulator", method="Battle.living")))
            if entity.uid not in previous_ids and not self.trace_diagnostics:
                events.append(TraceEvent("spawn", match.elapsed_ms, actor_id=str(entity.uid),
                                         actor_class=entity.name, team=entity.side, x=entity.pos.x / 1000,
                                         y=entity.pos.y / 1000, observability=Observability.SIMULATOR_ONLY,
                                         provenance=Provenance("simulator")))
        damage = match.battle.damage_log
        if not self.trace_diagnostics:
            for row in damage[previous_damage:]:
                if len(row) >= 4:
                    time_ms, actor_uid, target_uid, amount = row[:4]
                    actor = match.battle.get(actor_uid)
                    target = match.battle.get(target_uid)
                    events.append(TraceEvent("damage", int(time_ms), actor_id=str(actor_uid), target_id=str(target_uid),
                                             actor_class=actor.name if actor else None,
                                             target_class=target.name if target else None, value=float(amount),
                                             observability=Observability.SIMULATOR_ONLY,
                                             provenance=Provenance("simulator", method="Battle.damage_log")))
        if not self.trace_diagnostics:
            for item in match.battle.contact_trace:
                if item.get("time_ms", -1) == match.elapsed_ms:
                    events.append(TraceEvent(str(item.get("kind", "collision")), match.elapsed_ms,
                                             observability=Observability.SIMULATOR_ONLY,
                                             provenance=Provenance("simulator", method="Battle.contact_trace"),
                                             metadata=item))
        if self.trace_diagnostics:
            sink = match.battle.diagnostics
            for item in sink.events[diagnostic_cursor:]:
                events.append(TraceEvent(
                    str(item["event_type"]), int(item["time_ms"]),
                    actor_id=(str(item["source_uid"]) if item.get("source_uid") is not None else None),
                    target_id=(str(item["target_uid"]) if item.get("target_uid") is not None else None),
                    x=(item["target_pos"][0] / 1000 if item.get("target_pos") else None),
                    y=(item["target_pos"][1] / 1000 if item.get("target_pos") else None),
                    value=(float(item["value"]) if item.get("value") is not None else None),
                    observability=Observability.SIMULATOR_ONLY,
                    provenance=Provenance("simulator", method="Battle.diagnostics"),
                    metadata=item))
            diagnostic_cursor = len(sink.events)
        frames.append(NormalizedFrame(match.elapsed_ms, frame_id, tuple(entities), tuple(towers), tuple(events),
                                      Observability.SIMULATOR_ONLY,
                                      Provenance("simulator", method="Match/Battle"), 1.0,
                                      battle_time_ms=match.elapsed_ms,
                                      metadata={"finished": match.finished, "result": match.result}))
        return current_ids, len(damage), diagnostic_cursor


@dataclass(frozen=True)
class SyncResult:
    offset_ms: float | None
    uncertainty_ms: float | None
    matched: int
    status: ResultStatus
    reason: str = ""


def synchronize_timestamps(source_times: Sequence[float], battle_times: Sequence[float],
                           *, max_residual_ms: float | None = None) -> SyncResult:
    pairs = [(float(a), float(b)) for a, b in zip(source_times, battle_times)
             if math.isfinite(float(a)) and math.isfinite(float(b))]
    if not pairs:
        return SyncResult(None, None, 0, ResultStatus.UNMEASURED, "no valid timestamp pairs")
    offsets = [battle - source for source, battle in pairs]
    estimate = statistics.median(offsets)
    residuals = [abs(value - estimate) for value in offsets]
    uncertainty = statistics.median(residuals) * 1.4826 if residuals else 0.0
    status = ResultStatus.PASS
    if max_residual_ms is not None and max(residuals, default=0) > max_residual_ms:
        status = ResultStatus.WARN
    return SyncResult(estimate, uncertainty, len(pairs), status,
                      "robust median offset; uncertainty is scaled MAD")


class TimestampSynchronizer:
    def __init__(self, *, max_residual_ms: float | None = None):
        self.max_residual_ms = max_residual_ms

    def fit(self, source_times: Sequence[float], battle_times: Sequence[float]) -> SyncResult:
        return synchronize_timestamps(source_times, battle_times, max_residual_ms=self.max_residual_ms)

    def apply(self, source_time_ms: float, result: SyncResult) -> float | None:
        return None if result.offset_ms is None else float(source_time_ms) + result.offset_ms


@dataclass(frozen=True)
class ArenaMapping:
    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    inverse: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    reprojection_error: float
    correspondences: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def forward(self, point: tuple[float, float]) -> tuple[float, float]:
        return _project(self.matrix, point)

    def inverse_point(self, point: tuple[float, float]) -> tuple[float, float]:
        return _project(self.inverse, point)

    def to_dict(self) -> dict[str, Any]:
        return {"matrix": [list(row) for row in self.matrix], "inverse": [list(row) for row in self.inverse],
                "reprojection_error": self.reprojection_error, "correspondences": self.correspondences,
                "metadata": dict(self.metadata)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ArenaMapping":
        matrix = tuple(tuple(float(x) for x in row) for row in value["matrix"])
        inverse = tuple(tuple(float(x) for x in row) for row in value["inverse"])
        if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
            raise CalibrationError("homography matrix must be 3x3")
        return cls(matrix, inverse, float(value["reprojection_error"]), int(value["correspondences"]),
                   dict(value.get("metadata", {})))


class ArenaMapper:
    @staticmethod
    def fit(image_points: Sequence[tuple[float, float]], arena_points: Sequence[tuple[float, float]],
            *, metadata: Mapping[str, Any] | None = None, max_error: float | None = None) -> ArenaMapping:
        if len(image_points) != len(arena_points) or len(image_points) < 4:
            raise CalibrationError("ArenaMapper requires at least four point correspondences")
        rows: list[list[float]] = []
        rhs: list[float] = []
        for (x, y), (u, v) in zip(image_points, arena_points):
            rows.extend([[x, y, 1, 0, 0, 0, -u * x, -u * y],
                         [0, 0, 0, x, y, 1, -v * x, -v * y]])
            rhs.extend([u, v])
        solution = _solve_least_squares(rows, rhs)
        matrix = ((solution[0], solution[1], solution[2]), (solution[3], solution[4], solution[5]),
                  (solution[6], solution[7], 1.0))
        inverse = _inverse3(matrix)
        errors = [math.hypot(*(a - b for a, b in zip(_project(matrix, image), arena)))
                  for image, arena in zip(image_points, arena_points)]
        error = math.sqrt(sum(x * x for x in errors) / len(errors))
        if max_error is not None and error > max_error:
            raise CalibrationError(f"homography reprojection error {error:.6g} exceeds {max_error}")
        return ArenaMapping(matrix, inverse, error, len(image_points), dict(metadata or {}))

    @staticmethod
    def save(path: str | Path, mapping: ArenaMapping) -> None:
        Path(path).write_text(json.dumps(mapping.to_dict(), indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> ArenaMapping:
        return ArenaMapping.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Detection:
    class_name: str
    team: int | None
    x: float
    y: float
    confidence: float = 1.0
    flying: bool | None = None
    hitpoints: float | None = None
    uncertainty: Uncertainty = field(default_factory=Uncertainty)


class Detector(Protocol):
    def detect(self, frame: Any) -> Sequence[Detection]: ...


class GroundContactEstimator(Protocol):
    def ground_contact(self, detection: Detection) -> tuple[float, float] | None: ...


class TrackerBackend(Protocol):
    def update(self, time_ms: int, detections: Sequence[Detection]) -> Sequence[TrackedEntity]: ...


class HPEstimator(Protocol):
    def estimate(self, frame: Any, entity: TrackedEntity) -> tuple[float | None, Uncertainty]: ...


class RealTraceAdapter(Protocol):
    def read(self, source: str | Path) -> NormalizedTrace: ...


@dataclass
class _Track:
    entity: TrackedEntity
    last_time_ms: int
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    missed: int = 0


class SimpleGameAwareTracker:
    def __init__(self, *, max_distance: float = 2.0, max_speed: float = 12.0, max_gap: int = 3):
        if max_distance <= 0 or max_speed < 0 or max_gap < 0:
            raise CalibrationError("invalid tracker bounds")
        self.max_distance = max_distance
        self.max_speed = max_speed
        self.max_gap = max_gap
        self._next_id = 1
        self._tracks: dict[str, _Track] = {}

    def update(self, time_ms: int, detections: Sequence[Detection]) -> tuple[TrackedEntity, ...]:
        available = set(self._tracks)
        assignments: list[tuple[float, str, Detection]] = []
        for detection in detections:
            for track_id in available:
                track = self._tracks[track_id]
                dt = max(0.001, (time_ms - track.last_time_ms) / 1000.0)
                predicted = (track.entity.x + track.velocity_x * dt, track.entity.y + track.velocity_y * dt)
                distance = math.hypot(detection.x - predicted[0], detection.y - predicted[1])
                if distance <= self.max_distance and _compatible(track.entity, detection):
                    assignments.append((distance, track_id, detection))
        assignments.sort(key=lambda x: (x[0], x[1]))
        used_tracks: set[str] = set()
        used_detections: set[int] = set()
        for _, track_id, detection in assignments:
            marker = id(detection)
            if track_id in used_tracks or marker in used_detections:
                continue
            track = self._tracks[track_id]
            dt = max(0.001, (time_ms - track.last_time_ms) / 1000.0)
            vx = max(-self.max_speed, min(self.max_speed, (detection.x - track.entity.x) / dt))
            vy = max(-self.max_speed, min(self.max_speed, (detection.y - track.entity.y) / dt))
            track.velocity_x, track.velocity_y, track.last_time_ms, track.missed = vx, vy, time_ms, 0
            track.entity = _entity_from_detection(track_id, detection, vx, vy)
            used_tracks.add(track_id)
            used_detections.add(marker)
        for track_id, track in list(self._tracks.items()):
            if track_id not in used_tracks:
                track.missed += 1
                if track.missed > self.max_gap:
                    del self._tracks[track_id]
        for index, detection in enumerate(detections):
            if id(detection) in used_detections:
                continue
            track_id = f"track-{self._next_id}"
            self._next_id += 1
            entity = _entity_from_detection(track_id, detection, 0.0, 0.0)
            self._tracks[track_id] = _Track(entity, time_ms)
        return tuple(track.entity for track in sorted(self._tracks.values(), key=lambda x: x.entity.track_id))


def _entity_from_detection(track_id: str, detection: Detection, vx: float, vy: float) -> TrackedEntity:
    return TrackedEntity(track_id, detection.class_name, detection.team, detection.x, detection.y,
                         hitpoints=detection.hitpoints, velocity_x=vx, velocity_y=vy,
                         flying=detection.flying, confidence=detection.confidence,
                         observability=Observability.MEASURED,
                         uncertainty=detection.uncertainty,
                         provenance=Provenance("detector", method="SimpleGameAwareTracker"))


def _compatible(entity: TrackedEntity, detection: Detection) -> bool:
    return entity.class_name == detection.class_name and (entity.team is None or detection.team is None or entity.team == detection.team)


@dataclass(frozen=True)
class Metric:
    name: str
    category: str
    status: ResultStatus
    measured: int
    value: float | None = None
    tolerance: float | None = None
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "category": self.category, "status": self.status.value,
                "measured": self.measured, "value": self.value, "tolerance": self.tolerance,
                "details": dict(self.details)}


def compare_traces(observed: NormalizedTrace, simulated: NormalizedTrace,
                   *, position_tolerance: float = 0.5, time_tolerance_ms: float = 250.0) -> tuple[Metric, ...]:
    metrics: list[Metric] = []
    position_errors: list[float] = []
    sim_by_time = {frame.time_ms: frame for frame in simulated.frames}
    for frame in observed.frames:
        candidate = sim_by_time.get(frame.battle_time_ms if frame.battle_time_ms is not None else frame.time_ms)
        if candidate is None:
            continue
        actual = {entity.track_id: entity for entity in candidate.entities}
        for entity in frame.entities:
            other = actual.get(entity.track_id)
            if other is not None:
                position_errors.append(math.hypot(entity.x - other.x, entity.y - other.y))
    if position_errors:
        mean = sum(position_errors) / len(position_errors)
        metrics.append(Metric("position.mean_error", "position", ResultStatus.PASS if mean <= position_tolerance else ResultStatus.FAIL,
                              len(position_errors), mean, position_tolerance))
    else:
        metrics.append(Metric("position.mean_error", "position", ResultStatus.UNMEASURED, 0, None, position_tolerance))
    observed_events = [event for frame in observed.frames for event in frame.events]
    simulated_events = [event for frame in simulated.frames for event in frame.events]
    time_errors = []
    for event in observed_events:
        candidates = [item for item in simulated_events if item.event_type == event.event_type]
        if candidates:
            time_errors.append(min(abs(item.time_ms - event.time_ms) for item in candidates))
    if time_errors:
        mean = sum(time_errors) / len(time_errors)
        metrics.append(Metric("timing.event_error", "timing", ResultStatus.PASS if mean <= time_tolerance_ms else ResultStatus.WARN,
                              len(time_errors), mean, time_tolerance_ms))
    else:
        metrics.append(Metric("timing.event_error", "timing", ResultStatus.UNMEASURED, 0, None, time_tolerance_ms))
    categories = {"targeting": "target", "combat": "damage", "pathing": "move", "collision": "collision",
                  "projectile": "projectile", "event-order": "event_order"}
    for category, token in categories.items():
        count = sum(1 for event in observed_events + simulated_events if token in event.event_type)
        metrics.append(Metric(category, category, ResultStatus.UNMEASURED if not count else ResultStatus.WARN,
                              count, None, None, {"reason": "no standalone calibrated reference" if count else "no observable events"}))
    return tuple(metrics)


@dataclass(frozen=True)
class ScenarioComparison:
    scenario_id: str
    status: ResultStatus
    metrics: tuple[Metric, ...]
    observed: int
    simulated: int

    def to_dict(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "status": self.status.value,
                "metrics": [metric.to_dict() for metric in self.metrics],
                "observed_frames": self.observed, "simulated_frames": self.simulated}


def compare_scenario(scenario_id: str, observed: NormalizedTrace, simulated: NormalizedTrace) -> ScenarioComparison:
    metrics = compare_traces(observed, simulated)
    statuses = [metric.status for metric in metrics if metric.status != ResultStatus.UNMEASURED]
    status = ResultStatus.FAIL if ResultStatus.FAIL in statuses else ResultStatus.WARN if ResultStatus.WARN in statuses else ResultStatus.PASS if statuses else ResultStatus.UNMEASURED
    return ScenarioComparison(scenario_id, status, metrics, len(observed.frames), len(simulated.frames))


def report_json(result: ScenarioComparison) -> str:
    return json.dumps(result.to_dict(), indent=2, allow_nan=False) + "\n"


def report_markdown(result: ScenarioComparison) -> str:
    lines = [f"# Calibration report: `{result.scenario_id}`", "", f"Status: **{result.status.value}**", "",
             "| Metric | Category | Status | Measured | Value | Tolerance |", "|---|---|---:|---:|---:|---:|"]
    for metric in result.metrics:
        value = "" if metric.value is None else f"{metric.value:.6g}"
        tolerance = "" if metric.tolerance is None else f"{metric.tolerance:.6g}"
        lines.append(f"| {metric.name} | {metric.category} | {metric.status.value} | {metric.measured} | {value} | {tolerance} |")
    return "\n".join(lines) + "\n"


def aggregate_reports(results: Sequence[ScenarioComparison]) -> dict[str, Any]:
    statuses = [item.status for item in results]
    status = ResultStatus.FAIL if ResultStatus.FAIL in statuses else ResultStatus.WARN if ResultStatus.WARN in statuses else ResultStatus.PASS if ResultStatus.PASS in statuses else ResultStatus.UNMEASURED
    return {"status": status.value, "scenarios": [item.to_dict() for item in results],
            "counts": {value.value: statuses.count(value) for value in ResultStatus}}


@dataclass(frozen=True)
class CaptureValidation:
    status: ResultStatus
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status.value, "errors": list(self.errors), "warnings": list(self.warnings), "frames": self.frames}


def validate_capture_session(path: str | Path) -> CaptureValidation:
    root = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    try:
        session = json.loads((root / "session.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return CaptureValidation(ResultStatus.FAIL, (f"invalid session.json: {exc}",))
    total = 0
    expected_resolution = None
    for device in session.get("devices", ()): 
        index_path = root / str(device).replace(":", "_") / "frames.jsonl"
        if not index_path.exists():
            errors.append(f"missing frame index for {device}")
            continue
        previous_time = None
        previous_index = None
        seen_digests: set[str] = set()
        for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"malformed row {device}:{line_number}")
                continue
            if row.get("error"):
                errors.append(f"capture error {device}:{line_number}: {row['error']}")
                continue
            total += 1
            if "path" not in row:
                errors.append(f"missing image path {device}:{line_number}")
            elif not (root / row["path"]).exists():
                errors.append(f"missing image file {device}:{line_number}")
            timestamp = row.get("captured_at_utc", row.get("elapsed_seconds"))
            if timestamp is None:
                errors.append(f"missing timestamp {device}:{line_number}")
            if previous_time is not None and timestamp is not None and str(timestamp) <= str(previous_time):
                errors.append(f"non-monotonic timestamp {device}:{line_number}")
            previous_time = timestamp
            index = row.get("frame_index")
            if previous_index is not None and index is not None:
                if index <= previous_index:
                    errors.append(f"duplicate frame index {device}:{line_number}")
                if index > previous_index + 1:
                    warnings.append(f"frame gap {device}:{line_number}")
            previous_index = index
            digest = row.get("sha256_pixels")
            if digest and digest in seen_digests:
                warnings.append(f"duplicate frame pixels {device}:{line_number}")
            if digest:
                seen_digests.add(digest)
            resolution = (row.get("width"), row.get("height"))
            if resolution != (None, None):
                if expected_resolution is None:
                    expected_resolution = resolution
                elif resolution != expected_resolution:
                    errors.append(f"inconsistent resolution {device}:{line_number}")
    declared = session.get("duration_seconds")
    if declared is not None and session.get("started_at_utc") and session.get("stopped_at_utc"):
        # Datetimes are intentionally not parsed into a capture digest; validation only checks gross mismatch.
        if total == 0 and float(declared) > 0:
            warnings.append("duration declared but no frames captured")
    if errors:
        status = ResultStatus.FAIL
    elif warnings:
        status = ResultStatus.WARN
    else:
        status = ResultStatus.PASS
    return CaptureValidation(status, tuple(errors), tuple(warnings), total)


def _object(value: Any, name: str) -> None:
    if not isinstance(value, Mapping):
        raise CalibrationError(f"{name} must be an object")


def _required(value: Mapping[str, Any], names: Iterable[str], name: str) -> None:
    missing = [item for item in names if item not in value]
    if missing:
        raise CalibrationError(f"{name} missing required fields: {', '.join(missing)}")


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _finite(value: float, name: str) -> None:
    if not math.isfinite(value):
        raise CalibrationError(f"{name} must be finite")


def _bounded(value: float, low: float, high: float, name: str) -> None:
    _finite(value, name)
    if not low <= value <= high:
        raise CalibrationError(f"{name} must be between {low} and {high}")


def _solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [row[:] + [vector[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise CalibrationError("degenerate homography correspondences")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [x / divisor for x in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[column])]
    return [augmented[i][-1] for i in range(n)]


def _solve_least_squares(rows: list[list[float]], rhs: list[float]) -> list[float]:
    transpose = list(zip(*rows))
    normal = [[sum(a * b for a, b in zip(transpose[i], transpose[j])) for j in range(len(transpose))]
              for i in range(len(transpose))]
    target = [sum(a * b for a, b in zip(transpose[i], rhs)) for i in range(len(transpose))]
    return _solve_linear(normal, target)


def _inverse3(matrix: tuple[tuple[float, float, float], ...]) -> tuple[tuple[float, float, float], ...]:
    a, b, c = matrix[0]
    d, e, f = matrix[1]
    g, h, i = matrix[2]
    determinant = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(determinant) < 1e-12:
        raise CalibrationError("singular homography")
    return tuple(tuple(x / determinant for x in row) for row in (
        (e * i - f * h, c * h - b * i, b * f - c * e),
        (f * g - d * i, a * i - c * g, c * d - a * f),
        (d * h - e * g, b * g - a * h, a * e - b * d)))


def _project(matrix: tuple[tuple[float, float, float], ...], point: tuple[float, float]) -> tuple[float, float]:
    x, y = point
    denominator = matrix[2][0] * x + matrix[2][1] * y + matrix[2][2]
    if abs(denominator) < 1e-12:
        raise CalibrationError("homography projects to infinity")
    return ((matrix[0][0] * x + matrix[0][1] * y + matrix[0][2]) / denominator,
            (matrix[1][0] * x + matrix[1][1] * y + matrix[1][2]) / denominator)
