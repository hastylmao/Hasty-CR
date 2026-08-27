# RL Sprint 4 — Decisions (append-only)

Log every material choice: what was decided, evidence, expected effect, and outcome.

---

## 2026-08-25 — Baseline frozen as sprint4 start point

- **Chosen:** `tmp/rl/pilot_best.pt` step 4,392,960 (sha256 `2ff3b7b50...`) → `checkpoints/sprint4_baseline/pilot_best_4392960.pt`
- **Why:** True best on held-out brain (43.3% on 300 games, seed 8000, CI 37.8–49.0). `pilot_last` 6M is statistical tie (42.3% [36.9–48.0]) — retained as runner-up, not promoted. Both versioned under `checkpoints/candidates/`; sprint4 gets its own frozen copy so later edits cannot overwrite Sprint 3 artifacts.
- **Controls for variant:** init `tmp/rl/clone_pilot.pt`, hyper envs 10 rollout 128 gamma 0.997 clip 0.2 value_coef 0.5 entropy 0.03 lr 5e-5 target_kl 0.02 value_warmup 300k league 4 scripted_share 0.4, reward tower 10 crown 3 win 10.
- **Risk acknowledged:** Plateau is real (1.6M flat); next improvement must change reward/curriculum/observation/entropy, not just more steps with same settings.

---

## 2026-08-26 — Intervention 1 ABORTED at 730k: entropy 0.10 randomises the policy

- **Observed** (eval is 40 episodes vs a fixed meta pool, so it is comparable across rows):

  | step | eval | win rate | hog share | plays/match |
  |---|---|---|---|---|
  | 250k (warmup, = the clone) | W29 L11 | 72% | 15% | 52 |
  | 300k (policy just unfrozen) | W28 L12 | 70% | 15% | 48 |
  | 550k | W21 L19 | 52% | **4%** | **84** |

  Mean return over the same span went +9.03 → −15.23 and entropy rose 0.27 → 0.62.
- **Read:** this is not exploration, it is randomisation. The literature is explicit that
  an entropy coefficient set too high "causes excessive stochasticity that violates
  policy gradient assumptions, manifesting in discrete action spaces as loss of
  deterministic policy choices at critical state nodes" — which is exactly a policy that
  stops sending its win condition and starts playing 84 cards a match. Common practice
  for discrete PPO is ~0.01; the baseline used 0.03. 0.10 was 3.3× a value already
  above the norm, and the diagnostics justified *more* exploration without saying how
  much more.
- **Kept:** the direction (the crown-conversion failure is real, and reward shaping is
  still falsified). Rejected: this magnitude.
- **Falsifier status:** the abort gate was Brain WR ≤ 38.3% at 1.5M; the run failed a
  faster gate than the one written down, which is why the supervisor added behavioural
  triggers — hog share and plays/match move long before a win rate does.

---

## 2026-08-26 — Body-block deadlock fixed; every prior checkpoint is void

Found by the user playing the bot in a friendly 1v1 and saying it defended a Hog Rider
with an Ice Golem, "which won't do shit". Reproduced immediately:

| attacker | blocker | before the fix | after |
|---|---|---|---|
| hog_rider | (none) | 4.6s to the tower | 4.6s |
| hog_rider | skeletons | **never connects** | +0.5s |
| hog_rider | ice_golem | **never connects** | +0.5s |
| hog_rider | musketeer | **never connects** | +0.5s |
| hog_rider | cannon | never (correct - a building) | never |

- **Cause:** separation pushed purely along the line between two centres. Head-on that
  line is the direction of travel, so a unit stepped forward and was shoved back by the
  same amount every tick and the pair reached a stable standstill. Softening the push
  cannot fix it - at 50% and 70% the deadlock returned and at 100% contact became free.
  The geometry is degenerate: dead ahead there is no sideways to slide along.
- **Fix:** steering, in `_obstacles`, mirroring the existing `_avoid_buildings` - a unit
  walks *around* an enemy it is not permitted to attack, reusing the same side-commitment
  that stops it flip-flopping. A unit that *can* attack its blocker still stops and
  fights, so the asymmetry falls out on its own. `tests/test_body_block.py` (13 + 1 xfail).
- **Known gap:** charging units are not steered. Battle Ram (`charge_speed_multiplier`
  200) is still held permanently by one Knight. Strict xfail so it cannot be forgotten;
  Prince, Dark Prince and Ram Rider share it. No charging card is in the 2.6 deck.
