# Calibration backlog

Priority is based on expected impact and ability to isolate a mechanic.

| Priority | Evidence gap | Next capture | Promotion blocker |
|---|---|---|---|
| P0 | Building pull maps | Four placement grids for Hog/Cannon, Giant/Cannon, Balloon/Cannon, generic obstacle | No measured building_pull evidence |
| P0 | Clock and event order | Simultaneous damage, projectile impact, death, spawn, and stun expiry | No measured combat_timing evidence |
| P0 | Coordinate/arena mapping | Empty arena landmarks from both seats and bridge widths | No measured arena/pathing evidence |
| P1 | Target selection | Musketeer, Cannon, X-Bow distractor sweeps | No measured targeting evidence |
| P1 | Collision and push | Knight/Mini P.E.K.K.A overlap; Bowler/Log/Tornado controlled pushes | No measured collision/knockback evidence |
| P1 | Projectile timing | Fireball and Log launch/impact/area boundaries | No measured projectiles evidence |
| P2 | Spawning | Minions and supported death/spawn controls | No measured spawning evidence |
| P2 | Special mechanics | Fisherman and any explicitly supported mechanic, one variable per run | No measured special_mechanics evidence |

Synthetic fixtures support CI determinism and metric plumbing only. They cannot close any evidence gap or satisfy a readiness gate. Do not promote a parameter based on a simulator trace, reference hypothesis, or aggregate scalar score.
