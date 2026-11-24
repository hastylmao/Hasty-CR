"""Why does the engine re-drive of a scraped replay leave the recording? (2026-11-14)

engine_bc._decisions stops a game at the first recorded play whose card is not in
the re-drive's hand; on the 2,000-game UC pilot that kept 19 of about 33 plays per
winning seat. This re-drives games the same way and, at every recorded play, notes
whether the engine could take it (elixir at that tick, deploy check), then reports
what preceded each stop. Reads payload lines (scraped_to_payload.py output).

    .venvs\royalegym\Scripts\python.exe tools/league/redrive_diag.py --replays data/uc/pilot.jsonl --games 300
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools/league"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--replays", required=True)
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--abilities", type=int, default=1, help="replay ability presses (0 = the old behaviour)")
    ap.add_argument("--shift", type=int, default=0, help="ticks added to every recorded play tick")
    ap.add_argument("--out", default="runs/league/uc_diag/diag.jsonl")
    ap.add_argument("--to-end", action="store_true", help="after the last recorded play run to the end and compare crowns")
    ap.add_argument("--skip", type=int, default=0, help="skip this many games first")
    a = ap.parse_args()
    import rs_rows as RR
    import realsim
    from royalesim_redrive import base_key, deal_order
    royalesim, names, ids, _ = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    b = realsim.RealBattle()
    cat = json.loads(b.catalogue_json())
    why = collections.Counter()
    recs = []
    for n, line in enumerate(open(ROOT / a.replays, encoding="utf-8")):
        if n < a.skip:
            continue
        if n >= a.skip + a.games:
            break
        p = json.loads(line)
        battle = p["battle"]
        print("game", n, [[c["card_key"] for c in battle[s_]["players"][0]["deck"]] for s_ in ("team", "opponent")],
              file=sys.stderr, flush=True)
        decks, forms, levels = [], [], []
        ok = True
        for side in ("team", "opponent"):
            deck, form, level = [], [], []
            for card in battle[side]["players"][0]["deck"]:
                key, f = base_key(card["card_key"])
                name = names.get(key)
                if name is None or name not in ids or name not in b.eids:
                    ok = False
                    break
                deck.append(name); form.append(f); level.append(int(card.get("level") or 11))
            decks.append(deck); forms.append(form); levels.append(level)
        if not ok:
            why["card without an engine id"] += 1
            continue
        plays = {0: [], 1: []}
        for e in sorted(p["events"], key=lambda e: (e["replay_tick_20hz"], e["source_index"])):
            if e["kind"] == "play_card":
                u = e["coordinates"]["native_world_units"]
                plays[0 if e["side"] == "team" else 1].append(
                    (max(1, int(e["replay_tick_20hz"]) + a.shift), names.get(base_key(e["card_key"])[0]), int(u["x"]), int(u["y"])))
        presses = sorted((max(1, int(e["replay_tick_20hz"]) + a.shift), 0 if e["side"] == "team" else 1)
                         for e in p["events"] if e["kind"] == "activate_ability") if a.abilities else []
        pj, pressed = 0, 0
        dealt = []
        for seat in (0, 1):
            order = deal_order(decks[seat], [c for _, c, _, _ in plays[seat]])
            dealt.append(order)
        if None in dealt:
            # the recorded play order fits no four-card cycle (champion out of cycle, Mirror, ...)
            bad = [s for s in (0, 1) if dealt[s] is None]
            champ = any(cat[ids[c]][8] == "CHAMPION" if len(cat[ids[c]]) > 8 else False for s in bad for c in decks[s])
            why["no deal order fits the recorded plays"] += 1
            recs.append(dict(game=n, stop="no_deal_order", seats=bad, champion_in_deck=bool(champ),
                             decks=[decks[s] for s in bad]))
            continue
        perm = [[decks[s].index(c) for c in dealt[s]] for s in (0, 1)]
        tower = max(1, min(16, int(np.median([lv for s in levels for lv in s]))))
        b.set_command_delay_ticks(0, 0)
        try:
            b.reset(seed=0, decks=[[ids[c] for c in dealt[t]] for t in (0, 1)], shuffle=0, start_tick=0,
                    elixir_milli=None, tower_hp=None, spawns=[], forms=[[forms[t][i] for i in perm[t]] for t in (0, 1)],
                    levels=[[levels[t][i] for i in perm[t]] for t in (0, 1)], tower_levels=[tower, tower])
        except Exception as exc:              # engine_bc drops such a game whole (its try/except)
            why["reset failed: " + str(exc).split(":")[0][-60:].split(" has ")[-1]] += 1
            recs.append(dict(game=n, stop="reset_failed", error=str(exc)[:200]))
            continue
        queue = sorted((t, s, c, x, y) for s in (0, 1) for (t, c, x, y) in plays[s])
        end = min((queue[-1][0] if queue else 0) + 200, 6000)
        tick, i = 0, 0
        issues = {0: [], 1: []}            # per team: (play number, kind, detail) before the stop
        done = {0: 0, 1: 0}
        stop = None
        crown_ticks = [[], []]
        while tick <= end:
            s = json.loads(b.state_json())
            for t in (0, 1):
                if s["players"][t]["crowns"] > len(crown_ticks[t]):
                    crown_ticks[t].append(tick)
            if s["game_over"]:
                # engine crowns and when each fell, against the recorded final crowns
                stop = dict(stop="engine_game_over_early", tick=tick, left=len(queue) - i,
                            crown_ticks=crown_ticks, real_crowns=[battle["team"]["crowns"], battle["opponent"]["crowns"]],
                            hp=[[round(h / max(1, m), 2) for h, m in zip(pl_["tower_hp"], pl_["tower_max_hp"])]
                                for pl_ in s["players"]], tower_level=tower,
                            last_real_play=queue[-1][0]) if i < len(queue) else None
                break
            while i < len(queue) and queue[i][0] <= tick:
                _, team, card, x, y = queue[i]
                i += 1
                cid = ids[card]
                pl = s["players"][team]
                if cid not in pl["hand"]:
                    stop = dict(stop="card_not_in_hand", tick=tick, team=team, card=card, play_no=done[team],
                                of=len(plays[team]), hand=[cat[c][0] for c in pl["hand"]],
                                earlier=issues[team][-3:], game_plays_left=len(queue) - i + 1)
                    break
                k = pl["hand"].index(cid)
                short = pl["hand_costs"][k] * 1000 - pl["elixir_milli"]
                if short > 0:
                    issues[team].append((done[team], "elixir_short_milli", int(short), card))
                dep = b.check_deploy(team, k, x * sub, y * sub)
                if dep != 0:
                    issues[team].append((done[team], "deploy_refused", int(dep), card))
                b._sync()
                b._play(team, b.deck[team].index(cid), int(x), int(y), b.eng.t)
                done[team] += 1
            if stop:
                break
            while pj < len(presses) and presses[pj][0] <= tick:
                team = presses[pj][1]
                pj += 1
                ready = [k for k, row in enumerate(s["players"][team].get("abilities") or []) if row[0]]
                if ready:
                    b._ability(team, ready[0])
                    pressed += 1
            nxt = queue[i][0] if i < len(queue) else end + 1
            if pj < len(presses):
                nxt = min(nxt, presses[pj][0])
            step = max(1, min(nxt, tick + 20) - tick)
            b.step([], step)
            tick += step
        if stop is None:
            why["full game re-driven"] += 1
            rec = dict(game=n, stop="none", issues=[len(issues[0]), len(issues[1])], pressed=[pressed, len(presses)])
            if a.to_end:
                # Exact-match measure (2026-11-16): no more inputs exist after the last
                # recorded play, so the engine alone must reach the recorded final crowns.
                # The replay holds crowns only, no tower hit points, so equal crowns is a
                # necessary sign of an exact re-drive, not a proof of one.
                s = json.loads(b.state_json())
                while not s["game_over"] and tick < 9800:
                    b.step([], 20)
                    tick += 20
                    s = json.loads(b.state_json())
                eng = [s["players"][0]["crowns"], s["players"][1]["crowns"]]
                real = [battle["team"]["crowns"], battle["opponent"]["crowns"]]
                clean = rec["issues"] == [0, 0] and pressed == len(presses)
                rec.update(engine_winner=s.get("winner"), real_result=battle.get("result"),
                           hp=[[int(h) for h in pl_["tower_hp"]] for pl_ in s["players"]])
                rec.update(engine_crowns=eng, real_crowns=real, end_tick=tick, over=bool(s["game_over"]),
                           last_real_play=queue[-1][0] if queue else 0, crowns_equal=eng == real, clean=clean,
                           winner_equal=(eng[0] > eng[1]) - (eng[0] < eng[1]) == (real[0] > real[1]) - (real[0] < real[1]))
                why["to end: crowns equal, no issue" if eng == real and clean else
                    "to end: crowns equal, with issues" if eng == real else
                    "to end: winner equal, crowns differ" if rec["winner_equal"] else "to end: winner differs"] += 1
            recs.append(rec)
        else:
            if stop["stop"] == "card_not_in_hand":
                kinds = {x[1] for x in issues[stop["team"]]}
                tag = "after elixir shortfall" if "elixir_short_milli" in kinds else \
                    "after refused deploy" if "deploy_refused" in kinds else "no earlier issue seen"
                why[f"card not in hand, {tag}"] += 1
                stop["cause"] = tag
            else:
                why[stop["stop"]] += 1
            recs.append(dict(game=n, pressed=[pressed, len(presses)], **stop))
    b.close()
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(json.dumps(r) for r in recs))
    print(json.dumps(dict(why.most_common()), indent=1))


if __name__ == "__main__":
    main()
