# HastyCR Overnight Fidelity Sprint — Final Report

Date: 2026-08-23
Git HEAD: `1dc9e6dbbc97bf3f2c04ff8b9045dfa66ee7577`
Sprint status: COMPLETE
Calibration readiness: **NOT_READY**

## Outcome

The sprint established a clean-room, evidence-aware calibration workflow without claiming unmeasured accuracy. It added normalized schema-v2 traces, deterministic digests, scenario/catalog tooling, synthetic CI fixtures, opt-in simulator diagnostics, static APK/reference reports, category-gated readiness rules, and a practical recording campaign.

No APK or native payload was executed. No external simulator code was copied. No calibration constants or mechanics were promoted from reference consensus or synthetic traces. No commit was created.

## Delivered

- Clean-room research for ten pinned repositories with license/provenance records and explicit fact/claim/inference separation.
- Static ZIP/DEX/resource/native inventory for four APKs; raw output remains ignored under `_references/apk_analysis/` and tracked summaries live under `research/apk_analysis/` and `reports/apks/`.
- Versioned normalized calibration package in `tools/calibration/` and CLI in `scripts/fidelity.py`.
- Seventy valid scenarios across eleven categories: 56 train and 14 validation.
- Deterministic simulator/synthetic fixtures with checked SHA-256 manifest and corruption recovery tests.
- Opt-in `DiagnosticSink` for tick phases, targeting, attacks, movement, collisions, projectile lifecycle, damage, death, spawn, and cleanup.
- Recording campaign, backlog, mechanics registry, shared-physics registry, and category-specific readiness gates.

## Validation

- Full suite: `1445 passed, 1 skipped, 2 xfailed in 394.41s`.
- Focused calibration suite: `21 passed in 3.22s`.
- Earlier focused diagnostics/regression suite: `104 passed in 11.46s`.
- Catalog: 70 scenarios, 11 categories, 56 train, 14 validation, zero validation errors; every deck identifier resolves against HastyCR game data.
- CLI smoke: list, scenario validation, simulation, trace validation, inspection, identity comparison, and aggregation completed successfully.
- JSON parseability: 81 calibration/research JSON or JSONL files parsed successfully.
- Python compilation and `git diff --check`: PASS.
- Repeated normalized smoke trace digest: `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`.
- Checked-in normalized simulator fixture digest: `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`.
- All six fixture file hashes match `calibration/fixtures/fixture_digests.json`.

## Performance

| Measurement | Baseline | Final | Change |
|---|---:|---:|---:|
| 20-match runtime | 18.4 s | 17.1 s | -7.1% |
| Matches/s | 1.1 | 1.2 | +9.1% |
| Ticks/s | 4,742 | 5,093 | +7.4% |

Both benchmark runs produced 5W/15L/0D and crowns 6-17. The sample is a throughput check, not strategy evidence. Timing variance and concurrent system load prevent treating the percentage changes as a simulator optimization claim.

Diagnostics remain opt-in. A 9-run small probe measured disabled `0.025345s` versus enabled `0.025113s` (-0.91%, noise) for 2,712 events. A 5-run larger probe measured disabled `1.064405s` versus enabled `1.687068s` (+58.50%) for 161,040 retained events. Detailed tracing is therefore suitable for bounded calibration probes, not ordinary RL rollouts.

## Readiness Decision

Status remains **NOT_READY**. This is intentional and evidence-driven.

- No measured real-game trace campaign has been completed.
- Every category in `calibration/readiness_gates.json` lacks its required measured train and held-out validation evidence.
- Checked-in traces are synthetic or simulator-only and cannot satisfy promotion gates.
- Reference simulators disagree on same-tick ordering and cannot serve as ground truth.
- Detailed diagnostics do not yet cover every specialized projectile and forced-motion implementation.
- Sweep and pull-map CLI commands remain bounded `UNMEASURED` placeholders until calibrated search spaces and observed pull references exist.
- No global scalar accuracy score is computed or claimed.

## Reproducibility Checkpoints

- Baseline data aggregate SHA-256: `0e6d28a9a3dbf6be88b1fdff7bbf28f8bcfcf32c09faf00be685238a7f7693f7`.
- Baseline ad-hoc deterministic fingerprint: `8f5406326338cef63f1952ad0a62ba55c3d251438021446e99502ecff20d5281`.
- Catalog SHA-256: `08247519ae3f99c834c9383be7012455760038245087110c00421fd2fda001fa`.
- Readiness gates SHA-256: `f4f7592d2e8d19a53624576fbb46c75ee982d7bed23e699b07ba70826db46918`.
- Mechanics registry SHA-256: `3ba0e86e8edcc461bf415f7bb45934bd90e40672e789969060538cd31eea5c1c`.
- Shared-physics registry SHA-256: `bc53017ec96b301a4c36990cb75e28161af1f75b5fe51efcb60e87e439b8dd4d`.
- StatsRoyale snapshot SHA-256: `d67cebd4bbf9624a75e3c4a1fdb3a1284a285bf5c1620e3d84fab917f34139d0`.

## Next Actions

1. Execute `docs/CALIBRATION_RECORDING_CAMPAIGN.md`, beginning with arena anchors/time base and building-pull maps.
2. Validate every capture manifest before comparison and reserve held-out recordings before tuning.
3. Fill category evidence IDs in the registries and readiness gates; promote only measured, reproducible results.
4. Extend diagnostics for specialized projectile and forced-motion systems as each measured scenario requires.
5. Implement pull-map/sweep search only after observed references define bounds and objective functions.

Pre-existing dirty files were preserved. Sprint-owned files were not committed because no commit was requested.