# Overnight run — status and cold start

Written 2026-08-18 ~01:00. Update in place; this is the file to read first if a
session dies and a new one has to pick the run up.

## What is running

| thing | how | check it |
|---|---|---|
| bot | `run.ps1 -Forever` → `scripts/supervisor.py`, blocks of 5 matches | `tmp/live/supervisor_state.json` heartbeat |
| supervisor watchdog | Scheduled Task `HastyCR-Watchdog`, every 5 min | `tmp/live/watchdog.log` |
| emulator watchdog | Scheduled Task `HastyCR-EmulatorWatchdog`, every 5 min | `tmp/live/emulator_watchdog.log` |
| review loop | supervisor dispatches `scripts/review.py` per block | `tmp/live/reviews/` |

Restart the whole thing with `.\run.ps1 -Forever`, or double-click `bot.cmd`.
Stop with `.\run.ps1 -Stop`. Watch it with `.\studio.ps1`.

### Before recording, check the MIRROR chip in the studio header

MuMu stopped presenting its window at about 01:27 and had not resumed. The bot is
completely unaffected — it reads the framebuffer over ADB — but the studio's fast
60fps path was showing a frozen frame, so it now says **MIRROR via ADB** in amber
and falls back to 6fps of real gameplay. Honest and usable, but not what you want
for a Short.

To get the 60fps path back, restart just the Clash Royale instance:

    & 'C:\Program Files\Netease\MuMuPlayer\nx_main\MuMuManager.exe' control -v 3 restart

Instance **3** only — index 0 is the unrelated Clash of Clans device. That costs
the match in progress; the supervisor starts a new block by itself and the bot
relaunches Clash Royale once the device answers. I did not do this overnight
because it interrupts play for a benefit you only need when you sit down to
record.

## Checking how it is doing

    python scripts/record.py --hours 12      the record, split at each recorded change
    python scripts/record.py                 all of it

`took`/`conceded` are the share of matches with at least one crown either way.

**Only measure from 2026-08-18 10:48 onward.** Before that the enemy tower reader
was a quarter low in most arenas and returned zero in some, so every crowns-for
and `took` figure in this file's history is overstated. The ally reader was always
correct, so `conceded` is sound throughout. There is no way to rescore the old
matches - the saved frames are downscaled past reading.

On the corrected reader, 41 matches: W6 L20 D15, crowns 0.90 for / 1.32 against,
took 71%, **conceded 98%**. Conceding a tower in essentially every match is the
whole problem; the Hog side is not what is losing these games.

Change times live in `tmp/live/change_markers.txt`; append to it whenever you
change something you want measured.

## Do not break these

**MuMu instance 3 only.** This machine runs a second MuMu instance (index 0)
belonging to an unrelated Clash of Clans setup, plus a `pythonw.exe`
`coc_master/supervisor.py` process. Nothing here may restart instance 0, kill
`pythonw.exe`, or use `MuMuManager control -v all`. `emulator_watchdog.ps1` is
pinned to index 3 and refuses to act unless it is still named
`Android Device-1-2`.

**Never blind-tap the emulator.** Shop, gems, medals and any IAP surface are a
hard no. Verify on-screen state with a screenshot, not from logs alone.

## State of play

Perception was switched to the detector trained here (`--vision yolo`):

- unit detector: P 0.949 / R 0.926 / mAP50 0.959 over 201 classes, 1.5 ms/frame
- ally-vs-enemy classifier: 94.0% overall, 94.5% on units in *our* half
  (a blue-vs-red colour rule gets 52.8% there, i.e. a coin flip)
- on live frames: 20.7 ms/frame against upstream's 45.3 ms
- upstream's most common detection in a Hog 2.6 mirror was `baby_dragon` x28

Record either side of the switch, from `tmp/live/matches/*.json`:

    before (7 matches)     W0 L5 D2     crowns  2-10   hog  9.6%   conceded 100%
    after (100+ matches)   see `python scripts/record.py --hours 12`

At ~95 matches it read W7 L35 D53, crowns 0.63 for / 1.11 against, hog 16.4%.
Losses fell from 71% of matches to 37% and crowns scored roughly doubled. The
change was justified by detector accuracy beforehand rather than fitted to this
outcome, which is why I trust it more than the config tuning around it.

Revert with `--vision buildabot` if it turns out worse.

## The failure mode to watch for

