# HastyCR calibration core

The `tools.calibration` package is a dependency-free normalized calibration layer. It does not retune or modify the simulator. `NormalizedTrace` is schema version 2 and contains ordered frames, tracked entities, towers, events, observability (`measured`, `inferred`, `unknown`, or `simulator-only`), provenance, confidence, uncertainty, and non-volatile metadata.

## APIs

- `read_trace` / `write_trace`: strict JSON and JSONL I/O.
- `trace_digest`: canonical SHA-256 digest with sorted keys, normalized floats, and volatile capture/file metadata removed.
- `from_replay_frames` / `to_replay_frames`: compatibility adapter for `tools.replay_calibration` schema-v1 frames.
- `Scenario` / `load_scenario`: validated JSON scenarios with deployments, spells, buildings, ability actions, windows, measures, tags, evidence IDs, and train/validation/test split.
- `SimTraceAdapter`: deterministic controlled scenarios using public `sim.match.Match`, `Battle.living`, and `Match` action methods. Unsupported actions fail with `CalibrationError`.
- `TimestampSynchronizer`, `ArenaMapper`, `SimpleGameAwareTracker`, detector/ground-contact/tracker/HP/real-trace protocols.
- `compare_scenario`, `report_json`, `report_markdown`, and `aggregate_reports`: explicit category metrics and status aggregation. No global accuracy scalar is produced; unavailable categories are `UNMEASURED`.
- `validate_capture_session`: validates emulator manifests and frame indexes for malformed/error rows, gaps, duplicates, resolution/timestamp/path issues, and gross duration/no-frame mismatch.
- `tools/calibration/evidence`: validates and queries the canonical versioned mechanics evidence database, emits the Markdown truth table, and can derive a disposable SQLite index. `VERIFIED_CURRENT_DATA` means the value/field is directly present in the current local data; it does not mean live behavior has been observed.
- `tools/calibration/perception`: provides versioned frame packets, capture/iterable sources, arena mapping and detector/tracker adapters, conservative event derivation, normalized trace construction, and confidence/uncertainty-weighted comparison metrics.
- `tools/calibration/annotations`: provides annotation schema v1, append-only merge/split/relabel/point/death/spawn/queue operations, deterministic replay/validation/digests, and queue state.
- `tools/calibration/differential`: provides differential scenario schema v1, safe HastyCR execution, descriptor-only external adapters, capability/unsupported states, pairwise first-divergence ranking, and deterministic suite reports. External engines are never auto-built or started.
- `tools/calibration/mechanics_characterization.py`: provides bounded deterministic simulator-only probes for targeting, pathing, collision, attack/projectile timing, same-tick phases, and death/spawn ordering. It never counts as live evidence.
- `src/hastycr.observation`: provides a non-breaking deployable `GameState` observation/noise adapter; it preserves existing `GameState` and KataCR contracts.

Mechanics evidence commands:

```powershell
python -m tools.calibration.evidence validate
python -m tools.calibration.evidence summary
python -m tools.calibration.evidence query --domain targeting
python -m tools.calibration.evidence report
python -m tools.calibration.evidence sqlite --output tmp/mechanics.sqlite
```

The canonical source is `data/fidelity/mechanics.json`; SQLite and `reports/MECHANICS_TRUTH_TABLE.md` are deterministic derived views. Historical data, private-server artifacts, synthetic scenarios, and cross-implementation agreement cannot promote a mechanic to observed truth.

## Annotation commands

```powershell
python scripts/fidelity.py annotation-init calibration/fixtures/corrupted_observed.json --output tmp/annotations.json
python scripts/fidelity.py annotation-validate tmp/annotations.json
python scripts/fidelity.py annotation-append tmp/annotations.json --kind point --payload tmp/point.json --reason "visual correction"
python scripts/fidelity.py annotation-materialize tmp/annotations.json --output tmp/annotated-trace.json
```

Annotation documents are schema v1 and use an append-only correction ledger. Materialized traces remain normalized schema v2. No annotation command promotes a synthetic or contextual source to a real measurement.

## Perception fixture

```powershell
python -m tools.calibration.generate_perception_fixture --output-dir calibration/fixtures
```

The generated manifest is synthetic plumbing evaluation only: it reports `SYNTHETIC_ONLY`, `real_measurements=0`, and no detector performance claim.


Example:

```json
{"scenario_id":"hog_probe","duration_ms":1000,"dt_ms":50,"seed":7,"decks":[["hog_rider"],["hog_rider"]],"actions":[{"time_ms":0,"action":"deploy","side":1,"card":"hog_rider","position":[9,22]}]}
```

## Differential commands

```powershell
python -m tools.calibration.differential fixture --output-dir calibration/differential_scenarios
python -m tools.calibration.differential validate calibration/differential_scenarios/diff_knight_musketeer.json
python -m tools.calibration.differential suite --scenario-dir calibration/differential_scenarios --output calibration/differential_report.json --adapters hastycr crforge clash-royale-suite
```

The same operations are available through `scripts/fidelity.py` as `differential-fixture`, `differential-validate`, `differential-run`, and `differential-suite`. HastyCR is executable; CRForge and clash-royale-suite are currently descriptor-only and return `UNAVAILABLE` without importing, building, or starting external runtimes. Shared report statuses therefore remain `UNMEASURED` and do not establish live accuracy.

## Mechanics characterization

```powershell
python scripts/fidelity.py mechanics-characterize --output reports/mechanics_characterization.json --markdown reports/SPRINT2_MECHANICS_CHARACTERIZATION.md
```

The command runs six small fixed-tick probes against `Battle` with opt-in diagnostics and contact tracing. Output is explicitly `SIMULATOR_ONLY`, reports `real_measurements=0`, and includes a deterministic SHA-256 over the generated payload. Use it to inspect current implementation behavior and to turn future live observations into targeted calibration experiments; it does not establish live truth.
