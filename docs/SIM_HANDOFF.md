# Clash Royale simulator: handoff

A Python battle simulator for Clash Royale, built to train a reinforcement
learning agent for a Hog 2.6 bot. It reads Supercell's own shipped data files
rather than hand-authored card stats.

**Repository:** `HastyCR`, simulator under `sim/`. 1308 tests under `tests/`,
including 144 focused scenarios in `tests/test_sim_fidelity.py`.

---

## 1. Current state

| | |
|---|---|
| Deployable units parsed | 176/176 clear in the top-level raw-field scan |
| Spell cards resolved | 27; zero unresolved public spell rows, plus Mirror as a rule |
| Remaining semantic source graphs | 9, all explicitly live-calibration-gated |
| Tests | 1308 passing + 2 pinned gaps (full suite green on 2026-08-21) |
| RL readiness | blocked on live geometry/contact/projectile probes |

Run `python -m sim.coverage` for live figures and `python -m sim.check` for the
predictions the engine makes about specific situations.

### Implemented mechanics

Charge and its special hit; dashes with invulnerability; shields; splash;
projectile flight time; death damage; death spawns; periodic spawners; timed
buffs (freeze, slow, rage, heal); kamikaze units; lifetimes; knockback with
IgnorePushback; burrowing with untargetability in transit; lingering spell
areas; sight-limited aggro; solid buildings; tower windup; grid pathfinding
over the river and bridges; Mirror; Goblin Curse conversion; invisibility;
damage reflection; champion abilities that are plain buffs.

### Data sources

`tmp/gamedata/csv_logic/` — Supercell's shipped CSV and TOML. Cards come from
`spells*.csv`, characters and buildings from `characters/*.toml` and
`buildings/*.toml`, and each card's numbers are scaled from level-1 bases by
rarity. Public card identity/stat snapshots are versioned under
`data/royaleapi/`; externally verified behavior and balance overrides carry a
source URL and verification date in `combat_rules.json`.

---

## 2. Historical high-priority gaps (now resolved)

These were the original handoff's known failures and are retained as regression
history. Each now has source-backed implementation and tests.

| card | corrected behavior | current status |
|---|---|---|
| Arrows | staged damage, current radius and tower reduction | implemented/tested |
| Tornado | timed damage and centre pull | implemented/tested |
| Lightning | three highest-hitpoint legal targets in radius | implemented/tested |
| Goblin Curse | damage, slow and death conversion | implemented/tested |
| Vines | capped target selection, damage, snare and grounding | implemented/tested |
| Clone | duplicates eligible friendly troops at one HP | implemented/tested |
| Void (`dark_magic` internally) | three inverse-scaling waves and fixed tower damage | implemented/tested |

Champion/hero actions are explicit paid RL actions rather than automatic side
effects. The source-backed portions of Skeleton King, Golden Knight, Mighty
Miner, Monk, Little Prince, Boss Bandit, Goblinstein and the newer heroes are
implemented. Monk's spell/non-homing reflection geometry remains one of the
nine named live-calibration gates.

Not real cards, correctly ignored: Tri Wizards, Warm Spell, Merge Maiden.
Goblin Party Rocket is a party-mode skin of Rocket.

---

## 3. The most important thing to know

**Being consistent with the data files is not the same as being correct, and
this project has proved it repeatedly.**

The engine passed every test it had while being 25% wrong about the movement
speed of every unit in the game. The game's `Speed` field is tiles per
*minute* - Slow 45, Medium 60, Fast 90, Very Fast 120 - and the code was
treating it as something else. It was found when a player placed a single Ice
Golem in a real match and reported that it reaches the tower and lands one hit,
where the simulator had it dying three tiles short. That one observation
exposed five separate bugs.

### The recurring bug: unanchored key lookups

Three separate parsers had the same fault in one night. Searching a data
section for a key without anchoring it to the start of a line means a longer key
swallows the shorter one, and the number that comes back looks plausible:

