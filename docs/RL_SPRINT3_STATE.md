# RL Sprint 3 — State

Last update: 2026-08-25T00:57+05:30

## Current phase
Sprint 3 — checkpoint evaluation complete; training finished to 6M.

## Training
- Status: COMPLETED 6,000,640 steps (4802 log lines), ~790 env-steps/s at tail.
- Best checkpoint (train-eval + held-out screened): tmp/rl/pilot_best.pt step 4,392,960 W38 L2 on train-eval, 42.0–43.3% vs brain held-out (see below).
- Final checkpoint: tmp/rl/pilot_last.pt step 6,000,640 — statistical tie with best (42.3–43.0% vs brain).
- Prior frozen candidate: checkpoints/live_candidate/pilot_best_20260824.pt step 1,505,280 — 24% vs brain on 100 held-out (superseded).
- Init: tmp/rl/clone_pilot.pt (600 eps behaviour clone, val 0.77, 20.2M params, cuda).
- Hyper: envs 10 rollout 128 gamma 0.997 clip 0.2 value_coef 0.5 entropy 0.03 lr 5e-05 target_kl 0.02 value_warmup 300k, league 4 scripted_share 0.4, reward chip 10 crown 3 win 10.
- Log: tmp/rl/pilot.log — return climbs then plateaus ~17–21, entropy 0.14–0.34, KL ~0.0005–0.006.

## Held-out evaluation (COMPARE_SEED=8000, eval no_grad greedy argmax deterministic, Wilson 95%)

| Step | n (brain) | Brain | Wilson CI | Crown diff | Tower diff | vs meta (100) | vs simple (100) | Duration |
|---|---|---|---|---|---|---|---|---|
| 1,024,000 | 100 | 9.0% (9-91) | 4.8–16.2% | −0.75 | −0.36 | 77.0% | 100% | 200s |
| 1,505,280 | 100 | 24.0% (24-76) | 16.7–33.2% | −0.54 | −0.10 | 80.0% | 100% | 219s |
| 4,392,960 pilot_best | 100 | 42.0% (42-58) | 32.8–51.8% | −0.21 | +0.17 | 91.0% | 100% | 223s |
| 4,392,960 pilot_best | 300 | 43.3% (130-170) | 37.8–49.0% | −0.17 | +0.23 | NOT_MEASURED | NOT_MEASURED | 225s |
| 6,000,640 pilot_last | 100 | 43.0% (43-57) | 33.7–52.8% | −0.21 | +0.27 | 85.0% | 100% | 223s |
| 6,000,640 pilot_last | 300 | 42.3% (127-173) | 36.9–48.0% | −0.21 | +0.26 | NOT_MEASURED | NOT_MEASURED | 221s |

- True best: tmp/rl/pilot_best.pt step 4,392,960 — nominally best (43.3% brain on 300), with pilot_last (6M) a statistical tie. Either is defensible; use 4.39M as canonical. Both saved versioned under checkpoints/candidates/.
- Illegal rate: 0.0% everywhere held-out. Action masking clean.
- Plays per match vs brain: ~55–57 on late checkpoints → ~14–15 plays/min at ~220s matches. Previous "hold rate ~87%" measured holds among DECIDE_EVERY_MS=500 decision ticks; quote only with denominator. Direct time-at-10-elixir / avg-elixir-at-play NOT YET MEASURED (cadence probe TODO).

## Plateau verdict
- Performance improved sharply 9%→24%→43% to ~4.4M, then flat to 6M (1.6M additional steps, overlapping 300-game CIs). This is a genuine plateau under current opponent/reward/observation settings, not noise.

## Versioned candidates (nothing overwritten)
- checkpoints/candidates/pilot_best_4392960.pt (sha256 2ff3b7b50a4a0469d04b...) + .json manifest
- checkpoints/candidates/pilot_last_6000640.pt (sha256 b744accc821d7b51...) + .json manifest
- Eval detail: reports/rl_sprint3/eval_*.json ; curve: reports/rl_sprint3/LEARNING_CURVE.csv ; summary: reports/rl_sprint3/CHECKPOINT_EVALUATION.md

## Known gaps / NOT MEASURED (for next tasks)
- Elixir-leak metrics: time at 10 elixir, avg elixir at play — need dedicated probe (previous probe timed out).
- Heatmaps / per-card placement stats.
- PPO health deep parse, reward-vs-win correlation, brain audit/brain-loss analysis, robustness/exploit/metamorphic, observation parity / perception→policy adapter / shadow advisor (separate parallel prompts).