The bot froze for 13-23 seconds in every match and threw games doing it. Three
elixir gates had each been raised for a good reason by three agents that could
not see each other (`cycle_to_hog_elixir`, `probe_min_elixir`, `cycle_any_elixir`),
and together they left a band around 4-8 elixir where **no generator fires at
all**. It is invisible in any single sweep, because a sweep varies one setting
and is blind to what it composes with.

Two defences are now in place. `_anti_idle` in policy.py plays a cheap card when
the legal set is empty and the bot has been idle past `max_idle_seconds` - a
floor, never a preference, and it will not spend elixir the Hog is waiting on.
And `test_the_bot_is_never_idle_with_a_full_bar_and_no_threat` fails immediately
if the band reopens.

To check for it: `grep -c IDLE tmp/live/cr_bot.log` over a recent window, and
the share of plays tagged `idle_` - if the floor is doing more than a few
percent, the real generators have stopped firing and a threshold needs lowering.

## Fixed on 2026-08-18 morning, from watching it play

- **battle_guard was abandoning whole matches.** It wanted two of four princess
  bars above 10%; late in a close game every bar can legitimately be under it
  (saved frame: both our towers destroyed, theirs on 282 and 493 hitpoints). The
  bot stopped playing with a king to defend. It now tests the hand instead. Nine
  matches were lost this way in six hours and they leave no MATCH_END, so they
  are missing from the record - `scripts/record.py` reconstructs them.
- **Cannon answering Musketeers.** Cannon reaches 5.5 tiles, Musketeer 6.0, so
  it died without firing. `units.json` had no range data at all; it now carries
  real range and deploy time for 72 of 97 units, and the Cannon is only offered
  against something that must close the distance.
- **Cannon dropped onto the troops it should stop.** Everything takes 1.0s to
  deploy, so it absorbed free hits. It now steps back until it has clearance.

## Open questions, in priority order

1. **Does the Hog share hold up, and does it convert to wins?** Share is a proxy;
   the record is the answer. `python scripts/results.py` and `MATCH_END` lines.
2. **The policy was tuned against noisy perception.** Thresholds like
   `defend_min_threat` and `cannon_min_threat` were fitted when the detector was
   inventing Baby Dragons. They are worth re-sweeping now that the input changed.
3. **Simulator fidelity.** `play_card` rejected every spell aimed at the enemy
   half until tonight, which invalidated the offence measurements that depended
   on it. Assume there are more of these; `sim/validate.py` is the place to add
   checks.
4. **The simulator has no ladder-like opponent.** Self-play defends exactly as
   well as we attack; `SimpleOpponent` loses 99.7%. The ladder beats us 118-14.
   `sim/train_ppo.py` exists mainly to produce a sparring partner in between.
5. **Window capture can freeze.** For a fully occluded emulator, DWM returns the
   last presented frame indefinitely — PrintWindow keeps succeeding. The studio
   now shows MIRROR FROZEN, but any measurement taken from window captures needs
   this ruled out first. It already invalidated one card-classifier audit; the
   ADB path (`screencap_fast.FastScreenCap`) is immune.

## Traps this project has already fallen into

- **Seed-set noise reads as a finding.** The sweep control arm moved 51.5% →
  46.1% between runs of *identical* policies. Treat any single sweep under ~3
  points as silence. Act at ~2σ *with* independent corroboration.
- **A broken control invalidates the whole sweep.** `sim/sweep.py` freezes
  `config.json` as the baseline, so writing the value under test into that file
  before sweeping makes the "identical" arm not identical. Set the key to its
  off value first. If the control arm is not near 50%, you are measuring the
  harness.
- **The review loop drifts config.** It had pushed every defensive weight above
  every Hog weight. `config_guard.py` now handles dotted keys
  (`weights.defend_air`) and `bounds.json` pins the relationships.
- **A negative simulator result is a claim about the simulator** until its
  fidelity on that mechanic is checked.
- **The simulator cannot price tempo.** Nothing in it punishes passivity,
  because the only opponent is our own policy and that does not out-cycle
  anybody. It preferred `cycle_to_hog_elixir` 9.0 by 14.7 points, monotone over
  seven values, and held that preference even against a pool of jittered
  opponents - and shipping it froze the bot for 13-23s a match. Any change whose
  cost is paid in tempo has to be judged live.
- **`scripts/brain/*` is concurrently owned by the review loop**, which rewrites
  it every block. Read those files with `git show`, never with a
  snapshot-and-restore: a `cp` round-trip silently rolled back a whole review
  and left two settings below their own bounds.