- `SpeedMultiplier` matched inside `HitSpeedMultiplier` - 18 buffs wrong. Archer
  Queen's ability is +280 attack speed and -25 movement, and came out +280 to
  both.
- `Radius` matched inside `ProjectileStartRadius` - Fireball modelled a 0.7 tile
  blast instead of 2.5, about a quarter of its real size.

Every one of these survived because the cases used to verify them happened to
be symmetric. Freeze is -100/-100, so a parser reading one field twice looks
right. **Check any key lookup in this codebase for the anchor.**

`tests/test_parser_anchoring.py` now enforces this. It pins the asymmetric
Archer Queen case, proves the decoy value is real so the guard is not
theoretical, and scans `sim/` for any new unanchored key lookup. It was added
after a fourth instance was found latent in `spells.py`: `SpeedMultiplier`
sitting in the same lookup tuple as `HitSpeedMultiplier`, reachable only from a
code path no current spell card takes.

### Verified values are now carried across levels, not dropped at one

`combat_rules.json` holds 37 rules carrying externally verified numbers -
balance changes read off Supercell's own blog and RoyaleAPI, each with a source
URL and a verification date. They are the most expensive data here, because
each one cost a person going and checking. All were verified at level 11.

The loader used to apply such a value **only** at that exact level. Everywhere
else it fell back to raw client scaling, silently. That was not a hypothetical
reachable by typing `--level`: `Match.mirrored` resolves cards one level up, so
every Mirror play in every match landed on level 12 where none of them applied.
A mirrored Evolved Witch came out at **922 hitpoints against the 1451 she is
verified at** - weaker for being played higher.

`gamedata.carry_verified` now carries a verified value along the client's own
scaling curve, holding its ratio to `scale_stat` constant. This adds no claim
about the game: at the level it was verified at the value is returned exactly,
so level 11 - what everything here runs at - did not move, and elsewhere it
travels the way every other stat on that card travels.

    Evolved Witch hitpoints, verified 1451 at level 11
    level  9   1201      base Witch  695
    level 11   1451      base Witch  840   <- verified, exact
    level 12   1593      base Witch  922   <- what Mirror resolves against

An extrapolated value is sound enough to play against and must not be quoted as
a measurement. `python -m sim.level_audit --level N` says which values at a
level are exact, which are extrapolated, and which still cannot move at all
(counts and spawned-character names, which do not scale). `sim.readiness`
blocks if training is ever pointed at a level where they are not all exact.

### A card nobody decks crashed one random match in fifteen

A soak of 150 random public decks failed ten times with a RecursionError, and
no fixed-deck test could have caught it: Hog 2.6 contains no attachment card.

Resolving a spawned character went through the card table first, after
snake-casing the client name. That is right for most spawns and wrong for one
shape - `RamRider` snake-cases onto the `ram_rider` card, whose unit is the
Ram, and the Ram declares `RamRider` as its attachment. `Battle.add` built the
attachment, called itself, and did it again until the stack ran out. The exact
client identifier is tried first now, which is unambiguous by construction.

`python scripts/soak.py --matches 300` is the check. It also reports spells and
spawns the engine could not resolve, which are the quiet version of the same
problem: a hole in a card's behaviour rather than a crash.

### Two evolutions were missing entirely

Evolution overlays are compact `Base=` blocks rather than full character
sections, and they live in more than one file. The loader read
`characters_evo.toml` and not `buildings_evo.toml`, so Mortar Evolution and
Tesla Evolution had no character data at all: their card rows resolved to
nothing and were dropped without a word. The simulator reported 40 evolutions
where the client ships 42, and deployable units 174 where it is 176.

This is the same shape as the spell table that named two files which did not
exist, so the sim ran on two spells while appearing to support four. A
hand-written list of data files is a place for cards to go missing while
everything still passes. `tests/test_evolution_coverage.py` now counts the
overlays from the files rather than trusting the list.

### Card type came from a guess, and two cards broke it

