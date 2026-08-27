# Sprint 2 Differential Simulation Framework

Date: 2026-08-24
Status: **IMPLEMENTED / UNMEASURED**

## Scope

Task #7 adds a dependency-light differential framework around the existing normalized trace schema-v2. The common scenario schema is version 1 and carries:

- deterministic seed, fixed tick duration, duration, ordered actions, decks, and observation windows;
- declared capabilities and required capabilities;
- adapter provenance, explicit unsupported/unavailable states, and fail-closed diagnostics;
- `real_measurements: 0` and `SYNTHETIC_ONLY` provenance for generated fixtures.

The implementation lives in `tools/calibration/differential.py`, is exported by `tools/calibration`, and is available through `scripts/fidelity.py` as `differential-fixture`, `differential-validate`, `differential-run`, and `differential-suite`.

## Executable result

The bounded suite generated three deterministic shared scenarios:

| Scenario | Category | Duration | Tick | Actions |
|---|---|---:|---:|---:|
| `diff_fireball` | projectile | 750 ms | 50 ms | 2 |
| `diff_hog_cannon` | targeting | 750 ms | 50 ms | 2 |
| `diff_knight_musketeer` | arena | 750 ms | 50 ms | 2 |

HastyCR ran all three scenarios through `SimTraceAdapter` and emitted normalized simulator-only traces with 16 frames each. The generated scenario digest is `8cebf04cfc195d9fe2f057f76ad73945d7cb6cbf69ce2b8aa8d332bbdff0cb97`.

Two complete suite generations produced the same report SHA-256:

`FF3D97EC97712306CE29238003EBDB730F4B69B4EB4448DF91235FD402B0DAC8`

The report contains nine adapter results: three HastyCR `READY` results and six external `UNAVAILABLE` results. All nine pairwise comparisons are `UNMEASURED` and non-comparable because the external runtimes were not started.

## External adapter boundary

CRForge and clash-royale-suite adapters are descriptor-only. They do not import their packages, invoke Gradle or maturin, start a bridge, load external data, or execute external payloads. They return:

- CRForge: Java 17 and Gradle/JPype bridge requirements, `UNAVAILABLE`;
- clash-royale-suite: maturin-built `cr_engine` and data-file requirements, `UNAVAILABLE`;
- explicit `fail-closed` unsupported states for requested capabilities;
- provenance stating `execution: not-started` and `real_measurements: 0`.

This preserves the safety decision from `docs/LONGRUN_DECISIONS.md`: simulator agreement is not live truth, and unavailable runtimes cannot be silently substituted with synthetic or reference results.

## Comparison semantics

When two adapters are executable, the comparator aligns exact frame timestamps and ranks the first observed divergence by time. It reports category counts for sampling, identity/spawn, pathing, combat, events, and event order. It intentionally does not compute a global accuracy scalar or majority-vote truth claim.

With the current environment, no cross-engine pair is executable, so no disagreement is promoted. HastyCR output remains `SIMULATOR_ONLY`; `real_measurements` remains zero; readiness remains `RL NOT READY`.

## Validation commands

```powershell
& ".venvs\buildabot\Scripts\python.exe" -m tools.calibration.differential fixture --output-dir calibration\differential_scenarios
& ".venvs\buildabot\Scripts\python.exe" -m tools.calibration.differential suite --scenario-dir calibration\differential_scenarios --output calibration\differential_report.json --adapters hastycr crforge clash-royale-suite
& ".venvs\buildabot\Scripts\python.exe" -m compileall -q tools\calibration src\hastycr scripts\fidelity.py
git diff --check
& ".venvs\buildabot\Scripts\python.exe" -m sim.readiness
```

The readiness command is expected to return nonzero with `RL NOT READY`; this is an intentional evidence boundary, not a framework failure.
