# Mechanics Truth Table

Generated from `data/fidelity/mechanics.json`. `VERIFIED` is reserved for current direct data or controlled observation; cross-simulator agreement is not truth.

## collision.contact_radius

- **Current HastyCR:** Required ground gap is sum of source-backed collision radii.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, skeletons, prince, valkyrie, minions, fisherman, minipekka, battle_ram, bowler.
- **Implementation:** sim/entities.py:Entity.collision_radius_mt, sim/engine.py:Battle._separate.
- **Evidence `ev-hasty-collision`:** Current pairwise mass-weighted overlap correction and building push-out are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-collision`:** Independent engines include pair collision and mass/push concepts but differ in staging and correction procedure. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Radius fields are source-backed; visible contact semantics and attack geometry remain unresolved.
- **Needed experiment:** COLLISION-001 two-unit contact with ground-point annotation

## collision.iterations

- **Current HastyCR:** A fixed number of pairwise passes followed by a final building push-out.
- **Status:** `LEGACY_GUESS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** skeletons, knight, giant, hog_rider.
- **Implementation:** sim/engine.py:SEPARATION_PASSES, sim/engine.py:Battle._separate.
- **Evidence `ev-hasty-collision`:** Current pairwise mass-weighted overlap correction and building push-out are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Numerical solver choice is implementation-defined.
- **Needed experiment:** COLLISION-004 3/10/20-unit convergence series

## collision.mass

- **Current HastyCR:** Pair displacement is inverse-mass weighted.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, giant, hog_rider, skeletons, prince, valkyrie, minipekka, battle_ram.
- **Implementation:** sim/entities.py:Entity.mass, sim/engine.py:Battle._separate.
- **Evidence `ev-hasty-collision`:** Current pairwise mass-weighted overlap correction and building push-out are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-collision`:** Independent engines include pair collision and mass/push concepts but differ in staging and correction procedure. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Mass values exist in data; exact displacement model is a simulator interpretation.
- **Needed experiment:** COLLISION-002 heavy/light contact from controlled positions

## collision.order

- **Current HastyCR:** Insertion-ordered pair iteration; collisions occur after attack/movement in the active-unit stage.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** skeletons, knight, giant, hog_rider.
- **Implementation:** sim/engine.py:Battle._separate, sim/engine.py:Battle.step.
- **Evidence `ev-hasty-collision`:** Current pairwise mass-weighted overlap correction and building push-out are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-event-order`:** CRForge attacks before physics while CR Rudy moves/collides before combat; Python engines interleave per entity. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Potential insertion-order sensitivity and cross-engine disagreement need direct tests.
- **Needed experiment:** COLLISION-005 insertion permutation matrix

## collision.separation

- **Current HastyCR:** Overlap correction multiplies overlap by a fixed strength and distributes by mass.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, giant, hog_rider, skeletons, prince, valkyrie, minipekka, battle_ram.
- **Implementation:** sim/engine.py:Battle._separate.
- **Evidence `ev-hasty-collision`:** Current pairwise mass-weighted overlap correction and building push-out are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-collision`:** Independent engines include pair collision and mass/push concepts but differ in staging and correction procedure. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: fixed passes, fixed strength, inverse mass; CRForge: dedicated physics/sliding stage; CR Rudy: staged mass-based collision; Jason: speed-ratio pair push; Sam: global helper. Severity `HIGH`, RL impact `HIGH`.
- **Conclusion:** Correction model and strength are not current-data-backed.
- **Needed experiment:** COLLISION-003 clump relaxation over high-FPS frames

## combat.attack_cancel

- **Current HastyCR:** Target change resets windup; range loss stops attack but preserves timers according to current state fields.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, minipekka.
- **Implementation:** sim/engine.py:Battle._acquire_target, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-combat`:** Current range, windup, cooldown, release, and retarget procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Cancellation and backswing semantics are incomplete as an explicit state machine.
- **Needed experiment:** ATTACK-004 knockback/range-loss around release