Whether a card is a building was inferred from `Speed == 0`. That holds for
most buildings and was never true by definition. The reworked Furnace and
Goblin Drill both carry a real `Speed` in their character section, so the
simulator classed them as troops: they walked six and ten tiles in ten seconds,
drew no building-targeted aggro, and were solid to nothing. A Hog Rider ignored
a Furnace, which is most of what a Furnace is for.

The client answers this directly and always did - both cards are declared in
`spells_buildings.csv` - and the public snapshot independently types them as
Building. `UnitSpec.from_building_card` now carries the declaring file, and the
two sources agree on all 120 public cards. Pinned by `tests/test_card_types.py`.

The general lesson is the same one this file keeps repeating: the inference was
right about roughly a hundred cards, which is exactly why nobody checked it.

### Tower stats are derived now, and tower troops exist

The four tower constants were read off a live account, because the tower-level
curve was not in the shipped files. It is published after all - RoyaleAPI's
`cards_stats_building` gives hitpoints at every level and the tower projectiles
give damage at every level - and checked against it, the old values matched
**no level at all**: princess 3346 falls between levels 10 and 11 (3262, 3584),
king 5735 between 5592 and 6144.

`sim/towers.py` derives them instead, and models the tower troops, which are
not reskins:

| tower | hitpoints @11 | damage | hit speed |
|---|---|---|---|
| Princess Tower | 3584 | 128 | 800ms |
| Dagger Duchess | 3251 | 108 | **500ms** |
| Cannoneer | 3072 | 320 | **2200ms** |
| Royal Chef | 3174 | 128 | 1000ms |

A simulator that only ever models the Princess Tower is wrong about every match
played with one of the others. Only the standard tower has a published per-level
curve; a troop is carried along that same curve from its own client base, which
is an extrapolation and labelled as one.

Two traps found while writing it, both this project's usual shape.
`chef_tower.toml` holds `[CHARACTER.Chef]` at 5 hitpoints - the cook - and
`[BUILDING.ChefTower]` at 1240; taking the first match in the file gave Royal
Chef five hitpoints. And a troop's damage lives on its projectile, not its
tower block, exactly as Cannon and Musketeer's did.

### The seat is worth about ten points, and it is not the board

Measured on 2026-08-20 with `python scripts/seat_balance.py`. Mirror self-play,
same deck both sides, decided matches only:

| setup | bottom share | z |
|---|---|---|
| BrainPolicy both seats, bottom opens (400 matches) | 0.605 | +3.69 |
| BrainPolicy both seats, top opens (250 matches) | 0.575 | +2.15 |
| seat-agnostic policy both seats (300 matches) | 0.532 | +0.57 |

The board is not the cause. `tests/test_board_symmetry.py` proves the deploy
zones, river band, tower anchors, walkable grid and full path-cost field all
mirror exactly about the halfway line, and a seat-agnostic policy on both seats
shows no effect. The bias is in `BrainPolicy`, which was written for the bottom
seat because that is where the live bot plays. Giving the top seat the opening
decision removes about a third of it and leaves the rest.

**Consequence for measurement:** an A/B run that puts a variant on one seat and
the baseline on the other is confounded, and the seat is worth more than most
changes being tested. Run every comparison twice with the seats swapped and
average, or the result is about the seat. The historical river bug was the same
hazard at roughly twice the size.

### Other faults worth knowing about, all now fixed

- The river band sat entirely on one side of the halfway line, so one player
  walked an extra tile on every push. With a mirrored policy on both seats, the
  bottom seat won about two thirds of matches, which invalidates any A/B result
  run on that board.
- Both towers were built at one collision radius; the data gives princess
  towers 1000 millitiles and kings 1400.
- Towers had no first-shot windup, though `princesstower.toml` gives LoadTime
  1000, handing every tower a free second of damage.
- Tower shots landed instantly, though they are a projectile at 600 tiles per
  minute.
