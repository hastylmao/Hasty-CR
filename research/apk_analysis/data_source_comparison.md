# Data source comparison

Generated: `2026-08-23T20:02:09.659880+00:00`

Static clean-room analysis only. APK code and native libraries were never executed. Raw proprietary bytes remain ignored under `_references/apk_analysis/`.

Comparisons use case-insensitive exact string equality for names/schema identifiers found in DEX, selected assets/resources, and native strings. A match establishes shared vocabulary only.

| APK | cr-csv names | cr-csv schema | HastyCR names | HastyCR schema | Interpretation |
|---|---:|---:|---:|---:|---|
| clash-royale-mod-15-535-13-an1-com | 93 | 1420 | 172 | 120 | shared official/historical vocabulary |
| master-royale-apk-v3-2729-1 | 27 | 80 | 53 | 45 | shared official/historical vocabulary |
| nr-15-535-13-infinity-da5a0dc4-1 | 93 | 1420 | 172 | 120 | shared official/historical vocabulary |
| nr-15-535-13-infinity-da5a0dc4 | 93 | 1420 | 172 | 120 | shared official/historical vocabulary |

## clash-royale-mod-15-535-13-an1-com

- cr-csv typed entity-name samples: `Archer`, `ArcherQueen`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `ClanWarsSpawnFlareProjectile`, `Clone`, `DarkWitch`, `DummyKingTower`, `DummyKingTower2`, `Earthquake`, `ElectroGiant`, `ElectroSpirit`, `ElixirDrop`, `Firecracker`, `Fisherman`, `Freeze`, `Ghost`, `Giant`, `Goblin`, `GoblinDrill`, `GoblinGiant`, `Goblins`, `GoldenKnight`, `Golem`, `Graveyard`, `Heal`, `HealSpirit`, `HeistStorage`, `HeistStorage3`.
- cr-csv schema samples: `3DAssetPath`, `Ability`, `AbilityPendingEffect`, `AbilityStateDuration`, `Action`, `ActionArgString`, `ActionCount`, `ActionIsEnabled`, `ActionOrder`, `ActionSpawnCount`, `ActionSpawnDelay`, `ActionSpawnLevel`, `ActionSpawnX`, `ActionSpawnY`, `ActionStartCondition`, `ActionType`, `ActivationSpawnCharacter`, `ActivationSpawnDeployTime`, `ActivationTime`, `AffectsHidden`, `AgeRestriction`, `Align`, `AllTargetsHit`, `AllowAreaDmgWhenInvisible`, `AllowInFreeChronosOffers`, `AllowMultipleNewCards`, `AlwaysSpells`, `AmbientSound`, `Amount`, `AndroidID`, `AndroidTID`, `AngularDelay`, `AngularSpeed`, `AnimExportName`, `Animate`, `AnimationPrefix`, `AntiSpellSets`, `AoeToAir`, `AoeToGround`, `AppearAreaObject`.
- HastyCR typed entity-name samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `Champion`, `ClanWarsSpawnFlareProjectile`, `Clone`, `Common`, `DarkWitch`, `DummyKingTower`.
- HastyCR schema samples: `ability`, `aoeToAir`, `aoeToGround`, `archer_ev1`, `arena`, `arrows`, `base`, `blue`, `blueExportName`, `boost`, `boss_bandit`, `buff`, `burst`, `bytes`, `cards`, `clone`, `constantHeight`, `customSpawnFilter`, `damage`, `deathEffect`, `death_spawn`, `deflectBehaviour`, `description`, `earthquake`, `electro_spirit`, `elixir`, `exportName`, `fileName`, `fire_spirits`, `fisherman`, `flags`, `freeze`, `glow`, `goblin_barrel`, `gravity`, `green`, `healthBar`, `height`, `hitEffect`, `hitSpeed`.
- Exact selected-data hash matches against cr-csv/HastyCR: 0/0.

