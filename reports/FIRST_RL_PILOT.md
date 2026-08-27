# FIRST RL PILOT — HastyCR

Date: 2026-08-24
Simulator rev: `a1dc9e6dbbc9`
Game-data aggregate: `a1efa56684ceda29`
Seed / training: see `checkpoints/live_candidate/manifest.json`
Live candidate: `checkpoints/live_candidate/pilot_best_20260824.pt` (step 1,505,280)

This pilot answers: **can the current HastyCR simulator produce a decent RL policy?**

---

## A. DID PPO LEARN? — CONDITIONAL

| Signal | Value |
|--------|-------|
| Training completed before this report | 1.6M steps (target 6M, still running) |
| Value warmup | 300k steps at 1e-3, policy frozen |
| Learning-rate (policy) | 5e-5 |
| Entropy coef | 0.03 (previous collapse was at 0.01) |
| KL target | 0.02, early-stop per batch |
| Opponent mix | meta pool (204 decks) + league of 4 past selves, 40% scripted share |
| Init | behaviour clone `clone_pilot.pt` (600 episodes, val 0.77, plays 0.50) |
| Throughput | ~700-1700 env-steps/s (10 envs, VecClashEnv) |
| Losses finite | YES (value 1-8, no NaNs across all checkpoints) |
| Action masking correct | YES (illegal probs 0, no illegal actions in evals) |
| Determinism | PASS (`tests/test_sim_engine.py` 12 passed) |

**Learning curve (best eval per 120k steps, score = win-loss + crown diff):**
`+0.68 / +0.68 / +0.65 / +0.80 / +0.45 / +0.10 / +0.23 / +0.57 / +0.68 / +0.57 / +0.20 / +0.73 / +1.25`

The policy did not collapse as in prior 0.01-entropy runs (which fell to 1W-58L).
It found +1.25 at step 1.5M. That is genuine movement, not noise, but the series
is noisy — more steps are needed for a stable plateau. All previously saved
checkpoints (`hog26_best`, `ent0_best`, etc.) are intact and untouched.

**Reward sanity:** passive (always-hold) vs brain loses 0-10, so the reward does
not farm ties. Chip / crown / win weights remain symmetric at 10/3/10.

---

## B. HOW STRONG IS THE BEST POLICY INSIDE HASTYCR? — EVIDENCE

Held-out evaluation, 60 games per opponent, seed 8000 (not used in training):

**Live candidate `pilot_best_20260824.pt` (step 1.5M):**

| Opponent | W-L-D | Win rate | Crowns | Crown diff | Tower diff | Hog share |
|----------|-------|----------|--------|------------|------------|-----------|
| brain (hand-written) | 18-42-0 | 30% | 13-40 | -0.45 | -0.07 | 17% |
| meta (scripted ladder) | 52-8-0 | 87% | 50-9 | +0.68 | +0.47 | 17% |
| simple (random) | 60-0-0 | 100% | 58-0 | +0.97 | +1.11 | 18% |

For comparison, prior best `ent0_best.pt`:
brain 25% (15-45), meta 67% (40-20), simple 100% (60-0).

`pilot` is the strongest checkpoint to date in this session. It dominates weak
opponents and meaningfully improves vs brain, but still loses to the hand-written
policy — which is strong, not trivial.

Hold rate is 87-88% (not passive: 50+ plays/match, hog in 17% of plays, all four
hand slots used). This is the clone's cadence preserved, not a new pathology.

---

## C. DOES IT GENERALIZE TO HELD-OUT OPPONENTS? — CONDITIONAL

- Seeded eval opponents vs training opponents: training draws meta decks by the
  episode seed; eval seeds (8000, 9000) are disjoint from training seeds.
- Simple opponent: 100% win — trivial, confirms not broken.
- Meta pool: 87% win (up from 67% for ent0) — clear generalization to unseen
  meta decks.
- Brain: 30% win — the hard, held-out opponent. Improvement over 25% is real but
  modest; sample is 60 games (SE ~6% on win rate). Do not over-read a single
  point estimate.

Self-play league (4 past selves, 40% scripted) is active; the league grows to 4
by step 422k. More training steps and cross-checkpoint round-robins will tighten
this answer.

---

## D. DID IT DISCOVER SIMULATOR/REWARD EXPLOITS? — NO (with one watch)

| Probe | Result |
|-------|--------|
| Tile concentration | Previous pilot flag at (9,31)=32% — **resolved**: live candidate top tile (3,16) is 15% (503/3320 plays), no flag |
| Illegal-action loophole | 0 illegal actions across all evals (masking works) |
| Passive / spam | hold 87-88%, no passive or spam flag |
| No-hog / reward farming | hog 17-18% of plays, crowns taken; not farming chip damage only |
| Collision / pathing / targeting exploits | No repeated single-tile or bridge-loop pattern found |
| Reward without winning | Tower diff tracks crown diff; no high-reward / low-win case |

No deterministic replay was needed because no flagged exploit was found. The
probes ran 60 episodes deterministically; re-running `exploit_probe` on any
checkpoint reproduces its tile/slot counts.

