"""Opponent decks for league training, with their evolution / hero forms.

The Supercell API pull (tools/ladder_pull.py) is the fresher source, but its
key is bound to one public IP; when that fails, the IL_Replay corpus is the
fallback, and it is the better one for forms anyway: every card carries its
`-ev1` / `-hero` suffix. Both sides of every ranked match are counted.

Each deck is checked against the installed engine: every card must resolve
and `Battle.reset` must accept its forms, so a training worker never meets a
deck it cannot start.

    .venvs\\buildabot\\Scripts\\python.exe tools\\league\\meta_decks.py
writes data/league/meta_decks.json: [{"cards": [...8 names], "forms": [...],
"seen": n, "wins": w}], most played first.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

OUT = ROOT / "data" / "league" / "meta_decks.json"


def main() -> int:
    import pyarrow.parquet as pq
    import rs_rows as RR
    from royalesim_redrive import CORPUS, base_key
    royalesim, names, ids, cat = RR._setup()
    seen, wins = collections.Counter(), collections.Counter()
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        rows = pq.read_table(part, columns=["game_mode", "payload_json"]).to_pylist()
        for r in rows:
            if r["game_mode"] not in RR.MODES:
                continue
            b = json.loads(r["payload_json"])["battle"]
            res = str(b.get("result", "")).lower()
            for side in ("team", "opponent"):
                players = b.get(side, {}).get("players") or []
                if len(players) != 1 or len(players[0].get("deck") or []) != 8:
                    break
                deck = []
                for c in players[0]["deck"]:
                    key, form = base_key(c["card_key"])
                    name = names.get(key)
                    if name is None or name not in ids:
                        deck = None
                        break
                    deck.append((name, form))
                if deck is None:
                    continue
                k = tuple(sorted(deck))
                seen[k] += 1
                won = res in ("victory", "win") if side == "team" else res in ("defeat", "loss")
                wins[k] += won
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    out, refused = [], 0
    for k, n in seen.most_common():
        cards, forms = [c for c, _ in k], [f for _, f in k]
        try:
            b.reset(seed=0, decks=[[ids[c] for c in cards]] * 2, shuffle=0, start_tick=0,
                    elixir_milli=[5000, 5000], tower_hp=None, spawns=[], forms=[forms, forms])
        except Exception:
            refused += 1
            continue
        out.append({"cards": cards, "forms": forms, "seen": n, "wins": wins[k]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out))
    total = sum(d["seen"] for d in out)
    top300 = sum(d["seen"] for d in out[:300])
    print(json.dumps({"decks": len(out), "refused": refused, "deck_appearances": total,
                      "top300_share": round(top300 / max(1, total), 3)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
