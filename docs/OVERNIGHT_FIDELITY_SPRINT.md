# HastyCR Overnight Fidelity Sprint

Started: 2026-08-23
Status: COMPLETE
Primary objective: make disagreement between HastyCR and observed Clash Royale measurable, diagnosable, calibratable, and regression-testable without inventing mechanics.

## Operating decisions

- Preserve existing simulator behavior unless evidence and regression tests justify a change.
- Treat source-backed fields, historical data, observations, cross-simulator agreement, hypotheses, and unresolved behavior as different confidence classes.
- Keep external repositories and APK extraction output under `_references/`; never commit them.
- Use normalized real and simulated traces as the calibration boundary.
- Keep detailed tracing opt-in so normal RL throughput is not materially affected.
- Do not promote candidate calibration parameters automatically.
- Do not change the two known expected-failure mechanics without evidence.

## Baseline

- Git commit: `1dc9e6dbbc97bf3f2c04ff8b9045dfa66ee7577` (`pre-review snapshot block 245`, 2026-08-23T10:56:07+05:30).
- Working tree at start was already dirty. Existing modified files: `scripts/brain/config.json`, `scripts/brain/learned.json`, `scripts/brain/matchups.json`, `sim/engine.py`, `tests/test_sim_engine.py`. Existing untracked capture/replay calibration files were also present. These changes are preserved and will not be reverted.
- Baseline game-data aggregate SHA-256: `0e6d28a9a3dbf6be88b1fdff7bbf28f8bcfcf32c09faf00be685238a7f7693f7`, computed from sorted per-file SHA-256 records under `data/` excluding `data/validation/`; manifest stored locally at `tmp/baseline-data-hashes.txt`.
- Full test suite: `1424 passed, 1 skipped, 2 xfailed in 397.50s (0:06:37)` using `.venvs\\buildabot\\Scripts\\python.exe -m pytest -q`.
- Simulator benchmark: 20 BrainPolicy matches in 18.4s, 1.1 matches/s, 4,742 ticks/s; 5W/15L/0D and crowns 6-17. This small sample is a throughput baseline, not a strategy conclusion.
- Deterministic replay baseline digest: seeds 1 and 5 produced SHA-256 `8f5406326338cef63f1952ad0a62ba55c3d251438021446e99502ecff20d5281` over the existing test fingerprint representation (2,940 repr bytes). The planned normalized trace digest will replace this ad-hoc baseline.
- Readiness baseline: `RL NOT READY`; blockers are eight implemented source graphs with named measurement approximations plus missing accepted `building_contact`, `map_anchors`, and `troop_contact` live-probe categories.
- Coverage baseline: 207 parsed cards, 176 deployable units, 31 spell cards, 27 resolvable spells, no unresolved public spells, no known top-level unit raw-field gaps.
- Action-audit baseline: eight calibration-gated graphs: evolved Executioner, Balloon Hero, Elite Archer Hero, evolved Goblin Drill, Mega Minion Hero, Monk, evolved Princess, and Wizard Hero.

## Work completed

- Inspected repository architecture and existing continuation contract.
- Confirmed existing `Battle.contact_trace`, `damage_log`, replay-calibration primitives, read-only multi-emulator capture, strict readiness gate, live probe evidence model, and deterministic replay tests.
- Confirmed no repository `AGENTS.md` or `.kiro/steering` instructions.
- Created the persistent sprint work queue.

## Decisions and measurements

- Existing `tools/replay_calibration.py` is useful but too narrow for the requested scenario/trace/metric workflow. It will remain compatible while a dedicated calibration package is added.
- Existing emulator capture already records append-only frame metadata and pixel hashes; it will be extended through adapters/validation rather than replaced.
- No current reusable deterministic trace hash was found. A metadata-independent normalized trace digest is planned.
- No `jadx`, `apktool`, `aapt`, or `7z` command was detected on PATH at baseline; Java, Git, Python, and `certutil` are available. APK work will start with Python ZIP parsing/hashing and use downloaded official tool releases only if justified.

## References inspected

All ten requested repositories were inspected at pinned revisions with licensing and provenance recorded in `research/REFERENCE_LICENSES.md`. Comparative findings are indexed by `research/README.md`. Reference simulators disagree on same-tick ordering, so no consensus behavior was promoted as ground truth.

Four APKs were statically inventoried without execution. Raw extraction output remains ignored under `_references/apk_analysis/`; tracked evidence and per-APK summaries are under `research/apk_analysis/` and `reports/apks/`.

## Algorithms considered

- Normalized schema-v2 traces as the real/simulator calibration boundary rather than modifying replay schema-v1.
- Canonical metadata-independent SHA-256 digests for reproducible CI fixtures.
- Robust median timestamp offset with scaled-MAD uncertainty.
- Manual-anchor homography mapping with inverse transforms and reprojection validation.
- Game-aware bounded tracking using distance, class/team compatibility, velocity, and confidence.
- Category metrics and PASS/WARN/FAIL/UNMEASURED readiness instead of a global scalar accuracy claim.
- Opt-in deterministic event diagnostics rather than always-on logs.
- Non-promoting sweep/pull-map placeholders until observed references define calibrated bounds and objectives.

## Code reused

No external simulator implementation code was copied. Existing HastyCR replay calibration, capture manifests, match APIs, contact traces, and damage logs were preserved and adapted through new interfaces. External projects were used only as clean-room evidence and architecture comparison.

## License record

See `research/REFERENCE_LICENSES.md`. Projects with missing, inconsistent, restrictive, or uncertain licenses remain study-only regardless of technical relevance.

## Unresolved issues

- Calibration readiness remains `NOT_READY`: no measured real-game trace campaign has been completed.
- All eleven categories still require measured train and held-out validation evidence.
- Specialized projectile and forced-motion systems are not uniformly covered by detailed diagnostics.
- `sweep` and `pull-map` remain bounded `UNMEASURED` commands until calibrated ranges and observed pull references exist.
- Pre-existing dirty files remain in the workspace and no commit was created.

## Final validation

- Full suite: `1445 passed, 1 skipped, 2 xfailed in 394.41s`.
- Focused calibration suite: `21 passed in 3.22s`; focused diagnostics/regression suite: `104 passed in 11.46s`.
- Catalog: 70 valid scenarios across 11 categories, 56 train and 14 validation; all cards resolve.
- CLI list/validate/simulate/inspect/compare/report smoke workflow: PASS.
- Repeated smoke trace SHA-256: `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`.
- Checked-in normalized fixture digest: `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`; all six file hashes match the fixture manifest.
- JSON parseability: 81 files; Python compilation and `git diff --check`: PASS.
- Final benchmark: 20 matches in 17.1s, 1.2 matches/s, 5,093 ticks/s; 5W/15L/0D, crowns 6-17. Baseline was 18.4s, 1.1 matches/s, 4,742 ticks/s with the same record.
- Diagnostics performance: small probe -0.91% (noise, 2,712 events); larger retained-event probe +58.50% (161,040 events), confirming detailed tracing must remain opt-in.
- Final dashboard and reproducibility checkpoints: `reports/OVERNIGHT_FIDELITY_FINAL.md`.
