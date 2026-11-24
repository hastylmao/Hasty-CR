"""Train / live input audit: does the model see the same numbers live as in training?

For every recorded live frame (live_play --record-frames, with the full reader frame
under "raw"), the model's observation is built twice:
  live      the reader frame -> live_bridge.rs_state_from_frame -> league.live spell and
            hero rows -> league.obs.build  (exactly the live path)
  training  the same moment re-created in the real engine by tools/live_redrive.py
            (every play spawned where and when the reader saw it) -> the realsim state
            schema -> league.obs.build  (the path training sees)
Both builds share the live player block (hand, elixir, buttons), so the comparison is
about the board: which units exist, their features, the towers and the spells.

    .venvs/buildabot/Scripts/python.exe tools/audit_inputs.py reports/live_play/<log>.jsonl
        [--deck "Musketeer,Cannon,..."] [--max-frames N]
"""
import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools" / "league"), str(ROOT / "scripts" / "gamestate"), str(ROOT)]
import royalesim  # noqa: E402
import live_redrive as LR  # noqa: E402
import realsim  # noqa: E402
from league import obs as OBS  # noqa: E402

FEATS = ["own", "x", "y", "hp_frac", "flying", "building", "deploying", "vx", "vy", "log_maxhp",
         "target_alive", "target_structure"]


def engine_state(s, deck_rs):
    """A realsim-schema state from an engine state, without a live engine behind it."""
    rb = object.__new__(realsim.RealBattle)
    t = _tables = realsim._tables()
    rb.cat, rb.ut, rb.eids = t["cat"], t["ut"], t["eids"]

    class _E:
        pass
    rb.eng = _E()
    rb.eng.t = s["t"]
    rb.s = s
    rb.deck = [list(deck_rs), list(deck_rs)]
    rb.forms = [[0] * 8, [0] * 8]
    rb.levels = [[16] * 8, [16] * 8]
    rb.pending = [[], []]
    rb.queue = [[], []]
    rb.abil = [[], []]
    rb.pressed = [{}, {}]
    rb.casts = []
    rb.spell_pos = getattr(engine_state, "spell_pos", {})
    st = rb._state()
    engine_state.spell_pos = rb.spell_pos
    return st


