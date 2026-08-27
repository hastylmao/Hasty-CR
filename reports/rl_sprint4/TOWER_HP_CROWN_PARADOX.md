# Tower-HP / Crown Paradox — Sprint 4

**Key Finding:**
- Policy wins aggregate tower HP (tower_diff +0.23) but loses crowns (-0.17) and win rate (43.3%). The mechanism is **spread chip damage**: the policy damages both enemy princess towers without finishing either, while Brain concentrates to take one.
- Losses with positive tower HP: 65/170 (38%) of all losses — the paradox is not a tail artifact, it is the modal loss.
- Among games where policy leads on tower HP, it still only wins 66% — tower lead does not convert.

**Limitation:** Analysis uses remaining tower fractions (sum of 2 princesses) as recorded in `scalars[3:7]`; king tower HP not in that sum. Crown snowball (opened deployment strip) not directly measured.

## Evidence

| Metric | Wins (n=130) | Losses (n=170) | All (n=300) |
|---|---|---|---|
| Mean tower_diff (ours - theirs) | +0.718 | -0.149 | +0.227 |
| Mean crown_diff | +0.831 | -0.935 | -0.170 |
| Mean spread ratio min/max damage | 0.540 | 0.555 | — |
| At least one enemy princess taken | 39/130 | 5/170 | — |
| Both enemy princesses damaged | — | 162/170 | — |
| Both damaged, neither taken (spread) | — | 157/170 | — |

### Crown-margin histogram

| Crown diff (ours - theirs) | Count |
|---|---|
| -1 | 159 |
| +0 | 33 |
| +1 | 108 |

### Mechanism hypothesis (falsifiable)

**Hypothesis:** Reward shaping tower 10 + crown 3 + win 10 rewards spread chip equally to concentrated takes. Dealing 0.5 to each princess (total damage 1.0) yields shaping reward 10, same as dealing 1.0 to one princess (also 10) plus only +3 crown bonus — a 30% premium insufficient to offset the extra risk/effort of finishing a tower. The policy learns the low-risk spread strategy; Brain's rule-based `cannon_spot`/`hog_spot` concentrates and takes crowns.

**Predictions if true:**
1. Losses show high spread ratio and both enemy princesses damaged without a take.
2. Episode return correlates weakly with winning (reward misaligned).
3. Increasing crown/win weight or adding elixir-trade shaping improves crown conversion.

**Falsifier:** If `REWARD_DIAGNOSTIC` shows return/win correlation ≥0.6 and wins already have clearly higher return than losses, the reward is aligned and the paradox must be explained elsewhere (e.g., observation gap or execution failure in endgame).

### Supporting detail

- Games with tower_diff > 0: 193 total, win rate 66.3% — tower HP lead is not sufficient.
- Paradox losses (tower_diff > 0 but still lost): 65 games, e.g. seeds [9000, 10000, 12000, 25000, 35000].
- Loss spread ratio 0.555 vs win spread 0.540: losses are more spread (if loss > win, consistent with hypothesis).
