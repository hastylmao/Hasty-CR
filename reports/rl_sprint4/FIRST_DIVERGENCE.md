# First Divergence — Sprint 4

**Key Finding:**
- Compares mean tower_diff trajectory of wins vs losses to find earliest divergence bucket.

**Limitation:** Proxy is aggregate tower_diff, not win-probability model. No matched-pair analysis.

| Bucket (s) | Mean tower_diff wins | Mean tower_diff losses | Gap |
|---|---|---|---|
| 0-30 | +0.006 | -0.016 | +0.022 |
| 30-60 | +0.040 | -0.066 | +0.107 |
| 60-90 | +0.110 | -0.147 | +0.258 |
| 90-120 | +0.174 | -0.202 | +0.375 |
| 120-180 | +0.331 | -0.180 | +0.510 |
| 180-300 | +0.508 | +0.114 | +0.394 |
