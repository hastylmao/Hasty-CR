# Subsystem Classification

Static byte-container analysis only; no APK or native payload was executed, loaded, installed, launched, debugged, emulated, rebuilt, or decompiled. Counts and references do not establish runtime behavior.

Allowed vocabulary: `UNCHANGED_SHARED_CLIENT`, `MODIFIED_CLIENT`, `PRIVATE_SERVER_SPECIFIC`, `CUSTOM_DATA`, `UNKNOWN`. Per-APK filename/package/data presence is not component provenance; only manifest branding may support `APPLICATION_SHELL: PRIVATE_SERVER_SPECIFIC`. Pair labels are exact path/hash identity or `UNKNOWN` without an official baseline.

## Per APK

| APK | Application shell | DEX client | Native client | Selected data | Proprietary assets |
|---|---|---|---|---|---|
| `clash-royale-mod-15-535-13-an1-com` | `PRIVATE_SERVER_SPECIFIC` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `master-royale-apk-v3-2729-1` | `PRIVATE_SERVER_SPECIFIC` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `nr-15-535-13-infinity-da5a0dc4` | `PRIVATE_SERVER_SPECIFIC` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `nr-15-535-13-infinity-da5a0dc4-1` | `PRIVATE_SERVER_SPECIFIC` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |

## Per pair

| APK A | APK B | DEX client | Native client | Selected data | Proprietary assets |
|---|---|---|---|---|---|
| `clash-royale-mod-15-535-13-an1-com` | `master-royale-apk-v3-2729-1` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `clash-royale-mod-15-535-13-an1-com` | `nr-15-535-13-infinity-da5a0dc4` | `UNKNOWN` | `UNCHANGED_SHARED_CLIENT` | `UNKNOWN` | `UNKNOWN` |
| `clash-royale-mod-15-535-13-an1-com` | `nr-15-535-13-infinity-da5a0dc4-1` | `UNKNOWN` | `UNCHANGED_SHARED_CLIENT` | `UNKNOWN` | `UNKNOWN` |
| `master-royale-apk-v3-2729-1` | `nr-15-535-13-infinity-da5a0dc4` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `master-royale-apk-v3-2729-1` | `nr-15-535-13-infinity-da5a0dc4-1` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| `nr-15-535-13-infinity-da5a0dc4` | `nr-15-535-13-infinity-da5a0dc4-1` | `UNCHANGED_SHARED_CLIENT` | `UNCHANGED_SHARED_CLIENT` | `UNCHANGED_SHARED_CLIENT` | `UNKNOWN` |

## Evidence graph

The conceptual graph has 34567 nodes and 9082 bounded edges, including 248 mechanics-focused cross-layer edges. Every edge carries APK, layer, source locator, evidence label, and explanation. Limits apply per APK and layer; unsupported links are omitted rather than fabricated. `inferred` edges are explicitly non-direct.
