# Simulator continuation contract

This file exists so a fresh agent can continue the fidelity run without
repeating the original mistake: treating parsable data as evidence that a card
is simulated.

## Non-negotiable rules

- Do not implement a real-card mechanic from model memory. Use the shipped
  client data plus an official Supercell or RoyaleAPI source; record external
  values in `data/royaleapi/combat_rules.json`.
- Do not add internal-only rows such as `warm_spell` or `tri_wizards` as normal
  cards. The RoyaleAPI snapshot is the public-card allowlist.
- Do not change the emulator/controller while completing the headless sim.
  MuMu access is read-only evidence capture unless a separate user request
  authorizes play.
- Do not call the simulator complete from unit count. Run both `sim.coverage`
  and `sim.action_audit`; the latter inventories unsupported action graphs.
- Anchor every data-key lookup to the start of a line. `tests/test_parser_anchoring.py`
  guards this and uses an asymmetric case, because the historical failures all
  survived symmetric ones.
- `python -m sim.validate` reports plays per *minute* as well as per match.
  Simulated matches run about 51s longer than live ones because self-play is
  evenly matched and reaches overtime far more often than ladder does, which
  inflates the per-match figure to a 38% divergence where the rate difference
  is 9%. Read the rate.
- Open gap, deliberately unimplemented: Super Mini P.E.K.K.A and Santa Hog
  Rider each declare a periodic spawner whose object has no `Hitpoints` in the
  shipped data, so the engine creates it already dead and its death effect
  never fires - pancakes heal nothing, the present does nothing. Both are real
  public cards. A pickup that waits to be walked over and a bomb that goes off
  on arrival both fit these fields, so it needs an observation rather than a
  choice. Pinned as strict xfails in `tests/test_periodic_spawners.py`.
- Run `python scripts/soak.py --matches 300` after touching spawn, attachment
  or card-resolution code. Random decks reach card combinations the fixed decks
  never do; it found a `Battle.add` infinite recursion that 700 passing tests
  did not, because Hog 2.6 has no attachment card.
- Use `python scripts/ab_eval.py` rather than a single-seated A/B. It plays
  every seed on both seats and averages, which cancels the ~10 point seat
  effect; with identical configs it reports exactly 0.500 by construction.
- Evolution overlays are loaded from both `characters_evo.toml` and
  `buildings_evo.toml`. Reading only the first dropped Mortar Evolution and
  Tesla Evolution completely - 40 evolutions loaded where the client ships 42.
  Guarded by `tests/test_evolution_coverage.py`, which enumerates the overlays
  from the files instead of a hand-written list.
- Card type is read from the declaring spells CSV, not inferred from
  `Speed == 0`. `UnitSpec.from_building_card` is set for anything in
  `spells_buildings.csv`; the reworked Furnace and Goblin Drill carry a real
  Speed and were previously classed as walking troops. Checked against the
  public snapshot's `type` field for all 120 cards in `tests/test_card_types.py`.
- Open, deliberately unresolved: Goblin Drill resolves to
  `CHARACTER.GoblinDrillDig` (Hitpoints 1000) while the same file's
  `BUILDING.GoblinDrill` says 513, so the simulated drill has about twice the
  hitpoints of the emerged building. Listed in `python -m sim.check`; settle it
  by observation, not by picking the more plausible section.
- `sim.gamedata.GAMEDATA_ROOT` is the one place the extracted client data is
  located, and it is relative to the repository. `load_gamedata` used to
  default to an absolute home-directory path instead, so the project ran on one
  machine; missing data now raises rather than falling back to a flat 110%
  scaling curve that is about 1.3% off the shipped table.
- Train at level 11, which is the level every value in `combat_rules.json` was
  verified at. Away from it, verified values are *extrapolated* along the
  client scaling curve by `gamedata.carry_verified` rather than dropped - sound
  enough to play against, not something to quote as a measurement.
  `python -m sim.level_audit --level N` separates exact from extrapolated from
  still-pinned, and `sim.readiness` blocks if training points at a level where
  they are not all exact.
- Fixed 2026-08-20: the loader used to apply a verified override only at the
  exact level it was recorded at. Mirror resolves cards one level up, so every
  Mirror play discarded all 37 rules - a mirrored Evolved Witch had 922
  hitpoints against a verified 1451, weaker for being played higher. The carry
  uses the client's own curve and returns the verified value untouched at its
  own level, so level 11 did not move.
