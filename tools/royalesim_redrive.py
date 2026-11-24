"""Re-drive the same IL_Replay matches through RoyaleSim, for a paired
fidelity comparison with our own engine (tools/redrive_bench.py).

Runs in the isolated RoyaleGym environment:

    .venvs/royalegym/Scripts/python.exe tools/royalesim_redrive.py --pair b2000

It reads the match tags from reports/redrive/<pair>.jsonl, so both engines
play exactly the same matches, and writes reports/redrive/<pair>_royalesim.jsonl
with the same columns the report reads (winner / crowns agreement, refusals).

How a match is played, kept as close to our harness as the API allows:
* decks dealt unshuffled in an order under which every recorded play was in
  hand (searched, as RoyaleImitate does), so a hand refusal means the engine's
  cycle disagreed, not that the start was unknown;
* every card at its recorded level and form (evolution / hero), towers at the
  match's most common card level, both sides on 6 starting elixir;
* each play at its recorded tick and native tile. RoyaleSim cannot be told to
  ignore elixir, so a play it refuses is counted and dropped rather than
  forced. That is a harder test than ours, which tops elixir up.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations, permutations
from pathlib import Path
from statistics import mode

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "data" / "il_replay"


# The real engine never deals these into the starting hand: with one in deck slots
# 0-3 under FixedDeckOrder the hand is filled from slot 4 instead (measured
# 2026-11-14, both cards, slots 0 and 3). A deal order that starts with one cannot be
# re-driven; 12 of 200 UC pilot games were cut at an Elixir Collector play for this.
NOT_IN_START = {"Elixir Collector", "Mirror"}


def deal_order(deck, plays):
    for hand in combinations(deck, 4):
        if NOT_IN_START & set(hand):
            continue
        rest = [c for c in deck if c not in hand]
        for queue in permutations(rest):
            held, waiting = set(hand), list(queue)
            for card in plays:
                if card not in held:
                    break
                held.remove(card)
                waiting.append(card)
                held.add(waiting.pop(0))
            else:
                return [*hand, *queue]
    return None


def base_key(key):
    for suffix in ("-ev1", "-hero"):
        if key.endswith(suffix):
            return key[: -len(suffix)], (1 if suffix == "-ev1" else 2)
    return key, 0


_ENGINE = {}


def _engine():
    if not _ENGINE:
        import royalesim
        import royaleimitate
        names = json.loads((Path(royaleimitate.__file__).with_name("replay_cards.json"))
                           .read_text(encoding="utf-8"))
        b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        ids = {row[0]: i for i, row in enumerate(json.loads(b.catalogue_json()))}
        _ENGINE.update(royalesim=royalesim, names=names, ids=ids)
    return _ENGINE


def one(payload_text: str) -> dict:
    eng = _engine()
    royalesim, names, ids = eng["royalesim"], eng["names"], eng["ids"]
    p = json.loads(payload_text)
    battle = p["battle"]
    tag = p["source"]["replay_tag"]
    out = {"tag": tag, "ok": False, "error": "", "forced": {}, "plays": 0}
    sides = ("team", "opponent")
    decks, forms, levels = [], [], []
    for side in sides:
        players = battle[side]["players"]
        deck, form, level = [], [], []
        for card in players[0]["deck"]:
            key, f = base_key(card["card_key"])
            name = names.get(key)
            if name is None or name not in ids:
                out["error"] = f"card not in RoyaleSim: {key}"
                return out
            deck.append(name)
            form.append(f)
            level.append(int(card.get("level") or 11))
        decks.append(deck)
        forms.append(form)
        levels.append(level)
    events = sorted((e for e in p["events"] if e["kind"] == "play_card"),
                    key=lambda e: (e["replay_tick_20hz"], e["source_index"]))
    plays = {0: [], 1: []}
    for e in events:
        seat = 0 if e["side"] == "team" else 1
        key, _ = base_key(e["card_key"])
        name = names.get(key)
        u = e["coordinates"]["native_world_units"]
        plays[seat].append((int(e["replay_tick_20hz"]), name, int(u["x"]), int(u["y"])))
    # Which end the team owns, from its troop plays: blue is RoyaleSim's low-y side.
    ys = sorted(y for _, _, _, y in plays[0]) or [0]
    team_low = ys[len(ys) // 2] < 16_000
    team_seat = 0 if team_low else 1           # RoyaleSim team index of "team"
    dealt = []
    for seat in (0, 1):
        order = deal_order(decks[seat], [c for _, c, _, _ in plays[seat]])
        if order is None:
            out["error"] = "no deal order fits the plays"
            return out
        dealt.append(order)
    perm = [[decks[s].index(c) for c in dealt[s]] for s in (0, 1)]
    rs_side = {0: team_seat, 1: 1 - team_seat}          # our seat -> RoyaleSim team
    by_team = [None, None]
    for seat in (0, 1):
        by_team[rs_side[seat]] = seat
    lv_all = [lv for s in levels for lv in s]
    tower = max(1, min(16, mode(lv_all)))
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    b.reset(seed=0,
            decks=[[ids[c] for c in dealt[by_team[t]]] for t in (0, 1)],
            shuffle=0, start_tick=0, elixir_milli=[6000, 6000], tower_hp=None, spawns=[],
            forms=[[forms[by_team[t]][i] for i in perm[by_team[t]]] for t in (0, 1)],
            levels=[[levels[by_team[t]][i] for i in perm[by_team[t]]] for t in (0, 1)],
            tower_levels=[tower, tower])
    SUB = royalesim.SUBTILE_PER_MILLITILE
    queue = sorted([(t, seat, c, x, y) for seat in (0, 1) for (t, c, x, y) in plays[seat]])
    forced = Counter()
    tick, i = 0, 0
    last = queue[-1][0] if queue else 0
    while i < len(queue):
        t = queue[i][0]
        if t > tick:
            b.step([], t - tick)
            tick = t
        state = json.loads(b.state_json())
        if state["game_over"]:
            break
        cmds = []
        while i < len(queue) and queue[i][0] == t:
            _, seat, card, x, y = queue[i]
            team = rs_side[seat]
            hand = state["players"][team]["hand"]
            cid = ids[card]
            out["plays"] += 1
            if cid not in hand:
                forced["hand"] += 1
            else:
                if team_seat == 1:     # team owned high y: turn the board half a turn
                    x, y = 18_000 - x, 32_000 - y
                cmds.append((team, hand.index(cid), x * SUB, y * SUB))
            i += 1
        if cmds:
            res = b.step(cmds, 1)
            tick += 1
            for row in res:
                reason = royalesim.DEPLOY_REASONS[row[1]]
                if reason != "OK":
                    forced[reason.lower()] += 1
    end = min(last + 200, 6000)
    if tick < end:
        b.step([], end - tick)
    state = json.loads(b.state_json())
    if not state["game_over"]:
        b.step([], 6000)
        state = json.loads(b.state_json())
    crowns = {"team": state["players"][team_seat]["crowns"],
              "opponent": state["players"][1 - team_seat]["crowns"]}
    w = state["winner"]
    winner = ("team" if w == team_seat else "opponent" if w in (0, 1) else "draw")
    rec = battle["team"]["crowns"], battle["opponent"]["crowns"]
    result = str(battle.get("result", "")).lower()
    rec_winner = ("team" if result in ("victory", "win") else
                  "opponent" if result in ("defeat", "loss") else
                  ("team" if rec[0] > rec[1] else "opponent" if rec[1] > rec[0] else "draw"))
    out.update(ok=True, forced=dict(forced), engine_crowns=crowns,
               recorded_crowns={"team": rec[0], "opponent": rec[1]},
               winner_agree=winner == rec_winner,
               crowns_agree=crowns == {"team": rec[0], "opponent": rec[1]},
               end=state["tick"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="b2000")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    import pyarrow.parquet as pq
    wanted = {json.loads(l)["tag"] for l in
              (ROOT / "reports" / "redrive" / f"{args.pair}.jsonl").open(encoding="utf-8")}
    payloads = {}
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        acts = pq.read_table(CORPUS / "actions" / part.name,
                             columns=["replay_tag", "event_json"]).to_pylist()
        events = {}
        for a in acts:
            if a["replay_tag"] in wanted:
                events.setdefault(a["replay_tag"], []).append(json.loads(a["event_json"]))
        for r in pq.read_table(part, columns=["replay_tag", "payload_json"]).to_pylist():
            if r["replay_tag"] in wanted:
                payload = json.loads(r["payload_json"])
                payload["events"] = events.get(r["replay_tag"], [])
                payload.setdefault("source", {})["replay_tag"] = r["replay_tag"]
                payloads[r["replay_tag"]] = json.dumps(payload)
        if len(payloads) >= len(wanted):
            break
    print(f"{len(payloads)} of {len(wanted)} matches found", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as pool:
        rows = list(pool.map(one, list(payloads.values()), chunksize=8))
    out = ROOT / "reports" / "redrive" / f"{args.pair}_royalesim.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    ok = [r for r in rows if r["ok"]]
    errs = Counter(r["error"].split(":")[0] for r in rows if not r["ok"])
    forced = Counter()
    for r in ok:
        forced.update(r["forced"])
    plays = sum(r["plays"] for r in ok)
    e3 = sum(1 for r in ok if 3 in r["engine_crowns"].values())
    r3 = sum(1 for r in ok if 3 in r["recorded_crowns"].values())
    print(f"RoyaleSim: {len(ok)} ran ({time.time() - t0:.0f}s), errors {dict(errs)}")
    print(f"  winner agree {sum(r['winner_agree'] for r in ok) / max(1, len(ok)):.1%}, "
          f"crowns agree {sum(r['crowns_agree'] for r in ok) / max(1, len(ok)):.1%}, "
          f"3-crown {e3} vs recorded {r3}")
    print("  refused per 100 plays: " + ", ".join(
        f"{k} {100 * v / max(1, plays):.2f}" for k, v in forced.most_common()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
