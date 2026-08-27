# RL Sprint 4 — Queue

Updated: 2026-08-25
States: TODO IN_PROGRESS DONE BLOCKED

## Phase 0 — Hygiene
- IN_PROGRESS freeze baseline → checkpoints/sprint4_baseline/ (pt + expanded manifest)
- IN_PROGRESS create RL_SPRINT4_STATE/QUEUE/DECISIONS.md

## Phase 1A — Diagnostic dataset
- TODO lean logger scripts/diagnose_sprint4.py (300 games vs brain, seed 8000, <15 min)
- TODO run 300-game Brain diagnostic with per-tick traces → reports/rl_sprint4/matches/

## Phase 1B — Deep analyses (Sections 4–11, parallel after dataset)
- TODO TOWER_HP_CROWN_PARADOX.md (P0)
- TODO PHASE_ANALYSIS.md
- TODO ELIXIR_ANALYSIS.md (lean, no greedy re-eval)
- TODO CARD_USAGE.md
- TODO HEATMAPS.md
- TODO LANE_STRATEGY.md
- TODO ENDGAME.md
- TODO FIRST_DIVERGENCE.md

## Phase 1C — Opponent / reward / training health (Sections 12–18)
- TODO BRAIN_AUDIT.md (info advantage vs observe)
- TODO BRAIN_SCORECARD.md
- TODO REWARD_DIAGNOSTIC.md (return/win corr)
- TODO PPO_HEALTH.md (parse pilot.log)
- TODO OBSERVATION_AUDIT.md
- TODO MEMORY_HYPOTHESIS.md
- TODO ENTROPY_STUDY.md

## Phase 2 — One intervention
- TODO INTERVENTION_1_DECISION.md (ONE change, evidence→expected delta, falsifier)
- TODO staged training A (200k smoke) / B (1.5M mid) / C (4.5–6M full)
- TODO same-seed baseline-vs-variant eval (300 brain, seed 8000) with Wilson CI
- TODO accept/reject log in RL_SPRINT4_DECISIONS.md

## Phase 3A — Exploit & robustness
- TODO EXPLOIT_AUDIT.md
- TODO scripts/robustness_sprint4.py (verified overrides, assert sim actually changed)
- TODO ROBUSTNESS_MATRIX.csv
- TODO domain randomization (conditional)
- TODO SIM_TEST_FROM_EXPLOIT.md

## Phase 3B — Shadow / parity
- TODO LIVE_OBSERVATION_PARITY.md
- TODO shadow_adapter (minimal GameState → planes/scalars)
- TODO SHADOW_DEMO.md (10–20 states)
- TODO ACTION_DECODING.md
- TODO MATCH_REVIEW.md (5W/5L vs brain)
- TODO TOURNAMENT.md (round-robin)
- TODO throughput report

## Phase 4 — Final holdout & release
- TODO fresh final holdout FINAL_SEED=9000 (300 brain + 100 meta + 100 simple)
- TODO checkpoints/sprint4_final/ (manifest + pt)
- TODO readiness category (never LIVE_READY)
- TODO RL_SPRINT4_FINAL.md + RL_SPRINT4_MAJOR_DISCOVERIES.md
- TODO update STATE/QUEUE/DECISIONS for compaction recovery

## Guardrails
- Never waste time on APK/CSV/random cards/new decks/rewrites/giant frontends/auto-account/fidelity claims.
- Never declare Brain == real Clash.
- If >50% brain → continue to confidence; if nothing improves → ceiling → recommend Sprint 5.
