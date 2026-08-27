# Perception reference comparison

Observed 2026-08-24. `_references/cr-bot` is pinned to `a08a414433fec990f1af4b5bc22b060aceafb2f0` and was inspected without executing it. Its repository license is `CC-BY-NC-4.0` with a NonCommercial restriction; no reference implementation code or data was copied.

## Reusable concepts, clean-room only

- Separate frame preparation/replay from stateful tracking and evaluation.
- Preserve source frame index, video time, match time, and processing coordinates as distinct fields.
- Require direct temporal evidence for spawn/action onset and later confirmation for ambiguous release/death transitions.
- Keep review artifacts and annotation decisions immutable/auditable through hashes and stage checkpoints.
- Use candidate discovery to reduce review workload, but retain independent completeness sweeps.

## HastyCR implementation

- `tools/calibration/perception.py` adds dependency-light `FramePacket`, iterable/capture-index sources, detector/mapping/tracker adapters, conservative event derivation, and normalized trace construction.
- `tools/calibration/annotations.py` adds annotation schema v1, append-only correction operations (`merge`, `split`, `relabel`, `point`, `death`, `spawn`, `queue`), deterministic replay, validation, digest, and queue state.
- `src/hastycr/observation.py` adds a non-breaking `GameState` projection/noise adapter. It does not change `GameState`, `Action`, KataCR tensors, or live-action gating.
- `scripts/fidelity.py` exposes annotation initialization, append, validation, and materialization commands. Payloads may be supplied as JSON files to avoid shell quoting errors.

## Evidence boundary

No accepted labeled real trace, video, capture JSONL, or workspace PNG dataset was available. The generated perception outputs are synthetic plumbing fixtures only. `real_measurements=0`, no detector precision/recall claim is emitted, and `RL NOT READY` remains the required state.

## Safety and provenance

No APK/native payload, external decoder, model, or reference repository code was executed. The restrictive reference license is recorded in `research/REFERENCE_LICENSES.md`; the new HastyCR code is independently implemented around existing local calibration contracts.
