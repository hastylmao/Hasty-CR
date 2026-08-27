# Checkpoint Evaluation — Sprint 3

Date: 2026-08-25  
Sim rev: `a1dc9e6dbbc97bf3f2c04ff8b9045dfa66ee7577`  
Gamedata agg: `a1efa56684ceda29` (from `checkpoints/live_candidate/manifest.json`; repo-level hash fallback `535b959def28c4a9` for curiosity only — manifest is canonical)  
Eval protocol: `eval no_grad greedy argmax deterministic`, held-out `COMPARE_SEED=8000` for direct comparison, `FINAL_SEED=9000` reserved for final. Wilson 95% CI. No shared RNG/state between checkpoints (fresh `ClashEnv` per `evaluate_one` call).

## Training

- Init: `tmp/rl/clone_pilot.pt` (600 eps behaviour clone, 20.2M params)
- Device: cuda
- Hyper: envs 10, rollout 128, gamma 0.997, clip 0.2, value_coef 0.5, entropy_coef 0.03, lr 5e-05, target_kl 0.02, value warmup 300k at 1e-3 (policy frozen)
- League: up to 4 past selves + 40% meta decks
- Completed: 6,000,640 steps (4802 log lines), ~790 env-steps/s at the tail.

## Held-out comparison — same seed (8000), greedy

| Checkpoint | Step | n (brain) | Brain W-L | Win rate | 95% Wilson CI | Crown diff | Tower diff | vs meta | vs simple | Illegal |
|---|---|---|---|---|---|---|---|---|---|---|
| `pilot_league/step1024000.pt` | 1,024,000 (league snapshot) | 100 | 9-91 | 9.0% | 4.8%–16.2% | −0.75 | −0.36 | 77.0% (67.8–84.2) | 100% | 0.0% |
| `live_candidate/pilot_best_20260824.pt` | 1,505,280 (prior frozen best) | 100 | 24-76 | 24.0% | 16.7%–33.2% | −0.54 | −0.10 | 80.0% (71.1–86.7) | 100% | 0.0% |
| `pilot_best.pt` | 4,392,960 (train-eval best, also held-out screened) | 100 | 42-58 | 42.0% | 32.8%–51.8% | −0.21 | +0.17 | 91.0% (83.8–95.2) | 100% | 0.0% |
| `pilot_last.pt` | 6,000,640 (final step) | 100 | 43-57 | 43.0% | 33.7%–52.8% | −0.21 | +0.27 | 85.0% (76.7–90.7) | 100% | 0.0% |

Tighter estimate for the two late checkpoints (300 games vs brain, same seed):

| Checkpoint | n | W-L | Win rate | 95% CI | Crown diff | Tower diff | Duration (s) | Illegal |
|---|---|---|---|---|---|---|---|---|
| `pilot_best.pt` (4,392,960) | 300 | 130-170 | 43.3% | 37.8%–49.0% | −0.17 | +0.23 | 225 | 0.0% |
| `pilot_last.pt` (6,000,640) | 300 | 127-173 | 42.3% | 36.9%–48.0% | −0.21 | +0.26 | 221 | 0.0% |

Full detail: `LEARNING_CURVE.csv` and `reports/rl_sprint3/eval_*.json`.

## What the numbers say

- **Strong monotonic improvement to ~4.4M, then a plateau.** Brain win rate climbs 9% → 24% → 43% across the run. The last ~1.6M steps add nothing distinguishable on brain (42–43% both on 100 and 300 games, overlapping CIs), while meta even dips 91% → 85% (within noise but not an improvement). This looks like a genuine ceiling under current opponent/reward/observation settings, not a missed peak.

- **pilot_best (4,392,960) and pilot_last (6,000,640) are statistically tied** as best checkpoints. On both 100 and 300 brain games they overlap almost exactly. `pilot_best` has the marginally higher point estimate (43.3% vs 42.3% on 300 games) and better meta generalization (91% vs 85%), so it is nominally strongest; either is defensible as "true best" — they are interchangeable within error. The 6M checkpoint is NOT assumed best by recency.

- **Crown diff vs tower diff divergence is real.** Both late checkpoints are slightly negative on crown diff but positive on tower HP diff (+0.17–+0.27). That implies many close losses decided by the crown tiebreak / chip rather than raw tower HP — worth dissecting in loss analysis (holds as a pass-through until measured, not a claim).

- **Duration:** 219–225s vs brain, ~200s vs meta, ~188–190s vs simple — stable across checkpoints. No pathology where stronger play comes from stalling or timing out.

- **Illegal rate:** 0.0% everywhere on held-out eval. Action masking is clean.

