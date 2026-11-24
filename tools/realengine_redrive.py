"""Re-drive recorded official battles (data/il_replay) through the real
headless engine (vendor/re/headless, RealEngine) and compare the outcome
with what actually happened.

    py -3.12 tools/realengine_redrive.py --matches 200

This is the real-engine counterpart of tools/royalesim_redrive.py (RoyaleSim
reached 62.6% winner agreement). How a match is played:
* both decks dealt unshuffled (the game mode's FixedDeckOrder flag is set on
  the Ladder row) in an order under which every recorded play was in hand,
  searched as royalesim_redrive does;
* every card at its recorded level; towers and king at the tower card's level;
* each play at its recorded tick and native coordinates. Team is the blue
  player (low y). The engine applies its own elixir and hand rules, so a play
  it would refuse is simply not made; refusals are not counted yet.
* evolutions and heroes are played as their base card for now (the card-form
  bits of the play command are not mapped yet). Matches are split by whether
  either deck has a form, so their effect on agreement is visible.

Writes reports/realengine_redrive/<name>.jsonl, one row per match.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter
from itertools import combinations, permutations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADLESS = ROOT / "vendor" / "re" / "headless"
sys.path.insert(0, str(HEADLESS))
import engine  # noqa: E402

CORPUS = ROOT / "data" / "il_replay"
NAMES = json.loads((ROOT / ".venvs" / "royalegym" / "Lib" / "site-packages" / "royaleimitate" /
                    "replay_cards.json").read_text(encoding="utf-8"))
SUPPORT = {"tower-princess": "King_PrincessTowers", "cannoneer": "King_CannonTowers",
           "tower-cannoneer": "King_CannonTowers", "dagger-duchess": "King_KnifeTowers",
           "royal-chef": "King_ChefTowers"}
RUN_STATS = Counter()
MISS = Counter()  # ability sources with no matching unit, with the side's unit names
GAMEMODE = 72000006  # --gamemode; FixedDeckOrder is set on that row
SEED = 1  # replay JSON rndSeed (--seed); the real match seed is unknown
OFFSET = 0  # engine tick = replay tick + OFFSET (--offset)
JITTER = 0  # --jitter: each play moves by a random -J..J ticks and -J..J game units / 10 (a control)
JRNG = random.Random(0)
EVO = True  # mark evolution cards in the deck ("el": 1); --no-evo turns it off
CSV_DIR = ROOT / "vendor" / "re" / "target" / "data" / "decoded" / "csv_logic"


def card_costs():
    cost = {}
    for f in ("spells_characters.csv", "spells_buildings.csv", "spells_other.csv"):
        rows = list(csv.reader((CSV_DIR / f).open(encoding="utf-8")))
        h = rows[0]
        ni, mi = h.index("Name"), h.index("ManaCost")
        for r in rows[2:]:
            if r and r[0] and r[mi].strip():
                cost.setdefault(r[ni], int(r[mi]))
    return cost


# The engine never deals these into the starting hand: with one in deck slots 0-3
# under FixedDeckOrder the hand is filled from slot 4 instead (measured 2026-11-14,
# both cards, slots 0 and 3). A deal order that starts with one cannot be re-driven.
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


def build(payload, ids, cost):
    """Battle JSON + the list of play commands, or (None, reason)."""
    battle = payload["battle"]
    sides = ("team", "opponent")
    decks, levels, has_form, evo, hero = [], [], False, [set(), set()], [set(), set()]
    tower_level, support = [], []
    for side in sides:
        pl = battle[side]["players"][0]
        deck, level = [], []
        for c in pl["deck"]:
            key, form = base_key(c["card_key"])
            has_form |= form != 0
            name = NAMES.get(key)
            if name is None or name not in ids:
                return None, f"card {key}"
            deck.append(name)
            level.append(int(c.get("level") or 11))
            if form == 1:
                evo[len(decks)].add(name)
            elif form == 2:
                hero[len(decks)].add(name)
        decks.append(deck)
        levels.append(level)
        tc = pl.get("tower_card") or {}
        sname = SUPPORT.get(tc.get("card_key", "tower-princess"))
        if sname is None or sname not in ids:
            return None, f"tower card {tc.get('card_key')}"
        support.append(ids[sname])
        tower_level.append(int(tc.get("level") or max(level)))
    events = sorted((e for e in payload["events"] if e["kind"] == "play_card"),
                    key=lambda e: (e["replay_tick_20hz"], e["source_index"]))
    plays = {0: [], 1: []}
    for e in events:
        seat = 0 if e["side"] == "team" else 1
        key, _ = base_key(e["card_key"])
        u = e["coordinates"]["native_world_units"]
        jt = JRNG.randint(-JITTER, JITTER) if JITTER else 0
        jx, jy = (JRNG.randint(-JITTER, JITTER) * 10, JRNG.randint(-JITTER, JITTER) * 10) if JITTER else (0, 0)
        plays[seat].append((max(1, int(e["replay_tick_20hz"]) + jt), NAMES.get(key), int(u["x"]) + jx, int(u["y"]) + jy))
    dealt = []
    for seat in (0, 1):
        order = deal_order(decks[seat], [c for _, c, _, _ in plays[seat]])
        if order is None:
            return None, "no deal order"
        dealt.append(order)
    lvl = [{c: levels[s][decks[s].index(c)] for c in decks[s]} for s in (0, 1)]
    j = {"rndSeed": SEED, "time": 0, "endTick": 9000, "battle": {
        "gamemode": GAMEMODE, "location": 15000006, "arena": 54000001,
        "avatar0": {"accountID.hi": 0, "accountID.lo": 1, "name": "Team", "expLevel": 60, "arena": 54000001},
        "avatar1": {"accountID.hi": 0, "accountID.lo": 2, "name": "Opp", "expLevel": 60, "arena": 54000001},
        "hbd": [{"di": 0, "em": {}, "kt": tower_level[0]}, {"di": 1, "em": {}, "kt": tower_level[1]}]},
        "cmd": [], "evt": []}
    for s in (0, 1):
        def form_of(c):
            return 1 if c in evo[s] and EVO else 2 if c in hero[s] else 0
        j["battle"][f"deck{s}"] = {"sp": [dict({"d": ids[c], "l": lvl[s][c] - 1}, **({"el": form_of(c)} if form_of(c) else {}))
                                          for c in dealt[s]],
                                   "sc": [{"d": support[s], "l": tower_level[s] - 1}]}
    cmds = []
    for s in (0, 1):
        for t, c, x, y in plays[s]:
            slot = dealt[s].index(c)
            form = 1 if c in evo[s] and EVO else 2 if c in hero[s] else 0
            # pd bits 19-21: the card's form kind (1 evolution, 2 hero); without them the
            # engine never counts evolution progress for the card.
            cmds.append((t, {"ct": 153, "c": {
                "t": t, "t2": t, "idHi": 0, "idLo": s + 1, "px": x, "py": y, "sid": 0,
                "sel": {"os": ids[c], "pd": engine.pd(slot, lvl[s][c] - 1, cost.get(c, 3)) | (form << 19)}}}))
    j["cmd"] = [c for _, c in sorted(cmds, key=lambda tc: tc[0])]
    n_ability = sum(1 for e in payload["events"] if e["kind"] == "activate_ability")
    # Champion / hero abilities (type 189 with the unit's game id, filled in live).
    for e in payload["events"]:
        if e["kind"] != "activate_ability":
            continue
        s_ = 0 if e["side"] == "team" else 1
        src = [NAMES.get(base_key(k)[0]) for k in (e.get("ability_source_candidates") or [])]
        cmds.append((int(e["replay_tick_20hz"]), {"ct": 189, "c": {
            "t": int(e["replay_tick_20hz"]), "t2": int(e["replay_tick_20hz"]) + 1, "idHi": 0, "idLo": s_ + 1,
            "cgid": -1}, "_src": [x for x in src if x]}))
    j["cmd"] = [c for _, c in sorted(cmds, key=lambda tc: tc[0])]
    has_hero = any(c["card_key"].endswith("-hero") for side in sides for c in battle[side]["players"][0]["deck"])
    j["_meta"] = {"abilities": n_ability, "hero": has_hero}
    return (j, has_form, sum(len(v) for v in plays.values())), ""


def recorded(battle):
    rec = battle["team"]["crowns"], battle["opponent"]["crowns"]
    result = str(battle.get("result", "")).lower()
    w = ("team" if result in ("victory", "win") else "opponent" if result in ("defeat", "loss") else
         ("team" if rec[0] > rec[1] else "opponent" if rec[1] > rec[0] else "draw"))
    return rec, w


def run(eng, j, path):
    """Plays are injected live: just before each play the hand is read, and if
    the engine has that card in its evolution (or hero) form, the play names the
    form spell (sel.fs), the way the client does. Without fs the base card is
    played even when evolved."""
    cmds = j["cmd"]
    j = dict(j, cmd=[])
    path.write_text(json.dumps(j))
    eng.new_battle(str(path.relative_to(HEADLESS)).replace("\\", "/"))
    stats = Counter()
    for c in cmds:
        if c["ct"] == 189:
            t = c["c"]["t"] + OFFSET
            c["c"]["t"], c["c"]["t2"] = t, t + 1
            if t - 1 > eng.t:
                eng.step(t - 1 - eng.t)
            s = eng.state()
            if eng.finished(s):
                break
            side = c["c"]["idLo"] - 1
            src = c.pop("_src", [])
            # the side's live champion/hero unit whose name matches the ability source
            # (hero units are named <Card>Hero); the newest one if several
            cand = [o for o in s["objects"] if o[1] == side and
                    any(o[0].lower().startswith(n.lower()) for n in src)]
            stats["abilities"] += 1
            if not cand:
                stats["ability: no unit"] += 1
                MISS.update([(tuple(src), tuple(sorted({o[0] for o in s["objects"] if o[1] == side})))])
                continue
            c["c"]["cgid"] = max(o[6] for o in cand)
            eng._call("cmd " + json.dumps(c, separators=(",", ":")))
            continue
        c["c"]["t"] = c["c"]["t2"] = t = c["c"]["t"] + OFFSET
        if t - 1 > eng.t:
            eng.step(t - 1 - eng.t)
        s = eng.state()
        if eng.finished(s):
            break
        side = c["c"]["idLo"] - 1
        slot = ((c["c"]["sel"]["pd"] >> 22) & 0x3f) - 1
        pos = s["hands"][side][slot]
        stats["plays"] += 1
        if s["elixir"][side] < (c["c"]["sel"]["pd"] >> 28):
            stats["short of elixir"] += 1
        if not 0 <= pos <= 3:
            stats["not in hand"] += 1
        else:
            # Evolution: the engine's own ready check (progress >= cycles); then the
            # play is the evolved form (pd bits 0-3 = 1, fs = evolution spell) and the
            # engine resets progress. Hero cards are always played as the hero.
            kind = (c["c"]["sel"]["pd"] >> 19) & 7
            card = s["handcards"][side][pos]
            if kind == 1 and s["evoready"][side][slot] and card:
                c["c"]["sel"]["pd"] |= 1
                c["c"]["sel"]["fs"] = card[3]
                stats["evolved"] += 1
            elif kind == 2 and card:
                c["c"]["sel"]["pd"] |= 2
                c["c"]["sel"]["fs"] = card[4]
                stats["hero"] += 1
        eng._call("cmd " + json.dumps(c, separators=(",", ":")))
    RUN_STATS.update(stats)
    s = eng.state()
    while not eng.finished(s) and eng.t < 9000:
        eng.step(200)
        s = eng.state()
    c = engine.RealEngine.crowns(s)
    tw = engine.RealEngine.towers(s)
    if c[0] != c[1]:
        w = "team" if c[0] > c[1] else "opponent"
    else:  # no draws in ladder: lower total tower hitpoints loses (tiebreak); equal = draw
        hp = [tw[i]["king"] + sum(tw[i]["princess"]) for i in (0, 1)]
        w = "team" if hp[0] > hp[1] else "opponent" if hp[1] > hp[0] else "draw"
    return c, w, eng.t, tw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--name", default="first")
    ap.add_argument("--no-evo", action="store_true")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--jitter", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--gamemode", type=int, default=72000006)
    a = ap.parse_args()
    global EVO, OFFSET, SEED, GAMEMODE, JITTER
    EVO = not a.no_evo
    OFFSET = a.offset
    JITTER = a.jitter
    SEED = a.seed
    GAMEMODE = a.gamemode
    import pyarrow.parquet as pq
    eng = engine.RealEngine()
    eng._call(f"setrow 72 {GAMEMODE - 72000000} 0x60 256")  # game mode row: FixedDeckOrder on
    ids = eng._call("cards")
    cost = card_costs()
    out_dir = ROOT / "reports" / "realengine_redrive"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = HEADLESS / "redrive_tmp.json"
    rows, skipped = [], Counter()
    t0 = time.time()
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        acts = pq.read_table(CORPUS / "actions" / part.name, columns=["replay_tag", "event_json"]).to_pylist()
        events = {}
        for x in acts:
            events.setdefault(x["replay_tag"], []).append(json.loads(x["event_json"]))
        for r in pq.read_table(part, columns=["replay_tag", "payload_json"]).to_pylist():
            p = json.loads(r["payload_json"])
            p["events"] = events.get(r["replay_tag"], [])
            built, why = build(p, ids, cost)
            if built is None:
                skipped[why.split(" ")[0]] += 1
                continue
            j, has_form, nplays = built
            try:
                c, w, end, tw = run(eng, j, tmp)
            except RuntimeError as e:
                skipped["engine " + str(e)[:40]] += 1
                eng.close()
                eng = engine.RealEngine()
                eng._call(f"setrow 72 {GAMEMODE - 72000000} 0x60 256")
                continue
            rec, rw = recorded(p["battle"])
            meta = j.pop("_meta", {})
            rows.append({"tag": r["replay_tag"], "forms": has_form, "abilities": meta.get("abilities", 0),
                         "hero": meta.get("hero", False), "plays": nplays, "engine_crowns": c,
                         "recorded_crowns": list(rec), "engine_winner": w, "recorded_winner": rw,
                         "winner_agree": w == rw, "crowns_agree": c == list(rec), "end": end,
                         "recorded_seconds": (p.get("replay", {}).get("duration") or {}).get("timeline_seconds"),
                         "towers": tw, "recorded_towers": [p["battle"][s]["players"][0]["final_tower_hitpoints"]
                                                           for s in ("team", "opponent")]})
            if len(rows) % 20 == 0:
                print(f"{len(rows)} matches, {time.time() - t0:.0f}s", flush=True)
            if len(rows) >= a.matches:
                break
        if len(rows) >= a.matches:
            break
    eng.close()
    with (out_dir / f"{a.name}.jsonl").open("w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x) + "\n")

    def summary(sel, label):
        if not sel:
            return
        print(f"{label}: {len(sel)} matches, winner agree {sum(x['winner_agree'] for x in sel) / len(sel):.1%}, "
              f"crowns agree {sum(x['crowns_agree'] for x in sel) / len(sel):.1%}")
    summary(rows, "all")
    summary([x for x in rows if not x["forms"]], "no evo/hero")
    summary([x for x in rows if x["forms"]], "with evo/hero")
    summary([x for x in rows if not x["abilities"] and not x["hero"]], "no abilities, no hero")
    summary([x for x in rows if x["abilities"] or x["hero"]], "abilities or hero")
    print("skipped:", dict(skipped), f"time {time.time() - t0:.0f}s")
    print("plays:", dict(RUN_STATS))
    for k, v in MISS.most_common(8):
        print("ability miss", v, k)


if __name__ == "__main__":
    main()