## combat.attack_range

- **Current HastyCR:** Attack reach is source range plus target collision radius.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, minipekka.
- **Implementation:** sim/entities.py:Entity.range_mt, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-combat`:** Current range, windup, cooldown, release, and retarget procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-target-distance`:** Independent implementations use differing center/edge adjusted distance conventions; executable boundary comparison is pending. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Range value is data-backed; effective geometry is not observed.
- **Needed experiment:** ATTACK-001 stationary target approach boundary

## combat.cooldown

- **Current HastyCR:** Hit speed is loaded after a completed cycle; timer decrements before release test.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, minipekka.
- **Implementation:** sim/entities.py:Entity.hit_speed_ms, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-combat`:** Current range, windup, cooldown, release, and retarget procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Current values are data-backed; phase alignment is not measured.
- **Needed experiment:** ATTACK-003 repeated stationary attack intervals

## combat.hit_frame

- **Current HastyCR:** Damage/projectile launch occurs when the windup timer reaches zero on the fixed 50ms tick.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, minipekka.
- **Implementation:** sim/engine.py:Battle.step, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-combat`:** Current range, windup, cooldown, release, and retarget procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-event-order`:** CRForge attacks before physics while CR Rudy moves/collides before combat; Python engines interleave per entity. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Tick quantization and same-tick release order are unresolved.
- **Needed experiment:** TIMING-001 high-FPS launch/damage timestamp pairs

## combat.windup

- **Current HastyCR:** Load time starts on target change and counts down after entering attack range.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, minipekka.
- **Implementation:** sim/entities.py:Entity.load_time_ms, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-combat`:** Current range, windup, cooldown, release, and retarget procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-event-order`:** CRForge attacks before physics while CR Rudy moves/collides before combat; Python engines interleave per entity. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Value is data-backed; start/cancel/restart semantics need observation.
- **Needed experiment:** ATTACK-002 target enter/leave during windup

## events.same_tick_order

- **Current HastyCR:** Scheduled effects/projectiles/statuses precede deploy activation; then target, attack/move, separation, spawners, and cleanup in explicit code order.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, fireball, minipekka.
- **Implementation:** sim/engine.py:Battle.step.
- **Evidence `ev-hasty-event-order`:** Battle.step provides an explicit HastyCR same-tick procedure. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-event-order`:** CRForge attacks before physics while CR Rudy moves/collides before combat; Python engines interleave per entity. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: scheduled effects then target/attack-move/collision/spawn/cleanup; CRForge: combat before physics; CR Rudy: movement/collision before combat; Jason/Sam: per-entity updates then global collision. Severity `HIGH`, RL impact `HIGH`.
- **Conclusion:** Implementations materially disagree and no live result selects an order.
- **Needed experiment:** TIMING-002 simultaneous lethal/projectile/stun/death-spawn matrix

## movement.base_speed

- **Current HastyCR:** Client Speed converted as tiles/minute to integer millitiles/second; buffs and charge multiply it.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, skeletons, prince, valkyrie, minions, balloon, fisherman, minipekka, battle_ram, bowler.
- **Implementation:** sim/entities.py:speed_to_mt_per_sec, sim/engine.py:Battle._move.
- **Evidence `ev-speed-current-data`:** HastyCR loads a current Speed field and uses an explicit integer conversion. Source: HastyCR entity model; `VERIFIED_CURRENT_DATA` / `MEDIUM`.
- **Evidence `ev-synthetic-catalog`:** Synthetic scenarios prove deterministic plumbing only and cannot establish live mechanics. Source: Sprint 1 synthetic scenario catalog; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Current field and conversion are source-backed, but live trajectory calibration is absent.
- **Needed experiment:** MOVE-001 straight mirrored Knight/Giant trajectories

## movement.river_jump

