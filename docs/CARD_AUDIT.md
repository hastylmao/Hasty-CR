# Friendly card audit

Start the usual bot with `--card-audit`. This forces `--no-queue`; accept/start friendlies manually. No ladder queue is initiated by the runner. Leave the runner open between matches or close and restart it.

```bat
.venvs\royalegym\Scripts\python.exe scripts\gamestate\live_play.py --ckpt runs\selfplay\sp_v1\it020.pt --card-audit
```

For each opponent deck, add its eight simulator card names, comma separated:

```bat
.venvs\royalegym\Scripts\python.exe scripts\gamestate\live_play.py --ckpt runs\selfplay\sp_v1\it020.pt --card-audit --audit-expected "Knight,Archer,Giant,Fireball,Arrows,Minions,Valkyrie,Goblins"
```

Keep our own deck as usual. If changing the bot's deck, supply `--deck` in its deck-screen order. Deploy every declared opponent card. Declaring a card does not prove it was played. Evolutions/heroes are tracked as distinct unit/native-ID forms when observed, so first-seen base cards do not hide later variants. New records are deduplicated by native card ID, unit name, and bridge stage; model visibility is deduplicated by token identity. Multiple forms or different stages can add evidence for one card.

`reports/card_audit/coverage.json` is cumulative evidence; `coverage.txt` is a human-readable summary. Both update only on new findings, except initialization updates declared test cards. JSON commits use fsync then atomic replacement: already saved findings survive closing CMD. A card played immediately before termination can still be missed if no frame was processed yet. Closing CMD stops logging; it does not keep monitoring the remaining game.

Summary separates detected cards, bridged characters, model input tokens, declared cards not observed, and unobserved local-catalogue cards. Unobserved does not mean missing from the game reader. Effects/projectiles/spells are often correctly excluded from troop tokens. A dropped body is evidence of a bridge problem, but model visibility alone does not prove proper defence. The reader cannot log an object it never emits; compare declared deployments against video for that case.

The audit intentionally does not write repeated sightings or all frames. It establishes coverage, not the cause of a particular missed defence or 48-token truncation event. Preserve the cumulative files for later analysis; no reset occurs at match end or CMD restart.