- Self-play A/B results are confounded by the seat. Measured 2026-08-20:
  `BrainPolicy` on both seats wins 60.5% from the bottom over 400 matches
  (z=+3.69), and 57.5% even when the top seat opens (z=+2.15), while a
  seat-agnostic policy shows nothing (53.2%, z=+0.57). The board is provably
  symmetric - `tests/test_board_symmetry.py` checks deploy zones, river,
  anchors, walkability and the whole path-cost field - so the bias is in the
  brain, which was written for the bottom seat. Swap seats and average, or the
  A/B is measuring the seat. Reproduce with `scripts/seat_balance.py`.
- Elixir income is pinned to the published rates by `tests/test_elixir_economy.py`
  (2.8/1.4/0.933 seconds per elixir), asserted against the public figures rather
  than the constant in the code, since a test reading that constant cannot
  disagree with it.
- Replays are deterministic and asserted so by `tests/test_sim_determinism.py`,
  including that positions stay integer millitiles - a float position replays
  identically in-process and only diverges across machines.
- The in-game card info screens (170 screenshots, 2026-08-20, under
  `MuMuSharedFolder/VideoRecords/data/hero evo champs`) are the best available
  statement of what a Hero, Champion or Evolution *does*: they name the ability
  and spell out its mechanic. Used for mechanics only - the account is boosted
  to level 16, so displayed hitpoints are at a level the simulator does not
  run at. 16 checks pinned in `tests/test_card_screens.py`, including all 13
  evolution cycle counts.
- The three showcase recordings in `.../recording of cr showcase` are 60 fps,
  so unlike the 30 fps set they clear the frame-rate bar. They are still
  `contextual_only` and should stay that way: they are scripted demonstrations
  played inside a 960x530 panel with no known deployment coordinates, which is
  exactly what the protocol says cannot set a constant. Good for watching a
  mechanic, not for measuring one.
- Contact is settled by decision, not by measurement: nothing overlaps and
  nothing walks through anything, and the exact separation distance is not
  worth a video because the collision radii are already in the shipped data.
  `tests/test_no_overlap.py` checks it every tick of a whole match. The
  engaged-pair exemption is gone, deploying units are separated, and buildings
  are enforced last because a unit pushed off another can land inside one.
  Units mid-ability stay exempt on purpose - separating a hurled troop moved it
  off its declared landing tile.
- `scripts/sync_royaleapi_full.py` mirrors 13 public datasets (3.4MB) with
  SHA-256 provenance into `data/royaleapi/`. The project previously synced only
  `cards.json`. The rest carry per-level hitpoint and damage tables, every
  projectile's speed, `homing` and `check_collisions`, and every spell's radius
  and duration. Do not ask for a controlled capture of something that ships in
  a file - check here first.
- `python -m sim.level_stat_audit --all-levels` cross-checks every card at
  levels 1-15 against those tables. Differences are bucketed: sub-1% is the
  rounding path and not worth chasing; over 5% is real. Nine cards whose client
  base sits at their rarity's own level 1 rather than unified level 1 are
  corrected through `combat_rules.json`, sourced to the published table.
- `sim/towers.py` derives both towers from the published per-level tables and
  models the tower troops (Dagger Duchess 500ms, Cannoneer 2200ms, Royal Chef
  1000ms) from client data. The old hardcoded 3346/5735 matched no level.
- `python -m sim.readiness` now also runs the public stat audit and the level
  audit, so a card value drifting from the public snapshot, or a change of
  working level, blocks the gate rather than passing quietly.
- `python -m sim.public_stat_audit` checks every public card's elixir cost and
  rarity against the RoyaleAPI snapshot: 120 cards, 240 values. Rarity is the
  one that matters most, because stats are scaled from level-1 bases *by
  rarity*, so a miscategorised card is wrong at every level while parsing
  cleanly. One divergence is recorded and explained - the client ships the
  Goblin Hut rework at ManaCost 4 while the snapshot still carries 5. Do not
  silence a new divergence by adding it to `KNOWN_DIVERGENCES` without quoting
  the shipped row that settles it.

## Current verified baseline

- Focused simulator fidelity tests: 144 passing; full suite: 1308 passing plus 2 pinned xfails with
  `.venvs\\buildabot\\Scripts\\python.exe`; the full pytest suite and
  `python -m compileall -q sim` also completed green in that venv. The
  `clashai` venv is missing Pillow, so it cannot instantiate the live-brain
  opponent and is not the validation runtime.
- Source-backed: Lightning target selection, Vines target selection/snare/
  grounding, Clone, Void tiers/waves, Goblin Curse conversion/slow.
- The source snapshot is synced by `scripts/sync_royaleapi_cards.py`; known
  internal-only spells are quarantined instead of given guessed behaviour.
