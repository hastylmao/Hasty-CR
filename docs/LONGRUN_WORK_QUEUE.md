# HastyCR Long-Run Sprint 2 Work Queue

Updated: 2026-08-24T10:09:24+05:30
States: TODO, IN_PROGRESS, DONE, BLOCKED, DEFERRED.

## P0 — Persistent state and baseline

- DONE Read prior Sprint 1 reports, queue, backlog, recording plan, registries, research index, and continuation contract.
- DONE Create `docs/AGENT_LONGRUN_STATE.md`, this queue, `docs/LONGRUN_DECISIONS.md`, and `reports/SPRINT2_STARTING_GAPS.md`.
- DONE Independently rerun full/focused tests, determinism, catalog, readiness, benchmark, JSON/hash checks, and git status.
- DONE Record verified Sprint 2 baseline metrics and hashes in all persistent state files.

## P0 — Mechanics evidence database

- DONE Define versioned schema for mechanics, parameters, cards, sources, evidence, scenarios, implementations, disagreements, measurements, confidence, and game versions.
- DONE Seed the database from existing mechanics/shared-physics registries and research matrices.
- DONE Add deterministic query/export/report tooling and focused tests.
- DONE Generate an initial mechanics truth table without promoting historical/private/simulator consensus to verified truth.

## P0 — Historical CSV archaeology

- DONE Clone/pin `walle-d/cr-csv`; refresh refs/tags for existing `smlbiobot/cr-csv` without changing tracked project files.
- DONE Enumerate all tags/releases/commits and probable APK versions into `research/csv_history/version_inventory.csv`.
- DONE Extract longitudinal column/type/hash evolution for mechanics-relevant CSV files.
- DONE Build representative card/parameter timelines and separate balance from schema/engine changes.
- Sprint 2 Task #6 is complete: local Keschler/cr-bot was inspected at pinned HEAD `a08a414433fec990f1af4b5bc22b060aceafb2f0` without execution; its `CC-BY-NC-4.0` license is recorded as strict study-only. HastyCR now has dependency-light frame/detector/tracker/arena adapters, conservative event derivation, confidence/uncertainty-weighted comparison, annotation schema v1 with append-only correction replay and queue state, a non-breaking deployable observation/noise adapter, CLI commands, and deterministic synthetic fixtures. No accepted labeled real data was present, so no detector performance claim was made; `real_measurements=0` and readiness remains `RL NOT READY`.

## P0 — APK mechanics archaeology

- DONE Read every prior APK report and identify genuinely unexplored DEX/native/data areas.
- DONE Inspect modern trusted resource decoders and select a controlled extraction architecture; record pinned Apktool/JADX metadata and a future-only fail-closed sandbox policy without executing tools.
- DONE Build deterministic file/DEX/native/data inventory and path/multiplicity-aware similarity tooling for all four APKs; archive-bind every extraction manifest.
- DONE Triage bounded native strings/exports and local Supercell-container CSV/TOML data; do not execute APK/native payloads or external tools.
- DONE Reconstruct bounded source-labeled conceptual battle graphs where direct/static/inferred evidence supports them; omit unsupported links.
- DONE Classify application shell, DEX, native, selected data, and proprietary assets conservatively; use `UNKNOWN` absent component or official-baseline evidence.

## P0 — Differential simulation and core mechanics

- DONE Define and implement isolated common-schema adapters for HastyCR, CRForge, and clash-royale-suite; external adapters remain descriptor-only and fail closed.
- DONE Execute a bounded deterministic shared synthetic suite through the available HastyCR adapter; three scenarios emit normalized simulator-only traces and two generations reproduce the same report digest.
- DONE Produce ranked pairwise comparison records; current external engines are unavailable, so all cross-engine comparisons remain `UNMEASURED` rather than majority-vote truth claims.
- TODO Execute at least 50 meaningful normalized shared-scenario comparisons if engines run reliably.
- TODO Document HastyCR's actual targeting state machine in `docs/TARGETING_SPEC_CURRENT.md`.
- TODO Build procedural targeting decision-boundary sweeps and export CSV/heatmaps.
- TODO Implement building pull-map generation for Hog, Giant, Balloon, and supported equivalents.
- TODO Characterize collision geometry, mass, convergence, bridge congestion, insertion-order sensitivity, and same-tick events.

