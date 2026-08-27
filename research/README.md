# External-reference research

This directory is the clean-room output for overnight fidelity sprint task #2. It records observations about external projects without copying their implementation code, schemas, or assets into HastyCR.

## Evidence policy

- **Verified fact** means directly observed at the pinned local revision or in the immutable web snapshot.
- **Project claim** means stated by an upstream README or documentation and not independently reproduced here.
- **Inference** means a clean-room architectural interpretation that requires HastyCR-specific validation.
- Reference simulators and extracted/historical data are comparative evidence, never ground truth for live Clash Royale mechanics.
- No simulator code was reused and no simulator behavior was changed.

## Deliverables

- [Licensing and provenance](REFERENCE_LICENSES.md)
- [Web evidence](WEB_EVIDENCE_LOG.md)
- [CRForge analysis](crforge_analysis.md)
- [Clash Royale Suite analysis](clash_royale_suite_analysis.md)
- [Jason simulator analysis](jason_sim_analysis.md)
- [SamDickson simulator analysis](samdickson_analysis.md)
- [Historical protocol architecture](protocol_architecture_notes.md)
- [Berkan study-only notes](berkan_notes.md)
- [Simulator comparison](simulator_comparison.csv)
- [Shared physics matrix](shared_physics_matrix.md)
- [Event-order audit](event_order_audit.md)
- [cr-csv schema inventory](cr_csv_schema_inventory.md)
- [cr-csv relationship graph](cr_csv_relationship_graph.md)
- [Historical data gems](historical_data_gems.md)
- [StatsRoyale snapshot](statsroyale_snapshot.md)

## Scope and blockers

All ten requested repositories were inspected at exact HEADs. No isolated cross-simulator scenario run was attempted because scenario, coordinate, card-level, and timing normalization are not shared; comparing unnormalized outputs would manufacture precision. StatsRoyale was retrieved successfully, but its publisher provenance and relation to an official game version remain unverified.