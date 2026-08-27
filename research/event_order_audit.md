# Event-order audit

This audit compares implementation order only. It does not identify the live game's true order.

## Top-level sequences

| Stage | CRForge | CR Rudy | Jason | SamDickson |
|---|---:|---:|---:|---:|
| Tick/time advance | End frame increment | First | End | First |
| Elixir/phase | Early | Early | Early after win checks | Early |
| Deployment/spawners | Early explicit systems | Early explicit systems | External deploy; scheduled spawn at end | External deploy; entities immediate |
| Status/area effects | Before targeting/combat | Spell zones before targeting; buffs later | Entity-owned | Entity/mechanic-owned |
| Targeting | Before abilities/combat | Before movement | During entity update | During entity update |
| Movement | After combat | Before combat | During entity update | During entity update |
| Collision | After combat movement | Before combat | After all entity updates | After all entity updates |
| Troop combat | Before movement/collision | After movement/collision | During entity update | During entity update |
| Projectiles | Inside combat stage | After troop combat | Entity update order | Entity/mechanic order |
| Towers | Combat system | After projectiles | Building update order | Entity update order |
| Death spawns/cleanup | Delayed spawns early; death process late | Death processing then cleanup late | Dead filter next step; callbacks on damage/death | Cleanup/death spawning late |
| Match end | Time check before frame increment | After cleanup | Before updates | After cleanup |

## Consequential disagreements

1. **Move then attack vs attack then move.** CRForge attacks before physics; CR Rudy moves/collides before attacking. Range-boundary outcomes may differ by one tick.
2. **Projectile/tower ordering.** CR Rudy resolves troop combat, projectiles, then towers; Python entity loops can interleave by insertion order.
3. **Death visibility.** CR Rudy performs a dedicated late death pass; Jason filters previously dead entities at the next step start. Target availability and death spawns can differ.
4. **Buff timing.** CRForge updates statuses before combat; CR Rudy applies/ticks several buff systems after combat/towers. Expiration-edge attacks need direct tests.
5. **Clock semantics.** Some engines increment tick/time before systems and others after, affecting boundary phases and trace timestamps.

## Required HastyCR regression scenarios

- Two lethal attacks landing in the same tick: trade versus first-processed winner.
- Projectile in flight when shooter dies; target dies before impact; homing target disappears.
- Death-spawn unit versus same-tick area effect and collision.
- Stun/freeze/slow expiring on an attack-ready tick.
- Knockback crossing range or river/bridge boundaries before versus after attack.
- Two identical overlapping units with stable ID order and zero-distance normal.
- Tower activation and attack on the same tick a princess tower falls.
- Buff/DOT and direct damage jointly crossing lethal or HP-threshold boundaries.
- Deployment timer reaching zero during an active area effect.
- Match-time phase boundary where elixir, attacks, and end checks coincide.

## Audit evidence

- [CRForge GameEngine](../_references/crforge/core/src/main/java/org/crforge/core/engine/GameEngine.java)
- [CR Rudy engine](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/engine.rs)
- [CR Rudy combat stages](../_references/clash-royale-suite/cr-rudy-sim/simulator/engine/src/combat.rs)
- [Jason BattleState](../_references/jason-clash-royale-simulator/src/clasher_new/battle.py)
- [SamDickson BattleState](../_references/samdickson-clash-simulator/src/clasher/battle.py)

## Decision

Do not change HastyCR order based on this comparison. First instrument normalized per-stage events, preserve stable entity IDs/order, and compare controlled scenarios against observed traces. Simulator consensus is only a hypothesis generator.