## P0 — Sensitivity and calibration priority

- TODO Define explicit research-only perturbation ranges for uncertain shared mechanics.
- TODO Run local scenario sensitivity sweeps and record first divergence, trajectory, targeting, damage, tower HP, duration, and result changes.
- TODO Run seat-balanced same-policy mechanics perturbation smoke evaluations.
- TODO Compute transparent mechanics importance scores with published component weights.
- TODO Regenerate the real-game campaign from measured sensitivity and information gain.

## P1 — Perception and observation parity

- DONE Clone/analyze `Keschler/cr-bot`, verify license, and compare directly with HastyCR capture/calibration tooling.
- DONE Triage useful vision references and repository-local models/datasets/videos without crawling unrelated user directories; no accepted labeled real dataset was found.
- DONE Implement frame source, arena location/mapping, detector/tracker adapters, event derivation, and normalized trace pipeline.
- DONE Implement versioned manual annotation and semi-automatic correction operations: merge, split, relabel, point correction, death, spawn, and queue state.
- DONE Propagate confidence/uncertainty through traces and weighted comparison metrics.
- DONE Add detector/tracker evaluation on synthetic plumbing only, with no performance claim.
- DONE Audit RL observability and add a non-breaking deployable observation adapter plus explicit seeded noise injection.

## P1 — Exploit hunting and debugging

- TODO Add mirror, UID/insertion-order, irrelevant deck-order, determinism, and other metamorphic checks.
- TODO Add bounded property generation and optional seeded soak tooling with reproducible failures.
- TODO Hunt target thrashing, stuck units, clipping, overlap, cooldown/elixir errors, duplicate triggers, path loops, and performance cliffs.
- TODO Implement first-divergence and deterministic battle state-diff tooling.
- TODO Add versioned trace-to-regression-fixture freezing workflow.
- TODO Investigate snapshot/export/restore; implement only with exact continuation equality.

## P1 — Profiling and safe performance

- TODO Profile full matches, target scans, collision, pathfinding, projectile resolution, and observation construction.
- TODO Report hotspots before optimizing.
- TODO Prototype deterministic spatial broad-phase or allocation reductions only where profiles justify them.
- TODO Retain optimizations only with exact deterministic trace equivalence and broad regression passes.

## P2 — Research expansion

- TODO Deepen CRForge and clash-royale-suite behavioral pseudocode from concrete implementations.
- TODO Triage current 2024-2026 repositories and web evidence; update `research/WEB_EVIDENCE_LOG.md` and `research/NEW_REFERENCES.md`.
- TODO Benchmark executable external simulators fairly with runtime/scenario/tick/tracing context.
- TODO Build qualitative simulator scorecard with evidence.
- TODO Audit fake-confidence terminology in HastyCR comments/docs and downgrade unsupported claims.

## P2 — Capture package workflow

- TODO Add `python -m tools.calibration prepare <scenario>` package generation.
- TODO Generate placement visualizer images from homography/device resolution.
- TODO Add video/manual ingest pipeline to normalized traces.
- TODO Version simulator commit, game-data hash, scenario, capture, detector, arena calibration, and measurement date in every frozen fixture.

## P3 — Deferred until evidence/core health

- DEFERRED Massive PPO training or broad model retraining.
- DEFERRED Random card-specific mechanics unrelated to shared-system evidence.
- DEFERRED Production protocol/account interaction or any anti-cheat/authentication work.
- DEFERRED Promoting constants from simulator consensus, private-server data, synthetic traces, or historical values alone.
- BLOCKED Sim-to-real readiness promotion until measured controlled live traces satisfy every category gate.
