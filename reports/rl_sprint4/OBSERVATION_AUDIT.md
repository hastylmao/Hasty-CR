# Observation Audit — Sprint 4

**Key Finding:**
- Observation is 8 planes (ally/enemy units, HP, air, buildings) + 47 scalars. Missing vs Brain: opponent elixir estimate, building timers, cycle/answer_ready, precise HP beyond binned planes.
- Whether this gap explains the paradox is unproven — reward shaping is higher prior.

**Limitation:** No ablation (e.g., train with oracle opponent elixir) to quantify gap.

| Missing signal | Impact hypothesis |
|---|---|
| Opponent elixir | mis-timed pushes |
| Building timers | poor cannon/musketeer answers |
| Cycle order | suboptimal next-card play |

