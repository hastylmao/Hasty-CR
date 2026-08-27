# Brain Information Advantage — Sprint 4

Classifies every input the hand-written Brain (`scripts/brain/policy.py` + `sim/runner.py:BrainPolicy`) uses, relative to what the PPO policy's observation (`sim/env.py:observe()` — 8 planes 32×18 + 47 scalars) provides.

Categories:
- **SAME AS PPO** — Brain's value is derived from information the policy also receives.
- **OBSERVABLE BUT NOT PROVIDED** — in principle visible to a human player from the game screen, but absent from the current obs.
- **ESTIMATABLE FROM HISTORY** — reconstructable from a sequence of observations (requires memory; not present in a single frame).
- **PRIVILEGED SIM STATE** — only available because Brain is called with the simulator's internal `GameState`/`build_state`; not observable in a real game.
- **HEURISTIC** — not information per se; a derived rule/estimate Brain computes from other inputs.

## Classifications

| Brain input | Category | Notes |
|---|---|---|
| Own elixir (exact float) | SAME AS PPO | scalar 0 (scaled /10000). |
| Own hand (4 cards) | SAME AS PPO | scalars 7–38 one-hot. |
| Own next card | SAME AS PPO | scalars 39–46 one-hot. |
| Elapsed time / multiplier | SAME AS PPO | scalars 1–2. |
| Own 2 princess tower HP | SAME AS PPO | scalars 3–4 (exact fractions). |
| Enemy 2 princess tower HP | SAME AS PPO | scalars 5–6 (exact fractions). King tower not in either. |
| Unit positions + counts | SAME AS PPO | planes 0/1 (ally/enemy unit presence). |
| Unit HP per tile | SAME AS PPO | planes 2/3 (HP/1000 binned per tile; Brain has exact per-entity HP — slightly higher precision but same underlying signal). |
| Air units | SAME AS PPO | planes 4/5. |
| Buildings | SAME AS PPO | planes 6/7. |
| Opponent elixir estimate | ESTIMATABLE FROM HISTORY | Brain's `EnemyEconomy` tracks spend/regen. A human estimates it from when the opponent played; a feedforward net cannot without history. **Deliberately withheld** (not observable in real game). |
| Opponent cycle / `answer_ready()` | ESTIMATABLE FROM HISTORY | `OpponentModel` counts plays since each card seen. Requires remembering opponent placements over time. Not reconstructable from one frame. |
| Own cycle state / next-card timing | SAME AS PPO (partial) | Next card is in obs; exact elixir-to-next is derivable from scalar 0. Brain's `tracker`/cycle bookkeeping adds little beyond what hand+next already give. |
| Per-entity velocity / `Track.predict` intercepts | PRIVILEGED SIM STATE | Derived from exact entity positions across sim ticks; a screen-only observer sees motion but not the precise velocity vectors Brain's `predict_seconds` extrapolation uses. |
| Threat score / threat bucket / threat lane | HEURISTIC | Score Brain computes from positions+HP (its `threat_score`). Not raw information. |
| `contained` flag (defence already answered) | HEURISTIC + ESTIMATABLE FROM HISTORY | Derived from committed defenders vs incoming threats; partly state, partly bookkeeping of recent plays. |
| `last_hog_lane`, placement memory | ESTIMATABLE FROM HISTORY | Brain remembers what it just did. Policy has no history. |
| `cannon_spot` / `hog_spot` lane geometry | HEURISTIC | Fixed positional rules (river/bridge tiles). No information content. |
| Card costs / spell finish tables (`spellinfo`) | SAME AS PPO (static knowledge) | Constants; both could know them. Policy would have to learn them. |
| Exact per-entity HP (not binned) | PRIVILEGED SIM STATE (minor) | Obs has HP/1000 per tile; Brain reads entity HP exactly. Precision gap, not an information gap. |

## Verdict

Brain's genuine information advantages are exactly two:

1. **Opponent elixir estimate** — ESTIMATABLE FROM HISTORY, deliberately withheld from the policy. Giving it to the policy as an oracle would violate the real-game-observability constraint; a history-based estimator is the transfer-safe route, but that is a memory intervention, not an observation one.
2. **Temporal memory** (opponent cycle/`answer_ready`, own last play, intercept prediction from motion) — ESTIMATABLE FROM HISTORY / partly PRIVILEGED (velocity). A feedforward policy on single frames structurally cannot access any of it.

Everything else is either the SAME AS PPO (Brain's edge there is *decision quality on identical information*), HEURISTIC, or a minor precision difference. In particular: **tower HP fractions, hand, next card, board, elixir are all already in the policy's observation.** Brain's lane-concentration and tower-finishing behavior comes from its scoring rules and memory, not from hidden information. This directly informs `INTERVENTION_1_DECISION.md`.
