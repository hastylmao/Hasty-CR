# Jason-XII simulator analysis

Revision: `c8c0160fb0dd8c3930f8ac133d1a56f307fcdd50`. No license was found, so the repository is study-only. Upstream: https://github.com/Jason-XII/clash-royale-simulator.

## Verified architecture

The Python project concentrates simulation in [battle.py](../_references/jason-clash-royale-simulator/src/clasher_new/battle.py), arena/pathfinding in adjacent modules, and Gymnasium integration in [environment.py](../_references/jason-clash-royale-simulator/src/clasher_new/environment.py). Entities own update behavior; `BattleState` owns entities, towers, delayed spawn schedule, collision passes, deployment legality, and match time.

`BattleState.step(dt)` checks match state, regenerates elixir, removes previously dead entities, rebuilds building/path caches, updates each entity sequentially, enforces walkability after each update, resolves collisions, realizes scheduled spawns, and finally advances time/tick. Sequential entity updates make iteration order a potential same-tick dependency. Death callbacks activate king towers and invalidate building caches; dead entities persist until the next step's early filtering.

Collision separates overlapping ground-ground and air-air entity pairs using speed-derived ratios. It returns early on a zero-distance pair, which may leave later collisions unresolved. These are implementation observations, not live-game facts.

## RL contract

`CREnv` exposes Gymnasium `reset`, `step`, and `observe`. Verified spaces are a dictionary observation with arena grid, hand, and elixir, and a `MultiDiscrete([5, 32, 18])` action encoding. The environment advances multiple simulation frames per decision (the local code uses a 30-frame decision interval). This factorization is useful as an interface comparison, not an endorsed HastyCR action model.

## Relevant surfaces

- [battle.py](../_references/jason-clash-royale-simulator/src/clasher_new/battle.py): entity updates, projectiles, delayed spawns, pathing, collisions, death, area damage.
- [environment.py](../_references/jason-clash-royale-simulator/src/clasher_new/environment.py): spaces, observation and action packaging.
- [README](../_references/jason-clash-royale-simulator/README.md): project feature/performance claims and stated RoyaleAPI data use.

## Conclusion and uncertainty

Useful study topics are simple Gym integration, action factorization, delayed spawning, path cache invalidation, and explicit collision code. Do not copy any implementation or data because no permission grant was found. Accuracy, deterministic ordering, card coverage, data version, and the meaning of performance claims were not validated.