### Bounded entity/data classification

- `official match`: 172 typed identifiers (medium confidence vocabulary match; modification remains possible). Samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`.
- `official historical`: 0; not assigned without version-specific official provenance.
- `modified official`: 30 variant-style identifiers (low confidence). Samples: `AxeMan_crazy_1_tornado`, `AxeMan_crazy_3`, `BabyDragon_crazy_1`, `BabyDragon_crazy_1_Egg`, `BabyDragon_crazy_1_Spawn_Projectile`, `BabyDragon_crazy_1_Spawn_dummy_AEO`, `BabyDragon_crazy_2`, `BarbarianHut_crazy_1`, `BarbarianHut_crazy_2`, `BlowdartGoblin_crazy_2`, `BlowdartGoblin_crazy_3`, `BolaSnare_crazy_1`, `BolaSnare_crazy_2`, `BombTower_crazy_1`, `DarkWitch_crazy_2`, `DarkWitch_crazy_3`, `FishermanProjectile_crazy_1`, `Fisherman_crazy_1`, `GoblinDrillDig_crazy_1`, `GoblinDrillDig_crazy_2`, `GoblinDrillDig_crazy_3`, `GoblinDrill_crazy_1`, `GoblinDrill_crazy_1_Dig`, `GoblinDrill_crazy_2`, `GoblinDrill_crazy_3`, `Pekka_crazy_1`, `RamRider_crazy_1`, `RamRider_crazy_1_bola`, `RamRider_crazy_2`, `RamRider_crazy_2_bola`.
- `custom/private-server`: 0; package provenance alone was not used to label unmatched entities.
- `unknown`: unresolved/unmatched entities were not exhaustively decoded, so no false exhaustive count is claimed.

## master-royale-apk-v3-2729-1

- cr-csv typed entity-name samples: `Archer`, `Barbarians`, `Bats`, `Bomber`, `Bowler`, `CaptureTower`, `Clone`, `Freeze`, `Goblins`, `Graveyard`, `Heal`, `Knight`, `Lightning`, `Log`, `Minion`, `Mirror`, `Pekka`, `Poison`, `Prince`, `Rage`, `Skeletons`, `Snowball`, `Stun`, `Tornado`, `Valkyrie`, `Wallbreaker`, `Wizard`.
- cr-csv schema samples: `Action`, `ActionArgString`, `ActionType`, `Align`, `Amount`, `AndroidID`, `Animate`, `Available`, `Blue`, `BooleanValue`, `Buff`, `CNT`, `Category`, `Channels`, `Character`, `Clone`, `Count`, `Description`, `Disabled`, `DisplayName`, `Dummy`, `DurationMillis`, `Effect`, `Enabled`, `End`, `EventName`, `EventType`, `Exclusive`, `Family`, `FileName`, `Flags`, `FloatValue`, `Gravity`, `Green`, `Heal`, `Height`, `Hidden`, `Icon`, `Invisible`, `IsEnabled`.
- HastyCR typed entity-name samples: `Archer`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Barbarians`, `Bats`, `Bomber`, `Bowler`, `CaptureTower`, `Clone`, `Common`, `Experimental`, `Freeze`, `Goblins`, `Graveyard`, `Heal`, `Knight`, `Lightning`, `Log`, `Minion`, `Mirror`, `P.E.K.K.A`, `Pekka`, `Poison`, `Prince`, `Rage`, `Rare`, `Skeletons`, `Snowball`, `Stun`, `Tornado`, `Valkyrie`, `Wallbreaker`, `Wizard`, `barbarians`, `bats`, `bomber`, `bowler`, `clone`, `freeze`.
- HastyCR schema samples: `base`, `blue`, `buff`, `bytes`, `cards`, `clone`, `description`, `elixir`, `fileName`, `fire_spirits`, `flags`, `freeze`, `gravity`, `green`, `height`, `invisible`, `jump`, `key`, `level`, `lightning`, `log`, `mirror`, `name`, `one`, `poison`, `portal`, `rage`, `range`, `red`, `rules`, `scale`, `schema`, `sha256`, `shape`, `shield`, `snowball`, `sort_order`, `source`, `sources`, `subtitle`.
- Exact selected-data hash matches against cr-csv/HastyCR: 0/0.

