# Intervention 1 Decision — Sprint 4

## Question

Why does the baseline policy lose to Brain at 43.3%, and what is the ONE change most likely to raise it?

## Evidence chain

1. **The paradox is a tower-conversion failure, not a damage failure.**
   `TOWER_HP_CROWN_PARADOX.md`: policy wins aggregate tower HP (+0.227) yet loses crowns (−0.170) and WR. Enemy princess taken in 39/130 wins (30%) but only 5/170 losses (3%). In 157/170 losses both enemy princesses are damaged and neither is taken. Crown histogram: −1 in 159/300. The policy cannot convert chip into crowns.

2. **The reward hypothesis is falsified.**
   `REWARD_DIAGNOSTIC.md`: Pearson r(return, win) = 0.967 (falsifier threshold was 0.6). Wins mean return 19.67, losses −14.29; 0/30 low-return wins, 0/30 high-return losses. The reward already ranks winning above losing almost perfectly. Changing reward weights would not fix the behavior; the policy is not being misled by the reward — it is failing to execute the winning behavior.

3. **The specific missing behavior is measurable in card usage.**
   `CARD_USAGE.md`: fireball 0.7% of plays (n=120) and musketeer 0.6% (n=111) — the deck's two finishing/answer tools — are dramatically underused, while cheap cycle cards (ice_spirit 20.1%, skeletons 20.0%, ice_golem 19.3%) dominate. Hog share is identical in wins and losses (18.9% vs 18.6%), so the problem is not the win condition itself but the absence of finishing/pressure tools around it.

4. **Brain's edge is exactly this conversion machinery, and it is not information.**
   `scripts/brain/config.json`: `finish_tower: 100.0` is Brain's highest single weight; `fireball_finish_hp: 0.052` via `_finisher()`/`spellinfo.can_finish` fireballs a princess one spell from falling; `_attack_lane()` concentrates on the weaker tower when `abs(left−right) ≥ 0.12`; hog scoring includes `+6.0*(1.0 − min_enemy_hp)` concentrating on the weakest tower.
   `BRAIN_INFORMATION_ADVANTAGE.md`: tower HP fractions, hand, next card, board, and elixir are ALL already in the policy's observation. PPO can in principle compute fireball lethality (fireball ≈ 32% of a princess tower; scalars 5–6 give exact enemy tower fractions). Brain's advantage over the policy on this axis is decision quality and memory, not hidden information.

5. **It is not exploration collapse, elixir leak, or late-game passivity alone.**
   `PPO_HEALTH.md`: tail entropy 0.11–0.35, KL well under target — healthy. `ELIXIR_ANALYSIS.md`: time-at-10 is 0.1%, no leak. But `ENTROPY_STUDY.md`: hold rate 87.2%, and entropy_coef 0.03 over ~4.4M steps against a huge action space (2321) leaves rare-but-critical action classes (fireball on a low tower, musketeer answers) under-explored. A policy that almost never tries fireball in finishing positions never receives the crown-conversion reward signal that would reinforce it.

## Chosen intervention

**Raise entropy_coef from 0.03 to 0.10 for the first ~2M steps of variant training, then anneal linearly to 0.03 by ~4M steps.**

Everything else is held constant: same init (`tmp/rl/clone_pilot.pt`), same network, same reward weights, same observation, same opponent mix, same seeds.

## Why this and not the alternatives

- **Reward shaping**: falsified (r = 0.967). The user's directive explicitly forbids defaulting to it.
- **Observation enrichment (e.g. fireball-lethality flag)**: the underlying data (enemy tower fractions) is already in the obs; a derived flag adds convenience, not information, and risks teaching the net to read a shortcut rather than learn the board. Not the root cause.
- **Recurrent memory / history**: `BRAIN_INFORMATION_ADVANTAGE.md` shows Brain's real information edge is temporal (opponent elixir estimate, cycle tracking). That is a legitimate Sprint 5 candidate but is a large architectural change; one intervention at a time, and the conversion failure is measurable without it.
- **PPO schedule change (entropy)**: directly targets the measured mechanism — under-explored finishing actions. Minimal, reversible, cheap to test. If the policy explores fireball/musketeer use in finishing positions, the aligned reward (r = 0.967) will reinforce it; no reward change needed.

## Hypothesis

The plateau at 43.3% is maintained by insufficient exploration of high-value, low-frequency action classes (spell finishes, musketeer answers). Increasing exploration pressure will raise fireball/musketeer usage toward their useful share, convert more damaged towers into crowns, and lift Brain WR above 43.3%.

## Expected delta

+3 to +6 percentage points vs Brain (target ≥ 46%, stretch ≥ 49%) at 4.5–6M steps, same seed 8000, 300 games. Secondary: crown_diff moves toward 0 or positive; enemy-princess-taken rate in losses rises above 3%; fireball share rises above ~2%.

## Falsifiers

- Abort gate: variant Brain WR ≤ 38.3% (baseline −5pp) at the 1.5M checkpoint → abort, revert to baseline as final candidate.
- Final reject: 300-game WR within CI overlap of 43.3% [37.8–49.0] with no secondary gain (crown_diff, tower-conversion rate, fireball usage).
- Diagnostic falsifier: if variant fireball/musketeer usage stays < 1.5% despite higher entropy, the exploration hypothesis is wrong and the bottleneck is representation/memory → recommend Sprint 5 (recurrent policy or history stack).

## Controls

Same init checkpoint, same hyperparameters except entropy_coef schedule, same opponent mix, identical comparison seeds (COMPARE_SEED=8000), same eval protocol (greedy, no_grad).
