# HastyCR Long-Run Mechanics Decisions

Updated: 2026-08-24T09:49:01+05:30

This is an append-only scientific decision log. Implementation changes require evidence stronger than implementation consensus alone.

## Decision S2-001 — Prior sprint claims are hypotheses until reverified

**QUESTION**
Can Sprint 2 accept the previous chat summary as its baseline?

**EVIDENCE**
The canonical disk report records 1445 passed, 70 scenarios, deterministic hashes, 17.1-second benchmark, and `NOT_READY`. The user explicitly requires a fresh rerun.

**SOURCES**
`reports/OVERNIGHT_FIDELITY_FINAL.md`; `docs/OVERNIGHT_FIDELITY_SPRINT.md`; `calibration/readiness_gates.json`.

**DECISION**
Use disk reports to reconstruct scope, but label their metrics prior-recorded until fresh commands reproduce them.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Blindly trust the prompt or rerun nothing; both undermine the requested independent baseline.

**WHAT WOULD CHANGE THE DECISION**
Nothing short of missing/corrupt artifacts; current artifacts exist and are internally consistent.

## Decision S2-002 — Real evidence count remains zero

**QUESTION**
Can contextual recordings, synthetic fixtures, APK data, historical CSV, or external simulator traces count as measured real Clash calibration evidence?

**EVIDENCE**
Readiness gates explicitly reject synthetic/reference-hypothesis evidence. Prior reports state no measured real-game campaign was completed. Existing validation recordings are documented as contextual-only with unknown controlled coordinates.

**SOURCES**
`calibration/readiness_gates.json`; `reports/OVERNIGHT_FIDELITY_FINAL.md`; `docs/SIMULATOR_CONTINUATION.md`; `docs/CALIBRATION_RECORDING_CAMPAIGN.md`.

**DECISION**
Real measured trace count is **ZERO** until a controlled, versioned, manifest-validated capture is annotated and accepted with held-out coverage.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Counting synthetic traces, external simulators, private APK assets, or uncontrolled recordings as real truth.

**WHAT WOULD CHANGE THE DECISION**
A controlled capture satisfying live-evidence and category-gate requirements.

## Decision S2-003 — Cross-simulator consensus is not truth

**QUESTION**
Should shared behavior among independent simulators be promoted directly into HastyCR?

**EVIDENCE**
Inspected simulators disagree on movement/combat/death/projectile ordering. Agreement can reflect copied assumptions or shared simplifications.

**SOURCES**
`research/event_order_audit.md`; `research/shared_physics_matrix.md`; `research/simulator_comparison.csv`.

**DECISION**
Store agreement/disagreement as evidence classes and use them to prioritize measurement. Require current direct data or controlled observation before `VERIFIED` status.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Majority vote; it creates fake confidence.

**WHAT WOULD CHANGE THE DECISION**
Corroborating current official data or controlled live observation for a specific mechanic.

## Decision S2-004 — Historical and private-server values are schema evidence first

**QUESTION**
How should old CSV and private-server editor/APK values influence mechanics?

**EVIDENCE**
Existing `cr-csv` has unresolved provenance/license, and all four APKs are classified as custom/private-server clients. Old fields can reveal relationships and semantics while numeric values may be obsolete or modified.

**SOURCES**
`research/REFERENCE_LICENSES.md`; `research/cr_csv_schema_inventory.md`; `research/apk_analysis/inventory.md`; per-APK summaries.

**DECISION**
Use longitudinal/private-server artifacts to identify field semantics, relationships, engine concepts, and hypotheses. Never promote numeric values without current corroboration.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Treat old/private values as official current parameters; ignore them entirely.

**WHAT WOULD CHANGE THE DECISION**
A value independently matching current official data or controlled current observation.

## Decision S2-005 — Preserve diagnostic and dirty-work boundaries

**QUESTION**
Should Sprint 2 alter pre-existing dirty simulator work or enable diagnostics globally?

**EVIDENCE**
Five files were already modified before Sprint 1. Detailed diagnostics measured +58.5% runtime in a large retained-event probe, while `None` preserves the hot path.

**SOURCES**
`docs/OVERNIGHT_FIDELITY_SPRINT.md`; `reports/OVERNIGHT_FIDELITY_FINAL.md`; current `git status`.