### Bounded entity/data classification

- `official match`: 53 typed identifiers (medium confidence vocabulary match; modification remains possible). Samples: `Archer`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Barbarians`, `Bats`, `Bomber`, `Bowler`, `CaptureTower`, `Clone`, `Common`, `Experimental`, `Freeze`, `Goblins`, `Graveyard`, `Heal`, `Knight`, `Lightning`, `Log`, `Minion`, `Mirror`, `P.E.K.K.A`, `Pekka`, `Poison`, `Prince`, `Rage`, `Rare`, `Skeletons`, `Snowball`, `Stun`.
- `official historical`: 0; not assigned without version-specific official provenance.
- `modified official`: 0 variant-style identifiers (low confidence). Samples: none.
- `custom/private-server`: 0; package provenance alone was not used to label unmatched entities.
- `unknown`: unresolved/unmatched entities were not exhaustively decoded, so no false exhaustive count is claimed.

## nr-15-535-13-infinity-da5a0dc4-1

- cr-csv typed entity-name samples: `Archer`, `ArcherQueen`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `ClanWarsSpawnFlareProjectile`, `Clone`, `DarkWitch`, `DummyKingTower`, `DummyKingTower2`, `Earthquake`, `ElectroGiant`, `ElectroSpirit`, `ElixirDrop`, `Firecracker`, `Fisherman`, `Freeze`, `Ghost`, `Giant`, `Goblin`, `GoblinDrill`, `GoblinGiant`, `Goblins`, `GoldenKnight`, `Golem`, `Graveyard`, `Heal`, `HealSpirit`, `HeistStorage`, `HeistStorage3`.
- cr-csv schema samples: `3DAssetPath`, `Ability`, `AbilityPendingEffect`, `AbilityStateDuration`, `Action`, `ActionArgString`, `ActionCount`, `ActionIsEnabled`, `ActionOrder`, `ActionSpawnCount`, `ActionSpawnDelay`, `ActionSpawnLevel`, `ActionSpawnX`, `ActionSpawnY`, `ActionStartCondition`, `ActionType`, `ActivationSpawnCharacter`, `ActivationSpawnDeployTime`, `ActivationTime`, `AffectsHidden`, `AgeRestriction`, `Align`, `AllTargetsHit`, `AllowAreaDmgWhenInvisible`, `AllowInFreeChronosOffers`, `AllowMultipleNewCards`, `AlwaysSpells`, `AmbientSound`, `Amount`, `AndroidID`, `AndroidTID`, `AngularDelay`, `AngularSpeed`, `AnimExportName`, `Animate`, `AnimationPrefix`, `AntiSpellSets`, `AoeToAir`, `AoeToGround`, `AppearAreaObject`.
- HastyCR typed entity-name samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `Champion`, `ClanWarsSpawnFlareProjectile`, `Clone`, `Common`, `DarkWitch`, `DummyKingTower`.
- HastyCR schema samples: `ability`, `aoeToAir`, `aoeToGround`, `archer_ev1`, `arena`, `arrows`, `base`, `blue`, `blueExportName`, `boost`, `boss_bandit`, `buff`, `burst`, `bytes`, `cards`, `clone`, `constantHeight`, `customSpawnFilter`, `damage`, `deathEffect`, `death_spawn`, `deflectBehaviour`, `description`, `earthquake`, `electro_spirit`, `elixir`, `exportName`, `fileName`, `fire_spirits`, `fisherman`, `flags`, `freeze`, `glow`, `goblin_barrel`, `gravity`, `green`, `healthBar`, `height`, `hitEffect`, `hitSpeed`.
- Exact selected-data hash matches against cr-csv/HastyCR: 0/0.

### Bounded entity/data classification

- `official match`: 172 typed identifiers (medium confidence vocabulary match; modification remains possible). Samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`.
- `official historical`: 0; not assigned without version-specific official provenance.
- `modified official`: 36 variant-style identifiers (low confidence). Samples: `AngryBarbarian_crazy_3_as_melee`, `AngryBarbarian_crazy_3_retarget`, `AngryBarbarian_crazy_3_set_has_projectile_false`, `AngryBarbarian_crazy_3_set_melee_attack`, `AngryBarbarian_crazy_3_timer_action`, `AxeMan_crazy_1_tornado`, `AxeMan_crazy_3`, `BabyDragon_crazy_1`, `BabyDragon_crazy_1_Egg`, `BabyDragon_crazy_1_Spawn_Projectile`, `BabyDragon_crazy_1_Spawn_dummy_AEO`, `BabyDragon_crazy_2`, `BarbarianHut_crazy_1`, `BarbarianHut_crazy_2`, `BlowdartGoblin_crazy_2`, `BlowdartGoblin_crazy_3`, `BolaSnare_crazy_1`, `BolaSnare_crazy_2`, `BombTower_crazy_1`, `DarkWitch_crazy_2`, `DarkWitch_crazy_3`, `Firecracker_crazy_3`, `FishermanProjectile_crazy_1`, `Fisherman_crazy_1`, `GoblinDrillDig_crazy_1`, `GoblinDrillDig_crazy_2`, `GoblinDrillDig_crazy_3`, `GoblinDrill_crazy_1`, `GoblinDrill_crazy_1_Dig`, `GoblinDrill_crazy_2`.
- `custom/private-server`: 0; package provenance alone was not used to label unmatched entities.
- `unknown`: unresolved/unmatched entities were not exhaustively decoded, so no false exhaustive count is claimed.

