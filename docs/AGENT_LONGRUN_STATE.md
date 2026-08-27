# HastyCR Long-Run Agent State

Last update: 2026-08-24T12:30:00+05:30
Authority: this file, `docs/LONGRUN_WORK_QUEUE.md`, and `docs/LONGRUN_DECISIONS.md` override conversational memory after compaction.

## Current phase

Phase 5 — Perception and observation parity.

## Current task

Task #6 complete: perception/manual annotation plumbing is implemented and validated synthetically. Continue to Task #7, executable differential simulation adapters, while preserving the zero-real-measurement readiness boundary.

## Completed phases

- Sprint 1 calibration infrastructure, clean-room reference study, static APK inventory, 70-scenario catalog, synthetic fixtures, opt-in diagnostics, and final validation were reconstructed from disk.
- Sprint 2 authoritative state files and starting-gap inventory were created.
- Sprint 2 baseline independently reproduced: full/focused tests, catalog/card validity, deterministic smoke/fixture hashes, strict readiness, compilation, benchmark, and dirty-tree safety checks.
- Mechanics evidence database completed: 31 mechanics/parameters, 16 evidence records, six explicit disagreements, 12 sources, five implementations, deterministic JSON digest/query/report/SQLite tooling, and zero real measurements.
- Longitudinal CSV archaeology completed: deterministic Git-object tooling covers 92 canonical historical snapshots and 11 mechanics tables, emits version/table/column/change/rename/parameter indexes, deduplicates the walle lineage, and keeps all historical values study-only. NoxCardEditor relationship, CRUD, serialization, and license semantics are documented separately.
- Sprint 2 Task #6 implementation: `tools/calibration/perception.py` adds versioned frame packets/sources, detector/arena/tracker adapters, conservative event derivation, normalized trace building, and weighted comparison; `tools/calibration/annotations.py` adds schema-v1 append-only corrections, replay, validation, digest, and queue state; `src/hastycr/observation.py` adds non-breaking seeded observation noise/projection. CLI commands are in `scripts/fidelity.py`; synthetic outputs are in `calibration/fixtures/`; reports are in `research/perception_reference_comparison.md` and `research/perception_annotation_workflow.md`.
- Sprint 2 Task #7 differential framework is implemented in `tools/calibration/differential.py`: schema-v1 shared scenarios wrap normalized traces, HastyCR executes safely through `SimTraceAdapter`, CRForge and clash-royale-suite are lazy descriptor-only adapters, and pairwise comparison ranks first divergences without a global accuracy claim. The bounded synthetic suite has three scenarios, deterministic report SHA-256 `FF3D97EC97712306CE29238003EBDB730F4B69B4EB4448DF91235FD402B0DAC8`, three HastyCR-ready results, six external-unavailable results, zero comparable external pairs, `SYNTHETIC_ONLY`, and `real_measurements=0`. Report: `reports/SPRINT2_DIFFERENTIAL_SIMULATION.md`.

## Exact commands currently useful

```powershell
& ".venvs\buildabot\Scripts\python.exe" -m pytest -q
& ".venvs\buildabot\Scripts\python.exe" -m pytest -q tests/test_calibration_core.py tests/test_calibration_scenarios.py tests/test_calibration_synthetic.py tests/test_calibration_diagnostics.py tests/test_replay_calibration.py tests/test_emulator_capture.py
& ".venvs\buildabot\Scripts\python.exe" -m tools.calibration.catalog validate
& ".venvs\buildabot\Scripts\python.exe" -m tools.research.csv_history validate
& ".venvs\buildabot\Scripts\python.exe" -m tools.research.apk_deep_analysis validate
& ".venvs\buildabot\Scripts\python.exe" -m sim.readiness
& ".venvs\buildabot\Scripts\python.exe" -m sim.runner --matches 20 --seed 1
& ".venvs\buildabot\Scripts\python.exe" scripts/fidelity.py simulate calibration/scenarios/sprint5_001_arena.json --output tmp/sprint2-smoke.json
& ".venvs\buildabot\Scripts\python.exe" scripts/fidelity.py validate tmp/sprint2-smoke.json --kind trace
git status --short
git diff --check
```

## Important files

- Prior canonical report: `reports/OVERNIGHT_FIDELITY_FINAL.md`
- Prior sprint record: `docs/OVERNIGHT_FIDELITY_SPRINT.md`
- Prior queue: `docs/OVERNIGHT_WORK_QUEUE.md`
- Sprint 2 gaps: `reports/SPRINT2_STARTING_GAPS.md`
- Calibration gates: `calibration/readiness_gates.json`
- Initial registries: `calibration/registry/mechanics.json`, `calibration/registry/shared_physics.json`
- Catalog/fixtures: `calibration/catalog.json`, `calibration/scenarios/`, `calibration/fixtures/`
- Calibration core: `tools/calibration/core.py`, `tools/calibration/catalog.py`, `tools/calibration/synthetic.py`
- Evidence database/tooling: `data/fidelity/mechanics.json`, `tools/calibration/evidence.py`, `reports/MECHANICS_TRUTH_TABLE.md`, `tests/test_calibration_evidence.py`
- Diagnostics: `sim/diagnostics.py`, `sim/engine.py`, `tests/test_calibration_diagnostics.py`
- Historical research: `research/`
- Longitudinal CSV archaeology: `tools/research/csv_history.py`, `research/csv_history/`, `research/nox_card_editor_schema_analysis.md`
- APK research: `tools/research/apk_deep_analysis.py`, `research/apk_analysis/`, `reports/apks/`, ignored `_references/apk_analysis/`

