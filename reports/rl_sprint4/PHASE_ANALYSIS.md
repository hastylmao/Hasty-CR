# Match Phase Analysis — Sprint 4

**Key Finding:**
- Most tower damage occurs in mid/late game; early phases are low-event. OT behavior (if present) shows whether the policy can close.
- Phase segmentation reveals where the tower→crown conversion fails.

**Limitation:** Phases are wall-clock buckets, not game-state-aware (e.g., first crown taken). No win-conditioned split yet.

| Phase | Games reaching | Plays | Holds | Mean tower_diff delta in phase |
|---|---|---|---|---|
| 0-60s | 300 | 3457 | 32543 | -0.0256 |
| 60-120s | 300 | 2857 | 33143 | -0.0250 |
| 120-180s | 300 | 5863 | 30137 | +0.2321 |
| 180-240s | 214 | 3209 | 16263 | +0.0311 |
| OT 240s+ | 109 | 1855 | 5836 | +0.0649 |
