# HastyCR Determinism Audit

Status: Sprint 2.5 command-replay audit.

## Scope

This audit covers the battle/match execution path used by
`sim.match.Match`, `sim.engine.Battle`, `sim.entities.Entity`, the fixed arena,
and the command-only replay harness. It does not repeat Sprint 1/2 APK or CSV
research and does not treat policy randomness as hidden engine state.

## Classification

| Occurrence | Classification | Finding |
|---|---|---|
| `Match.__post_init__`: `random.Random(self.seed)` and deck shuffle | SEEDED | The seed deterministically creates each player's initial queue/hand. |
| `sim.runner.SimpleOpponent` local `random.Random(seed)` | NOT BATTLE RELATED / SEEDED | Generates external opponent commands; those commands must be recorded for replay. |
| `sim.deck_builder.random_public_deck` and `scripts/soak.py` RNG | NOT BATTLE RELATED / SEEDED | Generates episode/deck inputs, not hidden battle behavior. |
| `scripts/clone.py` Python/NumPy RNG | NOT BATTLE RELATED / SEEDED | Training/data split behavior only. |
| `Battle.next_uid` | SAFE | Monotonic integer allocation makes entity identity reproducible. |
| `Battle.entities` dictionary iteration | POTENTIAL NONDETERMINISM if construction order changes | Current insertion order is determined by monotonic UID creation and is stable for a fixed command stream. |
| Target candidate distance ties | FIXED | Equal-distance target, fallback, and sniper selection now explicitly prefers the lower UID. |
| Set fields in delayed effects | SAFE FOR DIGEST | Used for membership/visited bookkeeping, not ordered gameplay queues; canonical digest sorts set contents. |
| `hash()`, UUID, unseeded NumPy/Torch RNG in battle path | SAFE | None found. |
| `time.time`, `datetime.now`, wall clock in battle path | SAFE | None found. Benchmark/capture/supervisor clocks are excluded from simulation state. |
| Threads/concurrency in battle path | SAFE | None found. |
| Filesystem-order-dependent loading | SAFE FOR CURRENT LOADERS | Game-data hash canonicalizes relative paths; card/deck selection in replay is sorted before loading. |
| Global mutable battle RNG | SAFE | None found. Match uses a local seed RNG only during initialization. |

## Ordering Audit

The engine deliberately uses fixed phase order and insertion-ordered entity
collections. This is not accidental across a single deterministic run: every
entity enters through `Battle.add`, receives the next UID, and later scans see
the same UID insertion order. Existing targeting logic now has explicit UID
tie-breaks for equal edge gaps. The replay digest sorts mappings, set contents,
and entity keys so hash output itself is not dependent on container iteration.

Insertion-order perturbation of a replay-equivalent initial battle state was
run as a focused check and produced the same checkpoint/final digest for the
command demo. This does not prove every future engine mutation is independent
of insertion order; it establishes the current regression boundary and records
that UID order is the intended deterministic tie-break.

## Boundary

A deterministic HastyCR replay requires the exact recorded game-data hash and
simulator source revision. If either differs, the replay harness rejects the
file rather than silently replaying with different constants or mechanics.

The audit found no known unseeded randomness affecting battle behavior. It did
find that current battle loops rely on stable UID-driven insertion order in
many places. That is an explicit maintenance constraint, not a live-game
fidelity result.
