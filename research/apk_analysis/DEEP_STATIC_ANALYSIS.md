# Deep Static APK Analysis

Static byte-container analysis only; no APK or native payload was executed, loaded, installed, launched, debugged, emulated, rebuilt, or decompiled. Counts and references do not establish runtime behavior.

## Scope

- APKs: 4; pair comparisons: 6; conceptual graph edges: 9082.
- Inputs are existing ignored extraction manifests and bytes under `_references/apk_analysis/`; every original ZIP entry is streamed and matched to manifest path, size, and SHA-256 in the same operation.
- CSV/TOML parse coverage and proprietary/ELF unsupported counts are explicit; detailed machine output remains ignored under `_references/apk_analysis/deep/`.

## APK inventory

| APK | Entries | DEX | ELF | CSV/TOML | Unsupported proprietary |
|---|---:|---:|---:|---:|---:|
| `clash-royale-mod-15-535-13-an1-com` | 9921 | 1 | 16 | 585 | 8242 |
| `master-royale-apk-v3-2729-1` | 3689 | 2 | 8 | 175 | 336 |
| `nr-15-535-13-infinity-da5a0dc4` | 10448 | 1 | 16 | 740 | 8595 |
| `nr-15-535-13-infinity-da5a0dc4-1` | 10448 | 1 | 16 | 740 | 8595 |

## Future official-tool lane

This lane is explicitly non-executing and fail-closed policy metadata only; no network, tool, Java, plugin, or native payload was run. Controls are not enforced by this analyzer.

| Tool | Version | Release URL | Exact asset | Asset URL | Commit | Artifact SHA-256 | License |
|---|---|---|---|---|---|---|---|
| Apktool | `3.0.3` | `https://github.com/iBotPeaches/Apktool/releases/tag/v3.0.3` | `apktool_3.0.3.jar` | `https://github.com/iBotPeaches/Apktool/releases/download/v3.0.3/apktool_3.0.3.jar` | `18b5e99cb56ff9451e8aa55b065dcf5bbd616975` | `dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423` | `Apache-2.0` |
| Jadx | `1.5.6` | `https://github.com/skylot/jadx/releases/tag/v1.5.6` | `jadx-1.5.6.zip` | `https://github.com/skylot/jadx/releases/download/v1.5.6/jadx-1.5.6.zip` | `28ff15e4ae69950aebea110a13e5ab895d234dfc` | `545ea2be9c242511bc145755cf4bda2485ade42966e096f8b4d3da2a230e8974` | `Apache-2.0` |

## External study note

- `milanmaldini/cr-sc-dump2026` HEAD `46a4a2d6f0c01bf0549cde70dfcc35e0c9849b7c` is documented as a reported-zero-change-fork-unverified.
- License, tests, fixtures, data, and provenance are absent; it is study-only and was not cloned or run.

## Metric definitions

Every Jaccard is intersection weight divided by union weight; two empty collections score 1. `path_hash` items are `(full APK path, SHA-256)`. `content_hash` and basename variants retain duplicate counts. DEX semantic and native component items are `(owning path, item)` with multiplicity. Data total identity includes every `.csv`/`.toml`; parseable identity includes only successful syntax/schema extraction; opaque identity includes only non-successful data entries.

## Coverage

DEX checks include header bounds plus stored SHA-1/adler integrity, but not full map/header correspondence. ELF and graph inventories are bounded and may be partial. Proprietary formats remain unsupported. Static and inferred edges are not runtime proof.