## nr-15-535-13-infinity-da5a0dc4

- cr-csv typed entity-name samples: `Archer`, `ArcherQueen`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `ClanWarsSpawnFlareProjectile`, `Clone`, `DarkWitch`, `DummyKingTower`, `DummyKingTower2`, `Earthquake`, `ElectroGiant`, `ElectroSpirit`, `ElixirDrop`, `Firecracker`, `Fisherman`, `Freeze`, `Ghost`, `Giant`, `Goblin`, `GoblinDrill`, `GoblinGiant`, `Goblins`, `GoldenKnight`, `Golem`, `Graveyard`, `Heal`, `HealSpirit`, `HeistStorage`, `HeistStorage3`.
- cr-csv schema samples: `3DAssetPath`, `Ability`, `AbilityPendingEffect`, `AbilityStateDuration`, `Action`, `ActionArgString`, `ActionCount`, `ActionIsEnabled`, `ActionOrder`, `ActionSpawnCount`, `ActionSpawnDelay`, `ActionSpawnLevel`, `ActionSpawnX`, `ActionSpawnY`, `ActionStartCondition`, `ActionType`, `ActivationSpawnCharacter`, `ActivationSpawnDeployTime`, `ActivationTime`, `AffectsHidden`, `AgeRestriction`, `Align`, `AllTargetsHit`, `AllowAreaDmgWhenInvisible`, `AllowInFreeChronosOffers`, `AllowMultipleNewCards`, `AlwaysSpells`, `AmbientSound`, `Amount`, `AndroidID`, `AndroidTID`, `AngularDelay`, `AngularSpeed`, `AnimExportName`, `Animate`, `AnimationPrefix`, `AntiSpellSets`, `AoeToAir`, `AoeToGround`, `AppearAreaObject`.
- HastyCR typed entity-name samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`, `Bowler`, `BowlerProjectile`, `Cannon`, `CaptureTower`, `Champion`, `ClanWarsSpawnFlareProjectile`, `Clone`, `Common`, `DarkWitch`, `DummyKingTower`.
- HastyCR schema samples: `ability`, `aoeToAir`, `aoeToGround`, `archer_ev1`, `arena`, `arrows`, `base`, `blue`, `blueExportName`, `boost`, `boss_bandit`, `buff`, `burst`, `bytes`, `cards`, `clone`, `constantHeight`, `customSpawnFilter`, `damage`, `deathEffect`, `death_spawn`, `deflectBehaviour`, `description`, `earthquake`, `electro_spirit`, `elixir`, `exportName`, `fileName`, `fire_spirits`, `fisherman`, `flags`, `freeze`, `glow`, `goblin_barrel`, `gravity`, `green`, `healthBar`, `height`, `hitEffect`, `hitSpeed`.
- Exact selected-data hash matches against cr-csv/HastyCR: 0/0.

### Bounded entity/data classification

- `official match`: 172 typed identifiers (medium confidence vocabulary match; modification remains possible). Samples: `Archer`, `ArcherQueen`, `Archers`, `Arena1`, `Arena9`, `ArenaPvE`, `Arena_Boat`, `Arena_BootCamp`, `Arena_ClashFest`, `Arena_Electric`, `Arena_Goblin_Party`, `Arena_Halloween`, `Arena_Legendary`, `Arena_Miner`, `Arena_Monk`, `Arena_Pancakes`, `Arena_Ranked`, `Arena_Shipwreck_2`, `Arena_TouchdownTest`, `Arena_XMas2022`, `Arrows`, `Assassin`, `AxeMan`, `BabyDragon`, `Balloon`, `Bandit`, `Barbarians`, `Bats`, `Bomber`, `Boost`.
- `official historical`: 0; not assigned without version-specific official provenance.
- `modified official`: 36 variant-style identifiers (low confidence). Samples: `AngryBarbarian_crazy_3_as_melee`, `AngryBarbarian_crazy_3_retarget`, `AngryBarbarian_crazy_3_set_has_projectile_false`, `AngryBarbarian_crazy_3_set_melee_attack`, `AngryBarbarian_crazy_3_timer_action`, `AxeMan_crazy_1_tornado`, `AxeMan_crazy_3`, `BabyDragon_crazy_1`, `BabyDragon_crazy_1_Egg`, `BabyDragon_crazy_1_Spawn_Projectile`, `BabyDragon_crazy_1_Spawn_dummy_AEO`, `BabyDragon_crazy_2`, `BarbarianHut_crazy_1`, `BarbarianHut_crazy_2`, `BlowdartGoblin_crazy_2`, `BlowdartGoblin_crazy_3`, `BolaSnare_crazy_1`, `BolaSnare_crazy_2`, `BombTower_crazy_1`, `DarkWitch_crazy_2`, `DarkWitch_crazy_3`, `Firecracker_crazy_3`, `FishermanProjectile_crazy_1`, `Fisherman_crazy_1`, `GoblinDrillDig_crazy_1`, `GoblinDrillDig_crazy_2`, `GoblinDrillDig_crazy_3`, `GoblinDrill_crazy_1`, `GoblinDrill_crazy_1_Dig`, `GoblinDrill_crazy_2`.
- `custom/private-server`: 0; package provenance alone was not used to label unmatched entities.
- `unknown`: unresolved/unmatched entities were not exhaustively decoded, so no false exhaustive count is claimed.

## Limits

- Local cr-csv is historical, unlicensed study-only material at documented revision `899e45efc765fbf3902927bb2e37dc04a78f7823`.
- HastyCR comparison uses tracked `data/royaleapi/*.json`; it does not imply APK fields are current or authoritative.
- Exact-name overlap does not distinguish official, modified, emulated, or copied data by itself.
- No proprietary values or file bodies are reproduced here.
