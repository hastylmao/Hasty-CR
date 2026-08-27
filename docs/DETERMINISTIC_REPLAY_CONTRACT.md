# HastyCR Deterministic Replay Contract

Status: Sprint 2.5 audit contract, schema `hastycr-command-replay-v1`.

This document defines the boundary for reconstructing a HastyCR match from
player inputs. It is a reproducibility contract for the current simulator, not
a claim that HastyCR matches live Clash Royale mechanics.

## Contract

For a fixed HastyCR source revision, game-data hash, initial state, and fixed
ordered command stream:

```text
InitialState + ordered Commands -> deterministic engine -> complete battle
```

The simulator must not require a recorded trajectory, target choice, damage
result, projectile path, collision correction, spawn, death, or final result as
an authoritative replay input.

## Required Initial State

The authoritative initial state contains:

- `game_data_hash`: SHA-256 over the loaded `tmp/gamedata/csv_logic` files and
  the verified combat-rule table.
- `simulator_revision`: SHA-256 over the source files that define the current
  replay engine, arena, entities, match, game-data/spell loading, and replay
  schema. The current implementation uses a content revision so dirty
  checkouts remain identifiable.
- `level`: card/data level used to build the match.
- `seed`: deterministic match seed.
- Both ordered player decks, including their card identities and card levels as
  represented by the selected game-data level.
- `tick_ms` and ruleset identity. The current Match requires a 50 ms fixed tick.
- Initial elixir and elixir cap. The current Match requires 5000 milli-elixir
  and a 10000 milli-elixir cap.
- Arena/map constants used by the engine: dimensions, river boundary, and
  bridge centers. These are included in the serialized initial-state metadata.
- Explicit evolution slots and the `auto_abilities` compatibility flag when
  they are part of the match configuration.

The current `Match` derives the initial tower objects and tower state from the
rules/data and creates the initial hand/queue by shuffling each deck with a
local `random.Random(seed)`. An initial deck ordering may therefore replace
that seed in a future schema, but the current implementation requires the
seed and derives the ordering from it.

## Player Command Stream

Commands contain only external player-controlled actions:

```json
{
  "tick": 120,
  "player": 1,
  "type": "PLAY_CARD",
  "card": "musketeer",
  "x_mt": 9500,
  "y_mt": 20500
}
```

The current schema supports:

- `PLAY_CARD`: tick, player, card identity, and placement coordinates.
- `ACTIVATE_ABILITY`: tick, player, and the actor UID selected by the player.

Commands are ordered by nondecreasing tick. They are applied before the
simulation step at that tick, matching the existing fixed-step scenario
adapter. Rejected commands are not valid authoritative commands and should be
excluded from a clean replay; the recorder can expose rejection during audit.

No command stores a resulting position, target UID for card placement, HP,
damage, projectile, collision, spawn, death, crown, elixir, or winner value.
An ability actor UID is external selection input because the player explicitly
chooses the board entity; the ability's effects are derived.

## Derived Simulation State

The following are derived state and must not be replay inputs:

- entity creation, monotonic UID allocation, and spawn-group relationships;
- troop/building/tower positions and bridge-aware path choices;
- target acquisition, retargeting, target tie-breaks, and attack state;
- melee hit timing, projectile launch/flight/impact, and area effects;
- HP, shields, buffs, cooldowns, elixir regeneration, and hand cycling;
- collision separation, pushback, pulls, hurls, dashes, and forced movement;
- death resolution, death damage, child spawns, lifetime expiry, and cleanup;
- tower wake-up, tower HP, crowns, overtime/tiebreak, and winner.

The state digest serializes this derived state for verification only. It excludes
diagnostics, object identity, memory addresses, source paths, wall-clock values,
and other non-authoritative metadata. Mappings are key-sorted, sets are sorted
by canonical JSON, entities are keyed by UID, and Point values are integer
coordinate pairs.

## Randomness Audit

Battle-relevant randomness currently consists of the local Python
`random.Random(seed)` in `Match.__post_init__`, used to shuffle each player's
initial deck queue. No module-global RNG, unseeded NumPy/Torch RNG, UUID, or
wall-clock value was found in the battle path. UID allocation is monotonic
within `Battle.next_uid`.

The benchmark `SimpleOpponent`, random deck builder, soak scripts, and policy
training helpers use their own seeded RNGs to generate external commands or
benchmark episodes. They are not hidden engine state; their generated command
stream must be recorded if those policies are used.

Battle loops frequently iterate the insertion-ordered `Battle.entities`
dictionary. This is currently deterministic because entity insertion is
controlled by `Battle.next_uid`, and explicit `min(..., key=uid)` tie-breaks
are used in key selection paths. Set fields are used for membership/visited
bookkeeping, not as ordered action queues. The canonical digest sorts set
contents so a set's interpreter iteration order cannot alter the audit hash.

Known audit boundary: insertion order is an implicit part of current engine
execution in several loops. Future changes must preserve UID-based insertion
or introduce explicit UID sorting before changing construction order. The
Sprint 2.5 tests include irrelevant dictionary/set-order digest checks and
command-order validation.

## Historical Architecture Relevance

The pinned historical `royale-proxy/cr-messages` reference describes
`EndClientTurn` with `tick`, `checksum`, and `commands`, and its
`CommandComponent` carries command-specific payloads. This is historical
architectural evidence only; it does not establish current protocol formats,
current server behavior, or a modern protocol implementation. It is relevant
because it demonstrates the same useful separation: transmit player commands
and a state-check value, while the battle engine derives the world between
turns.

HastyCR does not reproduce Supercell's checksum algorithm. Its
`state_digest(tick)` is an independent SHA-256 audit digest with the only
required property: equivalent canonical simulator state produces the same
hash. It is intended for first-divergence debugging and regression detection.

## What Deterministic Does Not Mean

A deterministic simulator can consistently reproduce the wrong physics.

- **Determinism** means reproducibility: the same declared inputs produce the
  same HastyCR state and result, including across fresh Python processes when
  the same source/data hashes are present.
- **Calibration** means fidelity: HastyCR's derived state matches controlled
  observations of the target game.

Both are required. This contract makes no live-game accuracy claim and does
not change `real_measurements=0` or RL readiness.

## Versioned File

The canonical implementation is `tools/calibration/command_replay.py`.
`MatchReplay.to_dict()` and `write_replay()` use sorted-key, compact JSON. A
replay is valid only when its recorded game-data hash and simulator revision
match the executing checkout.
