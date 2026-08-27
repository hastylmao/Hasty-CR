# Placement Heatmaps — Sprint 4

**Key Finding:**
- Lane bias and depth reveal whether the policy commits to a lane or spreads.
- Heatmaps are textual (counts per lane half); PNG omitted for lean.

**Limitation:** No per-card heatmap image; no conditioning on game state (e.g., defense vs offense).

| Card | n | Left lane (x<9) | Right lane (x>=9) | Avg y (depth) |
|---|---|---|---|---|
| cannon | 3249 | 1995 (61%) | 1254 (39%) | 20.0 |
| fireball | 120 | 83 (69%) | 37 (31%) | 18.3 |
| hog_rider | 3233 | 1609 (50%) | 1624 (50%) | 16.0 |
| ice_golem | 3329 | 1241 (37%) | 2088 (63%) | 19.4 |
| ice_spirit | 3466 | 1142 (33%) | 2324 (67%) | 19.3 |
| musketeer | 111 | 64 (58%) | 47 (42%) | 23.7 |
| skeletons | 3456 | 1072 (31%) | 2384 (69%) | 19.9 |
| the_log | 277 | 106 (38%) | 171 (62%) | 21.7 |