**DECISION**
Preserve existing dirty work, make surgical edits only after reading files, keep diagnostics opt-in, and do not commit unless requested.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Resetting dirty files; always-on event capture; broad rewrites of `sim/engine.py`.

**WHAT WOULD CHANGE THE DECISION**
Explicit user authorization or a measured trace-preserving need that cannot be isolated.

## Decision S2-006 — Evidence database should be structured and deterministic

**QUESTION**
Should mechanics evidence live only in Markdown, SQLite, or versioned structured text?

**EVIDENCE**
Sprint 1 registries are JSON but too shallow for sources, implementations, disagreements, measurements, cards, and version relationships. SQLite improves joins but binary diffs are opaque and awkward for review.

**SOURCES**
`calibration/registry/mechanics.json`; `calibration/registry/shared_physics.json`; Sprint 2 requirements.

**DECISION**
Start with a normalized, versioned JSON evidence store plus deterministic Python query/export tooling. Generate SQLite as an optional derived artifact if query scale justifies it; do not make a binary database the sole source of truth.

**CONFIDENCE**
Medium-high.

**ALTERNATIVES REJECTED**
Markdown-only truth; SQLite-only canonical storage; Parquet dependency for a small review-heavy dataset.

**WHAT WOULD CHANGE THE DECISION**
Evidence volume/query performance becoming unmanageable in deterministic JSON.

## Decision S2-007 — Separate field provenance from behavioral verification

**QUESTION**
Does a parameter present in current local client data make the implemented mechanic verified?

**EVIDENCE**
Speed, sight, range, hit speed, collision radius, mass, projectile speed/radius/homing, and deploy fields are loaded from the current local data, but HastyCR still chooses distance formulas, timer phase, solver iterations, tie order, and state transitions.

**SOURCES**
`sim/gamedata.py`; `sim/entities.py`; `sim/engine.py`; `data/fidelity/mechanics.json`.

**DECISION**
Use `VERIFIED_CURRENT_DATA` only for the existence/value of a current source field. Keep `measurement_status` independently `UNMEASURED_LIVE`, and classify the surrounding behavior as `SINGLE_IMPLEMENTATION`, `HYPOTHESIS`, `LEGACY_GUESS`, or `UNKNOWN` as appropriate.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Calling a whole mechanic verified because one input field is source-backed; downgrading genuine current fields to unknown because behavior is uncertain.

**WHAT WOULD CHANGE THE DECISION**
A controlled observation may verify behavior but does not change field provenance; a newer authenticated current data source may supersede field values.

## Decision S2-008 — Canonical JSON, derived SQLite and truth table

**QUESTION**
How should database reviewability, relational querying, and reporting be balanced?

**EVIDENCE**
The initial store validates 31 mechanics, 31 parameters, 16 evidence records, six disagreements, and 12 sources with deterministic digest `69ea338dec1fc0a3ab1e29ae6d000c2e29f75cd1513e2a7220c07f62ac4bc1ec`. SQLite export and Markdown generation reproduce from the same source.

**SOURCES**
`data/fidelity/mechanics.json`; `tools/calibration/evidence.py`; `reports/MECHANICS_TRUTH_TABLE.md`; `tests/test_calibration_evidence.py`.

**DECISION**
Keep reviewable JSON canonical. Treat SQLite and Markdown as generated views carrying the canonical digest. Enforce references, status vocabulary, source types, and real-measurement rules in code.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Binary-only SQLite truth; manually maintained Markdown; an unvalidated free-form registry.

**WHAT WOULD CHANGE THE DECISION**
Scale or concurrency requirements that demonstrably exceed deterministic JSON plus generated SQLite indexing.

## Decision S2-009 — Traverse historical Git objects and deduplicate lineage

**QUESTION**
What constitutes a longitudinal CSV snapshot when tags, releases, merges, and repository forks overlap?

**EVIDENCE**
The smlbiobot history has 91 asset-changing commits and ten tags; the `3.2.1` tag peels to a merge tree not selected by the path-limited log. The walle repository's two tags peel to commits already present in smlbiobot history. GitHub releases are tag aliases whose recorded target was the moving `master` branch.

