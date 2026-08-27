# RL Sprint 4 — State

Last update: 2026-08-26
Phase: **Phase 2** (intervention 1 training; Phases 0/1A/1B/1C complete)

## Inherited from Sprint 3 (DO NOT retrain)

- Training completed: 6,000,640 steps (log `tmp/rl/pilot.log`, 4802 lines), ~790 env-steps/s.
- True best: `tmp/rl/pilot_best.pt` step 4,392,960 — Brain 43.3% [37.8–49.0] (300 games, seed 8000), crown diff −0.17, tower diff +0.23, illegal 0%.
- Runner-up: `tmp/rl/pilot_last.pt` step 6,000,640 — 42.3% [36.9–48.0], statistical tie.
- Both versioned under `checkpoints/candidates/`; Sprint 4 frozen copy under `checkpoints/sprint4_baseline/`.
- Eval protocol: eval mode, no_grad, greedy argmax; COMPARE_SEED=8000, FINAL_SEED=9000 (unseen).

## Sprint 4 question

Why does the ~43% policy lose to Brain, and can ONE evidence-backed intervention fix it?

## Tower-HP/crown paradox (core mystery)

Policy wins tower HP diff (+0.23 on 300 games) but loses crown diff (−0.17) and win rate.
Hypotheses ranked by prior (must be confirmed/overridden by data):
1. **Reward shaping** — tower 10 + crown 3 makes spread chip (0.5+0.5) equal to single-tower take;
   agent learns low-risk chip instead of concentrated pushes.
2. **Entropy collapse** — plateau at entropy 0.13–0.41 (looks healthy, likely NOT the cause).
3. **Observation gap** — Brain has opponent elixir estimate, building timers, cycle knowledge.
4. **Opponent ceiling** — Brain may be too strong for current settings.

## Current phase status

- [x] Phase 0: state docs + baseline freeze
- [x] Phase 1A: 300-game Brain diagnostic dataset (scripts/diagnose_sprint4.py)
- [x] Phase 1B/C: 17 analysis reports under reports/rl_sprint4/
- [ ] Phase 2: intervention 1 training ← NOW (run `s4ent`, log `tmp/rl/s4ent.out`)
- [ ] Phase 3: robustness / exploit / shadow
- [ ] Phase 4: final holdout + release

## Overnight run of 2026-08-26 (supervised, unattended)

Launched via `scripts/rl_supervisor.py`, which watches the eval line and restarts from
the best checkpoint down a ladder of tamer settings if the policy starts degrading.
Triggers: win rate below the clone's, hog share collapsing, plays/match blowing out,
score drifting below the best, log silence, low disk. See `checkpoints/night/`.

**Throughput sweep first** (`scripts/rl_throughput.py`, steady state, no value warmup,
130s per config on the RTX 4070 Ti SUPER / 8 physical cores):

| envs | steps/s | vs best |
|---|---|---|
| 8 | 1166 | 57% |
| 12 | 1016 | 50% |
| 16 | 1893 | 92% |
| 20 | 2048 | 100% |

More envs is faster largely because batch = envs × rollout, so a bigger batch means
fewer gradient steps per environment step — real wall-clock speed, paid for in sample
efficiency. 16 was chosen over 20: batch 2048 stays nearer the 1280 the 43% baseline
used, for 92% of peak throughput.

**The sweep overstated the real run and should not be quoted for it.** It ran without a
league, and the overnight configuration is `league 8 / scripted_share 0.3` — so 70% of
episodes now play a *learned* opponent, and every opponent decision is a network forward
pass instead of a scripted heuristic. Measured steady state on the actual run is
**614 steps/s**, about a third of the sweep figure, projecting to ~22M steps by the
13:10 deadline rather than the ~69M the sweep implied.

That is still 3.7× the 6M the baseline run completed, and step count was never the
binding constraint: the baseline reached 43% at 4.4M and was flat to 6M. The league is
the intervention against that plateau, so paying two thirds of the throughput for a
stronger curriculum is the trade being made deliberately, not an accident.

## Phase 2 answers (from Phase 1)

- Reward shaping is **falsified** as the cause: r(return, win) = 0.967.
- The failure is crown conversion: enemy princess taken in 30% of wins, 3% of losses;
  157/170 losses damage both enemy princesses and take neither.
- Chosen intervention: entropy 0.10 → 0.03 (hold 2M, anneal by 4M), nothing else moved.
  Details and falsifiers in RL_SPRINT4_DECISIONS.md.

## Live bridge status (independent of the above)

- No RL checkpoint has ever played a real match. The sim win rate is not evidence about
  the real game; perception noise, the unit-HP approximation and tap timing are all
  untested end to end.
- `run.ps1 -Brain rl` now defaults to `checkpoints\sprint4_baseline\pilot_best_4392960.pt`
  (43.3% vs Brain, 91% vs meta, 300/100 held-out games). Loads clean, 2.0 ms/decision.

## Known gaps carried forward

- Elixir-leak metrics (time at 10, avg elixir at play) — NOT MEASURED in Sprint 3.
- Card placement heatmaps, per-opponent win/loss splits.
- Robustness probe broken (perturbations did not actually change sim).
- Shadow advisor stub only; no GameState → env observe adapter.