## Reference repos cloned

- `_references/crforge` — pinned prior HEAD `90c043b3ab3271cc41b5b96d84df7bfb746129d9`
- `_references/clash-royale-suite` — `050275d70b84614953877e8075dc4b8ba907c67f`
- `_references/jason-clash-royale-simulator` — `c8c0160fb0dd8c3930f8ac133d1a56f307fcdd50`
- `_references/samdickson-clash-simulator` — `99f936f81109057ca6466feafcc816b72fc8b664`
- `_references/cr-csv` — `899e45efc765fbf3902927bb2e37dc04a78f7823`
- `_references/walle-cr-csv` — `7141bb508eb0a152f6e7d783bf72968d50573e0b`; its two tags share commits with `_references/cr-csv`
- `_references/NoxCardEditor` — `be08c7ffcdea8a6611f551620d76a692e2b3a118`; MIT editor code, private-server semantics only
- `_references/cr-messages`, `_references/berkan-clashroyale`, `_references/clash-royale-gym`, `_references/ByteTrack`, `_references/norfair`, `_references/statsroyale`
- Sprint 2 requested but not yet cloned: `milanmaldini/cr-sc-dump2026`, `Keschler/cr-bot`, optional decoder/vision references.

## External tools installed

- Known available from Sprint 1: Git, Java, Python, PowerShell, `certutil`.
- No output was returned for `jadx`, `apktool`, `aapt`, Ghidra headless, rizin/radare2, `readelf`, `objdump`, `nm`, or `strings` in the Sprint 2 kickoff probe; treat them as unavailable until independently rechecked.
- Python runtime: `.venvs\buildabot\Scripts\python.exe`.

## Unresolved blockers

- Real measured Clash traces: **ZERO**.
- Readiness remains `NOT_READY`; all eleven category gates need measured train and held-out validation evidence.
- Existing `sweep` and `pull-map` CLI paths are bounded `UNMEASURED` placeholders.
- Specialized projectile and forced-motion diagnostics are incomplete.
- Historical CSV provenance/licenses are uncertain; historical/private-server values are study-only.
- Deep static reconstruction now parses DEX/ELF tables and references, but three DEX code items remained partial, two `.so`-named files were not parseable ELF, and proprietary asset formats remain explicitly unsupported.
- Pre-existing modified files must be preserved: `scripts/brain/config.json`, `scripts/brain/learned.json`, `scripts/brain/matchups.json`, `sim/engine.py`, `tests/test_sim_engine.py`. Sprint 1 outputs are also currently untracked.

## Current hypotheses

- Effective target distance, contact/separation geometry, retarget timing, bridge/building pull behavior, and same-tick event order are likely high-RL-impact uncertainties, but Sprint 2 must quantify this rather than rely on intuition.
- Cross-simulator disagreement can locate decision boundaries but cannot establish live truth.
- Historical CSV evolution may reveal persistent semantic fields even when old numeric values are obsolete.
- A manual-annotation path can unblock real calibration earlier than a production detector.
- Detailed diagnostics are appropriate for bounded probes only; retained-event overhead is large at scale.

## Next 9 tasks in priority order

1. Review Keschler/cr-bot and implement practical perception/manual annotation plumbing.
2. Implement executable cross-simulator adapters and common scenarios.
3. Document and sweep HastyCR targeting/collision/event-order decision boundaries.
4. Run mechanics and policy sensitivity sweeps and compute transparent calibration priorities.
5. Expand exploit/metamorphic/soak testing and first-divergence debugging.
6. Profile measured hot paths and attempt trace-preserving optimization.
7. Improve capture debugging and regression workflows.
8. Validate completion gates and publish final Sprint 2 reports.

## Latest test result

Fresh Sprint 2 baseline: `1445 passed, 1 skipped, 2 xfailed in 386.04s`. Latest focused evidence/calibration suite: `25 passed in 2.61s`. Mechanics database validation PASS: 31 mechanics, 31 parameters, 16 evidence records, six disagreements, zero measurements, digest `69ea338dec1fc0a3ab1e29ae6d000c2e29f75cd1513e2a7220c07f62ac4bc1ec`. CSV archaeology generation/validation PASS: 92 snapshots, 11 target tables, 421 changed table transitions, 19 rename candidates, 129 representative timeline events, zero measurements, manifest digest `1bae2106f0e3822fe5f84f4579fb7b6095046597a222a3a89c151f387370fee0`. Deep APK generation/validation PASS: four APKs, six pairs, 34,506 archive-bound extraction entries, five integrity-valid DEX files with zero malformed traversals, 54/56 parseable ELF candidates, 2,240/2,240 parsed CSV/TOML files, 25,768 unsupported proprietary files, 9,082 graph edges including 248 cross-layer mechanics-chain edges, zero measurements, manifest digest `641c3b2d7f49056021ba41b9e868ec8e0e26cbe9975b0738c972d84daa4bb8aa`. Catalog validation: 70 scenarios, 11 categories, 56 train/14 validation, no invalid card IDs. Two independent smoke runs produced identical normalized digest `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`; fixture manifest matched and normalized fixture digest remained `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`. `compileall` and `git diff --check` passed. Strict readiness correctly exited nonzero with `RL NOT READY`; real measured trace count remains ZERO.

## Latest benchmark result

Fresh Sprint 2 baseline: 20 matches in 18.4s, 1.1 matches/s, 4,734 ticks/s; 5W/15L/0D, crowns 6-17. This is slower than the prior 17.1s/5,093-tick run but effectively reproduces the original 18.4s baseline and is treated as host/runtime variance, not a mechanics regression.
