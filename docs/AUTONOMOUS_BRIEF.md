# HastyCR autonomous run - standing brief

Read this first if you have just been handed control of this project. It is written
for a cold start: assume you know nothing about the run except what is in this file
and in `tmp/live/`.

## The goal

A Clash Royale bot plays the **Hog 2.6 cycle** deck (Cannon, Fireball, Hog Rider,
Ice Golem, Ice Spirit, Musketeer, Skeletons, The Log) on a MuMu emulator, unattended,
and gets measurably better over time. The owner is away and expects the loop to still
be running and still improving when they return. **Nothing here should ever stop
because one AI service ran out of quota.**

## The loop

```
scripts/watchdog.ps1   (Scheduled Task "HastyCR-Watchdog", every 5 min)
  └─ scripts/supervisor.py          keeps the loop alive, one block at a time
       ├─ scripts/cr_bot.py         plays 5 matches
       ├─ scripts/block_report.py   aggregates them into tmp/live/reviews/latest_block.md
       └─ scripts/review.py         hands the report to an agent CLI, which tunes the bot
scripts/captain.py     (Scheduled Task "HastyCR-Captain", every 30 min)
  └─ promotes a new lead agent if the current one has gone quiet
```

## The decision engine

`scripts/brain/` is the whole brain. It is a **candidate generator plus a scorer**,
not an if/else ladder:

- `arena.py` — geometry and the single definition of the coordinate convention.
  Grid is 18 wide x 32 tall, top-down y. `y < 16` enemy half, `y >= 16` ours.
  Our princess towers are at (4, 24) and (14, 24); theirs at (4, 7) and (14, 7).
  BuildABot reports tiles bottom-up, so a detection's row is `31 - tile_y`.
  **Only `arena.to_grid` performs that flip. Never do it anywhere else.**
- `knowledge.py` + `units.json` — per-unit properties (air, threat, dies to Log or
  Fireball, kitable). Fixing a wrong entry here is often the cheapest real improvement.
- `tracker.py` — frame-to-frame identity and velocity, so defenders are placed where a
  push *will be*, not where it was.
- `policy.py` — the rules. Each rule emits `Candidate`s; `score_candidate` ranks them.
- `config.json` — **every tunable number**. Prefer changing this over changing code.
- `push.py` — pushes as committed multi-card plans (Ice Golem, then Hog behind it),
  never one card at a time.
- `economy.py` — estimate of the **opponent's** elixir, so the Hog goes in when they
  cannot answer rather than whenever we happen to be able to afford it.
- `experience.py` — measures what each play achieved and learns from it (below).
- `advisor.py` — the local LLM. Owns *intent*; the policy keeps the exact tiles.

## The learning loop

Every play is scored a few seconds after it happens:

    reward = enemy elixir killed + tower damage dealt
           - elixir spent        - tower damage taken

Two artefacts come out of it, both under `brain/`:

- `learned.json` — mean reward per (situation, card). Added to that candidate's score,
  damped by sample count and clamped, so a few lucky episodes cannot overrule a
  hand-written rule that came from the actual 2.6 guides.
- `matchups.json` — per (our card, the unit it actually engaged). `scripts/lessons.py`
  turns this into `brain/lessons.md`, which is injected into the advisor's prompt.

**Two traps already hit here, do not re-introduce them:**

1. Credit only units the play could plausibly have fought (near where it landed, and
   only for engaging card families). Pairing every play with every unit on the field
   produced "hog_rider vs ice_golem: 100% kill rate" — the Hog never fought it.
2. Require enough samples. At two, a single coincidence became a confident "lesson".

## Rules for anyone touching this project

1. **Verify game mechanics with web search.** Every model's Clash Royale knowledge is
   stale. Do not adjust a placement, cost, or interaction from memory.
2. **Prefer `config.json` to `policy.py`.** At most three changes per review.
3. **Run the tests** after any change:
   `.venvs\buildabot\Scripts\python.exe -m pytest tests\test_brain.py -q`
   A failing tree must be reverted, not left for the next agent.
4. **Never edit** `supervisor.py`, `review.py`, `captain.py`, or `watchdog.ps1` unless
   you are specifically fixing the loop itself. They are the safety net.
5. **Never delete `tmp/live/matches/`.** It is the only record of how the bot played.
6. **Watch disk.** The machine has limited free space. `supervisor.py` prunes each
   block; if free space drops below ~10 GB, prune harder rather than adding anything.
7. **Do not blind-tap the emulator.** Only `cr_bot.py` may send taps, and only from a
   verified in-battle screen. Never tap in a shop, offer, or gem dialog.

## What "better" means, in priority order

1. **Crowns for minus crowns against**, over a block of 5 matches. This is the score.
2. **Hog Rider share of cards played.** Target 15-25%. It is the deck's only real
   damage source; below 12% the bot is not playing the deck.
3. **Cards played per match.** The deck is a cycle deck; too few plays means elixir
   is being banked and wasted.
4. **Elixir spent on nothing** — defensive cards played against a threat that was not
   real. Visible as `defend_fallback_*` tags in the block report.

## Known history (do not re-learn this the hard way)

- A learned StARformer checkpoint (`vendor/KataCR`) used to drive the bot. Over sixty
  logged matches it scored **11 crowns for, 90 against**. It is no longer in the hot
  path and should not be put back without evidence.
- Shimming that model produced 723 vetoes against 428 plays in one three-block sample:
  the bot spent most of each match declining to act. Do not rebuild a veto layer.
- The first version of the current brain treated *any* enemy unit past the river as a
  threat. That made it a turtle: 39 of 42 plays in one match were defensive and Hog
  share was 7%. The `defend_min_threat` gate in `config.json` exists because of this.
  If you raise defensive aggression, watch that number.

## Current state

Check these, in this order:

```powershell
Get-Content tmp\live\supervisor_state.json          # heartbeat, block number, status
Get-Content tmp\live\reviews\latest_block.md        # how the last 5 matches went
Get-Content tmp\live\supervisor.log -Tail 40        # what the loop has been doing
Get-Content tmp\live\cr_bot.log -Tail 60            # what the bot has been playing
Get-Content tmp\live\agents_state.json              # which agent CLIs are benched
```
