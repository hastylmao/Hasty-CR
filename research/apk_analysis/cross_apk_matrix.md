# Cross-APK matrix

Generated: `2026-08-23T20:02:09.659880+00:00`

Static clean-room analysis only. APK code and native libraries were never executed. Raw proprietary bytes remain ignored under `_references/apk_analysis/`.

Hash equality is exact SHA-256 equality. Payload equality compares every normalized ZIP entry path, size, and extracted SHA-256; a payload-equal but APK-different pair generally differs only in ZIP/signing container bytes.

| APK A | APK B | Identical APK | Identical payload | Shared entries | Shared DEX | Shared native | Shared data files |
|---|---|---:|---:|---:|---:|---:|---:|
| clash-royale-mod-15-535-13-an1-com | master-royale-apk-v3-2729-1 | False | False | 374 / 9921:3689 | 0 / 1:2 | 0 / 16:8 | 0 / 634:1288 |
| clash-royale-mod-15-535-13-an1-com | nr-15-535-13-infinity-da5a0dc4-1 | False | False | 9644 / 9921:10448 | 0 / 1:1 | 16 / 16:16 | 520 / 634:798 |
| clash-royale-mod-15-535-13-an1-com | nr-15-535-13-infinity-da5a0dc4 | False | False | 9644 / 9921:10448 | 0 / 1:1 | 16 / 16:16 | 520 / 634:798 |
| master-royale-apk-v3-2729-1 | nr-15-535-13-infinity-da5a0dc4-1 | False | False | 374 / 3689:10448 | 0 / 2:1 | 0 / 8:16 | 0 / 1288:798 |
| master-royale-apk-v3-2729-1 | nr-15-535-13-infinity-da5a0dc4 | False | False | 374 / 3689:10448 | 0 / 2:1 | 0 / 8:16 | 0 / 1288:798 |
| nr-15-535-13-infinity-da5a0dc4-1 | nr-15-535-13-infinity-da5a0dc4 | False | True | 10345 / 10448:10448 | 1 / 1:1 | 16 / 16:16 | 798 / 798:798 |

## Payload-equivalent variants

- `nr-15-535-13-infinity-da5a0dc4-1` and `nr-15-535-13-infinity-da5a0dc4` have identical extracted payloads but different complete APK hashes; differences are confined to ZIP/signing container bytes.

## Exact duplicate APK groups

- None.

## Shared component groups

- Cross-APK DEX hash groups: 1.
- Cross-APK native-library hash groups: 16.
- Cross-APK selected data-file hash groups: 798.
