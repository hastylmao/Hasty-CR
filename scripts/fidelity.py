"""HastyCR normalized fidelity calibration CLI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.calibration import (  # noqa: E402
    AdapterStatus,
    AnnotationRecord,
    ArenaMapper,
    CalibrationError,
    SimTraceAdapter,
    aggregate_reports,
    annotation_digest,
    annotation_from_trace,
    append_operation,
    compare_scenario,
    compare_traces_weighted,
    load_differential_scenario,
    load_scenario,
    materialize_annotation,
    read_annotation,
    read_trace,
    report_json,
    report_markdown,
    trace_digest,
    validate_annotation,
    validate_capture_session,
    write_annotation,
    write_trace,
)
from tools.calibration.command_replay import (  # noqa: E402
    CommandRecorder,
    ReplayError,
    create_initial_state,
    demo_replay,
    execute_replay,
    read_replay,
    state_digest,
    verify_replay,
    write_replay,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="list JSON scenarios")
    list_parser.add_argument("path", type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate a scenario, trace, or capture session")
    validate_parser.add_argument("path", type=Path)
    validate_parser.add_argument("--kind", choices=("scenario", "trace", "capture"), default="scenario")

    simulate_parser = subparsers.add_parser("simulate", help="run a deterministic simulator scenario")
    simulate_parser.add_argument("scenario", type=Path)
    simulate_parser.add_argument("--output", type=Path, required=True)
    simulate_parser.add_argument("--jsonl", action="store_true")
    simulate_parser.add_argument("--level", type=int, default=11)
    simulate_parser.add_argument("--diagnostics", action="store_true")

    compare_parser = subparsers.add_parser("compare", help="compare normalized observed and simulator traces")
    compare_parser.add_argument("observed", type=Path)
    compare_parser.add_argument("simulated", type=Path)
    compare_parser.add_argument("--scenario-id", default="comparison")
    compare_parser.add_argument("--output", type=Path)
    compare_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    compare_parser.add_argument("--weighted", action="store_true",
                                help="emit confidence/uncertainty-weighted metrics")

    report_parser = subparsers.add_parser("report", help="aggregate comparison JSON reports")
    report_parser.add_argument("inputs", nargs="+", type=Path)
    report_parser.add_argument("--output", type=Path)

    inspect_parser = subparsers.add_parser("inspect", help="inspect a normalized trace")
    inspect_parser.add_argument("trace", type=Path)

    sweep_parser = subparsers.add_parser("sweep", help="bounded placeholder for parameter sweeps")
    sweep_parser.add_argument("scenario", type=Path)

    pull_parser = subparsers.add_parser("pull-map", help="bounded placeholder for pull-map generation")
    pull_parser.add_argument("scenario", type=Path)

    map_parser = subparsers.add_parser("arena-map", help="fit a manual-point homography")
    map_parser.add_argument("points", type=Path, help="JSON object with image_points and arena_points")
    map_parser.add_argument("--output", type=Path, required=True)
    map_parser.add_argument("--max-error", type=float)

    annotation_parser = subparsers.add_parser("annotation-init", help="create an annotation document from a trace")
    annotation_parser.add_argument("trace", type=Path)
    annotation_parser.add_argument("--output", type=Path, required=True)
    annotation_parser.add_argument("--document-id")

    correction_parser = subparsers.add_parser("annotation-append", help="append one auditable annotation correction")
    correction_parser.add_argument("document", type=Path)
    correction_parser.add_argument("--kind", required=True,
                                   choices=("merge", "split", "relabel", "point", "death", "spawn", "queue"))
    correction_parser.add_argument("--payload", required=True, help="JSON object")
    correction_parser.add_argument("--author", default="manual")
    correction_parser.add_argument("--reason", default="")
    correction_parser.add_argument("--confidence", type=float, default=1.0)
    correction_parser.add_argument("--output", type=Path)

    annotation_validate = subparsers.add_parser("annotation-validate", help="validate and replay an annotation document")
    annotation_validate.add_argument("document", type=Path)

    annotation_materialize = subparsers.add_parser("annotation-materialize", help="replay annotations into a normalized trace")
    annotation_materialize.add_argument("document", type=Path)
    annotation_materialize.add_argument("--output", type=Path, required=True)

    differential_fixture = subparsers.add_parser("differential-fixture", help="write bounded shared differential scenarios")
    differential_fixture.add_argument("--output-dir", type=Path, required=True)

    differential_validate = subparsers.add_parser("differential-validate", help="validate a differential scenario")
    differential_validate.add_argument("scenario", type=Path)

    differential_run = subparsers.add_parser("differential-run", help="run a scenario through a safe differential adapter")
    differential_run.add_argument("scenario", type=Path)
    differential_run.add_argument("--adapter", choices=("hastycr", "crforge", "clash-royale-suite"), required=True)
    differential_run.add_argument("--output", type=Path, required=True)
    differential_run.add_argument("--level", type=int, default=11)
    differential_run.add_argument("--diagnostics", action="store_true")

    differential_suite = subparsers.add_parser("differential-suite", help="run shared scenarios and rank pairwise disagreements")
    differential_suite.add_argument("--scenario-dir", type=Path)
    differential_suite.add_argument("--output", type=Path, required=True)
    differential_suite.add_argument("--adapters", nargs="+", default=["hastycr", "crforge", "clash-royale-suite"])
    differential_suite.add_argument("--level", type=int, default=11)
    differential_suite.add_argument("--diagnostics", action="store_true")

    mechanics_parser = subparsers.add_parser("mechanics-characterize", help="run bounded simulator-only mechanics probes")
    mechanics_parser.add_argument("--output", type=Path, required=True)
    mechanics_parser.add_argument("--markdown", type=Path)

    record_replay = subparsers.add_parser("record-command-replay", help="record a deterministic command-only demo replay")
    record_replay.add_argument("--output", type=Path, required=True)
    record_replay.add_argument("--seed", type=int, default=7)
    record_replay.add_argument("--duration-ticks", type=int, default=60)

    verify_replay_parser = subparsers.add_parser("verify-command-replay", help="verify a command-only replay twice")
    verify_replay_parser.add_argument("replay", type=Path)
    return parser


def _emit(value: str, output: Path | None = None) -> None:
    if output is None:
        print(value, end="" if value.endswith("\n") else "\n")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(value if value.endswith("\n") else value + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "list":
            paths = [args.path] if args.path.is_file() else sorted(args.path.rglob("*.json"))
            scenarios = []
            for path in paths:
                try:
                    scenario = load_scenario(path)
                except (CalibrationError, OSError):
                    continue
                scenarios.append({"scenario_id": scenario.scenario_id, "category": scenario.category,
                                  "split": scenario.split, "path": str(path)})
            _emit(json.dumps({"status": "PASS", "scenarios": scenarios}, indent=2) + "\n")
            return 0
        if args.command == "validate":
            if args.kind == "capture":
                result = validate_capture_session(args.path).to_dict()
                _emit(json.dumps(result, indent=2) + "\n")
                return 1 if result["status"] == "FAIL" else 0
            if args.kind == "trace":
                trace = read_trace(args.path)
                _emit(json.dumps({"status": "PASS", "frames": len(trace.frames),
                                  "sha256": trace_digest(trace)}, indent=2) + "\n")
                return 0
            scenario = load_scenario(args.path)
            _emit(json.dumps({"status": "PASS", "scenario_id": scenario.scenario_id,
                              "actions": len(scenario.actions)}, indent=2) + "\n")
            return 0
        if args.command == "simulate":
            trace = SimTraceAdapter(level=args.level, trace_diagnostics=args.diagnostics).run(load_scenario(args.scenario))
            write_trace(args.output, trace, jsonl=args.jsonl)
            _emit(json.dumps({"status": "PASS", "frames": len(trace.frames),
                              "sha256": trace_digest(trace), "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "compare":
            observed = read_trace(args.observed)
            simulated = read_trace(args.simulated)
            if args.weighted:
                metrics = compare_traces_weighted(observed, simulated)
                payload = {
                    "scenario_id": args.scenario_id,
                    "status": "FAIL" if any(metric.status.value == "FAIL" for metric in metrics) else
                              "WARN" if any(metric.status.value == "WARN" for metric in metrics) else
                              "PASS" if any(metric.status.value == "PASS" for metric in metrics) else "UNMEASURED",
                    "metrics": [metric.to_dict() for metric in metrics],
                    "note": "Confidence/uncertainty-weighted metrics; no global accuracy scalar.",
                }
                _emit(json.dumps(payload, indent=2) + "\n", args.output)
                return 1 if payload["status"] == "FAIL" else 0
            result = compare_scenario(args.scenario_id, observed, simulated)
            text = report_json(result) if args.format == "json" else report_markdown(result)
            _emit(text, args.output)
            return 1 if result.status.value == "FAIL" else 0
        if args.command == "report":
            payloads = [json.loads(path.read_text(encoding="utf-8")) for path in args.inputs]
            statuses = [item.get("status", "UNMEASURED") for item in payloads]
            summary = {"status": "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else
                       "PASS" if "PASS" in statuses else "UNMEASURED", "reports": payloads,
                       "note": "No global accuracy scalar is computed."}
            _emit(json.dumps(summary, indent=2) + "\n", args.output)
            return 1 if summary["status"] == "FAIL" else 0
        if args.command == "inspect":
            trace = read_trace(args.trace)
            events = sum(len(frame.events) for frame in trace.frames)
            entities = sum(len(frame.entities) for frame in trace.frames)
            _emit(json.dumps({"status": "PASS", "trace_id": trace.trace_id,
                              "frames": len(trace.frames), "entity_observations": entities,
                              "events": events, "sha256": trace_digest(trace)}, indent=2) + "\n")
            return 0
        if args.command in {"sweep", "pull-map"}:
            scenario = load_scenario(args.scenario)
            _emit(json.dumps({"status": "UNMEASURED", "command": args.command,
                              "scenario_id": scenario.scenario_id,
                              "reason": "bounded core exposes schema validation only; no calibrated search space or pull reference was supplied"}, indent=2) + "\n")
            return 2
        if args.command == "arena-map":
            points = json.loads(args.points.read_text(encoding="utf-8"))
            mapping = ArenaMapper.fit(points["image_points"], points["arena_points"],
                                      metadata=points.get("metadata"), max_error=args.max_error)
            ArenaMapper.save(args.output, mapping)
            _emit(json.dumps({"status": "PASS", "reprojection_error": mapping.reprojection_error,
                              "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "annotation-init":
            document = annotation_from_trace(read_trace(args.trace), document_id=args.document_id)
            write_annotation(args.output, document)
            _emit(json.dumps({"status": "PASS", "revision": document.revision,
                              "sha256": annotation_digest(document), "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "annotation-append":
            document = read_annotation(args.document)
            payload_path = Path(args.payload)
            if payload_path.is_file():
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            else:
                payload = json.loads(args.payload)
            if not isinstance(payload, dict):
                raise CalibrationError("annotation payload must be a JSON object")
            updated = append_operation(document, args.kind, payload, author=args.author,
                                       reason=args.reason, confidence=args.confidence)
            output = args.output or args.document
            write_annotation(output, updated)
            _emit(json.dumps({"status": "PASS", "revision": updated.revision,
                              "sha256": annotation_digest(updated), "output": str(output)}, indent=2) + "\n")
            return 0
        if args.command == "annotation-validate":
            result = validate_annotation(read_annotation(args.document))
            _emit(json.dumps(result, indent=2) + "\n")
            return 0
        if args.command == "annotation-materialize":
            document = read_annotation(args.document)
            trace = materialize_annotation(args.output, document)
            _emit(json.dumps({"status": "PASS", "revision": document.revision,
                              "frames": len(trace.frames), "sha256": trace_digest(trace),
                              "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "differential-fixture":
            from tools.calibration.differential import generate_shared_scenarios, write_differential_scenario
            args.output_dir.mkdir(parents=True, exist_ok=True)
            scenarios = generate_shared_scenarios()
            for scenario in scenarios:
                write_differential_scenario(args.output_dir / f"{scenario.scenario_id}.json", scenario)
            _emit(json.dumps({"status": "PASS", "scenarios": len(scenarios),
                              "real_measurements": 0, "claim_class": "SYNTHETIC_ONLY",
                              "output_dir": str(args.output_dir)}, indent=2) + "\n")
            return 0
        if args.command == "differential-validate":
            scenario = load_differential_scenario(args.scenario)
            _emit(json.dumps({"status": "PASS", "scenario_id": scenario.scenario_id,
                              "schema_version": scenario.schema_version,
                              "capabilities": len(scenario.capabilities),
                              "actions": len(scenario.scenario.actions),
                              "real_measurements": scenario.real_measurements}, indent=2) + "\n")
            return 0
        if args.command == "differential-run":
            from tools.calibration.differential import adapter_by_name
            scenario = load_differential_scenario(args.scenario)
            result = adapter_by_name(args.adapter, level=args.level, trace_diagnostics=args.diagnostics).run(scenario)
            if result.trace is not None:
                write_trace(args.output, result.trace)
            result_path = args.output.with_suffix(args.output.suffix + ".result.json")
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(json.dumps(result.to_dict(), indent=2) + "\n", encoding="utf-8")
            _emit(json.dumps(result.to_dict(), indent=2) + "\n")
            return 0 if result.status == AdapterStatus.READY else 2
        if args.command == "differential-suite":
            from tools.calibration.differential import generate_shared_scenarios, run_differential_suite
            scenarios = (tuple(load_differential_scenario(path) for path in sorted(args.scenario_dir.glob("*.json")))
                         if args.scenario_dir else generate_shared_scenarios())
            payload = run_differential_suite(scenarios, args.adapters, level=args.level,
                                             trace_diagnostics=args.diagnostics)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            _emit(json.dumps(payload, indent=2) + "\n")
            return 0
        if args.command == "mechanics-characterize":
            from tools.calibration.mechanics_characterization import write_outputs
            payload = write_outputs(args.output, args.markdown)
            _emit(json.dumps({"status": payload["status"],
                              "probe_count": payload["probe_count"],
                              "real_measurements": payload["real_measurements"],
                              "sha256": payload["sha256"],
                              "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "record-command-replay":
            replay = demo_replay(args.seed, args.duration_ticks)
            write_replay(args.output, replay)
            _emit(json.dumps({"status": "PASS", "schema": "hastycr-command-replay-v1",
                              "commands": len(replay.commands), "output": str(args.output)}, indent=2) + "\n")
            return 0
        if args.command == "verify-command-replay":
            payload = verify_replay(read_replay(args.replay))
            _emit(json.dumps(payload, indent=2) + "\n")
            return 0 if payload["first_divergence"] is None else 1
    except (CalibrationError, OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
