# Clash Royale Suite / CR Rudy analysis

Revision: `050275d70b84614953877e8075dc4b8ba907c67f`. License: MIT. Upstream: https://github.com/nguiaSoren/clash-royale-suite.

## Architecture

**Verified facts.** The monorepo has `cr-data-engine`, `cr-deck-synergy`, `cr-perception`, and `cr-rudy-sim`. The simulator is Rust with PyO3 packaging, integer-valued state, JSON data inputs, replay/telemetry artifacts, and a large test suite. Core orchestration is [engine.rs](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/engine.rs); combat/physics-heavy logic is [combat.rs](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/combat.rs); state/data types are adjacent in [engine/src](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/).

**Project claims.** The [README](../_references/clash-royale-suite/README.md) reports 20 tps, integer-only determinism, 125+ entities, performance numbers, and 1,900+ assertions. These claims were not independently reproduced.

## Observed tick order

`engine::tick` increments the tick first, then runs:

1. Phase and elixir.
2. Deploy timers and burrow travel.
3. Building lifetime/spawners and troop spawners.
4. Spell zones.
5. Targeting.
6. Movement, attached-unit sync, collision resolution.
7. Troop combat, idle buffs, Fisherman hook.
8. Projectile movement/impact and morphs.
9. Tower buffs/attacks, evolution/hero/champion systems, HP-threshold buffs, active-buff timers/effects.
10. Death processing, crown recount, dead-entity cleanup, end check.

The sequence differs materially from CRForge: CR Rudy moves/collides before combat, separates troop combat/projectiles/towers, and processes active buffs late. Same-tick outcomes can therefore differ even with equal parameters.

## Shared physics and targeting

[combat.rs](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/combat.rs) exposes cohesive stages: target snapshots/targeting, troop movement, collisions, combat, projectiles, towers, deaths, spell zones, and morphs. Collision is described by the project as mass-based N-body separation and bridge routing as cost-based; those descriptions are project claims, while the presence and top-level call order are verified. Integer state and explicit stage boundaries are useful models for deterministic trace instrumentation.

## Relevant evidence

- [simulator README](../_references/clash-royale-suite/cr-rudy-sim/simulator/README.md): interface and project claims.
- [collision/pathfinding write-up](../_references/clash-royale-suite/cr-rudy-sim/27_collision_and_bridge_writeup.html): study material, not independently verified.
- [simultaneous-hits write-up](../_references/clash-royale-suite/cr-rudy-sim/28_simultaneous_hits_and_collision_writeup.html): candidate test ideas.
- [performance/observability write-up](../_references/clash-royale-suite/cr-rudy-sim/29_performance_observability_writeup.html): trace design ideas.
- [record_one.py](../_references/clash-royale-suite/cr-rudy-sim/simulator/record_one.py) and [replay viewer](../_references/clash-royale-suite/cr-rudy-sim/simulator/cr_replay_viewer.html): replay packaging surfaces.

## Reuse boundary and uncertainty

MIT permits reuse in principle, but this sprint copied no code. The strongest clean-room takeaways are integer/fixed-step state, explicit stage diagnostics, snapshot/replay boundaries, and tests around simultaneous effects. Accuracy, data lineage, coordinate conversion, hidden tie-breakers, and card-specific behavior remain uncertain. The suite must not be treated as an oracle.