# Historical data gems and calibration leads

These are candidate measurements discovered in historical `cr-csv` schemas, not verified current values. Every promoted parameter needs current provenance and observed-behavior validation.

| Candidate field family | Historical source | Potential fidelity use | Required validation |
|---|---|---|---|
| `CollisionRadius`, `Mass`, `Scale`, `TileSizeOverride` | [characters/buildings](../_references/cr-csv/assets/csv_logic/characters.csv) | Contact geometry, pair push weighting, building footprint | Establish units/version; compare live contact traces |
| `LoadTime`, `HitSpeed`, `StopTimeAfterAttack`, `AttackFinishTime` | characters/buildings | Windup, cooldown, backswing and animation lock | Separate visual timing from damage event; level/card tests |
| `LoadAfterRetarget`, `RetargetEachTick`, `RetargetAfterAttack` | characters/buildings | Target state-machine transitions | Controlled distract/retarget probes |
| `SightRange`, `Range`, `MinimumRange`, target-only flags | characters/buildings | Acquisition and attack boundaries | Hitbox-edge versus center-distance interpretation |
| `ProjectileStartRadius/Z`, speed, homing, radius, collision flags | [projectiles](../_references/cr-csv/assets/csv_logic/projectiles.csv) | Launch origin, travel, impact and collision | Camera mapping; units; homing target-loss behavior |
| `Pushback`, `PushMassFactor`, `PushSpeedFactor`, drag fields | projectiles/buffs/entities | Knockback and attraction calibration | Direction, duration, mass scaling, obstacle interaction |
| `SpawnRadius`, counts, angle shift, max angle, deployment delay | spells/entities/AoE | Formation geometry and stagger | Team orientation, RNG/tie rules, exact spawn timestamps |
| `DeathSpawn*`, `DeathAreaEffect`, `DeathSpawnDeployTime` | entities/AoE/buffs | Death ordering and spawned-unit lifecycle | Simultaneous lethal/AoE/projectile tests |
| `Dash*`, `JumpSpeed`, `ChargeSpeedMultiplier` | characters/buildings | Discrete movement state machines | Activation threshold, collision layer, invulnerability window |
| `BuffTime`, multipliers, DOT/HOT frequency, stacking/chaining | [character_buffs](../_references/cr-csv/assets/csv_logic/character_buffs.csv) | Status timing and effect composition | Tick alignment, refresh/stack policy, tower modifiers |
| `LifeDuration`, `HitSpeedOffset`, `FirstHitToTarget` | [area effects](../_references/cr-csv/assets/csv_logic/area_effect_objects.csv) | Zone first tick, cadence and expiration | Boundary-frame observations |
| Timeline elixir and event fields | [battle timelines](../_references/cr-csv/assets/csv_logic/battle_timelines.csv) | Match phase and elixir schedule hypotheses | Current mode/version and clock semantics |
| `BattleStartCooldown`, `Overtime`, `TripleElixir`, spawn mode fields | [game modes](../_references/cr-csv/assets/csv_logic/game_modes.csv) | Scenario configuration and nonstandard modes | Never apply mode-specific fields to standard ladder by default |
| `TileDataFileName` and tilemap assets | [locations](../_references/cr-csv/assets/csv_logic/locations.csv) | Historical map geometry/obstacle hypotheses | Provenance, coordinate orientation, current arena comparison |
| `ReleaseDate`, visibility, unlock fields | spells tables | Version chronology and inactive-content filtering | Git/tag snapshot comparison; do not infer mechanics accuracy |

## Highest-value next analysis

1. Build a tag-to-tag schema diff without copying data into production.
2. Record field presence/change history separately from values.
3. Compare candidate fields to current RoyaleAPI/HastyCR source-backed data with provenance per field.
4. Design live probes for timing, radius/contact, projectile travel, and event ordering.
5. Keep unresolved blanks/defaults explicit; never invent conversion constants.

The historical breadth is a discovery index, not a calibration result.