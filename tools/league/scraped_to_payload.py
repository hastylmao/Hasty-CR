"""Scraped RoyaleAPI replays (sqlite queue) -> the payload lines engine_bc.py reads.

The owner's collector (2026-11-12) stores one row per replay in a sqlite file:
queue(tag, battle JSON, state, payload, stats, plays JSON). engine_bc.py --replays
wants one JSON per line in the corpus format (schema royaleapi-battle-actions.v1).
This writes only the fields engine_bc._decisions and _wanted read.

    .venvs\\royalegym\\Scripts\\python.exe tools/league/scraped_to_payload.py
        --db <...>\\replays.sqlite3 --out data/mortar_exact_scraped.jsonl

Mapping, checked against corpus payloads on 2026-11-12:
  * side "blue" is the listed player = "team"; "red" = "opponent".
  * native_world_units = (x, 32000 - y) of the scraped x, y (the corpus has raw
    y 18500 -> native 13500 for a team play and 25500 -> 6500 for an opponent play).
  * In half of the scraped games the listed player's plays sit on the far half
    (median native y >= 16000). Those games are turned by 180 degrees (x -> 18000 - x,
    y -> 32000 - y, both seats). UNVERIFIED whether the true transform is a turn or
    a y-flip only; a whole game mirrored left-right is still a legal game.
  * result "win" / "loss" -> "victory" / "defeat"; anything else is kept as is, and
    --winners-only in engine_bc then drops the game.
  * an ability row (ability = 1, card "_invalid") -> activate_ability with the
    hero cards of that side's deck as candidates.

UNVERIFIED: the scrape has no card levels. Every card is written as level
--level (default 16: these are top-ladder ranked games). The owner's own deck
has cards at 13-15; that is a difference between this data and live play.

The sqlite file is opened read-only.
"""
import argparse
import collections
import json
import sqlite3
from pathlib import Path

RESULT = {"win": "victory", "loss": "defeat"}


UNKNOWN = {"minion-giant", "spirit-empress", "void", "rune-giant"}   # not in the engine build (2026-11-14)


def _base(c):
    for suffix in ("-ev1", "-ev2", "-hero"):
        if c.endswith(suffix):
            return c[:-len(suffix)]
    return c


def convert(tag, battle, plays, level, winner_as_team=False, skip_unknown=False):
    decks = {"team": battle["team_deck"].split(","), "opponent": battle["opponent_deck"].split(",")}
    if skip_unknown and any(_base(c) in UNKNOWN for d in decks.values() for c in d):
        return None, "card the engine does not have"
    # --winner-as-team: the winner becomes the "team" seat (and, after the turn below,
    # the near seat), because engine_bc's rows for the far seat are bad (HANDOFF,
    # 2026-11-13). Games without a winner are dropped.
    swap = False
    if winner_as_team:
        if battle.get("result") not in ("win", "loss"):
            return None, "no winner"
        swap = battle["result"] == "loss"
        if swap:
            decks = {"team": decks["opponent"], "opponent": decks["team"]}
    sides = {"blue": "opponent", "red": "team"} if swap else {"blue": "team", "red": "opponent"}
    if any(len(d) != 8 for d in decks.values()):
        return None, "deck is not 8 cards"
    events = []
    for n, p in enumerate(sorted(plays, key=lambda p: int(p["play_index"]))):
        side = sides.get(p["side"])
        if side is None:
            return None, "unknown side"
        e = {"replay_tick_20hz": int(p["tick"]), "source_index": n, "side": side}
        if str(p["ability"]) == "1":
            e.update(kind="activate_ability", card_key=None, coordinates=None,
                     ability_source_candidates=[c for c in decks[side] if c.endswith("-hero")])
        else:
            try:
                x, y = int(p["x"]), int(p["y"])
            except (TypeError, ValueError):
                return None, "play without a position"
            e.update(kind="play_card", card_key=p["card"], ability_source_candidates=[],
                     coordinates={"native_world_units": {"x": x, "y": 32_000 - y},
                                  "raw_royaleapi_units": {"x": x, "y": y}})
        events.append(e)
    # The corpus always has the listed player on the near half (1 far game in 1,500);
    # the scrape has it on the far half in half of the games. Turn those games by 180
    # degrees so both sources look the same to engine_bc (see the module text).
    ys = sorted(e["coordinates"]["native_world_units"]["y"] for e in events
                if e["kind"] == "play_card" and e["side"] == "team")
    if ys and ys[len(ys) // 2] >= 16_000:
        for e in events:
            if e["kind"] == "play_card":
                u = e["coordinates"]["native_world_units"]
                u["x"], u["y"] = 18_000 - u["x"], 32_000 - u["y"]
                e["coordinates"]["inversion_applied"] = True

    crown_key = {"team": "opponent_crowns", "opponent": "team_crowns"} if swap else {"team": "team_crowns", "opponent": "opponent_crowns"}
    result = "victory" if winner_as_team else RESULT.get(battle.get("result"), battle.get("result"))

    def seat(side, crowns):
        crowns = crown_key[side]
        return {"crowns": int(battle.get(crowns) or 0),
                "players": [{"deck": [{"card_key": c, "level": level} for c in decks[side]]}]}

    return {"schema_version": "royaleapi-battle-actions.v1",
            "source": {"collector": "scraped_to_payload", "replay_tag": tag, "player_tag": battle.get("player_tag"),
                       "battle_time": battle.get("battle_time"), "levels": "assumed"},
            "battle": {"battle_type": battle.get("battle_type"), "result": result,
                       "team": seat("team", "team_crowns"), "opponent": seat("opponent", "opponent_crowns")},
            "events": events}, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--level", type=int, default=16)
    ap.add_argument("--winner-as-team", action="store_true", help="swap seats so the winner is the team seat")
    ap.add_argument("--skip-unknown", action="store_true", help="drop games with a card the engine lacks")
    ap.add_argument("--offset", type=int, default=0, help="skip this many written games (slices of a big scrape)")
    ap.add_argument("--limit", type=int, default=0, help="write at most this many games")
    a = ap.parse_args()
    con = sqlite3.connect("file:" + Path(a.db).as_posix() + "?mode=ro", uri=True)
    skipped, n, seen, good = collections.Counter(), 0, set(), 0
    with open(a.out, "w", encoding="utf-8") as f:
        for tag, battle, plays in con.execute("select tag, battle, plays from queue where state='done' order by tag"):
            if tag in seen or not plays:
                skipped["duplicate or no plays"] += 1
                continue
            seen.add(tag)
            p, why = convert(tag, json.loads(battle), json.loads(plays), a.level, a.winner_as_team, a.skip_unknown)
            if p is None:
                skipped[why] += 1
                continue
            good += 1
            if good <= a.offset:
                continue
            if a.limit and n >= a.limit:
                break
            f.write(json.dumps(p, separators=(",", ":")) + "\n")
            n += 1
    print(f"{n:,} replays -> {a.out}; skipped: {dict(skipped) or 'none'}")


if __name__ == "__main__":
    main()
