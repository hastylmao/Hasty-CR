# Data Delta

Static byte-container analysis only; no APK or native payload was executed, loaded, installed, launched, debugged, emulated, rebuilt, or decompiled. Counts and references do not establish runtime behavior.

CSV/TOML bodies and values are never reproduced. Decode, syntax, schema, keyed-row-set, normalized-keyed-value, opaque, and extension-identity outcomes are separate.

| APK A | APK B | Total extension/path identity | Parseable/path identity | Opaque/path identity | Identical | Unresolved | Value only | Normalized format | Added | Removed |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `clash-royale-mod-15-535-13-an1-com` | `master-royale-apk-v3-2729-1` | 0.000000 | 0.000000 | 1.000000 | 0 | 137 | 4 | 23 | 11 | 421 |
| `clash-royale-mod-15-535-13-an1-com` | `nr-15-535-13-infinity-da5a0dc4` | 0.560660 | 0.560660 | 1.000000 | 476 | 97 | 12 | 0 | 155 | 0 |
| `clash-royale-mod-15-535-13-an1-com` | `nr-15-535-13-infinity-da5a0dc4-1` | 0.560660 | 0.560660 | 1.000000 | 476 | 97 | 12 | 0 | 155 | 0 |
| `master-royale-apk-v3-2729-1` | `nr-15-535-13-infinity-da5a0dc4` | 0.000000 | 0.000000 | 1.000000 | 0 | 137 | 4 | 23 | 576 | 11 |
| `master-royale-apk-v3-2729-1` | `nr-15-535-13-infinity-da5a0dc4-1` | 0.000000 | 0.000000 | 1.000000 | 0 | 137 | 4 | 23 | 576 | 11 |
| `nr-15-535-13-infinity-da5a0dc4` | `nr-15-535-13-infinity-da5a0dc4-1` | 1.000000 | 1.000000 | 1.000000 | 740 | 0 | 0 | 0 | 0 | 0 |

## Unsupported proprietary inventory

The ignored machine inventory records extension, detected magic, size, SHA-256, path, and `unsupported` status for `.sc`, `.sctx`, `.scw`, `.scdb`, `.rmat`, `.ktx`, `.glb`, and `.bank`.
