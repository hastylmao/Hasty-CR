# PPO Health — Sprint 4

**Key Finding:**
- Entropy tail (last 500 logs): 0.110 / 0.228 / 0.350 (min/mean/max) — not collapsed.
- KL tail: 0.00010 / 0.00120 / 0.00670 — rarely hits target_kl 0.02, so clipping is not binding; plateau is not a KL constraint.
- Value loss tail: 0.77 / 2.81 / 14.78.
- Tail return (last 500): 18.18 (last), mean last 100: 17.29.
- **Diagnosis:** Plateau is opponent/reward ceiling, not exploration collapse (entropy healthy, KL slack).

**Limitation:** No gradient norm or explained-variance; only log fields parsed.

Header: `2026-08-24 22:02:05 initialised from tmp\rl\clone_pilot.pt (weights only, step counter at 0)`

| Metric (tail 500) | min | mean | max |
|---|---|---|---|
| entropy | 0.1100 | 0.2281 | 0.3500 |
| kl | 0.00010 | 0.00120 | 0.00670 |
| value_loss | 0.770 | 2.806 | 14.780 |

Total log lines: 4802 Steps: 1280 → 6000640
