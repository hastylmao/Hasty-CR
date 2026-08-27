# Reference licenses and pinned revisions

Observed 2026-08-23. “Reusable” is a conservative sprint classification, not legal advice; reuse still requires attribution/notice and dependency review. Local links identify the inspected evidence.

| Project | Exact HEAD | Tag evidence | License evidence / SPDX conclusion | Sprint status | Uncertainty |
|---|---|---|---|---|---|
| [CRForge](../_references/crforge/) | `90c043b3ab3271cc41b5b96d84df7bfb746129d9` | No tags | [LICENSE](../_references/crforge/LICENSE), [NOTICE](../_references/crforge/NOTICE): Apache License 2.0; SPDX `Apache-2.0` | Reusable in principle; study only in this sprint | NOTICE/attribution obligations apply; mechanics accuracy not licensed truth |
| [clash-royale-suite](../_references/clash-royale-suite/) | `050275d70b84614953877e8075dc4b8ba907c67f` | No tags | [LICENSE](../_references/clash-royale-suite/LICENSE): MIT; SPDX `MIT` | Reusable in principle; study only | Repository may include externally sourced data/assets with separate provenance |
| [Jason simulator](../_references/jason-clash-royale-simulator/) | `c8c0160fb0dd8c3930f8ac133d1a56f307fcdd50` | No tags | No license file or package license found | Study-only / do not reuse | Absence of a license does not grant copying rights |
| [SamDickson simulator](../_references/samdickson-clash-simulator/) | `99f936f81109057ca6466feafcc816b72fc8b664` | No tags | [README](../_references/samdickson-clash-simulator/README.md) claims “MIT License - See LICENSE”; no LICENSE file found | Study-only pending clarification | README claim and missing referenced license are inconsistent |
| [cr-messages](../_references/cr-messages/) | `64560f4a3c78005cea53c697fbe8ad2bb55bb82d` | No tags | [package.json](../_references/cr-messages/package.json) declares `GNU GPLv3`; no standalone license | Historical architecture only; no reuse | Exact license text/version-or-later terms are not locally supplied |
| [Berkan ClashRoyale](../_references/berkan-clashroyale/) | `98b3656940d1606107527b9ddbc06a79f9a3016f` | No tags | [README](../_references/berkan-clashroyale/README.md) declares CC BY-NC-ND 4.0; SPDX `CC-BY-NC-ND-4.0` | Strict study-only | NoDerivatives and NonCommercial terms make implementation reuse inappropriate |
| [clash-royale-gym](../_references/clash-royale-gym/) | `1cd23be16e10b25c5a5a0889626a863092f32615` | Nearest/latest `0.0.1`, 99 commits behind HEAD; HEAD is untagged | [LICENSE](../_references/clash-royale-gym/LICENSE): MIT; SPDX `MIT` | Interface ideas reusable in principle | HEAD README and implementation disagree; current environment is mostly stubbed |
| [ByteTrack](../_references/ByteTrack/) | `d1bf0191adff59bc8fcfeaa0b33d3d1642552a99` | No tags in clone | [LICENSE](../_references/ByteTrack/LICENSE): MIT; SPDX `MIT` | API/algorithm study; prefer adapter or reviewed dependency | Model weights, datasets, detectors, and third-party components may have separate terms |
| [Norfair](../_references/norfair/) | `e517b4236f6b67a6ecf342f5df1fccb7788dbc54` | HEAD/latest/nearest `v2.3.0` | [LICENSE](../_references/norfair/LICENSE): BSD 3-Clause; SPDX `BSD-3-Clause` | API study; reviewed dependency is possible | Optional integrations/dependencies need separate review |
| [cr-csv](../_references/cr-csv/) | `899e45efc765fbf3902927bb2e37dc04a78f7823` | Nearest/latest `2020-07-07-balance`, 45 commits behind HEAD; HEAD untagged | No license file, README, package manifest, or SPDX marker found | Data and schema study-only / do not redistribute | Dataset origin, extraction authorization, field copyright, and version provenance are unresolved |
| [walle-d/cr-csv](../_references/walle-cr-csv/) | `7141bb508eb0a152f6e7d783bf72968d50573e0b` | Tags `2.0.1`, `2.1.5`; both commits overlap the smlbiobot lineage | No license file or SPDX marker found; README says decoded APK CSVs | Data and schema study-only / do not redistribute | README claims tags/releases match APK versions, but APK identity was not independently authenticated |
| [NoxCardEditor](../_references/NoxCardEditor/) | `be08c7ffcdea8a6611f551620d76a692e2b3a118` | No tags observed | [LICENSE](../_references/NoxCardEditor/LICENSE): MIT; SPDX `MIT` for editor code | Schema/editor behavior study; code reusable in principle after review | Private-server scope; MIT code license does not license decrypted/user-supplied CSVs or game assets |

## Public origins

- https://github.com/voonhous/crforge
- https://github.com/nguiaSoren/clash-royale-suite
- https://github.com/Jason-XII/clash-royale-simulator
- https://github.com/samdickson22/clash-simulator
- https://github.com/royale-proxy/cr-messages
- https://github.com/BerkanYildiz/ClashRoyale
- https://github.com/MSU-AI/clash-royale-gym
- https://github.com/FoundationVision/ByteTrack
- https://github.com/tryolabs/norfair
- https://github.com/smlbiobot/cr-csv
- https://github.com/walle-d/cr-csv
- https://github.com/EnderNox/NoxCardEditor

## Clean-room conclusion

Nothing from these repositories was copied into simulator implementation. Permissive licensing makes some projects candidates for later, separately reviewed reuse, but this sprint uses all of them as evidence and design comparison only. Missing or restrictive licensing overrides technical attractiveness.

| [Keschler/cr-bot](../_references/cr-bot/) | `a08a414433fec990f1af4b5bc22b060aceafb2f0` | No release/tag used for sprint pin | [LICENSE](../_references/cr-bot/LICENSE): Creative Commons Attribution-NonCommercial 4.0; SPDX `CC-BY-NC-4.0` | Strict study-only; clean-room interface comparison only | NonCommercial restriction; repository submodules/assets/data may carry separate terms; no code or data copied |


## Differential framework usage

Task #7 uses the CRForge and clash-royale-suite repositories as source/API and license evidence only. No code, data, bridge, extension, or runtime payload was copied or executed. The local adapters are clean-room descriptors that preserve the pinned provenance and return `UNAVAILABLE` until a separately authorized, dependency-complete execution environment is reviewed.
