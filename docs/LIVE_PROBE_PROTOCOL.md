# Live simulator calibration protocol

Ordinary matches are context, not physics proof.  The simulator must only use
a recording to calibrate an interaction when the clip identifies the cards and
levels, deployment positions, frame rate, relevant frame range and a single
observable outcome.

## Existing recordings

`scripts/ingest_live_recordings.py` catalogs the supplied MuMu recordings as
`contextual_only`. They contain realistic cards and useful visual reference,
but concurrent units/spells and unknown tap coordinates mean they must not set
collision, pathing or projectile constants.

Run the cataloguer after adding recordings:

```powershell
.\.venvs\buildabot\Scripts\python.exe scripts\ingest_live_recordings.py `
  "C:\Users\aksha\Documents\MuMuSharedFolder\VideoRecords\recordings"
```

The catalogue refresh merges with the existing probe manifest rather than
discarding review entries. A capture retains a `controlled` classification only
when its SHA-256 is unchanged; replacing/editing a video automatically returns
it to contextual status until it is reviewed again.

Before reviewing or accepting a frame range, recheck the source files:

```powershell
.\.venvs\buildabot\Scripts\python.exe scripts\verify_live_probe_assets.py
```

To inspect a candidate observation by source-frame number, extract it without
altering the source video:

```powershell
.\.venvs\buildabot\Scripts\python.exe scripts\extract_probe_frames.py `
  "C:\Users\aksha\Documents\MuMuSharedFolder\VideoRecords\recordings\Clash Royale(3).mp4" `
  900 990
```

The created `provenance.json` maps each PNG back to its original frame. Review
the result before adding any observation to the accepted probe manifest. The
extractor verifies that the declared range fits the source video and that every
requested frame was exported; do not use manually copied screenshots instead.

For a long ordinary gameplay recording, generate an unreviewed motion index
first. It finds busy arena segments but intentionally does not label cards or
claim mechanics. Each indexed clip carries its source SHA-256, so discard and
re-index the queue if the recording changes:

```powershell
.\.venvs\buildabot\Scripts\python.exe scripts\index_recording_motion.py `
  "C:\Users\aksha\Documents\MuMuSharedFolder\VideoRecords\recordings"
```

## Controlled capture checklist

- Record at 60 fps if available; do not crop, speed up or add transitions.
- Use Training Camp/friendly battle with no unrelated cards in the lane.
- Write the card level, arena skin, side, and exact deployment tile/relative
  position in the clip name or adjacent notes.
- Capture two seconds before deployment through two seconds after the observed
  hit, separation, miss, or despawn.
- One hypothesis per clip. Repeat each experiment three times.

## Required matrix

| Category | Minimum controlled observations |
|---|---|
| `map_anchors` | tower centres, bridge centres, river bounds, deploy boundary |
| `troop_contact` | same-size swarm, small+medium, medium+large, all near King Tower and open lane |
| `building_contact` | troop route/contact around Cannon, Tesla and Goblin Cage |
| `projectile_timing` | stationary and moving targets for a homing and a non-homing shot |
| `spell_timing` | cast-to-impact and final target position for Fireball, Arrows, Zap and Tornado |

For a matching simulator scenario, construct `Battle(trace_contacts=True)`.
`battle.contact_trace` records each existing building/troop separation with
source positions, required collision gap and resolved displacement. Non-homing
launch records now also retain speed, range and collision radius in
`battle.unmodelled_projectiles`. Compare these traces to the accepted frame
ranges before changing physics constants.

The trace also marks `engaged_contact_exempt` when two opposing units overlap
but the current approximation deliberately lets their mutual target engagement
touch. This is the key trace entry for a two-troop-at-King-Tower experiment:
it distinguishes an observed push from the simulator's present engagement
exception before anyone changes separation or hitbox logic.

For each accepted observation, add an entry to `accepted_evidence` in
`data/validation/live_probes.json` with: `capture_id`, `start_frame`,
`end_frame`, `cards_and_levels`, `deployment`, `observed_result`, and the test
that protects the result. Name that test exactly as
`tests/test_file.py::test_name`; readiness checks that the file and function
exist, and that the evidence range fits the catalogued source clip. An accepted
capture must be marked `controlled`, provide its source path and SHA-256, and
be at least 50 fps. The supplied 30 fps gameplay is deliberately ineligible.
`sim.readiness` validates each of these fields; a capture catalog or a bare
`completed` label cannot unlock training. Set the category status to
`accepted` and add it to `completed` only after the associated regression test
passes.

## Nine mechanic-specific captures

After the shared matrix, make isolated clips for the nine files shown by
`python -m sim.action_audit`: Executioner Evo, Goblin Drill Evo, Princess Evo,
Hero Balloon, Hero Magic Archer, Firecracker, Hero Mega Minion, Monk and Hero
Wizard. Measure the exact procedure named in that audit—not a similar-looking
interaction.
