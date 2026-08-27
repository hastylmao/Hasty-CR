# Physics and targeting diagnostics

HastyCR now exposes an opt-in `DiagnosticSink` for calibration probes. This is instrumentation only: no mechanics or calibration constants were changed.

## API

Attach `sim.diagnostics.DiagnosticSink` as `Battle(diagnostics=sink)` or set `battle.diagnostics = sink` before the first event to capture. `None` is the feature flag and default. `SimTraceAdapter(trace_diagnostics=True)` attaches a sink automatically and converts its records to normalized simulator-only `TraceEvent` values.

Every record includes `event_type`, `time_ms`, `tick`, phase-local `order`, `phase`, stable source/target UIDs, source/target millitile positions, `value`, `reason`, and `state`; event-specific values live in `metadata`. `DiagnosticSink.digest()` computes a canonical SHA-256 digest for repeated-run checks.

## Coverage

- `target_acquired` / `target_lost`: visible-nearest, fallback-building, sniper, taunt, and no-valid-candidate explanations.
- `attack_timing` / `attack`: windup, cooldown, and completed hit-cycle state.
- `projectile_launch` / `projectile_impact` / `projectile_lost`: launch snapshot, arrival, homing target loss, and positional splash after target loss.
- `movement`: prior position, waypoint, step, and actual displacement.
- `collision`: required gap, overlap correction, pair order, normal, and before/after positions. Exact coincidence reports the existing deterministic `(1, 0)` normal.
- `damage`, `death`, `spawn`, and `cleanup`: stable lifecycle identities and tick phase.
- `phase`, `tick_start`, and `tick_end`: explicit ordering audit markers.

The legacy `trace_contacts` / `contact_trace` API and all existing fields remain unchanged. When diagnostics are disabled, phase and event branches only test `Battle.diagnostics is not None`; no diagnostic dictionaries, lists, strings, or per-tick snapshots are allocated.

These events describe HastyCR's current procedure and simulator-only assumptions. They do not claim agreement with observed Clash Royale behavior or establish calibration accuracy.