- 5% of all elixir income was being truncated away by integer division.
- Spawned units are not cards. Golemite, BalloonBomb and LavaPups have no
  spells row, so every lookup failed and the spawn was skipped silently.
- Spell files were found by a hand-written table that named two files which do
  not exist, so the sim ran on two spells while appearing to support four.

---

## 4. Recommended next step

Do not add more inferred combat code. Run `python -m sim.action_audit` for the
nine exact trajectory probes, then record the live geometry/contact/projectile
matrix required by `python -m sim.readiness`. The most important measurements
are two-unit King Tower separation, collision-radius/mass pairs, building
routes, bridge/tower anchors, non-homing swept hits and spell timing.

`python -m sim.probe_plan` prints that matrix as 10 numbered clips - card,
level, deploy tiles, the single hypothesis, and the number this engine
currently predicts - so a recording is an immediate agreement or disagreement
rather than a judgement call. `--checklist` drops the predictions for use at
the capture machine. The nine gated graphs all reduce to one unknown:
non-homing projectile geometry meeting a contact radius, which is why the
matrix is about twenty clips rather than a card-by-card sweep.

The supplied gameplay videos are catalogued as contextual evidence only in
`data/validation/live_probes.json`; they must not be converted into constants
without an isolated, frame-linked observation. See `docs/LIVE_PROBE_PROTOCOL.md`.
The readiness gate additionally requires accepted evidence to use a controlled
50+ fps capture with SHA-256 provenance, valid source-frame bounds, and a real
pytest reference. `python -m sim.card_catalog_audit` confirms that every
synced public RoyaleAPI card maps uniquely into extracted client data.

## 4b. Throughput is not the constraint

Measured 2026-08-21 on this machine: **about 365 environment steps a second**
in a single process, roughly 365 steps to an episode. Ten million steps is
about 7.6 hours single-process, or an hour across eight workers. A full match
runs at about one a second single-threaded, roughly 4,200-4,800 engine ticks.

The 504 recorded here on 2026-08-20 does not reproduce. Re-measuring the same
script against the commit before this run's work gave 360, and against current
HEAD 365 - so the difference is the machine or the earlier measurement, not a
regression, and the mechanics added since (area attraction, drill relocation,
ability summons, paratroopers, boomerang axes) cost nothing detectable. The
conclusion below is unchanged either way.

Worth stating plainly because it changes what to worry about: the thing
standing between here and a trained agent is fidelity, not compute. Do not
spend time optimising the engine ahead of recording the probe matrix.

(The engine did get 10-20% faster on 2026-08-20 - target acquisition was half
of all runtime and was calling a hand-written `math.isqrt` four million times a
match - but that was cheap and bit-identical, not a campaign.)

## 5. Architecture, briefly

    sim/gamedata.py   parses the shipped data into card and character specs
    sim/entities.py   one Entity type for troops, buildings and towers
    sim/engine.py     the battle tick: target, dash, attack, move, separate, reap
    sim/arena.py      geometry, tiles, river, bridges, deploy zones
    sim/pathfind.py   breadth-first flow field over the 18x32 tile grid
    sim/spells.py     spell specs and resolution, including lingering areas
    sim/match.py      towers, decks, hands, elixir, clock, result, Mirror
    sim/opponents.py  scripted opponents piloting real archetype decks
    sim/meta_decks.py the archetype pool and a style classifier
    sim/watch.py      PyQt viewer; --skin game dresses the board like the
                      real arena, --skin debug is the flat hitbox diagram
    sim/coverage.py   what is and is not modelled
    sim/check.py      predictions a person can verify in a real match
    sim/probe_plan.py the controlled clips to record, each with its prediction
    sim/public_stat_audit.py  costs and rarities against the public snapshot
    sim/level_audit.py  which verified overrides actually apply at a level

The tick is 50ms. Positions are integer millitiles, 1000 to a tile, on an 18 by
32 grid. Everything is integer arithmetic so runs are reproducible.