- **Consequence: every checkpoint trained before 2026-08-26 is void.** Cheap-body defence
  was unbeatable, so the policies correctly learned to spam cheap bodies, hoard nothing,
  and never use Fireball or Musketeer. The 93.3% vs the rule engine and the 72-28
  head-to-head were faithful measurements of a game that is not Clash Royale.

### The other four observations were NOT sim bugs

Each was probed the same way. The simulator rewards all of them, strongly:

| observed | verdict |
|---|---|
| Cannon dropped into a push | correct - 0 vs 2,219 tower damage between good and bad placement |
| Fireball hitting the wrong lane | correct - 2,756 vs 0 damage centred vs off |
| four cards dumped in the opening | correct - start 5, 2.8s regen, double at 120s, triple at 240s |
| Ice Spirit dying on a swarm | probably correct - `characters.csv` has `DeployTime` but no deploy-immunity field, while dashes carry an explicit `DashImmuneToDamageTime` |

So one bug made four behaviours unlearnable rather than four separate bugs. The gradients
for all of them are large and were always there.

### Baseline in the fixed simulator (60 games, seed 8000, greedy)

`tmp/rl/clone_pilot.pt`: **18.3%** vs the rule engine [10.6-29.9], **78.3%** vs meta decks
[66.4-86.9]. The same clone read 62-72% vs the rule engine before the fix. It did not get
worse - the simulator stopped letting sloppy play hide behind an unbeatable body-block.
This is the number tonight's run has to beat, and the only one comparable to it.

---

## 2026-08-26 — Opponent diet mixed; both specialisation directions now measured

Tonight produced the same failure twice, in opposite directions, before the cause was
understood. All numbers are 60 held-out games at seed 8000, greedy, from a start of
41.7% vs the rule engine and 86.7% vs meta decks.

| training diet | eval selected on | vs rule engine | vs meta decks |
|---|---|---|---|
| meta + 70% self-play | meta | **16.7%** | 82.5% |
| rule engine + 50% self-play | rule engine | 93.3% | **76.7%** |
| 25% rule engine / 25% meta / 50% self-play | rule engine | **93.3%** | **81.7%** |

- **The mechanism, finally stated correctly:** `_LeagueSeat.choose` hands the scripted
  share back to the environment's base opponent, so `--opponent X` made X the *entire*
  non-self-play diet. Whichever opponent that was, the policy specialised into beating it.
  Selecting on that same opponent then made the specialisation invisible — and in the
  first case actively selected for it.
- **A log line helped hide it.** The trainer printed `"{share} of episodes still vs meta
  decks"` regardless of `--opponent`, so a run spending half its episodes against the rule
  engine reported itself as playing meta decks. Now it names the real mix.
- **Fix:** `--brain-share` splits the scripted episodes between the rule engine and meta
  decks; `--eval-opponent` decouples what selects a checkpoint from what it trains on.
  `tests/test_opponent_mixing.py` (10) covers the split, the deck-pool guard, and that
  self-play episodes still bypass the scripted choice.
- **Supervisor:** the audit now measures every axis in `--audit-opponents` and stops on a
  regression in *any* of them, and `--audit-anchor` seeds it with the starting policy's
  measured scores so the first audit tests a bar rather than defining one. Anchoring on
  the policy at 3M would have made any earlier regression the new baseline.
- **Result at 3.16M on the mixed diet:** rule engine held at 93.3%, meta decks recovered
  76.7% → 81.7%. Against the baseline: +51.6 and −5.0, with the meta intervals overlapping.
- **Limitation to carry forward:** with a mixed diet, both audited opponents are now
  in-distribution. The audit can detect trading one trained opponent for another; it
  cannot certify generalisation to an opponent never trained against. The only genuinely
  out-of-distribution test is a real ladder match.

---

## 2026-08-26 — Overnight run stopped at 10.3M and restarted: it was selecting on the wrong opponent

**The most important entry here.** The run looked like the best PPO result this project
had produced and was in fact the worst.

| | vs meta decks (the training eval) | vs the rule engine (60 games, seed 8000) |
|---|---|---|
| init (`pilot_best_4392960`) | — | **41.7%** [30.1–54.3] |
| night1 @ 10.3M | 82.5% and climbing | **16.7%** [9.3–28.0] |

Wilson intervals do not overlap. The policy got monotonically better on the number being
watched and collapsed on the number that matters, over ten million steps.

