"""Safe, deterministic differential simulation contracts and runners."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import (
    CalibrationError,
    NormalizedTrace,
    Provenance,
    ResultStatus,
    Scenario,
    ScenarioAction,
    SimTraceAdapter,
    canonical_json,
    load_scenario,
    read_trace,
    trace_digest,
    write_trace,
)

DIFFERENTIAL_SCHEMA_VERSION = 1


class AdapterStatus(str, Enum):
    READY = "READY"
    UNAVAILABLE = "UNAVAILABLE"
    UNMEASURED = "UNMEASURED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class Capability:
    name: str
    required: bool = False
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "required": self.required, "rationale": self.rationale}

    @classmethod
    def from_value(cls, value: Any) -> "Capability":
        if isinstance(value, str):
            return cls(value)
        if not isinstance(value, Mapping) or not value.get("name"):
            raise CalibrationError("capability must be a name or object with name")
        return cls(str(value["name"]), bool(value.get("required", False)), str(value.get("rationale", "")))


@dataclass(frozen=True)
class UnsupportedState:
    capability: str
    status: AdapterStatus
    reason: str
    action: str = "fail-closed"

    def to_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "status": self.status.value,
                "reason": self.reason, "action": self.action}


@dataclass(frozen=True)
class DifferentialScenario:
    scenario: Scenario
    capabilities: tuple[Capability, ...] = ()
    sampling: Mapping[str, Any] = field(default_factory=dict)
    provenance: Provenance = field(default_factory=Provenance)
    real_measurements: int = 0
    unsupported_states: tuple[UnsupportedState, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = DIFFERENTIAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != DIFFERENTIAL_SCHEMA_VERSION:
            raise CalibrationError(f"unsupported differential scenario schema {self.schema_version}")
        if self.real_measurements != 0:
            raise CalibrationError("differential fixtures cannot claim real measurements")
        errors = self.scenario.validate()
        if errors:
            raise CalibrationError("invalid differential scenario: " + "; ".join(errors))
        sampling = dict(self.sampling)
        dt_ms = int(sampling.get("dt_ms", self.scenario.dt_ms))
        if dt_ms != self.scenario.dt_ms:
            raise CalibrationError("sampling.dt_ms must match scenario.dt_ms")
        if dt_ms <= 0:
            raise CalibrationError("sampling.dt_ms must be positive")

    @property
    def scenario_id(self) -> str:
        return self.scenario.scenario_id

    def to_dict(self) -> dict[str, Any]:
        scenario = _scenario_to_dict(self.scenario)
        return {
            "schema_version": self.schema_version,
            "scenario": scenario,
            "sampling": {
                "dt_ms": self.scenario.dt_ms,
                "include_initial": True,
                "include_final": True,
                "observation_windows": [list(item) for item in self.scenario.observation_windows],
                **dict(self.sampling),
            },
            "capabilities": [item.to_dict() for item in self.capabilities],
            "provenance": self.provenance.to_dict(),
            "real_measurements": self.real_measurements,
            "unsupported_states": [item.to_dict() for item in self.unsupported_states],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DifferentialScenario":
        if not isinstance(value, Mapping):
            raise CalibrationError("differential scenario must be an object")
        version = int(value.get("schema_version", DIFFERENTIAL_SCHEMA_VERSION))
        if version != DIFFERENTIAL_SCHEMA_VERSION:
            raise CalibrationError(f"unsupported differential scenario schema {version}")
        scenario_value = value.get("scenario", value)
        scenario = Scenario.from_dict(scenario_value)
        capabilities = tuple(Capability.from_value(item) for item in value.get("capabilities", ()))
        sampling = value.get("sampling", {})
        if not isinstance(sampling, Mapping):
            raise CalibrationError("sampling must be an object")
        unsupported = tuple(_unsupported_from_dict(item) for item in value.get("unsupported_states", ()))
        return cls(scenario, capabilities, dict(sampling),
                   Provenance.from_dict(value.get("provenance")),
                   int(value.get("real_measurements", 0)), unsupported,
                   dict(value.get("metadata", {})), version)


def load_differential_scenario(path: str | Path) -> DifferentialScenario:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"invalid differential scenario JSON: {path}") from exc
    return DifferentialScenario.from_dict(value)


def write_differential_scenario(path: str | Path, scenario: DifferentialScenario) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scenario.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class AdapterResult:
    adapter: str
    status: AdapterStatus
    capabilities: tuple[str, ...] = ()
    unsupported_states: tuple[UnsupportedState, ...] = ()
    trace: NormalizedTrace | None = None
    diagnostics: tuple[str, ...] = ()
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self, *, include_trace: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "adapter": self.adapter,
            "status": self.status.value,
            "capabilities": list(self.capabilities),
            "unsupported_states": [item.to_dict() for item in self.unsupported_states],
            "diagnostics": list(self.diagnostics),
            "provenance": self.provenance.to_dict(),
        }
        if self.trace is not None:
            value["frames"] = len(self.trace.frames)
            value["trace_digest"] = trace_digest(self.trace)
            if include_trace:
                value["trace"] = self.trace.to_dict()
        return value


class DifferentialAdapter:
    name = "adapter"
    capabilities: tuple[str, ...] = ()

    def run(self, scenario: DifferentialScenario) -> AdapterResult:
        raise NotImplementedError

    def _unsupported(self, scenario: DifferentialScenario, reason: str) -> tuple[UnsupportedState, ...]:
        return tuple(UnsupportedState(item.name, AdapterStatus.UNMEASURED, reason)
                     for item in scenario.capabilities if item.name not in self.capabilities)

    def _required_missing(self, scenario: DifferentialScenario) -> tuple[Capability, ...]:
        return tuple(item for item in scenario.capabilities if item.required and item.name not in self.capabilities)


class HastyCRDifferentialAdapter(DifferentialAdapter):
    name = "hastycr"
    capabilities = (
        "normalized_trace", "deterministic_seed", "fixed_tick_sampling", "deploy",
        "spell", "building", "ability", "spawn_events", "damage_events", "simulator_only",
    )

    def __init__(self, *, level: int = 11, trace_diagnostics: bool = False):
        self.level = level
        self.trace_diagnostics = trace_diagnostics

    def run(self, scenario: DifferentialScenario) -> AdapterResult:
        missing = self._required_missing(scenario)
        if missing:
            states = tuple(UnsupportedState(item.name, AdapterStatus.UNMEASURED,
                                            "HastyCR adapter does not implement required capability")
                           for item in missing)
            return AdapterResult(self.name, AdapterStatus.UNMEASURED, self.capabilities, states,
                                 diagnostics=("required capability unavailable",),
                                 provenance=Provenance("simulator", method="HastyCRDifferentialAdapter"))
        unsupported = self._unsupported(scenario, "HastyCR adapter does not expose this requested capability")
        try:
            trace = SimTraceAdapter(level=self.level, trace_diagnostics=self.trace_diagnostics).run(scenario.scenario)
        except (CalibrationError, ImportError, KeyError, OSError) as exc:
            return AdapterResult(self.name, AdapterStatus.FAILED, self.capabilities, unsupported,
                                 diagnostics=(str(exc),),
                                 provenance=Provenance("simulator", method="HastyCRDifferentialAdapter"))
        return AdapterResult(self.name, AdapterStatus.READY, self.capabilities, unsupported, trace,
                             provenance=Provenance("simulator", method="HastyCRDifferentialAdapter",
                                                   details={"real_measurements": 0}))


class UnavailableExternalAdapter(DifferentialAdapter):
    """Descriptor for an external engine; never builds, imports, or starts it."""

    def __init__(self, name: str, capabilities: Sequence[str], requirements: Sequence[str]):
        self.name = name
        self.capabilities = tuple(capabilities)
        self.requirements = tuple(requirements)

    def run(self, scenario: DifferentialScenario) -> AdapterResult:
        requested = tuple(UnsupportedState(item.name, AdapterStatus.UNAVAILABLE,
                                            "external execution is disabled; no bridge or extension was started")
                          for item in scenario.capabilities)
        reason = "; ".join(self.requirements)
        return AdapterResult(self.name, AdapterStatus.UNAVAILABLE, self.capabilities, requested,
                             diagnostics=("fail-closed external adapter", reason),
                             provenance=Provenance("external-simulator", method="descriptor-only",
                                                   details={"execution": "not-started", "real_measurements": 0}))


class CRForgeAdapter(UnavailableExternalAdapter):
    def __init__(self):
        super().__init__("crforge", ("normalized_trace", "deterministic_seed", "deploy"),
                         ("Java 17 required", "Gradle/JPype bridge required", "bridge startup is not automatic"))


class ClashRoyaleSuiteAdapter(UnavailableExternalAdapter):
    def __init__(self):
        super().__init__("clash-royale-suite", ("normalized_trace", "deterministic_seed", "deploy", "spell", "building"),
                         ("maturin-built cr_engine extension required", "suite data files required", "extension execution is not automatic"))


def adapter_by_name(name: str, *, level: int = 11, trace_diagnostics: bool = False) -> DifferentialAdapter:
    normalized = name.lower().replace("_", "-")
    if normalized in {"hastycr", "hasty-cr"}:
        return HastyCRDifferentialAdapter(level=level, trace_diagnostics=trace_diagnostics)
    if normalized == "crforge":
        return CRForgeAdapter()
    if normalized in {"clash-royale-suite", "suite", "cr-suite"}:
        return ClashRoyaleSuiteAdapter()
    raise CalibrationError(f"unknown differential adapter: {name}")


@dataclass(frozen=True)
class Divergence:
    category: str
    time_ms: int | None
    left: Any
    right: Any
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"category": self.category, "time_ms": self.time_ms, "left": self.left,
                "right": self.right, "detail": self.detail}


@dataclass(frozen=True)
class PairwiseComparison:
    scenario_id: str
    left_adapter: str
    right_adapter: str
    status: ResultStatus
    comparable: bool
    first_divergence: Divergence | None
    category_counts: Mapping[str, int]
    compared_frames: int
    diagnostics: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "left_adapter": self.left_adapter,
                "right_adapter": self.right_adapter, "status": self.status.value,
                "comparable": self.comparable,
                "first_divergence": None if self.first_divergence is None else self.first_divergence.to_dict(),
                "category_counts": dict(self.category_counts), "compared_frames": self.compared_frames,
                "diagnostics": list(self.diagnostics),
                "note": "Agreement is not live-ground-truth accuracy; no scalar accuracy is computed."}


def compare_adapter_results(scenario_id: str, left: AdapterResult, right: AdapterResult) -> PairwiseComparison:
    if left.status != AdapterStatus.READY or right.status != AdapterStatus.READY or left.trace is None or right.trace is None:
        return PairwiseComparison(scenario_id, left.adapter, right.adapter, ResultStatus.UNMEASURED, False, None, {}, 0,
                                  (f"left={left.status.value}", f"right={right.status.value}"))
    return compare_traces_differential(scenario_id, left.adapter, left.trace, right.adapter, right.trace)


def compare_traces_differential(scenario_id: str, left_name: str, left: NormalizedTrace,
                                right_name: str, right: NormalizedTrace) -> PairwiseComparison:
    right_by_time = {frame.time_ms: frame for frame in right.frames}
    counts: dict[str, int] = {}
    first: Divergence | None = None
    compared = 0

    def record(category: str, time_ms: int | None, left_value: Any, right_value: Any, detail: str) -> None:
        nonlocal first
        counts[category] = counts.get(category, 0) + 1
        candidate = Divergence(category, time_ms, left_value, right_value, detail)
        if first is None or (candidate.time_ms is not None and first.time_ms is not None and candidate.time_ms < first.time_ms):
            first = candidate

    for left_frame in left.frames:
        right_frame = right_by_time.get(left_frame.time_ms)
        if right_frame is None:
            record("sampling", left_frame.time_ms, left_frame.frame_id, None, "right trace lacks timestamp")
            continue
        compared += 1
        left_entities = {item.track_id: item for item in left_frame.entities}
        right_entities = {item.track_id: item for item in right_frame.entities}
        for track_id in sorted(set(left_entities) | set(right_entities)):
            left_entity = left_entities.get(track_id)
            right_entity = right_entities.get(track_id)
            if left_entity is None or right_entity is None:
                record("spawn", left_frame.time_ms, _entity_summary(left_entity), _entity_summary(right_entity),
                       f"entity {track_id} present in only one trace")
                continue
            if (left_entity.class_name, left_entity.team) != (right_entity.class_name, right_entity.team):
                record("identity", left_frame.time_ms, _entity_summary(left_entity), _entity_summary(right_entity),
                       f"entity {track_id} identity differs")
            distance = ((left_entity.x - right_entity.x) ** 2 + (left_entity.y - right_entity.y) ** 2) ** 0.5
            if distance > 1e-9:
                record("pathing", left_frame.time_ms, [left_entity.x, left_entity.y], [right_entity.x, right_entity.y],
                       f"entity {track_id} position differs by {distance:.6g}")
            if left_entity.hitpoints != right_entity.hitpoints:
                record("combat", left_frame.time_ms, left_entity.hitpoints, right_entity.hitpoints,
                       f"entity {track_id} hitpoints differ")
        left_events = [_event_signature(item) for item in left_frame.events]
        right_events = [_event_signature(item) for item in right_frame.events]
        if left_events != right_events:
            category = "event-order" if sorted(left_events) == sorted(right_events) else "events"
            record(category, left_frame.time_ms, left_events, right_events, "frame event sequence differs")

    if not compared:
        return PairwiseComparison(scenario_id, left_name, right_name, ResultStatus.UNMEASURED, False, first, counts, 0,
                                  ("no common frame timestamps",))
    status = ResultStatus.WARN if counts else ResultStatus.PASS
    return PairwiseComparison(scenario_id, left_name, right_name, status, True, first, dict(sorted(counts.items())), compared)


def generate_shared_scenarios() -> tuple[DifferentialScenario, ...]:
    common = {
        "capabilities": [
            {"name": "normalized_trace", "required": True},
            {"name": "deterministic_seed", "required": True},
            {"name": "fixed_tick_sampling", "required": True},
            {"name": "deploy", "required": True},
            {"name": "damage_events"},
        ],
        "provenance": {"source": "generated_synthetic_catalog", "method": "bounded differential fixture",
                       "details": {"real_measurements": 0, "claim_class": "SYNTHETIC_ONLY"}},
        "real_measurements": 0,
    }
    definitions = (
        ("diff_knight_musketeer", 101, "arena", ("knight", "musketeer"), (("knight", "musketeer"), ("knight", "musketeer")),
         ((0, "deploy", 1, "knight", 9.0, 22.0), (150, "deploy", -1, "musketeer", 9.0, 9.0))),
        ("diff_hog_cannon", 102, "targeting", ("hog_rider", "cannon"), (("hog_rider", "cannon"), ("hog_rider", "cannon")),
         ((0, "deploy", 1, "hog_rider", 9.0, 22.0), (250, "building", -1, "cannon", 9.0, 9.0))),
        ("diff_fireball", 103, "projectile", ("fireball", "knight"), (("fireball", "knight"), ("fireball", "knight")),
         ((0, "deploy", -1, "knight", 9.0, 9.0), (300, "spell", 1, "fireball", 9.0, 14.0))),
    )
    result = []
    for scenario_id, seed, category, tags, decks, actions in definitions:
        scenario = Scenario(scenario_id, 750, 50, seed, decks,
                            tuple(ScenarioAction(time, action, side, card, x, y) for time, action, side, card, x, y in actions),
                            ((0, 750),), (), tags, category, "train", (), {})
        result.append(DifferentialScenario(scenario, tuple(Capability.from_value(item) for item in common["capabilities"]),
                                           {"include_initial": True, "include_final": True},
                                           Provenance.from_dict(common["provenance"]), 0, (), {"fixture": True}))
    return tuple(result)


def run_differential_suite(scenarios: Sequence[DifferentialScenario], adapter_names: Sequence[str], *, level: int = 11,
                           trace_diagnostics: bool = False) -> dict[str, Any]:
    results: list[AdapterResult] = []
    comparisons: list[PairwiseComparison] = []
    for scenario in scenarios:
        scenario_results = [adapter_by_name(name, level=level, trace_diagnostics=trace_diagnostics).run(scenario)
                            for name in adapter_names]
        results.extend(scenario_results)
        for index, left in enumerate(scenario_results):
            for right in scenario_results[index + 1:]:
                comparisons.append(compare_adapter_results(scenario.scenario_id, left, right))
    return {
        "schema_version": DIFFERENTIAL_SCHEMA_VERSION,
        "status": "WARN" if any(item.status == ResultStatus.WARN for item in comparisons) else "UNMEASURED",
        "scenarios": [item.scenario_id for item in scenarios],
        "adapters": list(adapter_names),
        "adapter_results": [item.to_dict() for item in results],
        "comparisons": [item.to_dict() for item in comparisons],
        "real_measurements": 0,
        "claim_class": "SYNTHETIC_ONLY",
        "note": "External adapters are descriptor-only and never build, import, or start simulator runtimes.",
    }


def _scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    return {
        "scenario_id": scenario.scenario_id, "duration_ms": scenario.duration_ms, "dt_ms": scenario.dt_ms,
        "seed": scenario.seed, "decks": [list(scenario.decks[0]), list(scenario.decks[1])],
        "actions": [
            {"time_ms": item.time_ms, "action": item.action, "side": item.side, "card": item.card,
             "position": None if item.x is None or item.y is None else [item.x, item.y],
             "uid": item.uid, "actor_id": item.actor_id, "metadata": dict(item.metadata)}
            for item in scenario.actions
        ],
        "observation_windows": [list(item) for item in scenario.observation_windows],
        "measures": [{"name": item.name, "category": item.category, "tolerance": item.tolerance,
                      "evidence_ids": list(item.evidence_ids)} for item in scenario.measures],
        "tags": list(scenario.tags), "category": scenario.category, "split": scenario.split,
        "evidence_ids": list(scenario.evidence_ids), "metadata": dict(scenario.metadata),
    }


def _unsupported_from_dict(value: Any) -> UnsupportedState:
    if not isinstance(value, Mapping) or not value.get("capability"):
        raise CalibrationError("unsupported state must contain capability")
    try:
        status = AdapterStatus(str(value.get("status", AdapterStatus.UNMEASURED.value)))
    except ValueError as exc:
        raise CalibrationError("invalid unsupported state status") from exc
    return UnsupportedState(str(value["capability"]), status, str(value.get("reason", "")), str(value.get("action", "fail-closed")))


def _entity_summary(entity: Any) -> Any:
    if entity is None:
        return None
    return {"track_id": entity.track_id, "class_name": entity.class_name, "team": entity.team,
            "x": entity.x, "y": entity.y, "hitpoints": entity.hitpoints}


def _event_signature(event: Any) -> tuple[Any, ...]:
    return (event.event_type, event.actor_id, event.target_id, event.actor_class, event.target_class,
            event.team, event.x, event.y, event.value)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fixture = subparsers.add_parser("fixture", help="write bounded deterministic shared scenarios")
    fixture.add_argument("--output-dir", type=Path, required=True)
    validate = subparsers.add_parser("validate", help="validate one differential scenario")
    validate.add_argument("scenario", type=Path)
    run = subparsers.add_parser("run", help="run one scenario through a safe adapter")
    run.add_argument("scenario", type=Path)
    run.add_argument("--adapter", choices=("hastycr", "crforge", "clash-royale-suite"), required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--level", type=int, default=11)
    run.add_argument("--diagnostics", action="store_true")
    suite = subparsers.add_parser("suite", help="run shared scenarios and pairwise comparisons")
    suite.add_argument("--scenario-dir", type=Path)
    suite.add_argument("--output", type=Path, required=True)
    suite.add_argument("--adapters", nargs="+", default=["hastycr", "crforge", "clash-royale-suite"])
    suite.add_argument("--level", type=int, default=11)
    suite.add_argument("--diagnostics", action="store_true")
    compare = subparsers.add_parser("compare", help="compare two normalized traces")
    compare.add_argument("scenario_id")
    compare.add_argument("left", type=Path)
    compare.add_argument("right", type=Path)
    compare.add_argument("--left-adapter", default="left")
    compare.add_argument("--right-adapter", default="right")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "fixture":
            args.output_dir.mkdir(parents=True, exist_ok=True)
            scenarios = generate_shared_scenarios()
            for scenario in scenarios:
                write_differential_scenario(args.output_dir / f"{scenario.scenario_id}.json", scenario)
            digest = __import__("hashlib").sha256(canonical_json([item.to_dict() for item in scenarios]).encode()).hexdigest()
            print(json.dumps({"status": "PASS", "scenarios": len(scenarios), "digest": digest,
                              "real_measurements": 0, "output_dir": str(args.output_dir)}, indent=2))
            return 0
        scenario = load_differential_scenario(args.scenario) if args.command in {"validate", "run"} else None
        if args.command == "validate":
            print(json.dumps({"status": "PASS", "scenario_id": scenario.scenario_id,
                              "actions": len(scenario.scenario.actions), "schema_version": scenario.schema_version}, indent=2))
            return 0
        if args.command == "run":
            result = adapter_by_name(args.adapter, level=args.level, trace_diagnostics=args.diagnostics).run(scenario)
            if result.trace is not None:
                write_trace(args.output, result.trace)
            args.output.with_suffix(args.output.suffix + ".result.json").write_text(
                json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
            print(json.dumps(result.to_dict(), indent=2))
            return 0 if result.status == AdapterStatus.READY else 2
        if args.command == "suite":
            if args.scenario_dir:
                scenarios = tuple(load_differential_scenario(path) for path in sorted(args.scenario_dir.glob("*.json")))
            else:
                scenarios = generate_shared_scenarios()
            payload = run_differential_suite(scenarios, args.adapters, level=args.level, trace_diagnostics=args.diagnostics)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(payload, indent=2))
            return 0
        if args.command == "compare":
            result = compare_traces_differential(args.scenario_id, args.left_adapter, read_trace(args.left),
                                                 args.right_adapter, read_trace(args.right))
            print(json.dumps(result.to_dict(), indent=2))
            return 0
    except (CalibrationError, OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}))
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
