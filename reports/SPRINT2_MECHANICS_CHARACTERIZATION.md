# Sprint 2 Mechanics Characterization

Generated from bounded deterministic HastyCR probes. This is simulator-only evidence, not live-game truth.

- Schema: `mechanics-characterization-v1`
- Status: `PASS`
- Probes: `6`
- Tick: `50 ms`
- Real measurements: `0`
- Report SHA-256: `cbb5dc71ccee595c738f86951f439c3b8c5a5f859e35d7a390efdb0c7c622601`

## Results

| Probe | Category | Current simulator observation |
|---|---|---|
| `TARGET-001` | `targeting` | `{"acquisition":{"event_type":"target_acquired","metadata":{"previous_target_uid":null,"sight_mt":5500,"windup_ms":0},"order":4,"phase":"targeting","reason":"visible_nearest","source_uid":1,"target_uid":2,"tick":1,"time_ms":50,"value":1000},"candidate_positions":{"2":[9500,19500],"3":[11500,20500]},"target_name":null,"target_uid":2}` |
| `PATH-001` | `pathing` | `{"bridge_contact_samples":[],"crossed_river":true,"final_position":[10085,9194],"first_waypoint":[9500,23500],"movement_events":461,"river_y_end":7500,"river_y_start":24500,"unique_position_samples":[[0,9500,24500],[50,9500,24463],[100,9500,24426],[150,9500,24389],[200,9500,24352],[22850,10137,9334],[22900,10124,9299],[22950,10111,9264],[23000,10098,9229],[23050,10085,9194]]}` |
| `COLLISION-001` | `collision` | `{"contact_events":1,"final_gap_mt":1250,"final_positions":{"1":[9435,20500],"2":[10685,20500]},"first_contact":{"first_after":[9435,20500],"first_before":[9500,20500],"first_uid":1,"gap_mt":0,"kind":"troop_contact","required_gap_mt":1250,"resolved_overlap_mt":1250,"second_after":[10685,20500],"second_before":[9500,20500],"second_uid":2,"time_ms":50},"nonoverlap":true,"required_gap_mt":1250}` |
| `TIMING-001` | `event_order` | `{"key_events":[{"event_type":"attack","metadata":{"gap_mt":0,"reach_mt":1700},"order":6,"phase":"attack","reason":"hit_cycle","source_uid":1,"target_uid":2,"tick":1,"time_ms":50,"value":1200},{"event_type":"damage","order":7,"phase":"attack","reason":"damage_log","source_uid":1,"target_uid":2,"tick":1,"time_ms":50,"value":1},{"event_type":"death","metadata":{"name":"skeleton","spawn_character":"","spawn_count":0},"order":11,"phase":"cleanup","reason":"lethal_or_expired","source_uid":2,"tick":1,"time_ms":50,"value":0},{"event_type":"cleanup","metadata":{"name":"skeleton"},"order":12,"phase":"cleanup","reason":"dead_entity_removed","source_uid":2,"tick":1,"time_ms":50}],"phase_order":["tick","scheduled_effects","deploy","targeting","attack","movement","collision","cleanup"],"target_removed":true}` |
| `PROJECTILE-001` | `attack_timing` | `{"damage_count":2,"first_damage":{"event_type":"damage","order":3,"phase":"scheduled_effects","reason":"damage_log","source_uid":1,"target_uid":2,"tick":9,"time_ms":450,"value":218},"first_launch":{"event_type":"projectile_launch","metadata":{"aim":[15500,20500],"arrival_ms":410,"speed_mt_per_sec":16666,"start":[9500,20500]},"order":7,"phase":"attack","reason":"homing","source_uid":1,"target_uid":2,"tick":1,"time_ms":50,"value":218},"launch_count":2}` |
| `SPAWN-001` | `death_spawn` | `{"event_sequence":[{"event_type":"spawn","metadata":{"group_uid":1,"name":"golem","owner_uid":0,"side":1},"order":0,"phase":"external","reason":"battle_add","source_uid":1,"tick":0,"time_ms":0},{"event_type":"death","metadata":{"name":"golem","spawn_character":"Golemite","spawn_count":2},"order":8,"phase":"cleanup","reason":"lethal_or_expired","source_uid":1,"tick":1,"time_ms":50,"value":0},{"event_type":"spawn","metadata":{"group_uid":1,"name":"golemite","owner_uid":1,"side":1},"order":9,"phase":"cleanup","reason":"battle_add","source_uid":2,"tick":1,"time_ms":50},{"event_type":"spawn","metadata":{"group_uid":1,"name":"golemite","owner_uid":1,"side":1},"order":10,"phase":"cleanup","reason":"battle_add","source_uid":3,"tick":1,"time_ms":50},{"event_type":"cleanup","metadata":{"name":"golem"},"order":11,"phase":"cleanup","reason":"dead_entity_removed","source_uid":1,"tick":1,"time_ms":50}],"living_names_after":["golemite","golemite"],"parent_removed":true}` |

## Interpretation

- Targeting uses current visible-candidate edge-gap selection and reports acquisition reasons through diagnostics.
- Ground cross-river movement uses the current cached bridge-aware flow field; dynamic buildings use local steering and collision push-out.
- Collision probes confirm current non-overlap behavior and expose the current mass-weighted solver output, not live collision semantics.
- Same-tick diagnostics expose the current phase order and death-before-cleanup behavior.
- Projectile timestamps are current fixed-tick scheduling behavior and require live target-motion observations before calibration.

## Boundary

The probes do not change `real_measurements=0`, do not produce an accuracy scalar, and do not move HastyCR to RL-ready status.