- Shared combat now reads character-level multi-target + stun fields
  (Electro Wizard), deployment AEOs (Electro/Ice Wizard), and staged damage
  + stun reset (Inferno Tower/Dragon/Mighty Miner). It also resolves chained
  hits (Electro Dragon/Spirit) and Fisherman's source-declared hook flight,
  drag direction/speeds/margin and verified slow. Mother Witch / Goblin Curse
  death conversions now use their BUFF DeathSpawn data and declared EXT base
  aliases instead of a hard-coded Goblin.
- Source `ActionRunActionAtHealth -> ActionChangeGameObjectData` transitions
  are now represented: Cannon Cart switches to Broken Cannon at its declared
  50% threshold while preserving its remaining health.
- Hero-form card declarations now load from the client `SPELL_HERO` blocks
  and their `EXT` character overlays, rather than silently deploying an
  ordinary base troop.  This makes hero identity, card cost, shield/ability
  fields and action availability visible to the environment; it does not yet
  mean every hero activation graph is implemented.
- The source-action extractor supports the explicit activation subset used by
  Hero Knight: its starting action clears the inherited shield, while its
  ability's action group restores the declared shield percentage and applies
  its declared five-second self buff.  Other action classes remain queued.
- Projectile steering is read from the client `Homing` field.  Explicitly
  homing shots resolve against their tracked target; non-homing launches are
  preserved for a geometry/projection probe instead of being guessed as
  homing hits.
- Evolution rows are materialized as deployable `CardSpec` objects. Explicitly
  equipped `Match.evolution_slots` use the row's `DarkElixirCost` as the cycle
  requirement and substitute/reset the evolved play deterministically.
- Implemented evolution mechanics include Knight fortification, Barbarian
  rage, Bats overheal, Skeleton duplication/cap, P.E.K.K.A kill-heal tiers,
  Witch's current initial-wave-only healing, Royal Giant attack blast, Royal
  Recruit shield-loss charge, Wall Breaker split/explosion, Wizard shield
  explosion, Minion Horde ghost state, Royal Ghost guardians, and the Goblin
  Barrel/Snowball/Zap spell evolutions. The current deterministic action-graph
  pass also covers Archers power shots, Ice Spirit's target-bound repeat
  blast, Goblin Giant's half-health Goblin stream, Royal Hogs' airborne
  landing, Hunter's homing Net, Baby Dragon's following wind, Mega Knight's
  alternating uppercut, and Electro Dragon's infinite/reduced chain bolts.
- The current Inferno Dragon evolution retains all four heat stages across
  targets and decays/resets from the published triggers. Current client Spirit
  rules use 215 HP and prohibit direct Crown Tower acquisition while retaining
  troop-triggered splash/chain interactions.
- Positive client speed fields are absolute multipliers: `130` is normalized
  to the engine's `+30` delta. This fixes movement/attack timing for evolution
  rage, Archer Queen and newer wind/hero buffs.
- Projectile `EXT` inheritance is materialized before character overlays;
  evolved Hunter and other inherited projectiles no longer silently become
  zero-damage attacks. Chain lightning now flies hop by hop rather than
  resolving every chained target on the first impact tick.
- Champion self-buff abilities are explicit masked RL actions. Automatic
  ability use is an opt-in compatibility flag, not training behaviour. Golden
  Knight's source action graph is implemented as a ground-target chain dash;
  Monk's source shield buff applies its 65% damage reduction. The remaining
  non-self-buff action graphs, including Monk projectile reflection, still
  need explicit handlers and live trajectory validation.
- Explicit paid action handlers now also cover Hero Ice Golem's three moving
  Blizzard pulses, Hero Musketeer's delayed Trusty Turret, Mighty Miner's
  horizontal Explosive Escape, Goblinstein's two-unit deployment and moving
  Lightning Link (including the dead Monster receiver), and Hero Berserker's
  cast-inclusive unkillable bear buff. Secondary card summons and projectile
  EXT inheritance are shared loader features rather than card-name patches.
- The later fidelity pass adds current, scenario-tested controllers for Cannon
  Evolution's nine-shell deployment barrage; base/evolved Lumberjack Rage and
  the fixed-life invulnerable ghost; Dart Goblin Evolution's June poison tiers;
  the reworked Furnace and its engaged hot-spawn loop; Goblin Cage Evolution's
  drag/capture/damage/release cycle; current Fire/Ice/Electro/Heal Spirit HP;
  Hero Mini P.E.K.K.A's cooking quest and level/heal selection; and Hero
  Knight's current shield-restoring 6.5-tile taunt.
