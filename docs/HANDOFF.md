# Handoff, 2026-11-12

State of the project and the agreed next steps. `README.md` is the map of the
files; `CLAUDE.md` holds the working rules. Update this file when the plan changes.

## Goal

A bot that climbs the real Clash Royale ladder. The owner's first target is
Ranked league 3. Three other bot developers have reached global rankings; the
owner cannot yet reach league 3.

## What exists and works

- **Live bot** (`scripts/gamestate/live_play.py`): reads game memory on MuMu
  instance 3 (`127.0.0.1:16480`), runs the model, taps, queues ladder battles.
  The game updated to build 160635007 on 2026-11-07; the battle global was
  found (`scripts/gamestate/offsets.json`) and one reader frame was checked
  (towers, units, elixir, hand). After a future update the bot searches for the
  new address itself in its first battle (`discover_build`). Not verified: a
  full game played on the new build, and the buff vtable address hard-coded in
  `native/hcr_reader.c` (the current models do not use those inputs).
- **Reader fix, 2026-11-07**: 4.5% of enemy bodies (Evolved Witch skeletons,
  Goblin hero, evolved Furnace and others) were dropped before reaching the
  model. `live_bridge.py` now maps all 131,434 enemy bodies in the recorded
  games. Not yet seen in a live game.
- **Trainer** (`tools/league/`): PPO in RoyaleSim or, with `--real`, in the real
  game engine extracted to `vendor/re/headless`.
- **Gated single-deck training, built 2026-11-11/12** (all off by default):
  - champion gate: `train_eval_cycle.py --gate`, logic in `tools/league/gate.py`
    (its header states the rules and which thresholds are unverified);
  - opponent shares: `actor.py --opp-shares il,gen,snap` with `--opp-il`,
    `--opp-gen` (frozen), snapshots as a mirror match, PFSP-weighted;
  - opponent decks: `--deck-shares common,worst,pool`, per-deck results in
    `<run>/deck_wl/`;
  - imitation step after each PPO update: `learner.py --il-dir --il-w --il-steps`;
  - KL reference: `learner.py --kl-ref champion.pt`;
  - per-card levels: `"levels"` and `"tower_level"` in `focus_deck.json`;
  - `engine_bc.py --overlap --min-overlap --winners-only --obs-v`;
  - `calibrate_wait.py` (below); split decoding for evaluation
    (`actor.py --card-temp --time-temp --tile-temp`).
  Exercised: a short run with all of them together (`_test_mortar`, deleted
  once the real run is going), and the gate's promote / bad / rollback / hold /
  stop decisions with scripted results.
- **Scraper** (`tools/royale_scrape.py --deck ... --out ...`): restored
  2026-11-11. RoyaleAPI allows about 100 replays a sitting and the owner must
  sign in and clear the bot check. Never work around that limit.

## The deck (locked 2026-11-11)

