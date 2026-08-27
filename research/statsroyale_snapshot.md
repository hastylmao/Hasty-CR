# StatsRoyale gamedata-v5 snapshot

## Retrieval record

- URL: https://cdn.statsroyale.com/gamedata-v5.json
- Retrieval completed: `2026-08-23T19:38:25.8327346Z` (local file completion); response `Date` was `2026-08-23T19:38:24Z`.
- Immutable body: [gamedata-v5.json](../_references/statsroyale/gamedata-v5.json)
- Response headers: [gamedata-v5.headers.txt](../_references/statsroyale/gamedata-v5.headers.txt)
- HTTP: `200 OK`, `Content-Type: application/json`, declared `Content-Length: 3001441`.
- Size: `3,001,441` bytes.
- SHA-256: `d67cebd4bbf9624a75e3c4a1fdb3a1284a285bf5c1620e3d84fab917f34139d0`.
- HTTP `Last-Modified`: `Mon, 04 May 2026 21:25:16 GMT`.
- ETag: `27cabac2d7f90b98037014a5dbc5bc80`.
- JSON parsed successfully with Python.

## Schema observations

Top-level keys are `meta` and `items`. `meta.fingerprint` is `43bb649e3447053cbbad350a6b74ed9cecf557a7`. `items` contains:

| Collection | Count |
|---|---:|
| `spells` | 147 |
| `arenas` | 298 |
| `gameModes` | 505 |
| `rarities` | 6 |
| `badges` | 185 |
| `expLevels` | 90 |
| `clanLeagues` | 12 |
| `regions` | 262 |

The 147 spell/card rows have 147 unique non-null IDs and 147 unique names. Their declared `source` breakdown is 100 `spells_characters`, 16 `spells_buildings`, 27 `spells_other`, and 4 `support_cards`. Rows can embed nested hero, evolution, summon-character, projectile, buff, or other stat data; therefore “147 cards” is a top-level row count, not a count of every nested entity/variant.

## Provenance and use boundary

The bytes and HTTP facts are verified. Publisher methodology, licensing, official authorization, game build mapping, freshness of every nested field, unit conversion, and completeness are not verified. The fingerprint is an opaque source field, not independently proven to identify an official release. Treat this snapshot as third-party comparative evidence only: do not redistribute it, automatically ingest it into production, or use it as ground truth without a separate provenance/license and field-level validation review.