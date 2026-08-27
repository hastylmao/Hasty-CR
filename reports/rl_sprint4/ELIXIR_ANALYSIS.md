# Elixir Analysis — Sprint 4

**Key Finding:**
- Time at 10 elixir: 0.1% of decision ticks (76/135163). Leak indicates missed deployment windows.
- Avg elixir at play: 2.52. High value suggests holding too long; low suggests elixir dumping.
- Plays total: 17241 across 300 games (57.5 per game).

**Limitation:** No greedy re-evaluation; elixir leak estimated from tick snapshots only. No opponent elixir comparison (not in observation).

| Elixir at play | Count | Share |
|---|---|---|
| 0-2 | 6487 | 37.6% |
| 2-4 | 6683 | 38.8% |
| 4-6 | 3830 | 22.2% |
| 6-8 | 165 | 1.0% |
| 8-10 | 76 | 0.4% |

- Ticks at 10 elixir: 76 / 135163 (0.1%)
- Games with any leak tick: 11/300