- **Cause, and it is mine.** Two settings, one mistake each:
  1. `--opponent meta` on the in-training eval. That eval selects `_best.pt` *and* feeds
     every supervisor trigger, so the whole safety apparatus was pointed at an opponent we
     do not care about. An eval against the wrong opponent is worse than no eval — it does
     not merely fail to catch a regression, it actively selects for one.
  2. `league 8 / scripted_share 0.30`, i.e. 70% self-play, chosen from a published ~75%
     figure for league training. `--scripted-share`'s own help text in this repository
     says: *"a league that only plays itself gets good at its own metagame and loses to an
     ordinary ladder deck."* That is exactly what happened. A general result about a
     different setup does not outrank this project's own recorded measurement of itself,
     and I should not have let it.
- **Also corrected:** earlier tonight I floated that the baseline might have improved in
  the fixed sim (small samples of 50% and 67%). At 60 games it reads **41.7%** against its
  recorded 43.3% — indistinguishable. The building-pull fix did not change the baseline's
  standing, and those small samples were noise I should not have reported as a signal.
- **Restarted 04:03** from `checkpoints/sprint4_baseline/pilot_best_4392960.pt` — the
  41.7% policy, not the 16.7% one — with `--opponent brain`, `league 4`,
  `scripted_share 0.50`, warmup 200k, eval every 750k, 8h deadline. Every ladder rung now
  keeps self-play a minority of episodes.
- **Preserved:** the meta-specialist and both measurements under
  `tmp/rl/night_meta_specialist/`. It is a genuine artifact — a policy that reached 82.5%
  against meta decks — and worth keeping as evidence of what league overfitting looks
  like, but it must never reach ladder.
- **Lesson for the harness, not just this run:** the supervisor's triggers were all
  behavioural (hog share, plays/match) or relative to its own eval. None of them could
  detect "improving against the wrong thing". Selecting and alarming on the true objective
  is the only structural fix; watching more statistics of the wrong opponent would not
  have helped.

---

## 2026-08-26 — Second automation stopped: `tmp/rl/oven_watch.ps1` respawning `crowns`

The `crowns` run killed at 01:00 came back at 01:17:58 with `--resume`. The respawner was
`tmp/rl/oven_watch.ps1` (pid 11188), a PowerShell supervisor left by an earlier session:
cutoff 13:30, disk guard, stall detection, entropy-collapse and KL-runaway ladders, and a
150-game morning eval. It is a competent piece of work and it is scoped to `crowns*`
files only, so it was never a threat to anything else on disk.

- **The conflict was CPU, not files.** 10 envs alongside this run's 16, on 8 physical
  cores. Measured effect: the overnight run fell from 2133 steps/s to 1024/s.
- **Decision:** stopped the watchdog, then its trainer. One full-speed supervised run
  serves "the best model by morning" better than two at half speed — particularly when
  the second is pursuing reward re-weighting (`--chip 5 --crown 12 --win 15`), which
  `REWARD_DIAGNOSTIC.md` falsified at r(return, win) = 0.967.
- **Nothing lost.** `crowns_best.pt` was copied to
  `checkpoints/candidates/crowns_best_20260826.pt` — exactly what `oven_watch.ps1` would
  have done at its own cutoff — with its json beside it, and the journal, state file and
  the watchdog script itself preserved under `tmp/rl/orphan_crowns/`.
- **Note for whoever wrote it:** its own header says it never touches other runs' files,
  and it kept that promise. The reason it had to stop is that it could not know another
  run existed. Two independent supervisors on one machine need a lock; there isn't one.

---

## 2026-08-26 — Overnight supervised run launched (12h, `scripts/rl_supervisor.py`)

- **Command:** `--name night --hours 12.0 --envs 16 --rollout 128 --value-warmup 300000
  --eval-every 1000000 --eval-episodes 40 --init tmp/rl/clone_pilot.pt --final-episodes 200`.
  Started 01:10, training deadline 13:10, held-out comparison after that.
- **Rung 0 settings:** entropy 0.03 held to 8M then annealed to 0.015 by 20M, lr 5e-5,
  target_kl 0.02, league 8, scripted_share 0.30, reward unchanged (chip 10 / crown 3 /
  win 10). Entropy stays at the value the 43% baseline used — tonight's abort showed the
  policy is fragile to raising it, and the annealing only ever reduces exploration.
