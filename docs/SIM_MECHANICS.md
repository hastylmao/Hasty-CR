# Simulator mechanics: what is in, what is missing, and in what order

The public/client catalogue contains ordinary, evolved, champion, and hero
forms, and the reflex is that each one is a special case.
It is not. Every behaviour we have hit so far falls into about seven families,
and the parameters for all of them are already in the game files under
`tmp/gamedata/csv_logic`. We are not missing data. We are missing behaviours
that read it.

Run `python -m sim.coverage` for the current numbers.

## Where the parameters already live

Nothing here was authored by hand. These are the game's own keys:

    miner          SpawnPathfindSpeed 650, DeployTime 1000
    balloon        DeathSpawnCharacter BalloonBomb
    ice_golemite   DeathDamage 33, DeathDamageRadius 2000
    battle_ram     DeathSpawnCharacter Barbarian, ChargeRange 300
    tombstone      SpawnCharacter Skeleton, SpawnPauseTime 3500, SpawnNumber 2

Charge was implemented in an afternoon exactly this way: the numbers were
sitting unused in the file, and the work was one function that read them.

## The families

The shared families below are implemented. `python -m sim.coverage` prints the
live figures; action-graph mechanics are tracked separately.

| family | covers | state |
|---|---|---|
| charge / dash | Prince, Dark Prince, Battle Ram, Boss Bandit, Mega Knight | done |
| shields | Dark Prince, Guards | done |
| splash, projectile flight | every ranged unit and both towers | done |
| death damage | Ice Golem, Golem, Giant Skeleton | done |
| death spawn | Golem, Battle Ram, Balloon, Lava Hound | done |
| periodic spawner | Tombstone, Witch, huts | done |
| timed buff | Freeze, Zap, Snowball, Ice Wizard, Poison | done |
| kamikaze and lifetimes | Ice Spirit, Fire Spirits, Tombstone | done |
| knockback | The Log, Barb Log, Rocket, Mega Knight landing | done |
| burrowing | Miner, Goblin Drill | done |
| lingering areas | Poison, Tornado, Earthquake, Graveyard | done |
| multi-stage spells | Arrows, Lightning, Void, Zap Evolution | done |
| rolling/capture spells | Log, Barbarian Barrel, Snowball Evolution | done |
| evolution cycle/selection | explicitly equipped evolution slots | done |
| evolution buffs/triggers | Knight, Barbarians, Bats, Skeletons, P.E.K.K.A, Witch, Minion Horde | done |
| evolution spawn/shield effects | Royal Ghost, Wall Breakers, Royal Recruits, Wizard, Royal Giant | done |
| delayed/threshold evolution actions | Ice Spirit, Goblin Giant, Royal Hogs, Hunter | done |
| following/forced-movement evolution actions | Baby Dragon wind, Mega Knight uppercut | done |
| alternate and infinite evolution attacks | Archers power shot, Electro Dragon chain | done |

Where it stands: the historical **116 of 116** number only cleared a limited
top-level-field scan; it is not a fidelity claim. Run `python -m sim.action_audit`
alongside coverage because AEO/ACTION graphs contain additional mechanics.
Spell resolution now includes all current public spell families represented in
the snapshot. Mirror replays the previous card one level higher; Rage and Royal
Delivery are routed as spells even though the client represents them with
temporary building objects. Graveyard uses its exact current twelve-event
action list rather than an inferred periodic timer.

## Order of work, by what we actually face

Threat names are logged on every play, so this is measured rather than guessed.
From 1601 sightings in about an hour of live play:

    skeleton 368   goblin 291   barbarian 190   miner 168
    hog_rider 147  ice_golem 109  musketeer 58   knight 53
    royal_hog 51   prince 46      royal_giant 45  dark_prince 41

The top three are plain troops already modelled correctly. Prince and Dark
Prince are 10th and 12th and charge is done. That leaves:

1. **Death damage** - two units, and Ice Golem is both in our deck and the 6th
   most common thing we face.
2. **Timed buff** - Ice Spirit is ours and currently just a cheap body.
3. **Knockback** - The Log is ours and currently just damage.
4. **Arrive from elsewhere** - Miner is the 4th most common card we face.
5. **Death spawn**, then **periodic spawner**.

Three of our own eight cards are in that list. Fixing our own deck first is not
parochial: every defensive measurement we take involves them.

## On outside sources

`Clash Royale Troop Stats Database.docx` (Gemini) is sound. Spot-checked against
the game files: Knight 1766 against our 1789, Musketeer 721 against 729, Hog
Rider 1696 against 1718, with hit speed and range matching exactly. That is
patch drift. It independently confirms the 50ms server tick and the 18x32
arena. Its value is the **mechanics catalogue** - it spells out behaviours the
raw CSV only implies - not its numbers, which are a worse copy of what we have.

`Executive Summary.pdf` (ChatGPT) **should not be used for numbers**. It gives
Knight 690 hitpoints and 79 damage against a real 1789 and 208, which look like
level-1 values labelled level-11. Its movement table says Medium is about 2.5
tiles per second; the real figure is 1.0, because the game's Speed field is
tiles per *minute*. Adopting that table would have re-introduced the exact fault
that made a lone Ice Golem die three tiles short of the tower. It also contains
5 of the 122 cards it describes, the rest being a placeholder comment.

The general rule this run has earned: **the game's own files win, a secondary
source is only worth its mechanics prose, and any number that changes behaviour
gets checked against something that can disagree with it.**
