# Sprint 2 Starting Gaps

Date: 2026-08-24
Basis: repository artifacts, not the conversation summary.

## Verified from prior artifacts

Sprint 1 delivered normalized trace/calibration infrastructure, deterministic fixtures, opt-in diagnostics, clean-room reference research, and static APK inventory. Its final disk report records:

- Full suite: `1445 passed, 1 skipped, 2 xfailed in 394.41s`.
- Catalog: 70 valid scenarios across 11 categories; 56 train and 14 validation.
- Repeated smoke digest: `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`.
- Checked-in normalized fixture digest: `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`; six file hashes matched their manifest.
- Throughput: 20 matches in 17.1s, 1.2 matches/s, 5,093 ticks/s.
- Readiness: `NOT_READY` with no scalar accuracy claim.
- Measured real-game traces: **ZERO**.

These values remain prior-recorded until Sprint 2 independently reruns them.

## Requested paths that do not exist

The prompt named several likely prior outputs that are absent under those exact paths:

- `reports/overnight_fidelity_report.md`
- `reports/OVERNIGHT_MAJOR_DISCOVERIES.md`
- `reports/CALIBRATION_BACKLOG.md`
- `reports/NEXT_REAL_GAME_CALIBRATION_CAMPAIGN.md`
- `data/calibration/`
- `tests/calibration/`

Actual equivalents are `reports/OVERNIGHT_FIDELITY_FINAL.md`, `docs/CALIBRATION_BACKLOG.md`, `docs/CALIBRATION_RECORDING_CAMPAIGN.md`, root `calibration/`, and root `tests/test_calibration_*.py`.

## P0 scientific gaps

### No live truth layer

- No controlled, normalized, accepted real-game trace exists.
- Arena homography, bridge/river anchors, clock alignment, controlled placements, and held-out repetitions remain unmeasured.
- Existing recordings are contextual-only and cannot promote mechanics.

### Mechanics evidence is shallow

- Existing registries contain only nine seed entries and lack normalized entities for sources, cards, implementations, disagreements, measurements, versions, and evidence relationships.
- There is no queryable mechanics truth table or systematic confidence/status audit.
- Implementation comments contain historical certainty language that needs evidence review.

### Shared mechanics remain unresolved

- Effective target distance and tie/stickiness/retarget semantics are not mapped as decision boundaries.
- Contact radius, mass weighting, separation passes/strength, convergence, and insertion-order sensitivity lack quantitative characterization.
- Bridge selection, dynamic obstacle cost, building pull maps, and river-jump behavior lack observed calibration.
- Projectile spawn offset, swept collision/interception, radius, and specialized projectile lifecycles are incomplete or unmeasured.
- Same-tick ordering around attacks, movement, projectile impact, stun, knockback, death, spawn, shield loss, and timers has limited regression coverage and no live resolution.

## P0 evidence archaeology gaps

- Existing `smlbiobot/cr-csv` work is a single-checkout schema inventory, not longitudinal across tags.
- `walle-d/cr-csv` has not been cloned or analyzed.
- No schema evolution table, historical field timeline, or balance-vs-engine-change classifier exists.
- NoxCardEditor has not been inspected for old/private CSV relationships.
- Current resource decoder projects have not been evaluated against the four APKs.

## P0 APK gaps

Sprint 1 safely inventoried four custom/private-server APKs but did not complete:

- DEX class/method/package similarity.
- Native export/string similarity and candidate addresses.
- Decoded modern Supercell data assets.
- Conceptual battle call graphs.
- Per-subsystem original-client versus modified/private/custom/unknown classification.

The two Infinity APKs have distinct container hashes but identical normalized extracted payloads. That result should prevent duplicate deep work.

## P0 differential and sensitivity gaps

- No executable common-schema cross-simulator framework exists.
- No meaningful cross-simulator scenario outputs or decision-boundary sweeps exist.
- No mechanics perturbation framework has measured trajectory, target, damage, tower HP, result, duration, or policy effects.
- No transparent importance score ranks real measurement needs by evidence, disagreement, frequency, card coverage, and sensitivity.

## P1 perception gaps

- Sprint 1 built interfaces and capture validation, not a complete frame-to-normalized-trace pipeline.
- Keschler/cr-bot has not been studied.
- No versioned manual annotation fallback or correction operations exist.
- Confidence is represented in normalized entities but does not yet drive a production ingest/evaluation workflow or weighted metrics comprehensively.
- No observability matrix or deployable observation adapter exists.

## P1 robustness/debugging gaps

- No general first-divergence debugger or deterministic state-diff tool.
- Snapshot/export/restore is deferred.
- Metamorphic coverage does not yet systematically test UID/insertion order, irrelevant deck order, physics mirror parity, and snapshot continuation.
- No unified seeded soak command or structured exploit hunt.
- No current profile report or trace-preserving spatial-index experiment.

## Evidence-backed starting priority

1. Build the evidence database so every subsequent finding is retained with status/version/source.
2. Complete longitudinal CSV archaeology and APK similarity to reveal candidate semantics without treating values as truth.
3. Execute differential targeting/collision/pathing experiments to locate disagreements.
4. Quantify mechanics and policy sensitivity to rank what must be measured live.
5. Build manual/perception ingest and experiment preparation so the resulting ranked captures can immediately become normalized traces and regression fixtures.

## Safety and ownership constraints

- Do not execute APK/DEX/native payloads or probe accounts/servers.
- Do not copy code from study-only/unlicensed references.
- Do not promote simulator consensus, synthetic traces, historical CSV, or private-server data as current truth.
- Preserve pre-existing modified files: `scripts/brain/config.json`, `scripts/brain/learned.json`, `scripts/brain/matchups.json`, `sim/engine.py`, and `tests/test_sim_engine.py`.
- No commits unless explicitly requested.
