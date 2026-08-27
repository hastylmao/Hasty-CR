# Sprint 2.5 Deterministic Command Replay Audit

Date: 2026-08-24
Status: **PASS — current HastyCR engine is command-replay deterministic under the declared contract**

This report proves reproducibility of the current HastyCR implementation. It
does **not** claim live Clash Royale fidelity.

## Answers

1. **Is HastyCR deterministic?** Yes, for a fixed simulator source revision,
   game-data hash, initial state, seed, and ordered command stream. The focused
   audit suite passed `61` tests, including the pre-existing determinism tests.
2. **Minimum reproduction information:** simulator revision, game-data hash,
   level/ruleset, seed, both ordered decks, fixed tick/rules configuration,
   initial elixir configuration, arena/map configuration, evolution/ability
   match flags, and timestamped player commands. The current replay schema
   stores this as `InitialState` plus `commands[]`.
3. **Is troop position continuously stored?** No. Position is derived by the
   engine. It appears only in non-authoritative checkpoint/digest output.
4. **Is target selection derived?** Yes. Candidate validity, sight, edge gap,
   fallback, retargeting, and UID tie-breaks are derived.
5. **Are projectile trajectories derived?** Yes. Launch, flight timing, target
   binding, impact, and delayed effects are derived from state and commands.
6. **Are spawns/deaths derived?** Yes. UID creation, death resolution, child
   spawns, cleanup, and lifetime expiry are derived.
7. **What RNG state is required?** The current engine requires the integer match
   seed because `Match` uses a local `random.Random(seed)` only to shuffle each
   initial deck queue. No unseeded battle RNG was found. Future RNG-bearing
   mechanics must record an explicit seed/state and consumption contract.
8. **Can command-only replay reconstruct the match?** Yes for the current
   supported command surface. `MatchReplay` contains no authoritative derived
   trajectory. Fresh matches reproduce the same checkpoint and final digests.
9. **Does it work across fresh Python processes?** Yes. Three subprocess runs
   with `PYTHONHASHSEED=random` produced the same final digest:
   `07d576aa5d1cecc61bd014019fa57d17ebd02d601ae3ffc10bf9e4802dc90291`.
10. **Known nondeterministic mechanics?** None found in the battle path. The
    maintenance boundary is that many engine scans rely on stable UID-driven
    dictionary insertion order. Equal-distance target/fallback/sniper choices
    now have explicit lower-UID tie-breaks. Policy/opponent randomness is
    external command generation and is not hidden engine state.

## Implementation

- `tools/calibration/command_replay.py` defines schema
  `hastycr-command-replay-v1`, canonical JSON, version/data hashes, commands,
  replay execution, state payload/digest, checkpoint collection, and
  first-divergence field reporting.
- `scripts/fidelity.py` exposes `record-command-replay` and
  `verify-command-replay`.
- `docs/DETERMINISTIC_REPLAY_CONTRACT.md` defines the required initial state,
  command-only architecture, derived-state boundary, RNG policy, historical
  command-stream relevance, and determinism-versus-calibration distinction.
- `reports/DETERMINISM_AUDIT.md` records the randomness, clock, UID, ordering,
  and filesystem audit classifications.
- `sim/engine.py` explicitly resolves equal-distance target, fallback-building,
  and sniper ties by lower UID.

## Recorded Demo

The clean CLI demo was generated with seed `37` and duration `60` ticks:

- Commands: `4`.
- Duration: `3000 ms`.
- Checkpoints: `61`.
- First divergence: `none`.
- Final digest: `07d576aa5d1cecc61bd014019fa57d17ebd02d601ae3ffc10bf9e4802dc90291`.
- Result: `deterministic replay PASS`.

Example:

```powershell
& ".venvs\buildabot\Scripts\python.exe" scripts\fidelity.py record-command-replay --output tmp\sprint2_5_demo.json --seed 37 --duration-ticks 60
& ".venvs\buildabot\Scripts\python.exe" scripts\fidelity.py verify-command-replay tmp\sprint2_5_demo.json
```

## Test Evidence

Focused command replay and baseline determinism:

- `61 passed in 158.39s` for `tests/test_command_replay.py`
  and `tests/test_sim_determinism.py`.
- `57 passed in 151.76s` for the command replay suite alone.
- The property/regression portion covers `50` deterministic seeds.
- The cross-process test executes the same replay in `3` fresh Python
  subprocesses with randomized hash seeds.
- Serialization test verifies authoritative replay JSON contains only schema,
  version/data identity, initial state, and command records; it contains no
  entities or trajectory fields.
- Ordering test rejects nonmonotonic command ticks.
- Digest test canonicalizes mappings and set contents.
- First-divergence test reports the divergent tick and state field.

Adjacent simulator/calibration regression selection also passed:

- `36 passed in 3.47s` for engine, calibration core/scenario/diagnostics, and
  legacy replay-calibration tests.
- `compileall -q sim tools scripts` passed.
- `git diff --check` passed; only existing line-ending warnings were emitted.

## Historical Checksum Note

The pinned historical `royale-proxy/cr-messages` reference describes
`EndClientTurn` as `tick`, `checksum`, and `commands[]`. HastyCR uses that only
as architectural context. Its SHA-256 state digest is independent and is not
Supercell's checksum algorithm.

## Scientific Boundary

The result proves reproducibility, not accuracy. A deterministic simulator can
reproduce incorrect targeting, pathing, projectile, collision, damage, or
spawn rules perfectly. HastyCR remains subject to the existing Sprint 2
boundary: `real_measurements=0` and RL readiness remains `NOT_READY`.

**Determinism = reproducibility. Calibration = fidelity. Both are required.**