- Current Hero Giant, Bowler, Dark Prince, Barbarian Barrel, and Valkyrie action
  graphs are explicit RL actions. This includes Giant's wait-for-target
  highest-HP throw, Bowler's fixed-position (missable) siege rocks, Dark
  Prince's HP/shield-preserving dismount and independently deploying Rhino,
  both phases of the Hero Barbarian Barrel card plus its heal/reroll hitbox,
  and Valkyrie's target-seeking 14-pulse Whirlwind that continues through
  ordinary combat locks. Their public balance values and source URLs are in
  `data/royaleapi/combat_rules.json`.
- The latest source-complete pass also covers Hero Goblins' last-survivor
  banner and brigade, Hero Tombstone's linked revival/Queen/death wave, Ronin's
  melee-only timed Parry, Boss Bandit's two-charge Getaway, Hero Wizard's
  timed aerial form and enhanced hit area, Firecracker's one-tile launch
  recoil, Hero Balloon's current Skeletrooper stats/landing AEO, and the homing
  projectile subset of Monk reflection. The audit now gives every remaining
  graph an exact live-calibration requirement instead of treating it as an
  unspecified coding backlog.
- MuMu read-only ADB endpoint: `127.0.0.1:7555`; its baseline was captured
  under `tmp/live/` without playing a match.
- On 2026-08-20, 19 user-supplied 1080x1920 gameplay recordings were catalogued
  under `data/validation/live_probes.json` with SHA-256 hashes, durations and
  approximately 30 fps timing. They are explicitly `contextual_only`: normal
  gameplay with overlapping actions and unknown deployment coordinates is not
  collision/projection proof. Use `scripts/ingest_live_recordings.py` and
  `scripts/extract_probe_frames.py`, then follow `docs/LIVE_PROBE_PROTOCOL.md`
  before promoting a frame range into accepted evidence.
- Live-evidence promotion is machine-checked: it must reference a known
  controlled capture at 50+ fps, immutable SHA-256 provenance, an in-range
  source-frame interval, and an existing pytest test in
  `tests/file.py::test_name` form. Re-running the cataloguer merges review
  metadata and demotes an edited capture rather than overwriting proof.
- `python -m sim.card_catalog_audit` currently maps all 120 synced public
  RoyaleAPI cards uniquely to the local client dataset using the public
  `sc_key`; this audit runs inside the RL readiness report.
- The recording motion queue and each extracted frame packet now carry the
  source video SHA-256. `scripts/verify_live_probe_assets.py` rechecks all
  catalogued recordings before a reviewer uses an observation.
- `python -m sim.watch --random-decks` now samples two unique eight-card decks
  from every public card the simulator can currently resolve. The synced
  RoyaleAPI snapshot has 120 public cards; 119 enter that sampler. Party Rocket
  is deliberately excluded because its client spell graph is quarantined, so
  it cannot silently spend elixir and resolve to nothing.

## Required next work, in dependency order

0. `python -m sim.probe_plan` emits the shared matrix as 18 numbered clips,
   each paired with the engine's current prediction, and `tests/test_probe_plan.py`
   fails if any of those scenarios stops producing a comparable number. Two
   findings are already baked in as predictions: the engine leaves two engaged
   opposing Knights overlapping below the sum of their radii (TC-4 decides
   whether the real game does), and it routes around buildings through the
   flow field rather than by push-out, so `building_contact` rows are the
   exception rather than the rule (BC-1..3 measure closest approach instead).

1. Run the exact live probes emitted by `python -m sim.action_audit`. All nine
   remaining public graphs now have their deterministic/source-backed subsets
   represented and an explicit collision/trajectory gate. Goblin Queen is
   excluded because it is an internal scenario/NPC graph absent from the
   public-card catalogue; King Tower activation is handled by the match wake
   rule.
2. Run live collision/map probes and only then replace the documented contact
   approximation. Required probes: two-unit King Tower placement, size/mass
   pairs, building routes, spell/projectile timings, bridge/tower anchors.
3. Populate the existing RL readiness gate from recorded scenarios. Training remains
   blocked for cards/mechanics without matching scenario tests.

## Completion estimate at this checkpoint

- Source-backed card mechanics and action graphs: roughly 90% complete.
- Whole simulator as an RL-faithful Clash Royale environment: roughly 78-82%
  complete. The gap is dominated by shared physics/pathing/projectile
  calibration, not missing damage constants.
- Engineering time for remaining deterministic cleanup discovered by probes:
  about 1-3 focused working days.
- Time for credible collision, placement, pathing, projectile interception and
  prediction parity: another 1-3 weeks, because it requires a repeatable matrix
  of live-game measurements. That work must not be replaced by guessed sprite
  boxes or ad-hoc separation constants.

`python -m sim.readiness` is the current strict gate. It is expected to report
`RL NOT READY` until the action-graph backlog is explicitly disposed of and a
read-only live probe matrix is recorded; do not override it by citing passing
unit tests.