**SOURCES**
`tools/research/csv_history.py`; `research/csv_history/version_inventory.csv`; `_references/walle-cr-csv/README.md`.

**DECISION**
Use immutable peeled commits and Git object reads without checkout. Canonicalize every asset-changing commit plus any otherwise-missing tagged tree, record tags/releases as aliases, and mark shared commits as duplicate lineage rather than independent corroboration.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Repeated tag checkout; counting two repository labels as two sources; trusting a release's moving branch target as immutable version evidence.

**WHAT WOULD CHANGE THE DECISION**
Authenticated APK hashes mapped to exact trees could strengthen version labels but would not change object-level deduplication.

## Decision S2-010 — Separate schema, row-set, and shared-value changes

**QUESTION**
Can a changed historical CSV blob be labeled a balance change?

**EVIDENCE**
Across 92 snapshots and 11 target tables, changed blobs include column/type changes, named-row additions/removals, shared-row payload changes, and formatting/duplicate-row changes. Commit subjects alone do not reliably distinguish them.

**SOURCES**
`research/csv_history/table_evolution.csv`; `research/csv_history/changes.csv`; `research/csv_history/rename_candidates.csv`.

**DECISION**
Classify structural schema, named-row-set, and shared-value changes independently. Treat lexical rename pairs as manual-review candidates only. Label stable-schema shared-value changes `VALUE_OR_BALANCE_CHANGE`, not proven balance or engine behavior.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Calling every changed blob a balance update; inferring engine behavior from a column addition; asserting a rename from lexical similarity.

**WHAT WOULD CHANGE THE DECISION**
Upstream migration metadata or authenticated release notes could refine individual classifications without weakening the separation.

## Decision S2-011 — NoxCardEditor semantics are operational conventions only

**QUESTION**
Should NoxCardEditor's associations and field groups be treated as the official relational schema?

**EVIDENCE**
The editor targets private servers, joins textual `Name`/TID values by first match, can duplicate same-name spell rows, does not inspect inbound references on delete, silently ignores load failures, and normalizes serialization. Its code is MIT licensed, while supplied/decrypted CSV data is not covered by that license.

**SOURCES**
`research/nox_card_editor_schema_analysis.md`; `_references/NoxCardEditor/NoxCardEditorV3.py`; `_references/NoxCardEditor/LICENSE`.

**DECISION**
Use its mappings and UI groups as schema-discovery evidence only. Do not treat CRUD behavior, uniqueness assumptions, serialized output, or private-server values as authoritative live truth.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Promoting editor categories to engine semantics; assuming the MIT code license applies to decrypted game data; copying private-server values into calibration.

**WHAT WOULD CHANGE THE DECISION**
Current authenticated schema documentation and controlled live evidence could independently corroborate specific relationships or field meanings.

## Decision S2-012 — Deep APK evidence remains static and provenance-bounded

**QUESTION**
How should deep DEX, native, data, and proprietary-asset evidence affect subsystem and mechanics claims?

**EVIDENCE**
The remediated bounded stdlib analyzer archive-binds all 34,506 extraction entries to four original ZIPs, verifies all five DEX stored SHA-1/adler integrity fields with zero malformed instruction traversals, structurally parses five DEX files and 54 of 56 ELF candidates, parses all 2,240 CSV/TOML entries after bounded local Supercell-container decoding, compares all six APK pairs with path/multiplicity-aware metrics, and emits 9,082 source-labeled graph edges including 248 cross-layer mechanics-chain edges. Two deterministic generations produced manifest digest `641c3b2d7f49056021ba41b9e868ec8e0e26cbe9975b0738c972d84daa4bb8aa`. DEX full map/header correspondence remains unvalidated, two `.so`-named files are not parseable ELF, proprietary formats remain opaque, and no payload or external tool was executed.

**SOURCES**
`tools/research/apk_deep_analysis.py`; `research/apk_analysis/deep_manifest.json`; `research/apk_analysis/DEX_RECONSTRUCTION.md`; `research/apk_analysis/NATIVE_RECONSTRUCTION.md`; ignored `_references/apk_analysis/deep/`.

