# Memory Hypothesis — Sprint 4

**Key Finding:**
- Current obs is Markov-ish per tick but lacks history (no frame stack, no RNN). First-divergence shows when trajectories split; if divergence is predictable from history but not from single frame, memory would help.
- Prior: memory is secondary to reward shaping; not the primary bottleneck.

**Limitation:** No recurrent vs feedforward ablation; hypothesis is unfalsified.