Evo Mortar 16, Evo Skeleton Barrel 15, Cannon Cart 13, Rascals 14, Goblin Gang
16, Fireball 16, Barbarian Barrel 16, Hero Ice Wizard 16; King Tower 16 (the
owner's screenshot). File: `runs/league/league_mortar1/focus_deck.json`. The
owner also owns Hero Berserker.

- Hero Ice Wizard loads in the real engine and its ability works: 2 elixir, an
  `IceWizardHero_IceCube` appears and the target is frozen, one use per deploy.
  A press with no enemy in range stays pending (`abilitycheck` code 1006) and
  costs nothing until a target appears. RoyaleSim cannot load this hero;
  `realsim.py` builds its ability row itself (`HERO_COST`).
- No replay shows this exact list (24 player-games with these eight cards, none
  with the hero). Imitation uses the archetype: Mortar decks sharing five or
  more of the eight cards, winner's seat only: 6,600 games, re-played in the
  engine (`runs/league/mortar_bc`), then cut to plays of the owner's eight cards
  (`runs/league/mortar_bc_f`: 122,324 plays; other cards' plays and Berserker
  button presses dropped). **No row shows the Hero Ice Wizard button**; PPO has
  to find it. Watch `button_rate` in `log.jsonl`.
- The owner asked for exact-deck imitation and accepted the archetype on the
  condition that it is measured (below). The October list (Minions + Hero
  Berserker, 5,313 exact games, export in `data/mortar_exact_winners.jsonl`) is
  the fallback if it turns out to hurt.

## Version 0 and what was measured (real engine, opponent levels 16)

`runs/league/league_mortar1/hog/v0.pt` = `runs/tokens/rs_big/best.pt` in league
form (obs_v 5), fine-tuned two epochs on `mortar_bc_f`
(`runs/league/mortar_bc_f/v0.pt`), then its wait bias lowered by 2.071
(`calibrate_wait.py`, scale 3.0).

| model, decoding | opponent | games | win rate |
|---|---|---|---|
| all-decks model, gate temp 1.0 | held-out | 200 | 14.5% [10.3, 20.0] |
| fine-tuned, gate temp 1.0 | held-out | 200 | 19.5% [14.6, 25.5] |
| fine-tuned, gate temp 0.1 or 0.3 | held-out | 200 each | 0% |
| fine-tuned, timing 1.0 / card 0.1 / tile 0.1 | held-out | 200 | 30.5% |
| fine-tuned + shift 0.69 (human play rate), 0.1 | held-out | 200 | 4.0% |
| + shift 1.38 / 1.73 / 2.07 / 2.42 / 2.76 / 3.45, 0.1 | held-out | 200 each | 31.75 / 39.5 / 57.5 / 51.0 / 52.5 / 35.5% |
| **version 0 (shift 2.07), 0.1, other seed** | held-out | 400 | **53.4% [48.5, 58.2]** |
| version 0, 0.1 | `league_hogreal/gen/latest.pt` | 200 | 72.0% |
| version 0, 0.1 | all-decks imitation model | 200 | 91.25% (that opponent barely plays at 0.1) |
| version 0, 0.3 | held-out | 200 | 52.0% |

- An imitation model copies how often humans wait, so near-greedy decoding never
  plays (the Golem clone did the same). The shift is one number; the best value
  is three times the one that matches the human play rate. It was chosen on the
  held-out opponent, then confirmed on another seed and two other opponents.
- The archetype fine-tune is +5 points over the all-decks model at temperature
  1.0, inside the noise of 200 games. Not shown to help, not shown to hurt.
- For comparison, Hog v8 final scored 55.5% (300 games) against the same
  held-out opponent.
- The imitation step scores human rows with the shift taken out
  (`learner.py imitate`), or it would pull the wait bias back.

## The gated runs (2026-11-12)

Gate (`train_eval_cycle.py --gate`): N updates, then 800 mirror games against the
champion and held-out games on ladder decks (and against version 0 once the
champion has changed), both seats at gate temperature 0.1 and tile temperature 0.1.
Tiles matter: the live bot takes the best tile (`tools/league/live.py`), while
evaluations used to sample tiles at temperature 1 plus the 3% training exploration;
version 0 scores 57.5% that way and 66.5% with sharp tiles (same 200 seeds).
Promote at 54% with no benchmark more than 4 points under the champion's; two bad
gates in a row roll the learner back (the trained value head is kept); ten gates
without a promotion stop the run. Stop by hand: create `STOP_ALL` in the run folder.

Version 0 for these runs also has its hero-button bias raised by 6.5
(`button_shift` in the checkpoint's meta): the button logit sat about 7 under the
wait logit, so the button was never sampled and PPO could not find it. Held-out
result with the raise 66.1% against 63.5% without (400 games each, same seeds).
In training the button is now pressed on 0.3-0.45% of decisions.

**Version 0, the number to beat: 66.75% [63.4, 69.9] against the held-out model
(800 games, seed 9001); 67.25% over 400 games on the gate's seed.**

### Setting A, `runs/league/league_mortar1` (stopped)

`launch.sh` there: lr 2e-5, KL 0.02 to the champion, entropy 0.003, 30 imitation
steps per update, training temperature 0.3, 10 value-only warm-up updates.

| gate | updates | vs champion (800) | held-out (400) | decision |
|---|---|---|---|---|
| 1 | 20 | 46.6% [43.1, 50.0] | 63.75% | bad |
| 2 | 40 | 55.1% [51.7, 58.5] | 62.75% | rollback (held-out regression) |

Re-measured over 800 games on another seed: 61.5% after 20 updates, 61.1% after
40. The policy learned the mirror and lost about 5 points on ladder decks, all of
it within the first 10 policy updates. The gate caught it in 50 minutes.

### Ablations, `tools/league/ablate.py` (results in `runs/league/ablate_mortar.jsonl`)

Ten updates from version 0 (with setting A's trained value head), one change each,
then 800 held-out games (seed 9001) and 400 mirror games against version 0.

| change from setting A | held-out | mirror vs version 0 |
|---|---|---|
| (version 0 itself) | 66.75% | 50% |
| none: setting A after 20 updates, 10 of them policy updates | 61.5% | 46.6% (gate 1) |
| no entropy bonus | 62.9% | 46.75% |
| no imitation step | 58.9% | 49.25% |
| **quarter step size (lr 5e-6)** | **66.6%** | **53.75%** |

Not run (stopped to start setting B): the same-settings control, training
temperature 0.1, KL weight 0.2. `ablate.py --only same,temp01,kl02` runs them.

Reading: the step size was the damage. One update sees about 190 games, so the
win/loss signal is mostly noise and a large step is a random walk (daybreak-cr
uses 1,024 games per update). The imitation step helps: without it the drop was
8 points instead of 4-5. The entropy bonus is not the cause.

### Setting B, `runs/league/league_mortar2` (running when this was written)

Setting A with lr 5e-6, gates every 30 updates, 800 held-out games per gate, no
warm-up (starts with the trained value head). Results: `gates.jsonl` there.

### Setting B result and the diagnosis (2026-11-12 midday)

| gate | updates | vs champion (800) | held-out (800) | vs version 0 | decision |
|---|---|---|---|---|---|
| 1 | 30 | 55.2% | 62.4% (baseline 66.1%) | - | promote (a gate fault, fixed: see below) |
| 2 | 60 | 53.6% | 60.25% | 56.6% | hold |

Stopped. The smaller step only slowed the same pattern: the mirror rises, the
held-out result falls. Gate fault found: the benchmark bar was the current
champion's own result, so it could slide 4 points at every promotion; `gate.py`
now keeps the best result any champion had.

Checked and ruled out (800 games each against the held-out model):
- decoding mismatch: under training-style decoding (gate 0.3, tiles sampled)
  version 0 scores 55.9% and the 60-update model 51.6%, so PPO made it worse as
  trained too;
- timing drift: raising the 60-update model's wait bias by 0.3 / 0.6 gives 62.0% /
  60.9% (60.25% untouched).

Open suspects, in `ablate.py` as `nomirror` (no snapshot opponents) and `nostarts`
(no mid-match / defence starts, which were built for Hog), with the `same` control.
See `runs/league/ablate_mortar.jsonl` for whether they have run.

Hog v8 final under the same live-style decoding: 59.3% [55.9, 62.7] over 800 games
(55.5% with sampled tiles). Version 0 of the Mortar deck: 66.75%.

### Later ablations and the verdict on PPO (2026-11-12 evening)

Same test (800 held-out games, seed 9001; version 0 = 66.75%):

| change from setting A | updates | held-out | mirror vs version 0 |
|---|---|---|---|
| no snapshot (mirror) opponents | 10 | 61.25% | 42.6% |
| no mid-match / defence starts | 10 | 63.5% | 51.25% |
| none (control; setting A again) | 10 | 62.5% | 56.4% |
| lr 5e-6 and no starts | 23 (60-minute cap) | 59.25% | 48.25% |

The control reproduces setting A's drop, so the table can be trusted to about
+-3.5 points. **No PPO setting tried has beaten version 0 on the held-out test;
every one loses 3-8 points, and the small step only delays it.** Ruled out as
the cause: step size alone, entropy bonus, the imitation step (it helps), mirror
games, scenario starts, decoding mismatch, timing drift. Not tried: more games
per update (one update sees about 190 games; daybreak-cr uses 1,024; memory
limits this PC), a critic that sees more than the policy, a different reward
(`--shape-w`), training temperature 0.1, KL weight 0.2. Do not start another long
PPO run in the current form.

## Replay sources (2026-11-12)

- `tools/royale_scrape.py` works again for the exact deck. Deck slugs need the
  forms: `mortar-ev1,skeleton-barrel-ev1,cannon-cart,rascals,goblin-gang,fireball,barbarian-barrel,ice-wizard-hero`.
  New options `--challenge-wait <s>` (a Cloudflare check mid-run waits instead of
  ending the run) and `--notify` (beep + Windows message when a person is needed).
  The login persists in `tmp/royale_loop_profile`. Two sittings gave 52 replays in
  `data/replays_mortar` (9-12 November, top-80 rated players, 106+ hero ability
  presses); 330 more battles are listed in `pending_battles.json`. The second
  sitting got 692 "too many requests" answers at 4 requests a second: use
  `--ceiling 1 --workers 4` next (untested). Never use proxies, extra accounts or
  an auto-clicker for the check (the owner asked; refused).
- The converter exists now: `tools/league/scraped_to_payload.py` (next section).
- `data/cochon/` = Hugging Face `Cochon123/clash-royale-replays`, snapshot
  2026-11-01 (MIT): 63,930 usable RoyaleAPI replay captures, all from July-August
  2026, base card names only (no forms). One seat with the exact list; 3,208
  archetype seats (5+ of the 8 cards). Older than `data/il_replay`; not used.

## Exact-deck replays and version 1 (2026-11-12 night / 11-13)

**Version 1 = `runs/league/mortar_exact_bc2/x_arch_c4.0_btn6.5.pt`. It is the first
model that beats version 0.**

- The owner collected 2,000 replays of the exact list with a Codex-built
  collector (outside this repo: `Documents/Codex/2026-11-12/.../outputs/exact-mortar-top-ladder/replays.sqlite3`;
  it routes six signed-in browsers; not built or maintained from here, see the
  rules). All `pathOfLegend`, 89 players, 7-12 November, 1,111 wins, hero
  ability presses in 1,749 games.
- `tools/league/scraped_to_payload.py --db <sqlite> --out data/mortar_exact_scraped.jsonl`
  writes the payload lines `engine_bc.py --replays` reads. It rewrites the whole
  file, so rerun it when the database grows. 160 of 2,000 games drop in the
  loader because the opponent has a card the engine does not know
  (`minion-giant` 91, `spirit-empress` 40, `rune-giant` 16, `void` 14).
  UNVERIFIED: the scrape has no levels; every card is written as level 16.
- **Orientation.** In half of the scraped games the listed player is on the far
  half; the corpus never has that. Rows from those games, read as they are, gave a
  start tile loss of 5.1 (near uniform). The converter now turns those games 180
  degrees; the start tile loss is then 2.66 / accuracy 0.30, the same as on the
  archetype rows. So `engine_bc.py`'s far-seat path produces rows the model reads
  badly; it is avoided, not fixed. UNVERIFIED whether the true transform is a
  turn or a y-flip (a game mirrored left-right is still legal).
- Rows: `runs/league/mortar_exact_bc2`, 1,114 winning seats, 73,079 rows, about
  18,950 card plays, 563 hero button presses (the first rows with presses).
- Fine-tune: 4 epochs, default lr and KL, from two starts. Held-out tile
  accuracy 0.30 -> 0.33 (`x_arch`, from `mortar_bc_f/v0.pt`) and 0.27 -> 0.32
  (`x_gen`, from the all-decks model).

Against the held-out model, gate and tile temperature 0.1, 800 games each:

| model | seed | win rate |
|---|---|---|
| version 0 | 9001 | 66.75% [63.4, 69.9] |
| `x_gen`, shift scale 3.0, no button raise | 9001 | 51.8% [48.3, 55.3] |
| `x_arch`, shift scale 3.0, no button raise | 9001 | 57.4% [54.0, 60.8] |
| `x_arch`, shift scale 4.0, no button raise | 9001 | 63.1% [59.7, 66.4] |
| **`x_arch`, shift scale 4.0, button +6.5 (version 1)** | 9001 | **72.9% [69.7, 75.8]** |
| version 1 | 7007 | 73.3% [70.1, 76.3] |
| version 1 against version 0, mirror | 7008 | 62.7% [59.3, 66.0] |

- Shift sweep for `x_arch` (200 games, seed 4242): scale 2 / 3 / 4 / 5 / 6 =
  28.25 / 54.0 / 63.0 / 56.0 / 42.5%. Applied shift 2.195. The shift has to be
  fitted again after every fine-tune.
- The exact rows alone (`x_gen`) are worse than the archetype rows alone: 73k
  rows against 667k. The gain comes from the two together.
- The button raise is worth about 10 points here and was worth 2.6 on version 0.
  563 presses moved `button_head.bias` only from -2.55 to -2.52, so the raise is
  still needed; reading (not tested): the rows taught when to press.
- Fireball is still played about half as often as the other cards; the human
  rows show the same ratio (5,277 casts against about 10,000 per other card).
- Not done: the 889 losing games are unused (value training); `x_arch` mixed
  with the archetype rows in one training; more than 4 epochs.

## Night of 2026-11-13: more data, and placement search

### More exact-deck data and training variants: no gain

The database had 2,948 games; rows in `runs/league/mortar_exact_bc3` (66 chunks),
mixed rows in `runs/league/mortar_mix` (hard links: archetype rows + exact rows
three times). Driver `tools/league/exact_cycle.py` (fine-tune, shift sweep at 400
games on seed 4242, button +6.5, 800 held-out games on seed 9001, 800 mirror games
against version 1 on seed 7008); results in `runs/league/exact_cycle.jsonl`.

| candidate | change | held-out | against version 1 |
|---|---|---|---|
| version 1 | 2,000 games, 4 epochs | 72.9% / 73.3% | - |
| `e4` | 2,948 games | 66.4% | 49.1% |
| `e8` | 8 epochs | 72.1% | 49.4% |
| `mix3` | archetype + exact x3, from the all-decks model | 73.3% | 47.8% |
| `e8kl` | 8 epochs, KL 0.02 | 70.9% | 50.5% |

All four are level with version 1 head to head. The held-out spread follows the
shift picked: neighbouring scales differ by 5 points and the 400-game sweep cannot
order them. Held-out tile accuracy stays at 0.32-0.33 in every run. Reading: this
recipe is at its plateau near 2,000 games; 948 more games is a small step, so the
question "does 10,000 help" is open, but the flat tile accuracy says not much.

### Placement search: +20 points on version 1 (real, checked with a control)

- `vendor/re/headless/loader_fork.c` = `loader.c` plus two commands; binary
  `loader_fork` (build: `gcc -O1 -g -o loader_fork loader_fork.c -ldl -lm` in WSL).
  The normal `loader` is unchanged; `LOADER=loader_fork` selects the new one.
  - `try <ticks> <command>`: a forked copy of the game runs the command, then
    the ticks, prints the state and exits; the game itself does not change.
    About 8 ms per trial of 160 ticks. Checked: a copy equals the original at the
    fork and after 300 ticks, and the original is unchanged after trials.
  - `fork`: a copy that serves a new TCP client. Works, but a new connection from
    Windows into WSL takes about 1 s; not used.
- `realsim.RealBattle.try_plays(team, hand slot, cells, horizon, material)`: one
  score per cell, daybreak-cr's formula (crowns + tower hp fractions, theirs
  minus ours, + material x unit hp in princess towers), no further plays in the
  copy. UNVERIFIED constants horizon 160 and material 0.3 (theirs).
- `actor.py --search-k K` (eval, candidate only): the policy's tile and its K
  best tiles are tried, the best is played. `--hide-inflight`: the opponent's
  plays reach the engine at their tick, so copies do not hold plays the candidate
  cannot see during the 26-tick command delay (`RealBattle.hold`).

Version 1, K = 8, 800 games each:

| test | no search | search | search, in-flight hidden |
|---|---|---|---|
| held-out, seed 9001 | 72.9% (71.1% with hiding) | 94.6% | **93.0% [91.0, 94.6]** |
| against version 1, mirror, seed 7008 | 50% | 89.6% | **87.7% [85.2, 89.8]** |
| held-out, horizon 80 | | 89.2% | |
| held-out, material 1.0 | | 94.5% | |

- The control (no search, hiding on) gives 71.1%: hiding changes nothing else.
  The foresight of plays in flight was worth about 1.5 points, not the gain.
- The search moves 62% of the placements.
- Still in the copies: the engine's exact future (same dice), and hero ability
  presses in flight. daybreak-cr accepts the first. They measured 65-70% for the
  same idea; ours is larger, probably because this policy's tiles are weaker (tile
  accuracy 0.33) and the opponents are soft.
- **Search cannot run live** (no engine copy of a real game). Its use is as a
  teacher. Running when this was written (`runs/league/night_1113d.sh`): 1,600
  searched games against `league_hogreal/gen/latest.pt` and version 0 (not the
  held-out model) -> labels in `runs/league/search_labels1` ->
  `tools/league/search_distill_prep.py` (a best score less than 0.02 over the
  policy's tile keeps the policy's tile) -> `engine_bc.py --tile-only` from
  version 1 (tile loss + KL anchor on the gate, so the wait shift and button raise
  stay) -> `runs/league/search_rows1/d1.pt`, 800 held-out games without search.

## First live games (2026-11-12, version 0, ladder)

`reports/live_play/20261112_135100.jsonl`: 8 games, 2 wins, 6 losses (0-1, 0-1, 0-3,
0-3, 0-3, 2-0 win, 1-2, 2-1 win). Eight games decide nothing (2 of 8 is compatible
with anything from 7% to 59%); the plan's 30 games are still owed.

- Plumbing worked: every play landed on its tile, the seeded deck order
  (`deck_order.json`, in deck-screen order) needed no correction, delay 24-27 ticks.
- The model behaves live as it does in the engine: share of decisions each card
  sat in hand, live / engine: Fireball 0.81 / 0.74, Cannon Cart 0.55 / 0.57, Mortar
  0.51 / 0.53; Fireball casts per game 0.9 / 2.0; plays per game 26 / 34 (engine
  games include overtime). `actor.py --eval` now prints `plays`, `plays_per_game`
  and `hand_share`.
- So the 66% in the engine and the losses on the ladder are the same policy:
  the engine's opponents (our own bots) are softer than people. No engine number
  here predicts the ladder; only ladder games do.
- Seen in the games: Fireball almost never cast; Skeleton Barrel, Goblin Gang and
  Barbarian Barrel placed on the same bridge tile nearly every time; Ice Wizard
  sent alone to the bridge; slow or no answer to Balloon and Mega Knight. Mega
  Knight's landing forms (`MegaKnightAppear`, `MegaKnight_EV1_appear`) are not in
  the model's vocabulary.
- Hero button: `tools/league/live.py` now knows Hero Ice Wizard (one press per
  deploy; the hero and its cubes all read as "IceWizard"). It tapped (100, 1470)
  1-5 times a game; **whether the ability fired on screen is not confirmed**.
  `live_play.py --button-px x,y` overrides the position.

## Next steps, in order

**Current order (2026-11-13); the numbered list below is the older plan and PPO
is shelved.**

- Live: the hero button position is fixed (2026-11-13, owner's screenshot): the
  first hero's button is bottom right, `BUTTON_PX[0] = (972, 1455)` in
  `tools/league/live.py`; it was the left spot before, so no press ever landed.
  Not yet seen working in a live game. The button is worth
  about 10 points in the engine. Then 30 ladder games. Version 0 went 2-6 live at
  66% in the engine, so the engine number alone proves little.
- More exact-deck replays: rerun the converter, re-play into a new rows folder,
  fine-tune from `mortar_bc_f/v0.pt`, sweep the shift, add the button raise,
  800 held-out games on seed 9001.
- Placement search and distillation (daybreak-cr's direction since 6 November:
  `experiments/search_labels.py`, `distill.py`): not started. First test: can
  the engine process be forked mid-game.


1. **Read the first three or four gates.** The held-out number is the one that
   matters (the mirror head-to-head can rise from learning the mirror only). If
   it does not rise above version 0's, stop and change the setup. Things to try
   then: fewer imitation steps or more, KL weight (daybreak-cr saw a stale
   champion anchor hold a learner back), training temperature 0.1 instead of
   0.3, the October list with exact-deck imitation.
2. **Live:** each promoted model plays 30 ladder games. The ladder record
   decides, not the simulator. Expect live bugs for the new deck: the hero
   button position, `IceWizardHero*` body names (mapped in `live_bridge.py`,
   not seen live), RoyaleSim's catalogue refusing the hero form in
   `live_play.py`.
3. **Scrape** about 100 current replays of the exact deck a day. The scraper
   keeps tile positions; a converter to the `data/il_replay` record format
   (`royaleapi-battle-actions.v1`) is not written.
4. Later experiments: placement search in the engine (daybreak-cr measured
   65-70% for search over the plain policy; PPO improved their timing, not their
   placement); the three split-decoding settings that printed no result.

## Decisions (owner)

1. 2026-11-11: Hog 2.6 is dropped. Deck above.
2. Train one deck, in the real engine, with the methods the other bots share.
3. Train rewards and scenarios, not hand-written live rules. Guards stay off.
4. The opponent's hand and elixir are never read from memory; opponent elixir
   is counted from their plays.
5. 2026-11-12: keep the Ice Wizard list and imitate the archetype, provided it
   is measured against the model without it.

## What the other bots do (read 2026-11-07 to 11-11)

- **Jason-XII/daybreak-cr**: trains in the real engine on 176,732 exactly
  re-played human games (a private dataset); imitation, then PPO under a
  champion gate; a critic that sees the opponent's hand in training only; card
  and tile temperature 0.05 live, timing sampled. Their findings: PPO improved
  when to play, not where; placement is their largest gap; self-play plateaus;
  precise cycle decks (Hog, X-Bow) suit a bot worst, Mortar best (59.6%
  self-play).
- **vegetableleaf/ClashAI**: imitation, then a forked RoyaleSim he corrects
  rule by rule; observation noise copying his live reader; a penalty for idling
  under threats; training at real card levels took him from 13k to 14,060
  trophies. No licence: use ideas, never copy code.

## Rules that are easy to break

- Never run the live bot and training together (memory ran out twice). MuMu
  was up when the run started on 2026-11-12; the owner was told.
- Never start MuMu automatically; drive instance 3 only.
- Never pass `--deck` or `--no-bm` to `live_play.py`.
- Never bulk-read the game's heap.
- No commits unless the owner asks.
- Evaluate with both seats at gate temperature 0.1, in the real engine. Do not
  evaluate while training runs.
- Mark guessed constants as unverified; measure before concluding.

## Disk clean-up (2026-11-14)

The C: drive was down to 5 GB free. Deleted, about 12 GB, all of it regenerable or
superseded: `data/cochon/` (unused Hugging Face snapshot, re-downloadable),
`runs/league/mortar_bc` (the uncut archetype rows; `mortar_bc_f` is the cut that
training reads, and the rows can be re-played from `data/il_replay`), the seven
`runs/league/abl_*` PPO ablations (PPO is shelved), `runs/league/_test_mortar`,
and the losing tower-phase candidates (`tower_phase/rows`, `rowsB`, models a8h,
a8k, a20, b8h). Kept: every model named in this file, all search labels,
`tower_phase/rowsA/a8.pt`, `mortar_bc_f`, `mortar_exact_bc2/3`, `data/il_replay`.

## Tower phase, UC generic model (2026-11-13 to 2026-11-14)

**Dead-lane bug (open).** Live, the bot keeps playing Mortar and Skeleton Barrel
into the lane whose enemy princess tower is already down. Measured with the
`lanes` count in `actor.py` eval output (plays split dead lane / live lane while
exactly one enemy princess is down) and `--eval-tower` (games start with one
enemy princess at 0 hp). Mortar into the dead lane: d1 56%; d1 with placement
search 16-19%; every distilled model (d2, a8, a8h, a8k, b8h, a20) 47-62%. Search
fixes it, distillation of the search labels does not carry it over, even with
164k labels and tower-start labels weighted x3. Cause not known. Not yet run:
check on held-out label rows whether the tower-down input changes the tile head
output at all.

**Models.** `runs/league/search_rows1/d1.pt`: 76.7% held-out, 62.6% vs version 1.
`runs/league/tower_phase/rowsA/a8.pt`: 75.6% held-out, 56.2% [52.7, 59.6] vs d1.
Both keep the dead-lane bug. Tower-start win rate is about 98.5% for every model,
so it cannot rank models; only the lane count can.

**UC scrape.** The owner's scrape (`C:\Users\aksha\Downloads\replays.sqlite3`,
read-only, never read its `proxy_pool` table) had 92,334 Path of Legend ultimate
champion games on 2026-11-14. `tools/league/scraped_to_payload.py` got
`--winner-as-team`, `--skip-unknown`, `--offset`, `--limit`. `engine_bc.py
--focus ""` collects all decks. Payloads in `data/uc/`, rows in
`runs/league/uc_pilot` (2,000 games) and `runs/league/uc_s1` (38,000 games).

**Generic model A** (`runs/league/uc_s1/genA.pt`, 3 epochs from
`league_hogreal/gen/latest.pt`): held-out tile accuracy 0.12 to 0.27, flat after
epoch 1. Fine-tuned on `runs/league/mortar_mix` with the version 1 recipe
(`exact_cycle.py --name gA_mix`): 77.3% [74.3, 80.1] held-out against 72.9% for
version 1 from the same recipe without the generic start; 58.3% vs version 1.
Checkpoint `runs/league/mortar_mix/gA_mix_c3.5.pt`.

**Why re-driven games are lost** (`tools/league/redrive_diag.py`, 200 pilot
games): 66 run to the end; 58 fail at reset; 46 end early in the engine (22 of
them at tick ~3690, where the real game went to overtime; cause unverified,
levels or tower levels are a guess); 30 stop on a card that is not in the hand
(12 are Elixir Collector at play 1-3, not diagnosed). The reset failures are Hero
Electro Wizard (40) and evolved Electro Giant, Giant and Mirror (18): the engine's
tables are build 160402012 and do not carry those forms (no
`characters/hero_form` file, placeholder row in `spells_hero_form.csv`). The live
game is build 160635007. This needs newer tables in the engine, not a realsim
patch.

## Newer game tables in the engine (2026-11-14)

`gA8` (`runs/league/tower_phase/rowsA/gA8.pt`): a8's search distillation on top of
`gA_mix`. 81.4% [78.5, 83.9] held-out (a8 75.6%), 53.5% [50.0, 56.9] against a8.
Best model so far; the dead-lane bug is still there (Mortar 55% dead lane).
`gA_mix` alone lost to a8, 42.3%.

The build 160635007 logic tables were pulled read-only from instance 3 into
`vendor/re/target/build_160635007/` (`decode.py` decodes them). The engine code is
still build 160402012. `vendor/re/headless/merge_assets_new.sh` builds
`/root/assets_merged_new`; the engine uses it only when `HASTY_ASSET_ROOT` is set
(from Git Bash also set `MSYS_NO_PATHCONV=1`). Default is unchanged. Measured:

- Every new table: load crashes on `ClassType = "ActionAbilityDelivered"` (five
  files, kept old). Without those it loads, but battles break from the first play
  (elixir short, deploys refused). Not diagnosed.
- All of `characters/`: an engine fault mid-battle (pilot game 55). The file that
  causes it was not found.
- New-form files + `spells_*` + `hero_form/` only: runs. Reset failures 58 -> 1 of
  200 pilot games. Evolved Electro Giant, Giant and Mirror games look normal (4 of 21
  end before 3:00, small sample). Hero Electro Wizard does not: 24 of 42 games end
  before 3:00, against 11 of 142 for other games. It is left out of `HERO_COST`, so
  its games are still dropped at reset.

`realsim.reset` now builds its ability template without any form RoyaleSim cannot
load, not only Hero Ice Wizard. `vendor/re/target/build_160635007/form_test.py`
plays one form in the engine; `tools/league/redrive_diag.py` prints each game's
decks to stderr.

## Re-drive fixes (2026-11-14, later)

Measured on the 200 UC pilot games with `tools/league/redrive_diag.py` (old tables):
full games 66 -> 93, "card not in hand" 30 -> 10.

- **Elixir Collector and Mirror are never dealt into the starting hand.** With one
  in deck slots 0-3 the engine fills the hand from slot 4. `deal_order`
  (`tools/royalesim_redrive.py`, `tools/realengine_redrive.py`) now skips such
  starting hands.
- **Champion ability presses were lost.** The scrape does not name the pressed unit
  and `scraped_to_payload.py` lists only `-hero` cards as candidates. `engine_bc.py`
  now presses whichever button is ready when the candidates do not match.
- **Play timing is right.** Shifting every play by -20 / -10 ticks adds elixir
  shortfalls; +10 / +20 changes nothing.
- **Open: engine game over early, 55 of 200.** A tower falls in the engine that did
  not fall in the real game, about as often for the real loser as for the real
  winner, so it is divergence, not a one-sided bias. 20 end at 3:00 on a crown lead,
  26 by sudden death in overtime. Unknowns the scrape cannot give: card levels
  (assumed 16), tower troop type. The engine also plays the old build's balance.
  Everything after the cut is lost, which thins exactly the late game.
- Control `tools/league/controls/hog_hits.py`: 7 hits, identical trace, with the
  default tables and with `/root/assets_merged_new/`.

Pilot re-collect with all fixes and the new-table tree: 135,677 -> 162,077 rows
(`runs/league/uc_pilot2`). Full re-collect of 75,443 games and the genB -> gB_mix ->
gB8 chain: `runs/league/uc_v2/chain.sh`, log `chain.log`. Its evals run with the
new-table tree, so compare gB8's held-out number with gA8 re-run under the same tree,
not with gA8's 81.4%.

## Engine port to build 160635007 (2026-11-14, evening)

The live game's engine code now runs in the headless loader. Opt in with

    MSYS_NO_PATHCONV=1 HASTY_ASSET_ROOT=/root/assets_new_full/ \
    HASTY_LIBG=../target/build_160635007/dump/libg_mem.so LOADER=loader_new

Default (no variables) is still the build 160402012 engine; nothing of it was changed.

How it was made (all in `vendor/re/port/`, sources of truth, re-runnable):
- `target/build_160635007/dump/`: the six libg.so segments read from `/proc/<pid>/mem`
  of the running game on instance 3 (library image only, no heap); `build_mem.py`
  joins them into `libg_mem.so`. Base 0x7dcfd224c000, code segment 0x1a56000.
- `xref_map.py`: translates an old address through the code that references it
  (4-byte RIP-relative fields, context matched in the new code, sites vote).
  `func_map.py`: second method, function body with 4-byte fields wild. 62 addresses
  agree between both; a single xref vote was wrong once, so body wins over < 3 votes.
- `ctor_map.py`: carries the recovered constructor heads over (710 of 760 entries).
- `make_loader.py`: writes `headless/loader_new.c` from `loader_fork.c` (97 addresses,
  hand-checked ones listed in it). Tables object: 0xdf -> 0xe2 tables, fields from
  +0x6f8 up by 0x18. `+0x1098` and `+0xfe4` got the same shift UNVERIFIED.
- `/root/assets_new_full`: old raw assets + all decoded build 160635007 tables.

Measured: load matches the old engine's log (22,616 rows, 40 faulted, 39 before);
`controls/hog_hits.py` gives 7 hits with the identical trace; all 200 pilot games
re-drive without an engine fault (99 full).

Open on the ported engine:
- **Hero Electro Wizard attacks 3.6x too fast** (`controls/unit_hits.py ElectroWizard 2`:
  a hit every 10 ticks, all three towers dead; form 0: every 36 ticks). It starts in
  its ability attack sequence. Its `ActionSelect` picks the sequence by the condition
  `!UNIT_CUSTOM_TAG_1`; that condition seems to evaluate false here. Same symptom on
  the old engine code. Cause not found (a faulted or head-less static constructor is
  the first suspect: 12 faulted, 58 without a head). Until fixed its games stay out.
- 12 constructors fault (4 on the old build), 58 have no head (55).
- `loader_new` is the fork-capable loader only; `try` (placement search) not tested.
- Struct offsets inside rows and battle objects were not audited; only what the
  controls exercise is known to work.

Later the same evening: constructor heads redone with `port/recover_new.py`
(recover_ctors.py's solver on the new image, RIP references from objdump): 4
constructors fault, as on the old build; 58 stay without a head (55 before). Hero
Electro Wizard is unchanged by that. Checked: it has no buff and its ability is not
pressed, yet it uses the fast sequence; the constructor that references the string
`UNIT_CUSTOM_TAG_1` (0x7dcfd3304610) has a head and does not fault. Still open.
`HERO_COST` leaves it out on both engines.

## UC re-collect, 75k games: gB8 (2026-11-14)

`runs/league/uc_v2/chain.sh` re-collected all 75,443 UC games (3,018 row files) with the
re-drive fixes and the safe new-table tree (`HASTY_ASSET_ROOT=/root/assets_merged_new/`,
old engine code), then repeated the gA8 path: `genB` -> `mortar_mix/gB_mix_c4.0.pt` ->
`tower_phase/rowsA/gB8.pt`.

Results, all 800 games, same asset tree:

- Held-out: gB8 81.5% [78.7, 84.0]; gA8 81.4% [78.6, 84.0]. No difference.
- gB8 as candidate vs gA8 (seed 7008): 55.3% [51.9, 58.7].
- gA8 as candidate vs gB8 (seed 7108): 47.0% [43.6, 50.5], so gB8 53.0%.
- Pooled 1,600 games: gB8 about 54.2%, roughly [51.7, 56.6]. Crown difference near zero.

Reading: doubling and cleaning the generic data gave no held-out gain and a small
head-to-head edge. Generic data looks saturated near 38k games. gB8 is the best model
by a thin margin; it has not been played live. Dead-lane share is unchanged (Mortar 54%,
Skeleton Barrel 78% in the held-out run). The fine-tune sweep was noisy at 400 games
(74% / 80% / 73.5% for c3.5 / c4.0 / c4.5), so the c4.0 pick may be partly luck.

## Tower vector is not in the model's frame (2026-11-15, cause UNVERIFIED)

Live game with gB8: the bot pushed the 1787 hp princess while the other was at 230 hp.
Code facts: `obs.towers_vec` orders princess slots by world x (slot 1 = x < 9000), but
`obs.own()` mirrors x for team 1; towers are left out of the unit list (`obs.build`); the
model is trained on both teams (`engine_bc` focus teams, `actor.py`). So no input tells the
model whether slot 1 is its left or its right. Live the bot was team 1 in all 14 games of
`reports/live_play/20261114_231857.jsonl` (every tile is the mirror of the model tile).
This would explain the coin-flip Mortar lane share (54% dead) in every model, but that is
a hypothesis, not a measurement.

`HASTY_TOWERS_OWN=1` (tools/league/obs.py) puts slot 1 on the model's left for both teams.
Off by default. The live bot uses the same builder, so it needs the same variable for a
model trained with it. Control still to run (needs the engine, so the live bot off):
re-collect `runs/league/mortar_mix` and the tower-phase search labels with the variable
set, repeat the fine-tune and distillation from `uc_v2/genB.pt`, compare the `lanes`
counts of `actor.py --eval-tower` against gB8. Rows made with and without the variable
must never be mixed.

## Mother Witch pigs were invisible live (2026-11-15)

`live_bridge.rs_state_from_frame` dropped every body that has a unit token but no
card (`rs_card < 0`). The Mother Witch's `VoodooHog` is one: capture
`reports/card_audit/unknown_captures` of 2026-11-13 shows it as "living character
excluded from bridge". The drop is removed; such bodies now go in with card -1, as in
real-engine training states (card_id is -1 for every unit there). Not yet seen working
in a live game: needs a bot restart and an opponent with Mother Witch, then check that
no new `VoodooHog` capture appears. Units with no token at all (`ChefTowerKing`,
`electro_dragon_ev1`) are still dropped.

## Game tags were never loaded: every tag condition read false (2026-11-15)

Root cause of the Hero Electro Wizard bug, and it was not specific to that card. The
table driver (old `FUN_79df9fecf470`, new `0x7dcfd31efc60`) handles file type 3
(`game_tags.csv`) and type 2 only when its arg 6 is set. The loader leaves arg 6 off
and does that pass by hand, so the tag init (old `FUN_79df9fe78640`, new
`0x7dcfd31965e0`, fills the name maps at tables +0x1030 / +0x1058) never ran. A
condition that names a tag then fails to resolve and reads false, negated or not.

How it was measured (`vendor/re/target/build_160635007/probe_cond.sh`): the first
condition of Hero Electro Wizard's attack `ActionSelect` replaced in a copy of the
table tree. `1 == 1`, `!is_clone()`, `is_active_or_secondary_champion` took the first
branch (hit every 36 ticks); `UNIT_CUSTOM_TAG_1`, its negation, `!NO_ATTACK`,
`!CHARGING()`, `!CASTING_ABILITY` and a made-up name all did not (every 10 ticks).

32 table files use tag conditions: 12 heroes, the evolved Battle Ram, Electro Dragon,
Furnace, Royal Ghost, Goblin Cage, Hunter, Inferno Dragon, Minion Horde, Barbarians,
Royal Hogs, Wizard, plus Golden Knight, Little Prince, Goblinstein, Goblin Machine,
Rune Giant and others. All of them ran with those conditions false in every
collection and training run so far, on both engine builds.

Fix: `loader_fork.c` calls the tag init for the type-3 file before the row passes
(`NO_TAGS=1` restores the old behaviour; type 2 stays skipped, `TYPE2=1` runs it,
UNVERIFIED what it holds). `make_loader.py` carries both addresses.

Second bug found on the way: `make_loader.py`'s `0xdf -> 0xe2` table-count pattern
held backspace characters and matched nothing, so the ported loader's row passes
skipped the three tables the new build appended. Fixed; the load now reports 22,631
rows (22,616 before), still 40 faulted, all in the same five meta tables.

Built as `headless/loader_new.build` and `headless/loader_fork.build` so runs in
progress keep their binary. NOT yet renamed over `loader_new` / `loader_fork`: do that
when nothing is running, then re-run the controls on the old build too.

Measured with `LOADER=loader_new.build` on the new tables:
- `controls/unit_hits.py ElectroWizard 2`: 4 hits, 36 ticks apart, same as form 0
  (was 32 hits, 10 apart). After an ability press the 10-tick sequence appears, as the
  table says it should.
- `controls/hog_hits.py`: 7 hits, identical trace.
- 200 pilot re-drives with Hero Electro Wizard allowed (`HASTY_HERO_TEST=ElectroWizard=2`,
  a test-only switch in realsim.py): 126 run to the end (99 before), 62 end early (92).
  `tools/league/redrive_cards.py` ranks cards by early-end rate; no card stands out
  clearly at 200 games, the rate is about 30% without any given card.

What a scraped replay can and cannot check: its levels are "assumed", it has no final
tower hit points and no seed, only plays and crowns. So a re-drive that ends early
shows a difference but cannot say whether the engine, the levels or randomness made it.
The exact check is `tools/live_redrive.py` on live logs made with `--record-frames`:
every unit's position and hit points per frame at known levels. No log of the current
game build has frames yet.

`tools/league/controls/card_battery.py` (new): every card in every form alone against
towers, evolutions reached by cycling the deck with spells, ability pressed for forms
with a button; flags errors, refused deploys, forms that play like the base, hit gaps
that differ from the table. Output `runs/league/battery/`.

Search gap, relevant to "a tower at 200 hit points and no Fireball": `actor.py`'s search
tries only other tiles for the card the policy already chose. Which card to play, and
whether to play, is never searched, so distillation cannot teach "Fireball now ends it"
unless the policy already picks Fireball.

## Input version 7 and card search (2026-11-15, code only, nothing trained on them)

**obs_v 7** (`tools/league/obs.py` `build(..., obs_v=7)`, `model.py`): live crown towers
are unit tokens (first in the list: position in the model's frame, hit point fraction,
size, building flag), and `towers` has 12 values: the six fractions in the model's
frame plus the six hit points / 5000. Default stays 6, old rows and models unchanged.
`from_league` widens `state_in` with zero weights for the new values; the tower tokens
have untrained embeddings, so a converted model does not play like its parent until
trained. Callers pass the version: `engine_bc.py --obs-v 7` (collect and train),
`actor.py` (each seat's model), `live.py` (the loaded model). Tested on a RoyaleSim
state for both teams (a 200 hp enemy tower shows on the correct side for each).
Rows of different versions must not be mixed. `HASTY_TOWERS_OWN` is the smaller,
vector-only version of the same idea, used by the control `runs/league/tower_own`.

Not in any input yet: whether the card in hand is evolved on its next play; the king
tower's awake state. Both would need a live reader field first (UNVERIFIED that the
reader can get them).

**Card search** (`tools/league/actor_new.py`, a patched copy of `actor.py` made by
`patch_cardsearch.py` while a chain was using `actor.py`; replace `actor.py` with it
when nothing runs): `--search-cards K` compares the policy's choice with waiting
(`realsim.try_wait`) and with every other playable card at its K best tiles,
`--search-at-wait P` does that at a share P of the policy's wait decisions,
`--search-elixir W` adds W x (own - enemy elixir bank at the end) to the score so a
cheaper answer that holds wins. Labels carry `gate_score` [wait, slot 0-3] and
`policy_a`; `a` is the search's choice.

Smoke run (8 games, K 3, W 0.05, P 0.05): of 370 card-search decisions 154 kept the
policy's choice, 143 turned a wait into a play, 45 changed the card, 28 turned a play
into a wait. The wait -> play share is a warning: in the forked copy nobody plays after
the candidate, so any troop put down walks to the tower unanswered and scores. W = 0.05
is UNVERIFIED and probably too low. Calibrate W by closed-loop win rate (card search on
at several W against no card search) before any label from it is used for training.
Still to write: training on these labels (gate loss, not `--tile-only`) and
`search_distill_prep.py` handling of card-changed rows.

Card battery on the new engine with tags (`runs/league/battery/new_tags2.jsonl`, 476
battles, level 11): no engine fault, no refused deploy, no card without a unit. 87
evolutions and 18 heroes play differently from their base card. Left open by it:
- Goblins hero: `GoblinHero_Ability` exists in the table (ManaCost 1) but realsim never
  shows its button as available, so its ability is never pressed in a re-drive.
- Tombstone hero and Barbarian Barrel hero: the battery presses only after a first
  tower hit, which never comes; their ability is untested.
- Giant hero and Mega Minion hero: the press changes nothing in the tower trace; not
  known whether that is right (the ability may not concern towers).
- Hit-gap flags on evolved Hog Rider, Dark Prince, Monk, Ronin, Boss Bandit, Prince
  variants, Electro Giant: these have charges, combos or reflected damage, so a gap
  different from HitSpeed is expected; none was checked against the real game.
- Elixir Collector has no evolution or hero that loads (reset refuses both).

## Constructors without a head: 16 of 50 recovered by shape (2026-11-15)

The 50 stubbed constructors the solver left open on the new build had been skipped
because the engine ran without them; nobody had checked what they set up.
`port/unrecovered.py` lists them, `port/recover_shapes.py` recovers the ones whose lost
4 bytes follow from the rest of the function (each must then decode cleanly to a ret or
a jump out): 10 that zero a static and register its destructor (`xorps; movups`; several
set a float 1.0, the load factor of an empty hash map), 2 guard checks, 4 global
strings. Heads appended to `port/ctor_heads_new.txt` (backup
`ctor_heads_new.before_shapes.txt`).

Effect, measured: row-load faults fell from 40 to 12. Tables 99, 100, 167 and 196 now
load every row; only table 93 (12 rows) still faults. Hog control and Hero Electro
Wizard control unchanged. 4 constructors still fault when run.

Still open, 34: nine 17-byte guard setters and about ten 26-byte destructor
registrations (one unknown displacement byte each; they only register or flag, so low
value), four that call the allocator first (`push rax; mov edi, size`: the size's low
bytes are lost), and larger ones touching MovieClip, blend modes, JSON escapes, an
integer regex and a `[bitmask()] / [enum()]` attribute regex. Not done for the old
build (`ctor_heads.txt`, 55 open).

**Win/loss end score** (2026-11-15, code only): `realsim._score(..., win, end_tick)` adds
+-`win` when a search copy reaches the end of the game (more crowns; at equal crowns the
side whose weakest standing tower has more hit points, UNVERIFIED against the engine's
result flag). `actor_new.py --search-win W`, default 0 = old score. Not run yet.

Data on hand (2026-11-15): generic `data/uc/gen2.jsonl` 114,831 games (39,388 not in
`all.jsonl`); exact deck `data/mortar_exact_all.jsonl` 6,767 games (6,156 from the
owner's deck database + 611 found in the generic one). The model is 5.7M parameters
(d 256, 6 layers).

## What the model sees: three more gaps (2026-11-15)

- **Royal Chef king was invisible live.** Its unit name is `ChefTowerKing`, missing from
  `live_bridge.CROWN_TOWERS`: against those opponents the king was dropped and the tower
  vector read their king as destroyed. Added (also `bm.py`; `live_play` crown count now
  tests "King" in the name). All tower troops now map to the KingTower / PrincessTower
  tokens, the only ones training has (training battles always use the Tower Princess;
  the troop's own damage and range are a known training / live gap).
- **Training was blind to bodies the live reader shows.** realsim named only the Hero Ice
  Wizard's bodies; anything else outside RoyaleSim's unit list got no token. Missing from
  every engine-collected row: Goblin Barrel's goblins, the evolved Witch's skeletons,
  evolved Giant / Electro Giant / Goblin Giant spear goblins, Hero Electro Wizard, the
  Berserker hero's bear, the Tombstone hero's skeletons. `tools/league/unitmap.py` holds
  the live reader's rules (checked equal on 220 names); realsim uses it with
  `HASTY_UNIT_FALLBACK=1`. Off by default so old rows stay comparable: set it for the
  re-collect and for every evaluation of models trained on those rows.
- Card-less bodies (Mother Witch pigs, `electro_dragon_ev1`) reach the model live since
  the earlier fix of the same day. Not seen in a live game yet.

## Tower control result and the re-collect (2026-11-15)

`runs/league/tower_own` (chain.sh, chain.log): the tower vector in the model's frame is
the cause of the dead-lane plays. Same 400 tower-start games (seed 5150), dead-lane share:

| card | gB8 | gT8 (labels and model with `HASTY_TOWERS_OWN=1`) |
|---|---|---|
| Mortar | 51% (381 / 745) | 21% (146 / 701) |
| Skeleton Barrel | 66% (616 / 940) | 29% (277 / 962) |
| Fireball | 54% (196 / 366) | 33% (118 / 355) |

Normal held-out games (800, seed 9001): gT8 78.3% [75.3, 81.0], Mortar dead lane 28%
(109 / 384); gB8 81.5% [78.7, 84.0], Mortar dead lane 54%. So the lane is learned, the
win rate against the simulator opponent did not rise (3 points lower, inside two
intervals).

Live: the owner played gT8 for 22 games (`reports/live_play/20261115_162019.jsonl`):
5 wins, 17 losses. gT8 reads the tower vector correctly only with `HASTY_TOWERS_OWN=1`
in the bot's environment; the command the owner used was not given by this session and
the log does not record the environment. Without the variable gT8 gets the two princess
slots swapped live (the bot is always team 1 there) and would aim at the wrong lane on
purpose. UNVERIFIED which it was; 22 games cannot separate 23% from gB8's 33% either.
obs_v 7 models do not need the variable (the version is in the checkpoint).

Swapped in when nothing ran: `headless/loader_fork` and `loader_new` are the builds with
game tags (previous binaries: `*.pre_tags`); `tools/league/actor.py` is the card-search
version (previous: `actor_pre_cardsearch.py`). `engine_bc.py` now passes `--obs-v` to its
collection workers (they built obs_v 6 rows regardless before); `exact_cycle.py --obs-v`.

Re-collect chain `runs/league/uc_v3/chain.sh` (log `chain.log`), about 10 hours: new
engine with tags, obs_v 7, `HASTY_UNIT_FALLBACK=1`, Hero Electro Wizard allowed. Rows:
`mx7_exact` (6,767 exact games), `mx7_arch` and `mx7_bait` (archetype seats), mix in
`mx7_mix`, generic in `uc_v3` (114,831 games; a 300-game smoke run gave 26,029 rows in
62 s). Then genC -> `exact_cycle` gC_mix -> tests against gB8 in the same environment.
Deleted for space: row files of `uc_s1`, `uc_pilot`, `uc_pilot2`, `uc_v2` (models kept).
No search distillation in this chain: the search labels must be made again with obs_v 7.

## 2026-11-16 night: exact-match measure, dropped cards, outside repositories

**Exact-match measure.** `tools/league/redrive_diag.py --to-end` runs a re-driven
replay on after its last recorded play until the engine ends the game and compares
with the record. The scrape holds crowns and the result only (no tower hit points,
no card levels: `levels = assumed`, all 16), so agreement is a necessary sign, not
proof. 300 games of `data/uc/gen2.jsonl` (`--skip 100000`), new engine, tags loaded
(`runs/league/uc_diag/exact300b.jsonl`):

| outcome | games |
|---|---|
| full length | 189 |
| engine ends the game early | 86 |
| card not in hand | 25 |
| full length, engine winner = recorded winner | 151 |
| full length, wrong winner | 38 |

So at most half of the games end as they were played. A game the engine ends at
0-0 on the tiebreak is recorded 1-0 by RoyaleAPI: compare the winner, not crowns.

- Control: every play 21 ticks later (`--shift 21`; daybreak-cr's rule 1 says
  RoyaleAPI's tick is the tap and the play lands 21 ticks after). Crowns equal 96 ->
  94 of 254, 248 of 254 games unchanged. Timing is not the cause on our data.
  Whether `scraped_to_payload.py` already shifts was not checked.
- Not yet tried, from `vendor/ext/daybreak-cr/docs/CONVERSION.md` (54% -> 95.6%
  exact for them): King level per side, selection at the tap, Mirror, game data by
  battle date, seed search for dice cards, placement of Elixir Collector / Mirror.
- The scrape database's `stats` column has each side's elixir spent and leaked: a
  second check that needs no tower hit points. Not joined into the payloads yet.

**Four card keys were dropping games whole.** `replay_cards.json` (RoyaleImitate
package) has no `minion-giant`, `void`, `spirit-empress`, `rune-giant`. Every game
with one was skipped: 17.3% of the generic set, 546 of 6,767 exact-deck games.
`tools/rs_rows.py` `_setup` now maps them (MinionGiant, DarkMagic, MergeMaiden,
GiantBuffer). The dropped games are in `data/uc/gen2_newcards.jsonl` (18,930) and
`data/mortar_exact_newcards.jsonl` (546); not collected yet, and no model has
seen these four cards. Engine's Void cost is 5: UNVERIFIED against the live game.

**Outside repositories** are shallow clones in `vendor/ext/` (git-ignored; 14, read
for method). Points that matter:
- RoyaleFish's micro-interaction rewards are described in its README but not in its
  code; `royalefish/reward.py` has only win/loss, tower potential, elixir overflow
  and King activation. Its address tables do not fit our image (other build).
- RoyaleFish's host (`test_x86.cpp` inside `patches/probe_x86_64_16635.diff`) lets
  the system linker load `libg.so`, so constructors run by themselves, and lists the
  start order (paths, resource loader, mounts, table files, `initDataTables`, one
  finalize call per table). Not tried here.
- Same patch, hero abilities: remaining charges -1 means unlimited; one failed
  ability must not empty the list. Not compared with our code yet.

## 2026-11-16 day and evening: imitation saturated, ghost games work

### Imitation variants, all the same live result
| model | what changed | held-out (800) | head to head | live |
|---|---|---|---|---|
| gB8 | reference, obs_v 5 | 58.1% in the fixed engine | - | 33% |
| `runs/league/mx7_mix/gC_mix_c3.5.pt` | fixed engine, obs_v 7 (towers) | 66.4% | level with gB8 | 14W-29L, 33% (43 games, 25 of 29 losses 0-1) |
| `runs/league/mx8_mix/gD_mix_c3.5.pt` | + four recovered cards, + `HASTY_EXACT_ONLY=1` (keep a game only if the re-drive ends with the recorded winner; about 62% of rows survive) | 63.3% | 42.6% vs gC_mix, 38.5% vs gB8 | not run |

The exact-match filter did not help; the run changed two things at once (filter and
cards), so which one hurt is not known. The held-out opponent did not predict live
results. More imitation runs are not the way.

### Self-play, old and new
- `league_mortar1` (2026-11-12) was rolled back at update 40 while beating its parent
  55.1% head to head, because its held-out number fell. New gated runs pass
  `--bench-tol 1.0`: the held-out number is recorded, never used to fail.
- `actor.py`: with a learning general brain in the run (`--learn hog,gen`), the "gen"
  share of `--opp-shares` is that brain, not the frozen `--opp-gen` file.
- `runs/league/league_mortar4`: plain self-play with that learning opponent, stopped at
  update 20 before its gate (`hog/v20_ungated.pt`, not tested).
- `runs/league/league_mortar2` held the shelved 2026-11-12 run; its last weights were
  overwritten by mistake on 2026-11-16 (see `OVERWRITTEN.md` there).

### Ghost games (RoyaleFish's method, after ClashAI; our code)
A real winner's plays are replayed as the opponent; each ghost is played 4 times with
the same seed and the same own deal order; every decision of a try gets the try's score
minus the group mean, where the score is minus the weighted tower damage taken. No
critic target from these rows.
- `tools/league/ghost_prep.py` -> `data/ghosts/gen2_all.jsonl` (110,181 ghosts from
  114,831 scraped games; levels unknown, ghosts play at 16).
- `actor.py --ghosts FILE --ghost-share S --ghost-tries 4` (passed through by
  `learner.py`). Ghost plays go straight to the engine at the recorded tick; 0.6% are
  dropped for a missing card or elixir. `GHOST_WAIT` and `GHOST_ADV_SCALE` are
  unverified first values.
- `league_ghost1` (lr 2e-5, 2 epochs of batch 512, KL 0.02): 30.4% head to head after
  20 updates, damage taken flat at 0.43 per game. Too large a step for this signal.
- `league_ghost2` (1 epoch, batch 1024, lr 5e-6, target KL 0.004, KL 0.1, max lag 3):
  gate 1 53.5% [50.0, 56.9], gate 2 57.1% [53.7, 60.5] head to head against gC_mix
  (800 games each), held-out 66.9%, promoted at update 40. Damage taken per ghost game
  in 5-minute windows moved from about 0.39 to 0.34-0.40 (noisy, about 100 groups per
  window). Not yet played live.
- Open: the reward has no attack term; the ghost never reacts to our pushes.

### Engines
- Null's Royale 16.635.1 (arm64 only) crashes on the Android 15 instance (its injector,
  `libwildcat.so`, under ARM translation) and runs on a new Android 12 instance
  ("Android Device-1", index 1, port 16416, root through `su`). Official Clash Royale on
  instance 3 is x86_64, 16.635.7.
- RoyaleFish's `probe_x86_64_16635.diff` targets an x86_64 `libg.so` of 16.635.1 that
  the repository does not ship and Null's does not contain; its address tables do not
  fit our 16.635.7 library. The author has been asked where that library comes from.
- Training plus one MuMu instance fills the 32 GB of RAM; a second instance fails to
  start (Windows error 1455).
- A second disk, `D:` (954 GB), was added on 2026-11-16; nothing has been moved to it.

## 2026-11-17 morning: update 80 live, attack term run

`league_ghost2/hog/gates/cand_004_v80.pt` played live from 05:19: 17W 22L (44%) over 39 games against 33% for gC_mix, and the owner reports it reached Champion league. Most games are still decided by one tower (13 of 17 wins 1-0, 17 of 22 losses 0-1).

`league_ghost3` (started 08:34) continues from update 80 with one change: `--ghost-attack 0.5` adds damage dealt to the ghost's towers to the ghost score (UNVERIFIED weight; `actor.py` `ghost_finish`, new stats `ghost_taken`, `ghost_dealt`, `ghost_games`). Gates judge head to head against update 80 (its `v0`). Gate 0: update 80 wins 71.4% [66.8, 75.6] against the held-out opponent. Never run it together with the live bot; stop with `runs/league/league_ghost3/STOP_ALL`.