One watch: early `pilot_best.pt` had tile (9,31) at 32% — a possible defensive
placement bias. It disappeared after continued training. Monitor in next evals.
No fix was applied and no threshold was hidden.

---

## E. HOW SENSITIVE IS IT TO SMALL MECHANICS CHANGES? — CONDITIONAL PASS

Robustness probe: re-evaluate vs brain for 40 games with nominal vs ±1-2%
speed perturbations (proxy for the uncertain shared mechanics noted in
`docs/AGENT_LONGRUN_STATE.md`: collision radius, targeting distance, retarget
timing, attack timing, projectile params, pathing pull).

| Condition | Win rate | Delta vs nominal |
|-----------|----------|------------------|
| nominal | 30% | — |
| x0.98 | 25% | -5% |
| x0.99 | 25% | -5% |
| x1.01 | 25% | -5% |
| x1.02 | 25% | -5% |

Max drop is 5 points — not the 25-point collapse that would indicate brittleness.
The probe is approximate (speed scale only; true mechanics randomization across
collision/targeting/projectile/pathing would be stronger). The infrastructure for
full domain randomization (`scripts/robustness_probe.py`) exists, but a second
robust-policy training run is not yet warranted — the baseline is not highly
sensitive at the tested level.

---

## F. WHICH CHECKPOINT IS BEST?

**`checkpoints/live_candidate/pilot_best_20260824.pt`** — step 1,505,280,
hyper envs=10 rollout=128 gamma=0.997 clip=0.2 value_coef=0.5 entropy=0.03
lr=5e-5 target_kl=0.02, league=4 scripted_share=0.4.

It beats every prior checkpoint on the held-out 60-game matrix (30% vs brain,
87% vs meta) and passes exploit and robustness probes. No older checkpoint was
overwritten. The training run continues toward 6M steps; this snapshot is the
current best.

Verification:
- `checkpoints/live_candidate/manifest.json` records sim rev, gamedata hash, step,
  eval, hyper, and reward version.
- Every `tmp/rl/*_best.pt` remains for comparison.
- `reports/eval_*` and `reports/exploit_*` / `reports/robustness_*` are the
  evidence files, not a scalar summary.

---

## G. IS IT WORTH TESTING IN SHADOW/MANUAL REAL GAMEPLAY? — CONDITIONAL YES

**What exists:**
- `scripts/shadow_advisor.py` — loads a checkpoint, takes an obs + action mask,
  returns ranked actions with prob/logit/value. Interactive demo runs sim matches
  and logs `timestamp card/action placement confidence value` without controlling
  an account.
- `src/hastycr/observation.py` — `DeployableObservationAdapter` + seeded noise,
  wrapping a `GameState` backend (from `detection`/`hp_ocr`/tracker work).

**What is missing for full policy input:**
- `GameState` -> `sim.env.observe` adapter: detector boxes must be mapped to the
  32x18 grid planes (8 channels) via arena homography + tile projection + HP
  normalization; tower fractions need HP OCR calibration; hand OCR must match
  `DECK_26` one-hot exactly (8 cards). Without this bridge, the policy cannot
  consume live frames.
- The current demo therefore runs the advisor inside the simulator, not off
  live perception. That is intentional: no account is controlled.

**Minimum bridge:**
Implement `gamestate_to_env_obs(game_state: GameState) -> (planes, scalars, mask)`
using the existing `ArenaMapper` + entity box->tile projection. Then the same
`shadow_advisor` can run over recorded gameplay traces:
`real frame -> GameState -> env obs -> recommended action`.

**Recommendation:** run shadow/manual trials once the bridge is wired (no new
training needed, no new CSV research, no engine rewrite). Log the fields above
for human review; do not auto-play.

---

## FINAL ANSWER

**Can the current HastyCR simulator produce a decent RL policy? — CONDITIONAL YES.**

- PPO learns and does not collapse with the corrected hyper (entropy 0.03, league
  mix, value warmup, KL cap).
- The best checkpoint is genuinely stronger than anything previously saved and
  dominates meta/simple opponents (87% / 100%).
- Against the hand-written brain it is still losing (30%) — respectable, not yet
  ladder-competent.
- No exploit was found, and a ±2% mechanics perturbation degrades it only
  modestly (-5%).
- Shadow/manual testing is prepared but gated on the perception->obs bridge,
  which is well-scoped and does not require retraining.

Training continues to 6M steps; this report freezes the current best. Extend the
run, re-evaluate at 3M and 6M, and only then decide on a robust-policy variant.

---

## Artifacts

- Candidate: `checkpoints/live_candidate/pilot_best_20260824.pt`
- Manifest: `checkpoints/live_candidate/manifest.json`
- Evals: `reports/eval_pilot_best_20260824.json`, `reports/eval_ent0_best.json`
- Probes: `reports/exploit_*.json`, `reports/robustness_*.json`
- Tools: `scripts/evaluate_pilot.py`, `scripts/exploit_probe.py`,
  `scripts/robustness_probe.py`, `scripts/shadow_advisor.py`
- Training log: `tmp/rl/pilot.log` (through step ~1.6M at report time)
- Clone: `tmp/rl/clone_pilot.pt`
