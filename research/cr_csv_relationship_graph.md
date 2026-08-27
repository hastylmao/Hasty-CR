# cr-csv relationship graph

The graph is inferred from column names and matching textual keys at revision `899e45efc765fbf3902927bb2e37dc04a78f7823`. It is not an upstream-declared relational schema.

```text
spells_characters.SummonCharacter ─┐
spells_buildings.SummonCharacter ──┼──> characters.Name / buildings.Name
spells_*.SummonCharacterSecond ─────┘

characters.Projectile / ProjectileSpecial / CustomFirstProjectile ──> projectiles.Name
buildings.Projectile / SpawnProjectile / DeathSpawnProjectile ───────> projectiles.Name
spells_*.Projectile / CustomFirstProjectile ─────────────────────────> projectiles.Name

characters.AreaBuff / StartingBuff / BuffOnDamage / BuffOnKill ─────> character_buffs.Name
area_effect_objects.Buff ─────────────────────────────────────────────> character_buffs.Name
projectiles.TargetBuff ───────────────────────────────────────────────> character_buffs.Name

spells_*.AreaEffectObject / characters.AreaEffectOnDash ─────────────> area_effect_objects.Name
projectiles.SpawnAreaEffectObject ────────────────────────────────────> area_effect_objects.Name
area_effect_objects.SpawnAreaEffectObject ───────────────────────────> area_effect_objects.Name

characters.SpawnCharacter / DeathSpawnCharacter / MorphCharacter ───> characters.Name
buildings.SpawnCharacter / DeathSpawnCharacter / AttachedCharacter ─> characters.Name
area_effect_objects.SpawnCharacter / DeathSpawnCharacter ────────────> characters.Name
character_buffs.SpawnObject / MorphTarget / DeathSpawn ──────────────> character/buff keys (ambiguous)

game_modes.BattleTimeline ────────────────────────────────────────────> battle_timelines.Name
game_modes.FixedArena ────────────────────────────────────────────────> arenas.Name or locations.Name (ambiguous)
arenas.PvpLocation / TeamVsTeamLocation ─────────────────────────────> locations.Name
locations.TileDataFileName ───────────────────────────────────────────> tilemaps or locations asset filename

spells_*.Rarity / characters.Rarity / buildings.Rarity ──────────────> rarities.Name
spells_*.UnlockArena ─────────────────────────────────────────────────> arenas.Name
```

## Relationship cautions

- There are no explicit foreign-key constraints; names can be blank, reused, version-dependent, or point across category tables.
- Some references are polymorphic (`SpawnObject`, fixed arena/location fields), and suffixes such as variants/evolutions may require alias resolution.
- Multiple numbered fields represent lists or ordered fallbacks; preserving order matters.
- Asset-file references bridge logic and client directories but do not imply permission to redistribute assets.
- A robust importer should preserve raw text, source file/row, unresolved references, and conversion uncertainty rather than silently dropping unmatched keys.
- NoxCardEditor independently demonstrates a practical `Name`/TID association convention, but its first-row joins and incomplete inbound-reference handling are editor behavior rather than schema authority. See [`nox_card_editor_schema_analysis.md`](nox_card_editor_schema_analysis.md).

## Suggested clean-room normalized model

Use independently designed records for `CardDefinition`, `EntityDefinition`, `ProjectileDefinition`, `AreaEffectDefinition`, `BuffDefinition`, `TimelineDefinition`, and `ArenaDefinition`, connected by typed reference IDs plus provenance. This is a design inference; do not copy the CSV's broad row layout into HastyCR.