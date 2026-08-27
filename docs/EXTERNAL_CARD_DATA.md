# External card data and fidelity rules

The simulator has two independent inputs. Neither is treated as a complete
description of Clash Royale on its own.

| Source | Used for | Not used for |
|---|---|---|
| `tmp/gamedata/csv_logic` | client-side stats, hitboxes, action graphs, buffs, cards and spawned units | assuming an undocumented field has an obvious meaning |
| `data/royaleapi/cards.json` | player-facing card names, costs, types, descriptions and evolution links | hidden combat values or collision algorithms |
| `data/royaleapi/combat_rules.json` | an audited mechanic the client data does not contain, with source URL, date and level | unsourced “best guesses” |

Refresh the RoyaleAPI catalogue with:

```powershell
python scripts/sync_royaleapi_cards.py
```

The sync file stores the retrieval time and SHA-256 digest so a changed card
catalogue is visible in version control.

## Rule for adding mechanics

Every mechanic must meet one of these standards before it changes training:

1. A field/action in the shipped game data defines both the value and behaviour.
2. A player-visible source defines the missing behaviour and its exact values;
   record it in `combat_rules.json` with the URL, verification date and level.
3. The behaviour has no authoritative formula available. Add a live-probe
   scenario first, then implement only the measured result. Do not substitute a
   plausible physics rule.

This last case applies to collision resolution and Tornado displacement. The
client exposes sprite collision radii, mass, and Tornado's attraction fields,
but not its server solver. They need reproducible, recorded probes—not guessed
mass physics—before they are promoted to RL truth.

## Current source-backed spell work

- Lightning: linked area/projectile definition, 3 highest-current-HP targets,
  3.5-tile target selection and stun.
- Vines: action-graph source, 3 highest-current-HP targets, two-second snare
  and the actual snare damage source.
- Clone: three-tile friendly troop copies at one HP; buildings and clones are
  excluded.
- Void (`dark_magic` internally): the client file has only display labels. Its
  level-11 three damage tiers and waves are recorded separately rather than
  invented in the loader.
- Fireball, Rocket, Snowball and Goblin Barrel: fixed-point launch timing from
  the King Tower so moving units can leave the aimed area before impact.
- Arrows: three client-timed waves and current total Crown Tower damage.
- Royal Delivery: current 384 damage, own-side placement, three-second drop,
  and 250 ms Recruit deploy.
- Graveyard: the exact current twelve spawn delays/offsets and 500 ms deploy.
- Goblin Barrel and Giant Snowball Evolutions: mirrored decoy barrel with the
  current 66-damage decoys; four-tile capture roll and release slow.
- Zap Evolution: current two-pulse action graph and changing pulse radius.
- Archers Evolution: current 140-damage power shot at 4.5+ tiles.
- Ice Spirit Evolution: current 110-damage initial/repeat blasts and 1.1-second
  freeze, with the second target-bound blast after three seconds.
- Goblin Giant Evolution: permanent half-health trigger, 2.2-second interval,
  and Goblins spawning 2.5 tiles behind.
- Royal Hogs Evolution: 0.5-second descent and current 84 ground-only landing
  damage in a two-tile area.
- Hunter Evolution: current five-second Net cooldown and three-second snare.
- Baby Dragon Evolution: current symmetric +30/-30 movement wind.
- Mega Knight Evolution: current every-other-attack, four-tile uppercut.
- Electro Dragon Evolution: current 64-damage fourth-and-later chain bolts.

Current Supercell balance changes also override stale extracted values for
P.E.K.K.A Evolution, Witch Evolution, Wizard Evolution, Goblin Barrel decoys,
Royal Delivery, and other version-sensitive values. Every override carries its
source, verification date, and level in `combat_rules.json`.

The regression tests in `tests/test_sim_fidelity.py` cover each of these rules.

Run `python -m sim.action_audit` alongside `python -m sim.coverage`. The former
is the non-flattering report: it inventories evolution, hero, active-ability
and other client action graphs that the base card loader cannot call complete.
