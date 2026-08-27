# Brain Audit — Sprint 4

**Key Finding:**
- Brain (hand-written policy) uses full match state via `brain.policy.Brain` — it sees exact HP, full deck, rule-based elixir management, and `cannon_spot`/`hog_spot` lane logic. The learned policy sees only 8 planes (32×18) + 47 scalars (elixir, elapsed, regen, 4 tower fractions, hand/next one-hots). Opponent elixir is deliberately withheld (not observable in real game, per `sim/env.py` docstring).
- Information advantage is by design (no oracle), not a bug.

**Limitation:** No per-decision comparison of Brain vs policy on same state; advantage is architectural, not measured move-by-move.

| Signal | Brain | Learned obs |
|---|---|---|
| Own elixir | yes (exact) | yes (scalar 0) |
| Opponent elixir | estimated via Brain economy model | not observed (must infer from planes) |
| Tower HP | exact | 4 scalars (our 2 + their 2 princess fractions) |
| Unit HP/pos | exact from `match.battle.entities` | binned planes (count + HP/1000) |
| Hand/next | exact | one-hot 4×8 + 8 |
| Timers / cycle | internal Brain state | not observed |

