# HastyCR Overnight Work Queue

Updated: 2026-08-23
Sprint state: COMPLETE
Calibration readiness: NOT_READY

States: TODO, IN_PROGRESS, BLOCKED, DONE, DEFERRED.

## Completed

- DONE Established baseline commit, dirty-state inventory, data hash, full test result, benchmark, deterministic fingerprint, and readiness blockers.
- DONE Added `_references/` ignore rules and preserved pre-existing dirty files.
- DONE Inspected and licensed ten pinned external references using clean-room evidence only.
- DONE Retrieved and hashed the StatsRoyale snapshot; documented provenance uncertainty.
- DONE Statically inventoried four APKs without executing APK, DEX, or native payloads.
- DONE Built normalized schema-v2 traces, replay compatibility, deterministic digests, scenario validation, simulator adapter, timestamp synchronization, arena mapping, tracker interfaces, metrics, reporting, capture validation, and fidelity CLI.
- DONE Generated 70 valid scenarios across eleven categories, with 56 train and 14 held-out validation scenarios.
- DONE Added mechanics/shared-physics registries, category readiness gates, recording campaign, and prioritized backlog.
- DONE Added deterministic synthetic corruption/recovery fixtures and CI regression coverage.
- DONE Added opt-in simulator diagnostics and event-order/physics regression tests while preserving diagnostic-off behavior.
- DONE Ran full integration, CLI, JSON, deterministic digest, fixture hash, compilation, diff, and performance validation.
- DONE Produced final dashboard and reproducibility checkpoints in `reports/OVERNIGHT_FIDELITY_FINAL.md`.

## Validation Checkpoint

- Full suite: `1445 passed, 1 skipped, 2 xfailed in 394.41s`.
- Focused calibration: `21 passed in 3.22s`; focused diagnostics/regressions: `104 passed in 11.46s`.
- Catalog: 70 scenarios, 11 categories, 56 train, 14 validation, zero errors.
- Repeated smoke digest: `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`.
- Checked-in normalized fixture digest: `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`.
- Benchmark: 20 matches in 17.1s, 1.2 matches/s, 5,093 ticks/s.
- JSON parseability, fixture manifest, `py_compile`, and `git diff --check`: PASS.

## Blocked on Evidence

- BLOCKED Readiness promotion: no measured real-game traces exist; all category gates remain unmet.
- BLOCKED Parameter fitting and automatic promotion: requires measured train and held-out validation evidence.
- BLOCKED Calibrated sweep and pull-map generation: requires observed references and bounded objectives.
- BLOCKED Scalar accuracy claim: prohibited by the evidence model and intentionally not implemented.

## Deferred

- DEFERRED Uniform detailed diagnostics for every specialized projectile and forced-motion subsystem; add only when measured scenarios require them.
- DEFERRED Snapshot/export/restore and broader randomized property testing.
- DEFERRED Gymnasium/vector/PPO interface work until calibration readiness is healthy.
- DEFERRED Checkpoint commits. No commit was requested, and pre-existing dirty changes must remain separable.

## Next Evidence Work

1. Record arena anchors/time base from both seats.
2. Execute Hog/Giant/Balloon building-pull grids.
3. Capture targeting, combat timing, collisions, knockback, projectile, spawning, and special-mechanics controls.
4. Validate manifests, reserve held-out sessions, and attach evidence IDs.
5. Re-evaluate each category independently; retain `NOT_READY` until every gate is met.