- **Current HastyCR:** All non-flying units use bridge terrain; JumpEnabled does not grant unrestricted river traversal.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** hog_rider, prince.
- **Implementation:** sim/engine.py:Battle._waypoint.
- **Evidence `ev-hasty-pathing`:** Current static flow-field and local dynamic obstacle behavior are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Code choice is explicit but live jump boundary/timing is unresolved.
- **Needed experiment:** PATH-003 controlled river-edge jump placements

## movement.turning

- **Current HastyCR:** Instant direction change with integer step; obstacle steering chooses and persists a perpendicular side.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, giant, hog_rider, prince, battle_ram.
- **Implementation:** sim/engine.py:Battle._move, sim/engine.py:Battle._avoid_buildings.
- **Evidence `ev-hasty-movement`:** Current code uses instantaneous normalized stepping and persistent perpendicular obstacle steering. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Implementation-defined and likely trajectory-sensitive.
- **Needed experiment:** MOVE-002 obstacle corner approach from mirrored offsets

## pathing.bridge_anchor

- **Current HastyCR:** Ground movement uses a static flow field over modeled river/bridge terrain.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, giant, hog_rider, skeletons, prince, valkyrie, fisherman, minipekka, battle_ram.
- **Implementation:** sim/arena.py:BRIDGE_X, sim/engine.py:Battle._waypoint, sim/pathfind.py.
- **Evidence `ev-hasty-pathing`:** Current static flow-field and local dynamic obstacle behavior are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Arena coordinates and bridge geometry lack controlled current observation.
- **Needed experiment:** ARENA-001 both-seat landmarks and bridge edges

## pathing.building_pull

- **Current HastyCR:** Building-only units consider visible buildings by target edge gap; otherwise nearest building is fallback destination.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** giant, hog_rider, balloon, battle_ram, cannon.
- **Implementation:** sim/engine.py:Battle._acquire_target, sim/engine.py:Battle._waypoint.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-hasty-pathing`:** Current static flow-field and local dynamic obstacle behavior are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** No measured pull map; this remains a primary RL uncertainty.
- **Needed experiment:** PULL-001 Hog/Giant/Balloon versus Cannon tile sweep

## pathing.obstacle_cost

- **Current HastyCR:** Static terrain flow field plus local dynamic-building perpendicular steering.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, giant, hog_rider, skeletons, prince, valkyrie, fisherman, minipekka, battle_ram.
- **Implementation:** sim/engine.py:Battle._avoid_buildings, sim/engine.py:Battle._waypoint, sim/pathfind.py.
- **Evidence `ev-hasty-pathing`:** Current static flow-field and local dynamic obstacle behavior are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-pathing`:** Independent engines use A-star, arena flow/routing, or local obstacle helpers; behavior has not been normalized/executed. Source: Jason-XII simulator pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: static flow field plus local perpendicular steering; CRForge: arena-aware physics/pathing; CR Rudy: bridge-aware deterministic routing; Jason: A-star/walkability; Sam: bridge/pathfinding modules. Severity `HIGH`, RL impact `HIGH`.
- **Conclusion:** Dynamic obstacle routing is implementation-defined and cross-engine architectures differ.
- **Needed experiment:** PATH-001 controlled obstacle offsets and trajectories

## projectile.homing

- **Current HastyCR:** Homing shots follow target identity; non-homing shots retain launch geometry.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** musketeer, cannon, xbow.
- **Implementation:** sim/entities.py:Entity.projectile_homing, sim/engine.py:Battle._resolve_projectiles.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Flag is source-backed; target-loss and moving-target parity need observation.
- **Needed experiment:** PROJECTILE-003 target moves/dies during flight

## projectile.interception

