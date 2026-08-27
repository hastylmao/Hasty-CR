# NoxCardEditor schema and relationship analysis

Inspected revision: `be08c7ffcdea8a6611f551620d76a692e2b3a118` (2026-03-10). Upstream: https://github.com/EnderNox/NoxCardEditor. This is private-server tooling, so its behavior is useful schema evidence but not authoritative Clash data or live-mechanics truth.

## Scope and license

- The README explicitly targets **Clash Royale Private Server** developers and expects decrypted server CSV inputs.
- The editor code is MIT licensed, copyright 2026 EnderNox.
- The MIT license covers the repository's software; it does not establish a license for user-supplied/decrypted CSV data, game assets, or generated server content.
- No Nox code or input data was copied into HastyCR. The analysis records concepts and limitations only.

## CSV interpretation

`DataManager.load_data` reads seven expected files with pandas and `header=None`:

| Category | Logic file | Spell/meta file |
|---|---|---|
| Characters | `characters.csv` | `spells_characters.csv` |
| Buildings | `buildings.csv` | `spells_buildings.csv` |
| Spells | `spells_other.csv` | `spells_other.csv` |
| Projectiles | `projectiles.csv` | none |

The remaining file is `texts.csv`. CSV row 1 becomes the column header, row 2 becomes the parallel declared-type list, and rows 3 onward become data. Load exceptions are silently swallowed, so an absent/malformed table can disappear without a diagnostic.

## Exact join semantics

- Logic and spell/meta rows join by textual, case-sensitive equality on `Name`.
- `get_combined_data` selects only `rows.iloc[0]` from each file; duplicate names are neither rejected nor combined.
- Localization resolves a `TID` or `TID_INFO` by equality against the **first column** of `texts.csv`; it takes the requested language column when present, otherwise the second column, and again returns only the first match.
- Characters/buildings therefore form an application-level three-way association: spell `Name` ↔ logic `Name`, then spell/logic `TID` and spell `TID_INFO` ↔ localization key.
- Spells map logic and spell to the same `spells_other.csv`. Both read paths can therefore describe the same first row, and add/delete paths operate on the same dataframe twice.
- Projectiles have no spell/meta association in `file_map`; only their logic row and optional direct `TID` cleanup are managed.

These are editor conventions, not declared foreign keys. They do not prove global uniqueness, referential integrity, polymorphic target rules, or engine lookup behavior.

## Field categorization

The V3 UI's curated groups provide useful vocabulary for schema discovery:

| Group | Fields |
|---|---|
| Combat | `Hitpoints`, `Damage`, `HitSpeed`, `Speed`, `Range`, `MinimumRange`, `DamageSpecial`, `AreaDamageRadius`, `TargetsAir`, `TargetsGround` |
| Deployment/physics | `DeployTime`, `SightRange`, `CollisionRadius`, `Mass`, `Scale` |
| Death | `DeathDamage`, `DeathDamageRadius`, `DeathEffect`, `DeathSpawnCharacter`, `DeathSpawnCount` |
| Summon/spawn | `SpawnCharacter`, `SpawnNumber`, `SpawnInterval`, `SpawnLimit` |

The group labels are UI organization. They are not evidence of units, defaults, formulas, execution order, or server/client authority.

## CRUD and integrity limitations

- `add_card_common` appends localization rows and logic/spell rows without checking for an existing `Name` or TID. Duplicate mode copies only the first same-name source row.
- For a new row, unspecified columns remain null/blank. The editor does not enforce required fields, declared types, or cross-table constraints before append.
- `delete_card` removes every same-name row from mapped logic/spell dataframes and the TID rows directly discovered there. It does not scan inbound references from entities, projectiles, area effects, buffs, game modes, or other tables.
- Because Spells use one dataframe as both logic and spell, deletion and addition run twice against the same mapped table. The second delete is normally empty; addition can append duplicate same-name rows.
- Renaming a `Name`, `TID`, or `TID_INFO` through generic cell editing does not cascade to references or localization keys.
- `set_text` updates only the first matching localization key and only when the requested language column exists.
- Missing files and parser errors can be ignored by `load_data`, while `save_all` writes only loaded tables; this is not transactional multi-file persistence.

## Serialization behavior

`save_all` reconstructs every loaded file rather than preserving original bytes:

- Header and type cells are always double-quoted.
- Null, empty, and `nan` values become unquoted blanks.
- Boolean fields emit quoted `"true"` only for case-insensitive `true`; every other non-empty boolean value becomes blank.
- Integer-like declared fields are emitted unquoted only when their string is an optional minus sign plus digits.
- All other non-empty values are wrapped in double quotes without explicit embedded-quote escaping.
- Original quoting, line endings, numeric lexical form, whitespace, and unknown formatting distinctions are not retained.

This can be appropriate for a specific private-server parser, but it is not byte-preserving round-trip evidence for official files.

## Clean-room conclusion

NoxCardEditor corroborates that name-based card/entity/spell/localization associations are operationally useful and that combat/deploy/death/spawn fields form practical study groups. Its first-row joins, incomplete inbound-reference handling, private-server scope, and normalizing serializer prevent promotion to an authoritative relational schema. Historical/private values remain study-only, and real measured Clash traces remain **ZERO**.