- **What differs from the baseline run, and why:** a bigger league (8 vs 4) and more
  self-play (70% vs 60%, matching the ~75% reported for league-play setups) as the
  curriculum lever against the measured plateau; 16 envs instead of 10 for 2.4× the
  throughput; and — the reason there is genuinely new signal to learn — the sim's
  building-pull bug is fixed, so a Hog push is no longer cancelled by a cross-map pull.
  This is a performance run, not a controlled single-variable experiment, and is logged
  as such.
- **Supervision:** eval-line triggers, not loss curves. Win rate below the clone's on two
  evals, hog share below 40% of the clone's on one (that statistic is a fraction of ~2000
  plays, so it barely moves on noise, unlike a 40-game win rate), plays/match above 1.6×
  the clone's, score drifting a point below the best for four evals, 20 minutes of log
  silence, or free disk under 10 GB. On a trip: kill, step down a ladder of tamer
  settings, restart **from the best checkpoint so far**, never from the wreck.
- **Selection:** `checkpoints/night/best.pt` is kept on the 40-episode smoke eval; the
  morning verdict comes from 200 held-out games at seed 9000 against both the rule engine
  and meta decks, run for the night's policy *and* the sprint4 baseline, because the sim
  changed and the recorded 43.3% is no longer comparable. Overlapping Wilson intervals
  are reported as "too close to call" and the tie goes to the incumbent.
- **Storage:** each attempt costs ~1.1 GB; previous attempts are pruned once their weights
  are safely copied out. 58.8 GB free at launch.
- **Outcome:** pending — see `checkpoints/night/SUPERVISION.md`.

---

## 2026-08-26 — Orphaned `crowns` run killed; it was hung and starving the machine

- **What it was:** `sim.train_ppo --name crowns --chip 5 --crown 12 --win 15 --steps 20M`,
  started 00:45:16 from a parent process that no longer exists. `HastyCR-Captain` and
  `HastyCR-Watchdog` are both Disabled and no other Claude session is running, so it was
  left behind by an earlier one.
- **State when found:** last log line 00:59:52 at 779,520 steps, then **nothing for over
  thirty minutes** while eleven processes held memory — 7.0 GB free of 31.6 GB, which is
  what had the test suite crawling.
- **Its own numbers before it hung** (12 episodes an eval, so barely more than anecdote):
  W8 L4 → W8 L4 → W6 L6 → W5 L7 → W7 L5. Hog share rose 14% → 18% under the crown-heavy
  reward, which is mildly interesting and nowhere near evidence.
- **Action:** killed. `tmp/rl/crowns.out` and `crowns_best.json` copied to
  `tmp/rl/orphan_crowns/`; `crowns_best.pt` left where it is. Nothing was deleted.
- **Why it had to go:** it was hung, unsupervised, taking half the machine for a night the
  user asked to be spent on one well-supervised run, and its reward re-weighting is the
  intervention `REWARD_DIAGNOSTIC.md` already falsified (r(return, win) = 0.967).

---

## 2026-08-26 — Simulator bug: buildings pulled building-targeters from any distance

Found by the user watching the simulator, then reproduced (`scripts/probe_mechanics.py`).

- **Symptom:** a Hog Rider deployed at the back of the right lane, tile (14,26), turned
  and walked 8.5 tiles across the arena to a Cannon at (3,13) — **seventeen tiles away,
  against a sight range of 9.5.**