def match_units(a, b):
    """Pairs (i, j) of padded unit rows with the same token, nearest own-frame position."""
    ia = [i for i in range(len(a["unit_ids"])) if a["unit_ids"][i] > 0]
    jb = [j for j in range(len(b["unit_ids"])) if b["unit_ids"][j] > 0]
    pairs, used = [], set()
    for i in ia:
        cand = [j for j in jb if j not in used and b["unit_ids"][j] == a["unit_ids"][i]]
        if not cand:
            continue
        fa = a["unit_feats"][i]
        j = min(cand, key=lambda j: (b["unit_feats"][j][1] - fa[1]) ** 2 + (b["unit_feats"][j][2] - fa[2]) ** 2)
        used.add(j)
        pairs.append((i, j))
    ua = [i for i in ia if i not in {p[0] for p in pairs}]
    ub = [j for j in jb if j not in used]
    return pairs, ua, ub


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--deck", default="Musketeer,Cannon,IceSpirits,HogRider,Skeletons,IceGolemite,Log,Fireball")
    ap.add_argument("--heroes", default="Musketeer,IceGolemite")
    ap.add_argument("--max-frames", type=int, default=0)
    a = ap.parse_args()

    import live_bridge as LB
    from league.live import LeagueLive
    import torch
    OBS.setup(royalesim)
    F = OBS.F
    b0 = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    cat = json.loads(b0.catalogue_json())
    unit_types = json.loads(b0.unit_types_json())
    ids = {row[0]: i for i, row in enumerate(cat)}
    deck = a.deck.split(",")
    deck_rs = [ids[c] for c in deck]
    sub = royalesim.SUBTILE_PER_MILLITILE
    blob = torch.load(ROOT / "runs/league/league_hogreal/hog/latest_v8final.pt", map_location="cpu",
                      weights_only=False)
    live = LeagueLive(blob, unit_types, deck, a.heroes.split(","))
    unit_tok = np.arange(len(unit_types), dtype=np.int64) + 2
    name_of_tok = {int(t): unit_types[t - 2] for t in unit_tok}

    stats = {"frames": 0, "feat": collections.defaultdict(list), "only_live": collections.Counter(),
             "only_engine": collections.Counter(), "towers": [], "spells_live": 0, "spells_engine": 0,
             "team_flip": 0, "side_none": 0, "by_unit": collections.defaultdict(list)}
    trackers = {}

    def hook(bi, t, s, units):
        if a.max_frames and stats["frames"] >= a.max_frames:
            return
        raw = LR.RAWS.get((bi, t))
        if raw is None:
            return
        frame, side = raw
        if side is None:
            stats["side_none"] += 1
            return
        ls = LB.rs_state_from_frame(frame, side, deck_rs, unit_types, cat, sub)
        my_team = next((e[F["team"]] for e in ls["entities"] if False), None)
        # our team in RoyaleSim terms: the bridge maps our reader side to the low-y team or not
        kings = [u for u in frame["u"] if (u[10] if len(u) > 10 else "") == "KingTower" and u[3] == side]
        team = 0 if kings and kings[0][5] < 16000 else 1
        es = engine_state(s, deck_rs)
        # the same player block on both sides (hand, elixir, buttons come from the reader)
        tr = trackers.setdefault(bi, (OBS.Tracker(), OBS.Tracker()))
        tr[0].update(ls["entities"], t, sub)
        tr[1].update(es["entities"], t, sub)
        rows, _ = live.hero_rows(ls, team, unit_types, F)
        p = dict(ls["players"][team], abilities=rows)
        players = [p if i == team else ls["players"][i] for i in (0, 1)]
        lst = dict(ls, players=players, spells=live.spell_rows(ls.get("spells_seen") or [], t))
        est = dict(es, players=players)
        mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}, "t0": 0}
        ol = OBS.build(lst, team, mem, t, tr[0], unit_tok, sub)
        oe = OBS.build(est, team, mem, t, tr[1], unit_tok, sub)
        stats["frames"] += 1
        pairs, ua, ub = match_units(ol, oe)
        for i, j in pairs:
            d = ol["unit_feats"][i] - oe["unit_feats"][j]
            for k, v in enumerate(d):
                stats["feat"][k].append(abs(float(v)))
                if abs(float(v)) > 0.05:
                    nm = name_of_tok.get(int(ol["unit_ids"][i]), "?")
                    stats["by_unit"][(k, nm)].append((float(ol["unit_feats"][i][k]), float(oe["unit_feats"][j][k])))
        for i in ua:
            stats["only_live"][name_of_tok.get(int(ol["unit_ids"][i]), "?")] += 1
        for j in ub:
            stats["only_engine"][name_of_tok.get(int(oe["unit_ids"][j]), "?")] += 1
        stats["towers"].append(np.abs(ol["towers"] - oe["towers"]).max())
        stats["spells_live"] += int((ol["spell_ids"] > 0).sum())
        stats["spells_engine"] += int((oe["spell_ids"] > 0).sum())

    LR.HOOK = hook
    sys.argv = [sys.argv[0], a.log]
    LR.main()
    n = stats["frames"]
    print(f"\n==== INPUT AUDIT over {n} frames ====")
    print("Per-unit feature gap, live vs training, on matched units (mean |diff|, share of pairs off by > 0.05):")
    for k in range(len(stats["feat"])):
        v = np.asarray(stats["feat"][k])
        name = FEATS[k] if k < len(FEATS) else f"f{k}"
        print(f"  {k:2d} {name:16s} mean {v.mean():.4f}  off {(v > 0.05).mean() * 100:5.1f}%  (n={len(v)})")
    print("Where the big feature gaps are (feature, unit: count, mean live value, mean training value):")
    for k in (5, 7, 8, 10, 11, 3):
        rows = sorted(((nm, v) for (kk, nm), v in stats["by_unit"].items() if kk == k), key=lambda r: -len(r[1]))[:6]
        for nm, v in rows:
            lv = np.mean([x[0] for x in v]); ev = np.mean([x[1] for x in v])
            print(f"  {FEATS[k]:16s} {nm:24s} n={len(v):4d} live {lv:+.3f} training {ev:+.3f}")
    print("Units the model sees LIVE but training would not (per frame):")
    for k, v in stats["only_live"].most_common(15):
        print(f"  {k:28s} {v / max(1, n):.2f}")
    print("Units in TRAINING that live does not show (per frame):")
    for k, v in stats["only_engine"].most_common(15):
        print(f"  {k:28s} {v / max(1, n):.2f}")
    print(f"Tower inputs: mean max gap {np.mean(stats['towers']):.4f}")
    print(f"Spell rows per frame: live {stats['spells_live'] / max(1, n):.2f}, training {stats['spells_engine'] / max(1, n):.2f}")


if __name__ == "__main__":
    main()