- **Current HastyCR:** Only explicit source-declared reflection/deflection subsets intercept tracked projectiles.
- **Status:** `HYPOTHESIS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** fireball, musketeer.
- **Implementation:** sim/engine.py:Battle._reflect, sim/engine.py:Battle._resolve_projectiles.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Special-case coverage is partial and shared interception semantics unresolved.
- **Needed experiment:** PROJECTILE-005 controlled Monk/deflector trajectories

## projectile.radius

- **Current HastyCR:** Area/splash radii are source fields evaluated at impact.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** fireball, log, cannon, xbow.
- **Implementation:** sim/entities.py:Entity.splash_radius_mt, sim/engine.py:Battle._deal_damage.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Data-backed radius does not settle center/contact or swept-boundary semantics.
- **Needed experiment:** PROJECTILE-002 radial target boundary sweep

## projectile.spawn_offset

- **Current HastyCR:** Generic flight distance is computed from attacker/target positions with no calibrated visual muzzle offset.
- **Status:** `UNKNOWN`; confidence `NONE`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** musketeer, cannon, xbow, fireball.
- **Implementation:** sim/engine.py:Battle._deal_damage, sim/engine.py:Battle._resolve_projectiles.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Unknown shared launch geometry.
- **Needed experiment:** PROJECTILE-001 launch contact-point and impact annotation

## projectile.speed

- **Current HastyCR:** Source projectile speed determines integer flight time from launch gap.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** musketeer, cannon, xbow, fireball.
- **Implementation:** sim/entities.py:Entity.projectile_speed_mt_per_sec, sim/engine.py:Battle._deal_damage.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Value is source-backed; visual trajectory/quantization parity is unmeasured.
- **Needed experiment:** PROJECTILE-001 multiple known launch distances

## projectile.swept_collision

- **Current HastyCR:** Generic projectiles resolve scheduled impacts; rolling spells use separate movement/hit logic.
- **Status:** `UNKNOWN`; confidence `NONE`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** fireball, log.
- **Implementation:** sim/engine.py:Battle._resolve_projectiles, sim/engine.py:Battle._tick_rolling_spells.
- **Evidence `ev-hasty-projectile`:** Current scheduled generic flight, homing, rolling-spell, area, and reflection subsets are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-projectile`:** External engines stage projectiles differently; no current live observation selects a procedure. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: scheduled generic impacts and separate rolling-spell geometry; CRForge: combat-owned projectile system; CR Rudy: separate projectile stage after troop combat. Severity `MEDIUM`, RL impact `MEDIUM`.
- **Conclusion:** No unified swept-collision model is established.
- **Needed experiment:** PROJECTILE-004 crossing target at high relative speed

## spawn.deploy_delay

- **Current HastyCR:** Deploy remaining time gates active targeting/movement/attack.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** skeletons, minions, cannon, fisherman.
- **Implementation:** sim/match.py:Match.play_card, sim/engine.py:Battle.step.
- **Evidence `ev-hasty-spawn`:** Current deployment activation, group insertion, and formation procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Source delays exist; first-active phase and visual spawn timing need measurement.
- **Needed experiment:** SPAWN-001 deploy frame to first movement/attack

## spawn.multi_unit_stagger

- **Current HastyCR:** Members of a deployment group are added sequentially in one action; no generic temporal stagger is modeled.
- **Status:** `UNKNOWN`; confidence `NONE`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** skeletons, minions.
- **Implementation:** sim/match.py:Match.play_card, sim/engine.py:Battle.add.
- **Evidence `ev-hasty-spawn`:** Current deployment activation, group insertion, and formation procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Potentially important swarm timing is unknown.
- **Needed experiment:** SPAWN-002 frame-by-frame multi-unit appearance/activity

## spawn.position_pattern

- **Current HastyCR:** Summon count/radius are source-backed; members are evenly distributed around a circle.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** skeletons, minions.
- **Implementation:** sim/match.py:Match._formation_offset.
- **Evidence `ev-hasty-spawn`:** Current deployment activation, group insertion, and formation procedures are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Radius is data-backed but angular ordering/orientation is an implementation interpretation.
- **Needed experiment:** SPAWN-003 mirrored formation ground-point annotation

