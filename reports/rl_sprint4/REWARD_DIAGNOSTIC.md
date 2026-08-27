# Reward Diagnostic — Sprint 4

**Key Finding:**
- Mean return: wins 19.67 vs losses -14.29 (gap +33.97).
- Return/win Pearson r = 0.967. Reward is aligned (r≥0.6) — paradox likely not a pure reward bug.
- Low-return wins: 0/30 bottom of return; High-return losses: 0/30 top of return.

**Limitation:** Return is shaped (tower 10 + crown 3 + win 10); decomposition into shaping vs terminal not separated.

| Stat | Value |
|---|---|
| Wins mean return | 19.67 |
| Losses mean return | -14.29 |
| Pearson r(return, win) | 0.967 |
| Falsifier threshold | 0.6 |
