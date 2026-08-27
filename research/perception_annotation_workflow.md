# Perception and manual annotation workflow

## Workflow

1. A `PacketSource` emits versioned `FramePacket` values with source frame, video time, optional battle time, provenance, confidence, and uncertainty.
2. A detector adapter emits normalized `Detection` values. `MappedDetector` applies the existing arena homography and increases uncertainty by the mapping reprojection error.
3. A tracker adapter emits the existing `TrackedEntity` contract. The default `SimpleGameAwareTracker` remains deterministic and can be replaced by an reviewed adapter.
4. `EventDeriver` emits only conservative spawn, inferred death, and relabel transitions; missing tracks are tolerated for a bounded gap.
5. `PerceptionTraceBuilder` emits schema-v2 `NormalizedTrace` frames and preserves source metadata.
6. `annotation_from_trace` creates an auditable annotation document. Corrections append to the operation ledger and never mutate history.
7. `replay_annotations` validates and deterministically materializes corrected normalized frames. Queue operations expose pending/in-review/reviewed/blocked frame counts.
8. `compare_traces_weighted` reports confidence/uncertainty-weighted position and timing metrics while leaving the existing comparison API unchanged.
9. `DeployableObservationAdapter` optionally injects seeded observation noise while preserving the deployable `GameState` and KataCR observation contracts.

## Correction semantics

- `merge`: aliases two or more source annotation IDs to one target.
- `split`: assigns records at/after a time to a new track ID.
- `relabel`: changes class identity from a specified time.
- `point`: corrects one annotation's frame-local position and uncertainty.
- `death`: removes records at/after the manually observed death time and emits an inferred death event.
- `spawn`: appends a validated manually created record.
- `queue`: changes frame review state without changing semantic labels.

## Commands

```powershell
python scripts/fidelity.py annotation-init calibration/fixtures/corrupted_observed.json --output tmp/annotations.json
python scripts/fidelity.py annotation-validate tmp/annotations.json
python scripts/fidelity.py annotation-append tmp/annotations.json --kind point --payload tmp/point.json --reason "visual correction"
python scripts/fidelity.py annotation-materialize tmp/annotations.json --output tmp/annotated-trace.json
python -m tools.calibration.generate_perception_fixture --output-dir calibration/fixtures
```

The checked-in fixture is deliberately synthetic. Its manifest says `SYNTHETIC_ONLY`, `real_measurements=0`, and `performance_claim=null`.