- **Hold rate.** Previous reports quoted a `hold_rate` around 87–88%. That figure counts `action==0` decisions among `DECIDE_EVERY_MS=500` decision ticks — i.e. decision-level holds, not raw simulator ticks. Verify before reusing: if a future helper ever switches to counting `env.step` vs `match.step` ticks the number is meaningless. For this evaluation the reliable cadence numbers are `plays_per_match` (55–57 vs brain at the top) plus `duration_s`; derive `plays/min = plays_per_match / (duration_s/60) ≈ 14–15/min` vs brain. Do not quote "hold rate" without stating the denominator. A proper `time at 10 elixir` / `avg elixir at play` probe should be added as a direct elixir-leak metric (NOT MEASURED in this checkpoint screening — see TODO below).

## True best checkpoint

**`tmp/rl/pilot_best.pt` at step 4,392,960** is the true best on current evidence:

- Brain: **43.3% over 300 games, 95% CI 37.8%–49.0%** (42.0% on the comparable 100-game slice, 95% CI 32.8%–51.8%).
- Crowns: −0.17 (300) / −0.21 (100).
- Tower HP diff: +0.23 / +0.17.
- Meta: 91.0% (83.8–95.2) on 100 games; simple: 100% (96.3–100.0%).
- Illegal: 0.0%, duration ~225s vs brain.

Runner-up `pilot_last.pt` (6,000,640) at 42.3% (36.9–48.0%) is indistinguishable; either may be promoted as `live_candidate` — the versioned manifest below records the selected best explicitly. If downstream work wants a single canonical checkpoint, use `pilot_best.pt` (4,392,960).

## Answers to the asked questions

1. **Is performance still improving with training?** Up to ~4.4M, yes — sharply (9% → 24% → 43%). Beyond that, no measurable improvement on brain or meta through 6M.

2. **Has it plateaued?** Yes — from 4.39M to 6.00M on held-out brain. Two independent 300-game estimates are within 1 point and overlapping CIs. The reward trace also flattens (return ~17–21 late, versus early climb). This is a plateau under current settings, not a transient fluctuation.

3. **What is the true best checkpoint?** `tmp/rl/pilot_best.pt` step 4,392,960 (hash `2ff3b7b50a4a0469…`). `pilot_last.pt` step 6,000,640 is a statistical tie; either suffices, but 4.39M is nominally best.

4. **Brain win rate and CI?** **43.3% (37.8%–49.0%) on 300 held-out games, seed 8000** (42.0% [32.8–51.8] on the 100-game comparable slice). Crown diff −0.17, tower diff +0.23, illegal 0%.

5. **Is the brain gap still the main bottleneck?** Yes. Simple is solved (100%), meta is near-solved (85–91%), brain remains at ~43% with a ~14-point gap to even. Every late checkpoint loses more crowns than it takes while actually winning tower HP — the gap is strategic (decision quality vs brain), not a reward or action-legality issue.

## Preserved artifacts (nothing overwritten)

- `tmp/rl/pilot_best.pt` (4,392,960) and `tmp/rl/pilot_last.pt` (6,000,640) both retained.
- Prior `checkpoints/live_candidate/pilot_best_20260824.pt` (1,505,280) retained.
- New detailed evals: `reports/rl_sprint3/eval_live_100.json`, `eval_pilot_best_100.json`, `eval_pilot_last_100.json`, `eval_pilot_best_300brain.json`, `eval_pilot_last_300brain.json`, `eval_league_1024k_100.json`.
- Curve: `reports/rl_sprint3/LEARNING_CURVE.csv`.

## Versioned true-best manifest (next step)

A versioned candidate with checkpoint hash, step, sim rev, gamedata hash, config, and held-out scores will be saved under `checkpoints/candidates/` (mirroring `checkpoints/live_candidate/manifest.json` schema). Use:

- checkpoint: `tmp/rl/pilot_best.pt` (promote a copy)
- checkpoint sha256: `2ff3b7b50a4a0469d04b1c9ffc3d85729cc9732cb6ee1fba4a69fcba7d131d6b`
- step: 4392960
- sim rev: a1dc9e6dbbc97bf3f2c04ff8b9045dfa66ee7577
- gamedata agg: a1efa56684ceda29
- hyper: envs 10 rollout 128 gamma 0.997 clip 0.2 value_coef 0.5 entropy 0.03 lr 5e-05 target_kl 0.02
- reward: tower 10 crown 3 win 10 chip 10 (default)
- held-out (seed 8000): brain 130-170/300 = 43.3% [37.8–49.0], crown −0.17 tower +0.23; meta 91.0% [83.8–95.2] on 100; simple 100%.

## TODO / NOT MEASURED for follow-up

- Direct `time at 10 elixir` / `avg elixir at play` (elixir-leak metric) — needs a dedicated cadence probe stepping with `DECIDE_EVERY_MS` accounting, not inferred from plays/min. Previous cadence attempt timed out.
- Card placement heatmaps and per-opponent win/loss splits beyond the headline numbers above.
- Robustness / exploit / observation-parity work from the separate parallel prompt.
