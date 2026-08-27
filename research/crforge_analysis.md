# CRForge clean-room analysis

Revision: `90c043b3ab3271cc41b5b96d84df7bfb746129d9`. License: Apache-2.0 with NOTICE. Upstream: https://github.com/voonhous/crforge.

## Architecture

**Verified facts.** The Gradle project separates a GUI-independent `core`, card/data loading in `data`, LibGDX tooling in `desktop`, a Java ZMQ server in `gym-bridge`, and a Python Gymnasium client in `python`. The core coordinator is [GameEngine.java](../_references/crforge/core/src/main/java/org/crforge/core/engine/GameEngine.java); systems include deployment, spawning, statuses, timers, area effects, targeting, abilities, combat/projectiles, transformations, physics, and death handling. Bridge DTOs and tests are under [gym-bridge](../_references/crforge/gym-bridge/).

**Project claim.** The [README](../_references/crforge/README.md) describes a deterministic tick-based research engine and Python integration. Determinism/fidelity were not independently benchmarked.

## Tick and event order

The code constant is 20 ticks/s (`DELTA_TIME = 0.05`), despite stale method comments saying 30 FPS. The observed top-level order in `GameEngine.tick()` is:

1. Apply pending prior-tick spawns/removals.
2. Match and elixir update, then collectors.
3. Queued deployments, live spawners, delayed death spawns.
4. Statuses, attached-unit synchronization, entity timers.
5. Area effects, targeting, abilities.
6. Combat/projectiles, HP-threshold transformations.
7. Physics movement/collision/bounds.
8. Death processing, time-limit check, frame increment.

This implies attacks use pre-physics positions for that tick and ordinary death processing follows movement. That is an observed implementation choice, not evidence that the live game uses the same order.

## Shared physics

[PhysicsSystem.java](../_references/crforge/core/src/main/java/org/crforge/core/physics/PhysicsSystem.java) performs movement first, then pair collision resolution, then arena bounds enforcement. The implementation distinguishes collision eligibility, detects overlap, derives push ratios, adds sliding adjustment, and enforces arena bounds. Physics consumes entity radius/mass-like properties and arena geometry. Important clean-room questions for HastyCR are coordinate units, deterministic pair ordering, zero-distance tie-breaking, iterative convergence, and whether post-combat movement can move an entity that became lethal earlier in the tick.

## Useful evidence surfaces

- [GameEngine.java](../_references/crforge/core/src/main/java/org/crforge/core/engine/GameEngine.java): authoritative local subsystem sequence.
- [PhysicsSystem.java](../_references/crforge/core/src/main/java/org/crforge/core/physics/PhysicsSystem.java): movement, collision, sliding, push ratios, bounds.
- [core engine tests](../_references/crforge/core/src/test/): scenario and system behavior examples.
- [BridgeServer.java](../_references/crforge/gym-bridge/src/main/java/org/crforge/bridge/BridgeServer.java), [ObservationBuilder.java](../_references/crforge/gym-bridge/src/main/java/org/crforge/bridge/observation/ObservationBuilder.java), and [StepAction.java](../_references/crforge/gym-bridge/src/main/java/org/crforge/bridge/dto/StepAction.java): process boundary and typed transport.
- [simulation documentation](../_references/crforge/docs/simulation.md): project explanations that must be separated from verified code behavior.

## Reuse boundary and uncertainty

The architecture and Apache-2.0 license make later reuse legally plausible with NOTICE handling, but no code was copied. Study value is high for subsystem separation, explicit event order, bridge DTOs, and test organization. Fidelity remains uncertain: comments conflict on tick rate, upstream data provenance requires separate review, and cross-simulator agreement cannot establish truth.