- **Cause:** `Battle._acquire_target` gates what a unit can *see* by sight range, but the
  fallback that gives a unit its destination was not gated for `target_only_buildings`.
  The comment directly above it already described this exact failure for ordinary troops
  ("a Skeleton deployed on the right walk[ing] diagonally across the arena to an Inferno
  Tower at the *left* bridge… Nothing in the real game does that") and fixed it for them.
  Building-targeters kept it. `_walk_destination` had the same hole.
- **Real mechanic** (Clash Royale Wiki, *Basics of Battle* and the sight-range card
  studies): troops engage the nearest enemy of their target category **within sight
  range**. Building-targeters are given a *longer* sight range than other cards — above
  6 tiles, 9.5 for the Hog — precisely so buildings can pull them. It is a longer leash,
  not an unlimited one.
- **Fix:** a non-tower building only pulls, or serves as a destination, from within
  sight range. Crown towers stay eligible at any range — they are not a pull, they are
  where a unit goes when it can see nothing.
- **Why it matters for training, not just for looks:** both players in a 2.6 mirror hold
  a Cannon. Every Hog push was answered by a cross-map pull no real opponent could make,
  so the simulator was systematically pricing the win condition below its true value —
  the original complaint that "the sim says hog doesn't even need to be played".
- **Tests:** `tests/test_building_pull.py` (8) — the cross-lane pull is refused, a Cannon
  inside sight still pulls, the boundary is sight range, crown towers stay reachable from
  the back corner, ordinary troops are unaffected, and every building-targeter obeys it.
- **Also checked and found correct:** the hand and cycle. Over three full matches the
  closest repeat of any card was 12.3 s and 5 plays apart; `PlayerState.play` moves the
  card to the back of an eight-card queue and `play_card` refuses anything not in hand.
  The sim is not replaying cards out of cycle.

---

## 2026-08-26 — Intervention 1 launched: entropy 0.10 held to 2M, annealed to 0.03 by 4M

- **Hypothesis:** the 43.3% plateau is an exploration failure, not a reward failure.
  `REWARD_DIAGNOSTIC.md` puts r(return, win) at 0.967, which falsifies reward shaping;
  `CARD_USAGE.md` puts fireball at 0.7% of plays and musketeer at 0.6% — the two cards
  that convert chip into a crown are barely tried, so the crown-conversion reward is
  never delivered to them. See `reports/rl_sprint4/INTERVENTION_1_DECISION.md`.
- **Change (exactly one):** entropy coefficient becomes a schedule. Everything else is
  held at the baseline manifest: init `tmp/rl/clone_pilot.pt`, envs 10, rollout 128,
  gamma 0.997, clip 0.2, value_coef 0.5, lr 5e-5, target_kl 0.02, value_warmup 300k,
  league 4, scripted_share 0.4, reward chip 10 / crown 3 / win 10 / elixir 0,
  opponent meta, 6M steps.
- **Code:** `sim/train_ppo.entropy_schedule` plus `--entropy-final/--entropy-hold/
  --entropy-anneal`; the coefficient is logged per step as `ecoef` so the schedule is
  auditable from the log. `tests/test_entropy_schedule.py` (10 tests) covers the joins,
  the degenerate `anneal <= hold` case, and that the flags reach the function.
  Constant-coefficient behaviour is unchanged when `--entropy-final` is omitted, so no
  earlier run's settings move.
- **Run:** `tmp/rl/s4ent.out`, launched 2026-08-26 00:21, ~1740 steps/s in warmup.
  Baseline took 2h06m for 6M on the same GPU.
- **Gates:** abort if Brain WR ≤ 38.3% at the 1.5M checkpoint. Reject if the 300-game
  WR at seed 8000 stays inside 43.3% [37.8–49.0] with no secondary gain. If fireball
  and musketeer usage stay below 1.5% *despite* the higher coefficient, the exploration
  hypothesis is wrong and the bottleneck is representation/memory → Sprint 5.
- **Outcome:** pending.

---

## 2026-08-26 — Live checkpoint path pointed at a vetted policy

- **Found:** `run.ps1 -Brain rl` defaulted to `tmp\rl\hog26v6_best.pt` — a collapsed run
  that won 1 of 59. The studio's brain dropdown listed `tmp/rl/*.pt` only, sorted by
  modification time, so the file at the top of the list was whatever was training at
  that moment, and `checkpoints/` was not offered at all.
- **Change:** default is now `checkpoints\sprint4_baseline\pilot_best_4392960.pt`; the
  dropdown lists `checkpoints/**` first with its held-out score and `tmp/rl/*` below,
  prefixed `scratch:`. Labels distinguish a held-out number from a self-eval — the same
  `live_candidate` policy reads 82% on its own eval and 24% held out.
- **Pre-flight:** the checkpoint loads through `brain/rl_policy.py` (step 4,392,960) and
  costs 2.0 ms per decision on CPU against a 500 ms decision tick.
- **Not verified:** anything about real-game performance. No RL checkpoint has played a
  live match yet; the sim number says nothing about perception noise, the HP
  approximation, or tap timing.

---

## (append below — one entry per intervention, plus final accept/reject)

### Template
- **Date — Title**
- Hypothesis:
- Evidence (report + figure):
- Change (exactly ONE):
- Expected Brain delta + falsifier:
- Outcome (after eval):
- Next bottleneck:
