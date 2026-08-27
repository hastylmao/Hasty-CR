# Web evidence log

Retrieval dates are UTC. Web content is supporting evidence, not official mechanics truth.

| Retrieved UTC | URL | Evidence retained | Supported claim | Version signal | Confidence / caveat |
|---|---|---|---|---|---|
| 2026-08-23T19:38:24Z | https://cdn.statsroyale.com/gamedata-v5.json | Immutable body at [gamedata-v5.json](../_references/statsroyale/gamedata-v5.json), response at [headers](../_references/statsroyale/gamedata-v5.headers.txt) | Endpoint returned JSON with `meta.fingerprint` and categorized game-data objects | HTTP `Last-Modified: Mon, 04 May 2026 21:25:16 GMT`; fingerprint `43bb649e3447053cbbad350a6b74ed9cecf557a7` | High for bytes/HTTP observations; low for official provenance or game-version mapping |
| 2026-08-23 | https://github.com/voonhous/crforge | Local Git clone pinned in [license record](REFERENCE_LICENSES.md) | Repository identity and upstream project claims | Exact HEAD recorded | High for local source facts; project accuracy claims unverified |
| 2026-08-23 | https://github.com/nguiaSoren/clash-royale-suite | Local Git clone pinned in [license record](REFERENCE_LICENSES.md) | Repository identity and project-stated simulator design | Exact HEAD, no tags | High for local source facts; benchmark/fidelity claims not reproduced |
| 2026-08-23 | https://github.com/smlbiobot/cr-csv | Local Git clone and tag history | Historical schema and tag chronology | Tags 2.0.1 through `2020-07-07-balance`; HEAD commit dated 2023-03-28 | High for Git/schema facts; unknown for official provenance |
| 2026-08-23 | https://creativecommons.org/licenses/by-nc-nd/4.0/ | URL named by Berkan README; not used as source code | Meaning of declared license family | 4.0 | Declaration verified locally; no standalone license file |

## Interpretation boundary

The repository URLs identify public origins. Claims about tick rates, performance, completeness, or fidelity remain **project claims** unless this report explicitly says they were verified from code. The CDN snapshot is a third-party publication and must not automatically overwrite HastyCR data or become a calibration oracle.