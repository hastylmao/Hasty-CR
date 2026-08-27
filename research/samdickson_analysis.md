# SamDickson simulator analysis

Revision: `99f936f81109057ca6466feafcc816b72fc8b664`. The README claims MIT but the referenced LICENSE file is absent; treat as study-only pending clarification. Upstream: https://github.com/samdickson22/clash-simulator.

## Verified architecture

The Python package separates [battle state](../_references/samdickson-clash-simulator/src/clasher/battle.py), [engine facade](../_references/samdickson-clash-simulator/src/clasher/engine.py), entity classes, card loading/factories, a [mechanics package](../_references/samdickson-clash-simulator/src/clasher/mechanics/), spells, arena/pathfinding, Gym integration, replay utilities, and tests.

`BattleState.step` advances time/tick, updates elixir modes/regeneration, updates all entities, resolves troop collisions, removes dead entities (including death-spawn handling), then checks win conditions. The explicit cleanup stage makes it easier to audit death spawning than entity-owned immediate removal, but entity iteration still creates ordering questions.

The battle code contains explicit deployment validation, swarm formations, bridge/tower obstacle handling, hitboxes, collision separation, and mechanic hooks. Some formations use randomness; unless seeded and serialized, this conflicts with strict deterministic replay requirements.

## Interfaces

`BattleEngine` provides `run_battle`, `run_headless`, `simulate_action`, `get_battle_state`, and `save_replay`. The [README](../_references/samdickson-clash-simulator/README.md) claims 33 ms fixed steps, Gymnasium support, a 128×128×3 observation, 2,304 discrete actions, replay recording, and high turbo throughput. These are project claims unless directly represented by interface code; no benchmarks were rerun.

## Relevant surfaces

- [battle.py](../_references/samdickson-clash-simulator/src/clasher/battle.py): lifecycle, deployment, swarms, collisions, cleanup/death spawning.
- [engine.py](../_references/samdickson-clash-simulator/src/clasher/engine.py): orchestration and replay API.
- [mechanics](../_references/samdickson-clash-simulator/src/clasher/mechanics/): composable hooks for knockback, stun, charge, shields, spawn/death behavior.
- [tests](../_references/samdickson-clash-simulator/tests/): project-specific behavior expectations, not ground truth.

## Conclusion and uncertainty

Study value is high for modular mechanics, replay facade, and test organization. Permission is uncertain, so no code was reused. README self-labels itself outdated; physics fidelity, data provenance/version, deterministic RNG, event ordering, and claimed performance remain unresolved.