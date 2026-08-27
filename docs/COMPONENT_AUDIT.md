# Component audit

Audit date: 2026-08-05. Repositories are pinned locally by their cloned commit in `vendor/`.

| Project | Strongest contribution | Verified locally | Main limitation | Integration decision |
|---|---|---|---|---|
| vegetableleaf/ClashAI | Headless simulator, imitation-data pipeline, CNN/DDQN policy workflow, deck knowledge base | Python compiles; CLI loads; simulator completed matches at ~2,285 steps/s in a 20-match smoke benchmark | No license; no automated tests; heavily deck/doctrine-specific; random actions won 12/20 smoke matches, so simulator strength/fidelity needs calibration | Runtime adapter only until permission/license is obtained; primary experimental training spine |
| Pbatch/ClashRoyaleBuildABot | Bundled ONNX unit/side detectors, card/elixir/screen detection, structured battle state | Python compiles; package and ONNX Runtime install; imports succeed | No tests; fixed geometry; detector/controller are tightly coupled in the stock bot | Use the detector behind a neutral perception adapter |
| pyclashbot/py-clash-bot | Emulator lifecycle, ADB backends, navigation, recovery, UI state machine | 47 offline tests pass; package installs on Python 3.12 | Fixed ~419x633 coordinates; policy is not strategic; custom non-commercial copyleft license | Communicate only through public controller interfaces to remain an independent work |
| wty-yy/KataCR | Offline sequence models, perception datasets, state/action builders | Python sources compile | Live validation is Linux/JAX/NVIDIA/V4L2-specific; complex three-framework environment; models are narrow/fixed-deck | Reference algorithms and MIT-licensed components selectively after isolated tests |
| krazyness/CRBot-public | Compact example of DQN + Roboflow wiring | Python sources compile | README says it is broken; remote inference dependency; 41-float state discards unit identity/HP; simplistic two-layer DQN | Reference only; do not make it a runtime dependency |

## Immediate architecture

1. py-clash-bot-compatible controller provides frames and menu recovery.
2. BuildABot detector produces a neutral `GameState`.
3. ClashAI simulator and training pipeline produce policy candidates.
4. HastyCR validates and logs normalized actions before any optional live execution.
5. Recorded-frame evaluation comes before emulator play; live action execution remains opt-in.

## Licensing boundary

- BuildABot, KataCR, and CRBot-public are MIT licensed.
- py-clash-bot uses a non-commercial copyleft license, but its license explicitly treats software communicating only through public interfaces/protocols as independent work.
- ClashAI has no license file. Source can be inspected and run locally, but should not be copied, modified, or redistributed as part of HastyCR without written permission or an explicit upstream license.

