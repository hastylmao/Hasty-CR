# Calibration recording campaign

This campaign is ordered by information value and safety. It records evidence; it does not retune simulator constants during capture.

1. **Arena and time base:** record empty-arena landmarks, both seats, fixed screen configuration, frame timestamps, and bridge/river geometry. Repeat twice per seat.
2. **Single-unit movement:** Knight, Giant, Hog Rider, Balloon, and Minions from mirrored legal placements. Capture spawn, route, bridge crossing, stop, and tower contact.
3. **Targeting:** Musketeer versus ground/air distractors; Cannon/X-Bow versus Hog/Giant/Balloon. Vary one placement coordinate at a time.
4. **Building pulls:** execute placement grids for Hog/Cannon, Giant/Cannon, Balloon/Cannon, and a neutral obstacle/map control. Record accepted/rejected cells and the resulting route/target sequence.
5. **Combat timing:** Knight/Mini P.E.K.K.A trades, Musketeer shots, Fireball/Log impacts, and simultaneous lethal boundaries. Record launch, impact, damage, death, and next-target timestamps.
6. **Collision and knockback:** Bowler, Log, Fisherman, and Tornado against controlled formations. Capture pair identities, overlap, displacement, and recovery.
7. **Spawning and special mechanics:** Minions and supported spawn/death effects, one mechanic per recording. Mark unsupported mechanics explicitly rather than inferring them.
8. **Held-out repetitions:** repeat each category with a new seed/placement and reserve the validation recordings before inspecting simulator comparisons.

Every session should include game build/version, device/emulator dimensions, orientation, capture settings, frame hashes, monotonic timestamps, operator notes, and an evidence ID. No recording is promotion evidence until the capture manifest passes validation and the category has held-out regression coverage.
