# RL Sprint 3 — Queue

Updated: 2026-08-25T00:57+05:30

States: TODO IN_PROGRESS DONE BLOCKED

## P0 — Training + evaluation

- DONE PPO pilot training to 6M (6,000,640 steps, log 4802 lines)
- DONE Fix evaluation protocol (Wilson CI, fixed seed sets 8000/9000, greedy eval no_grad, tower/duration/illegal)
- DONE Evaluate pilot_best + pilot_last + live_candidate (+ league 1M) on 100-game matrix (brain/meta/simple) — all on COMPARE_SEED 8000
- DONE 300-game brain evals on pilot_best (43.3% [37.8–49.0]) and pilot_last (42.3% [36.9–48.0])
- DONE Learning curve CSV across milestones (LEARNING_CURVE.csv)
- DONE Select true best by held-out brain + crown/tower diff, save versioned candidates (pilot_best 4,392,960 true best; pilot_last 6M tie runner-up)

## P0 — Diagnosis

- TODO Brain opponent audit (brain vs meta/simple/self) -> BRAIN_OPPONENT_AUDIT.md
- TODO Brain loss analysis (50-100 losses, replay, categories) -> BRAIN_LOSS_ANALYSIS.md
- TODO Wins vs losses comparison
- TODO Placement heatmaps per card
- TODO Action cadence (plays/min, time at 10 elixir, avg elixir at play) -> ACTION_CADENCE.md — verify hold-rate denominator, add direct elixir-leak probe
- TODO Reward ablation / correlation (high-reward losses, low-reward wins)
- TODO Observation bottleneck audit -> OBSERVATION_BOTTLENECKS.md

## P1 — Robustness + PPO health

- TODO Verify perturbations actually change sim; fix robustness_probe
- TODO Robustness matrix (2-3 candidates x ±1/2%, ±1 tick) -> ROBUSTNESS_MATRIX.csv
- TODO Decision stability (action agreement under perturbation)
- TODO Metamorphic tests (mirror, UID, replay)
- TODO Exploit red team sweep -> EXPLOIT_AUDIT.md
- TODO PPO health report -> PPO_HEALTH.md (parse pilot.log entropy/KL/value loss)

## P1 — Architecture / curriculum / self-play

- TODO Network architecture audit; prototype if justified
- TODO Opponent curriculum investigation
- TODO Self-play league quality check + mini tournament if candidate strong

## P2 — Shadow / parity / transfer

- TODO Harden shadow_advisor
- TODO GameState -> env observe adapter (minimum bridge)
- TODO Parity report -> LIVE_OBSERVATION_PARITY.md
- TODO Offline demo log
- TODO Transfer risk report

## P2 — Final

- TODO Representative match review (5 wins/5 losses vs brain, etc.)
- TODO RL_SPRINT3_FINAL.md + RL_SPRINT3_MAJOR_DISCOVERIES.md
