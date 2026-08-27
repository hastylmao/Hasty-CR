# Shared physics and interface matrix

`Observed` means present in inspected source. It does not mean accurate to Clash Royale.

| Concern | CRForge | CR Rudy | Jason | SamDickson | Clean-room implication |
|---|---|---|---|---|---|
| Fixed timestep | 20 tps constant; contradictory stale comments | Project/code structured around 20 tps integer ticks | Caller-supplied `dt` | README claims 33 ms; battle stores fixed `dt` | Trace schema must record exact dt/tick and reject implicit conversion |
| Coordinate arithmetic | Floating-point vectors | Integer-valued engine state | Floating-point tile coordinates | Floating-point tile coordinates | Normalize units explicitly; never compare raw positions |
| Movement vs combat | Combat before physics | Movement/collision before combat | Per-entity update mixes movement/attack, then global collision | Per-entity update, then global collision | Build same-tick movement/attack scenarios; do not select by majority vote |
| Pair collision | Dedicated physics stage | Dedicated combat collision stage | Pair combinations; speed-ratio push | Global troop collision helper | Log pair order, overlap, normal, displacement and pass count |
| Mass/push weighting | Push-ratio function uses entity properties | Project describes mass-based separation | Uses speed ratio | Implementation-specific helper | Treat weight model as calibratable until measured |
| Sliding | Explicit sliding adjustment | Collision/pathing write-up discusses separation/routing | No explicit shared sliding stage observed | No explicit shared sliding stage established | Measure tangential displacement near blockers |
| Arena bounds | Explicit final enforcement | State/pathing constraints in engine | Per-entity walkability enforcement | Arena validity/snap helpers | Separate hard bounds, river, tower footprints, and deploy legality |
| Ground vs air collision | Eligibility predicate | Entity-kind/state logic | Ground and flying pairs separated | Troop implementation distinguishes air | Record collision layer as an explicit trace field |
| Building blocking | Physics eligibility and arena | Collision after movement includes building blocking | Building cache and overlap checks | Deployment/arena obstacle checks | Test dynamic cache invalidation and radius conventions |
| Bridge/river pathing | Arena-aware physics | Explicit bridge-aware movement | A* with river/jump checks | Bridge/pathfinding modules and arena checks | Calibrate route selection separately from movement speed |
| Projectiles | Combat-owned projectile system before physics/death | Separate projectile stage after troop combat | Projectile entities update in iteration order | Entity/mechanics/spell architecture | Log launch, target snapshot, travel, impact, AoE, death timestamps |
| Knockback/status coupling | Abilities/status/physics are separate stages | Combat/buffs/hooks/projectiles stages | Some projectile push applied immediately | Mechanics package includes knockback/stun hooks | Define when impulse affects same-tick targeting/combat |
| Deterministic tie handling | Needs explicit test; collection ordering matters | Integer/staged design; exact tie rules still need tests | Dict/insertion and pair iteration can matter | RNG appears in formations | Require stable IDs/order and seeded RNG in HastyCR traces |
| Tracking API comparator | N/A | Per-tick state/replay concepts | N/A | Replay/state facade | For real traces, define an adapter rather than importing simulator state |

## Tracking abstraction findings

ByteTrack revision `d1bf0191adff59bc8fcfeaa0b33d3d1642552a99` exposes `BYTETracker.update(output_results, img_info, img_size)` and uses high-confidence association followed by low-confidence recovery, prediction, track activation/lost/removal states, and bounding boxes. Norfair `v2.3.0` exposes `Tracker.update(detections, period, coord_transformations)` over point-based `Detection` objects with configurable distances, filters, initialization delay, hit counters, optional ReID, and coordinate transforms. Relevant files are [ByteTrack tracker](../_references/ByteTrack/yolox/tracker/byte_tracker.py), [ByteTrack matching](../_references/ByteTrack/yolox/tracker/matching.py), [Norfair tracker](../_references/norfair/norfair/tracker.py), [Norfair filters](../_references/norfair/norfair/filter.py), and [camera motion](../_references/norfair/norfair/camera_motion.py).

A HastyCR tracker interface should accept timestamped detections in arena coordinates plus class/team/confidence, return stable IDs with position/velocity/uncertainty and lifecycle state, and allow pluggable association. This is an inference, not copied code. Game-aware class/team compatibility and bounded arena motion are domain requirements absent from generic tracker APIs.