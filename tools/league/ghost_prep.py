"""Ghost opponents: the winning side of real games as a scripted opponent.

    py -3.12 tools/league/ghost_prep.py --replays data/uc/gen2.jsonl --out data/ghosts/gen2.jsonl

One line per game: the winner's deck in the order the engine must deal it
(royalesim_redrive.deal_order, so every recorded play finds its card in hand),
forms, and the plays in the winner's own frame (x 0..18000 left to right,
y 0..32000 with the own king at 32000; actor.py's to_world turns that into
world units for either seat).

The idea (replay a human winner card by card and train the bot to defend it)
is RoyaleFish's, after ClashAI; this file and the trainer side are ours.

Levels are not in the scrape ("levels": "assumed"), so ghosts play at 16.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replays", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-plays", type=int, default=12)
    a = ap.parse_args()

    import rs_rows as RR
    from royalesim_redrive import base_key, deal_order
    _, names, ids, _ = RR._setup()
    eids = json.load(open(ROOT / "vendor/re/headless/engine_cards.json"))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = kept = 0
    why = {}
    own_half = [0, 0]
    with open(a.replays, encoding="utf-8") as f, open(out, "w", encoding="utf-8") as g:
        for line in f:
            if a.limit and n >= a.limit:
                break
            n += 1
            p = json.loads(line)
            battle = p["battle"]
            res = battle.get("result")
            won = 0 if res == "victory" else 1 if res == "defeat" else -1
            if won < 0:
                why["draw"] = why.get("draw", 0) + 1
                continue
            side = ("team", "opponent")[won]
            players = battle[side]["players"]
            if len(players) != 1:
                continue
            deck, form = [], []
            for card in players[0]["deck"]:
                key, fm = base_key(card["card_key"])
                name = names.get(key)
                if name is None or name not in ids or name not in eids:
                    deck = None
                    break
                deck.append(name)
                form.append(fm)
            if not deck:
                why["card"] = why.get("card", 0) + 1
                continue
            plays, presses, team_ys = [], [], []
            for e in sorted(p["events"], key=lambda e: (e["replay_tick_20hz"], e["source_index"])):
                seat = 0 if e["side"] == "team" else 1
                if e["kind"] == "play_card":
                    u = e["coordinates"]["native_world_units"]
                    if seat == 0:
                        team_ys.append(int(u["y"]))
                    if seat == won:
                        plays.append((int(e["replay_tick_20hz"]), names.get(base_key(e["card_key"])[0]),
                                      int(u["x"]), int(u["y"])))
                elif e["kind"] == "activate_ability" and seat == won:
                    presses.append(int(e["replay_tick_20hz"]))
            if len(plays) < a.min_plays or any(c not in deck for _, c, _, _ in plays):
                why["plays"] = why.get("plays", 0) + 1
                continue
            order = deal_order(deck, [c for _, c, _, _ in plays])
            if order is None:
                why["order"] = why.get("order", 0) + 1
                continue
            # World units exactly as engine_bc.py re-drives them, then the own frame.
            team_ys.sort()
            team_seat = 0 if (team_ys or [0])[len(team_ys) // 2] < 16_000 else 1
            eng_team = team_seat if won == 0 else 1 - team_seat
            rows = []
            for t, c, x, y in plays:
                if team_seat == 1:
                    x, y = 18_000 - x, 32_000 - y
                ox, oy = (x, 32_000 - y) if eng_team == 0 else (18_000 - x, y)
                rows.append([t, c, ox, oy])
                own_half[0] += int(oy >= 16_000)
                own_half[1] += 1
            perm = [deck.index(c) for c in order]
            g.write(json.dumps({"tag": p["source"].get("replay_tag"), "deck": order,
                                "forms": [form[i] for i in perm], "plays": rows, "presses": presses}) + "\n")
            kept += 1
    print(json.dumps({"games": n, "ghosts": kept, "dropped": why,
                      "plays_on_own_half": round(own_half[0] / max(1, own_half[1]), 3)}))


if __name__ == "__main__":
    main()
