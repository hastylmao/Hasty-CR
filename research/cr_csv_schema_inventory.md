# cr-csv schema inventory

Repository revision: `899e45efc765fbf3902927bb2e37dc04a78f7823`, commit dated 2023-03-28. No license/provenance metadata was found; all content is study-only. Upstream: https://github.com/smlbiobot/cr-csv.

## Version history

Tags observed: `2.0.1` (2017-10), `2.1.5` (2017-12), `2.2.1` (2018-04), `3.2.1` (2018-09), `2018-10`, `3.1354_enterprise`, `2.5.0` (2018-12), `2019-02-04`, `2019-04`, and `2020-07-07-balance`. The nearest/latest tag is `2020-07-07-balance`; HEAD is 45 commits later and untagged. Tag names are inconsistent and must not be treated as a reliable semantic-version line.

Sprint 2 now inventories every asset-changing commit plus every tagged tree without checkout mutation. The deterministic outputs live under [`research/csv_history/`](csv_history/): 92 canonical historical snapshots, including 91 first-parent asset-changing snapshots and the otherwise-missing `3.2.1` tagged merge tree. The overlapping `walle-d/cr-csv` tags are aliases of the same commit objects and are marked duplicate lineage rather than counted as independent evidence. See [`LONGITUDINAL_SCHEMA_ARCHAEOLOGY.md`](csv_history/LONGITUDINAL_SCHEMA_ARCHAEOLOGY.md) and [`version_inventory.csv`](csv_history/version_inventory.csv).

## Asset families

| Directory | Files | Approx bytes | Role inferred from names |
|---|---:|---:|---|
| [csv_logic](../_references/cr-csv/assets/csv_logic/) | 73 CSV | 1,471,316 | Mechanics, cards, game modes, rewards, progression |
| [csv_client](../_references/cr-csv/assets/csv_client/) | 25 CSV | 7,750,648 | Client assets/localization/config references |
| [locations](../_references/cr-csv/assets/locations/) | 91 CSV | 299,214 | Per-location/map data fragments |
| [tilemaps](../_references/cr-csv/assets/tilemaps/) | 12 CSV | 53,311 | Tile/grid layout data |

## High-value logic tables at HEAD

| Table | Rows | Columns | Mechanics-relevant field groups |
|---|---:|---:|---|
| [characters.csv](../_references/cr-csv/assets/csv_logic/characters.csv) | 114 | 336 | target/range, deploy/load/hit timing, speed, HP/damage, radius/mass, projectiles, buffs, dash/jump, spawn/death spawn, morph, abilities, retargeting |
| [buildings.csv](../_references/cr-csv/assets/csv_logic/buildings.csv) | 70 | 336 | same broad entity schema plus lifetime, spawners, turret/building targeting |
| [projectiles.csv](../_references/cr-csv/assets/csv_logic/projectiles.csv) | 92 | 98 | speed/homing, radius, air/ground, pushback, buffs, chain/drag/scatter, collision/deflection |
| [spells_characters.csv](../_references/cr-csv/assets/csv_logic/spells_characters.csv) | 95 | 83 | cost, summon references/count/formation/delay, deployment bounds, hero/passive fields, release date |
| [spells_buildings.csv](../_references/cr-csv/assets/csv_logic/spells_buildings.csv) | 18 | 83 | card-to-building summon and placement fields |
| [spells_other.csv](../_references/cr-csv/assets/csv_logic/spells_other.csv) | 22 | 83 | projectile/AoE/heal/buff and placement fields |
| [area_effect_objects.csv](../_references/cr-csv/assets/csv_logic/area_effect_objects.csv) | 55 | 66 | duration/tick timing, radius, damage/buff, spawn/death/deflection/follow behavior |
| [character_buffs.csv](../_references/cr-csv/assets/csv_logic/character_buffs.csv) | 48 | 72 | multipliers, DOT/HOT, invisibility, push factors, chaining, clone/shield/jump/morph/team switch |
| [battle_timelines.csv](../_references/cr-csv/assets/csv_logic/battle_timelines.csv) | 43 | 15 | phase length/type/flags, starting elixir, elixir rate, cooldown and timed events |
| [game_modes.csv](../_references/cr-csv/assets/csv_logic/game_modes.csv) | 433 | 90 | timeline references, deck rules, towers, global buffs, spawns, elixir and overtime variants |
| [locations.csv](../_references/cr-csv/assets/csv_logic/locations.csv) | 96 | 42 | tile-data reference, win condition, effects/music, location metadata |

## Schema observations

- `characters.csv` and `buildings.csv` share the same 336-column shape, suggesting one broad entity schema split by category.
- Card rows reference entity rows by textual names (`SummonCharacter`, secondary summons), projectiles (`Projectile`, `CustomFirstProjectile`), area effects, and buffs.
- Multiple repeated/secondary fields encode ordered or alternate behavior without a normalized child table.
- Units appear mixed: timings are often milliseconds, spatial values appear scaled integer units, booleans may be blank, and some fields are percentages. Conversion rules are not contained in the CSV schema.
- Blank does not safely mean zero or false; it may mean inherit/default/not applicable.
- Row count includes historical/unused/special entities and must not be equated to playable card count.

## Safety conclusion

The schema is exceptionally useful for discovering candidate mechanics and relationships, but not safe as an authoritative or redistributable dataset. Before using any field, require provenance, version mapping, unit interpretation, current-source corroboration, and behavior validation.