## targeting.effective_distance

- **Current HastyCR:** Target acquisition subtracts target collision radius; attack reach adds target collision radius but not attacker radius.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, balloon.
- **Implementation:** sim/engine.py:Battle._acquire_target, sim/engine.py:Battle._attack.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-target-distance`:** Independent implementations use differing center/edge adjusted distance conventions; executable boundary comparison is pending. Source: CRForge pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: target-edge gap for sight; target radius added to attack reach; CRForge: physics/vector distance conventions require executable normalization; CR Rudy: integer staged targeting; exact edge adjustment requires executable normalization. Severity `HIGH`, RL impact `HIGH`.
- **Conclusion:** Fundamental shared geometry is unresolved and simulators use differing conventions.
- **Needed experiment:** TARGET-001 plus ATTACK-001 center/edge distance isolation

## targeting.retarget_interval

- **Current HastyCR:** Periodic full scan staggered by UID; current constant is implementation-defined.
- **Status:** `LEGACY_GUESS`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, balloon.
- **Implementation:** sim/engine.py:RETARGET_INTERVAL_MS, sim/engine.py:Battle._acquire_target.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** High-frequency shared timing has no direct evidence.
- **Needed experiment:** TARGET-003 frame-accurate distractor entry sweep

## targeting.sight_range

- **Current HastyCR:** Candidate edge gap must be within source sight range; fallback building/tower may be outside sight as destination.
- **Status:** `VERIFIED_CURRENT_DATA`; confidence `MEDIUM`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow, balloon.
- **Implementation:** sim/engine.py:Battle._acquire_target, sim/entities.py:Entity.sight_range_mt.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Conclusion:** Field is current-data-backed; edge-distance semantics are not observed.
- **Needed experiment:** TARGET-001 radial distractor boundary sweep

## targeting.target_stickiness

- **Current HastyCR:** Valid current target is retained between periodic scans; some units clear it after attack via RetargetAfterAttack.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow.
- **Implementation:** sim/engine.py:Battle._acquire_target.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-target-order`:** Staged targeting and sticky-target concepts exist independently, but exact tie rules have not been reproduced. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Conclusion:** Sticky behavior exists but timing and RetargetAfterAttack semantics are inferred.
- **Needed experiment:** TARGET-002 crossing distractors before/after hit

## targeting.tie_breaking

- **Current HastyCR:** Strictly smaller edge gap wins; exact ties retain first entity insertion order.
- **Status:** `SINGLE_IMPLEMENTATION`; confidence `LOW`; measurement `UNMEASURED_LIVE`.
- **Affected cards:** knight, musketeer, giant, hog_rider, cannon, xbow.
- **Implementation:** sim/engine.py:Battle._acquire_target.
- **Evidence `ev-hasty-targeting`:** Current candidate filtering, edge-gap distance, periodic scan, fallback, stickiness, and tie procedure are directly observed in code. Source: HastyCR current engine implementation; `SINGLE_IMPLEMENTATION` / `HIGH`.
- **Evidence `ev-cross-target-order`:** Staged targeting and sticky-target concepts exist independently, but exact tie rules have not been reproduced. Source: clash-royale-suite / CR Rudy pinned implementation; `HYPOTHESIS` / `LOW`.
- **Disagreement:** HastyCR: first insertion order on exact gap tie; CR Rudy: stable integer stage; exact tie unverified; Jason/Sam: collection/entity update order may decide. Severity `MEDIUM`, RL impact `MEDIUM`.
- **Conclusion:** Insertion-order tie behavior is deterministic but may be externally meaningless or exploitable.
- **Needed experiment:** TARGET-004 symmetric equidistant target pair

## Database checkpoint

- Mechanics: 31
- Parameters: 31
- Evidence records: 16
- Disagreements: 6
- Real measured traces: **0**