**DECISION**
Use exact path/hash identity only for `UNCHANGED_SHARED_CLIENT`; without an identified official baseline, classify differing DEX/native/data components `UNKNOWN`. Manifest branding may classify only the application shell `PRIVATE_SERVER_SPECIFIC`. Use bounded normalized keyed digests for same-schema/same-key-set value-only data changes, and source-labeled static/inferred edges for conceptual chains. Keep opaque, partial, inferred, or incomplete evidence explicit; never call static references measured behavior, decompilation, or live mechanics truth. Future Apktool/JADX controls are a non-executing fail-closed policy and are not currently enforced.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Treating equal symbol surfaces as unchanged implementations; interpreting proprietary bodies or numeric values in tracked reports; running APK/native payloads; treating private-server evidence as live truth.

**WHAT WOULD CHANGE THE DECISION**
A separately authorized sandbox lane could deepen static decoding, while controlled real observations could verify behavior; neither would retroactively convert unsupported static evidence into measurements.

## Decision S2-013 — Perception remains adapter-based and annotation-led

**QUESTION**
How should Task #6 add perception and manual labels without destabilizing deployable or calibration contracts?

**EVIDENCE**
The inspected Keschler/cr-bot reference separates frame preparation, replay, tracking, and staged review, but its repository is licensed `CC-BY-NC-4.0` and no accepted labeled real dataset exists locally. HastyCR already has normalized trace v2, `ArenaMapper`, detector/tracker protocols, emulator capture JSONL, and deployable `GameState`/KataCR adapters.

**DECISION**
Implement clean-room, dependency-light adapters around the existing contracts. Store manual corrections in schema-v1 append-only ledgers with deterministic replay and queue state. Preserve confidence and uncertainty in every derived trace and use weighted comparison as a new API rather than changing existing metrics. Keep the deployable observation adapter non-breaking and noise injection explicit/seeded. Synthetic fixtures may validate plumbing only; they cannot increase `real_measurements` or readiness.

**CONFIDENCE**
High.

**ALTERNATIVES REJECTED**
Copying restrictive reference code/data; coupling annotations to a detector runtime; destructive label edits; changing the normalized trace or KataCR observation schemas; claiming detector accuracy without accepted real labels.

**WHAT WOULD CHANGE THE DECISION**
An accepted controlled labeled capture could drive a separately versioned evaluator, while a legal dependency review could permit an independently maintained tracker implementation.

## Decision S2-009 — Differential adapters fail closed when external runtimes are unavailable

**QUESTION**
How should the differential framework behave when CRForge or clash-royale-suite cannot be safely executed in the current environment?

**EVIDENCE**
The bounded synthetic suite ran three scenarios through HastyCR and produced deterministic normalized simulator-only traces. CRForge requires Java 17 plus a Gradle/JPype bridge; clash-royale-suite requires a maturin-built `cr_engine` extension and data files. Neither runtime was started. Two complete suite generations reproduced report SHA-256 `FF3D97EC97712306CE29238003EBDB730F4B69B4EB4448DF91235FD402B0DAC8`.

**SOURCES**
`tools/calibration/differential.py`; `reports/SPRINT2_DIFFERENTIAL_SIMULATION.md`; `research/REFERENCE_LICENSES.md`; pinned reference inventories in `docs/AGENT_LONGRUN_STATE.md`.

**DECISION**
Use one versioned common schema around normalized traces. Execute HastyCR directly. Represent unavailable external engines with lazy descriptor-only adapters that never import, build, start, or execute them; emit explicit `UNAVAILABLE` and `fail-closed` states. Pairwise comparison is `UNMEASURED` unless both traces are executable, and no scalar accuracy or majority-vote truth is produced. Keep `real_measurements=0` and HastyCR observability `SIMULATOR_ONLY`.

**CONFIDENCE**
High for safety and provenance; no behavioral confidence is claimed.

**ALTERNATIVES REJECTED**
Automatic Gradle/maturin builds; bridge/service startup; silently treating unavailable engines as agreement; counting synthetic simulator traces as live measurement.

**WHAT WOULD CHANGE THE DECISION**
An explicitly authorized, isolated runtime environment with pinned dependencies, verified licenses/data provenance, bounded execution, and separate evidence review could enable an external adapter without changing the common schema or live-measurement boundary.
