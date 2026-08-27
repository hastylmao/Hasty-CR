# Sprint 2 Verified Baseline

Recorded: 2026-08-24T09:58:51+05:30
Git HEAD: `1dc9e6dbbc97bf3f2c04ff8b9045dfa66ee7577`

## Independent verification

- Full suite: `1445 passed, 1 skipped, 2 xfailed in 386.04s`.
- Focused calibration/capture/determinism selection: `35 passed in 12.17s`.
- Catalog validation: PASS; 70 scenarios, 11 categories, 56 train, 14 validation, zero errors.
- Card resolution: all scenario deck/action identifiers resolve against current HastyCR game data.
- Determinism: two independent simulations of `sprint5_001_arena` produced identical normalized SHA-256 `80ba57326b5b851656f53c09165fbc5126229fc44220869f5392bebb6ce1a03b`.
- Fixture integrity: all file hashes match `calibration/fixtures/fixture_digests.json`; normalized simulator fixture digest is `e35e14103e1f75770b592756a769aa55d29ce6304e86811e4e8abef2bf5d1890`.
- Compilation: `python -m compileall -q sim tools scripts` passed.
- Patch hygiene: `git diff --check` passed; only the existing `.gitignore` LF/CRLF warning was emitted.
- Reference safety: ignored `_references/apk_analysis/inventory.json` and `_references/statsroyale/gamedata-v5.json` remain ignored.

## Readiness

`python -m sim.readiness` correctly exited nonzero with:

- `RL NOT READY`
- eight source graphs implemented with named measurement approximations;
- missing live probe matrix categories: `building_contact`, `map_anchors`, and `troop_contact`.

The calibration gate also records `NOT_READY`, no scalar accuracy claim, and no accepted measured category evidence. Real measured Clash trace count is **ZERO**.

## Performance

Fresh 20-match BrainPolicy benchmark:

- 18.4 seconds
- 1.1 matches/s
- 4,734 ticks/s
- 5W/15L/0D
- crowns 6-17

The prior sprint's final benchmark was 17.1 seconds and 5,093 ticks/s, while its original baseline was also 18.4 seconds at 4,742 ticks/s. The fresh result reproduces the original baseline closely. This short run is retained as a host/runtime throughput observation, not a strategy or optimization conclusion.

## Data-hash note

A fresh aggregate over the current tracked/working `data/` tree excluding `data/validation/` produced `68e2215edd12592ac3ffc05e190201dd37898a00aa5b972dc811a29b7568411c` across 16 files. This is not directly comparable to Sprint 1's recorded `0e6d28...` checkpoint because the original manifest construction and working-tree population are not fully retained. Versioned calibration artifacts therefore continue to use their own explicit hashes rather than inferring a regression from this aggregate.

## Working-tree ownership

The workspace remains intentionally dirty. Pre-existing modified files were not overwritten:

- `scripts/brain/config.json`
- `scripts/brain/learned.json`
- `scripts/brain/matchups.json`
- `sim/engine.py`
- `tests/test_sim_engine.py`

Sprint 1 and Sprint 2 artifacts remain untracked. No reset, cleanup, branch, or commit was performed.
