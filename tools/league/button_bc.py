"""Teach a league brain's ability buttons from replays, before league training.

A fresh league brain starts with its button logits at -6 (league/model.py), and
PPO never found them: league_v9 pressed 0.035% of decisions after 190 updates,
and live the bot pressed no hero ability in 26 games. The replays hold the
presses (activate_ability events), so this re-drives recorded games through
RoyaleSim, builds the league observation at every decision where the focus
player could press, and fits only the button parts of the network (abil_in,
button_head) to when people pressed. Everything else stays frozen, so card
play is untouched.

    .venvs\\buildabot\\Scripts\\python.exe tools/league/button_bc.py --run league_g1 --focus Golem

Writes the run's hog/latest.pt, parent.pt and pool/000000.pt in place (the
parent is the KL reference, so it must press too or the penalty pulls the
buttons back to -6); the untouched originals go to hog/pre_button/.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

DECIDE = 5


def _decisions(payload, focus, ctx):
    """(obs, mask, label) for every focus-seat decision with a pressable button.
    label: -1 no press within this decision window, else the button index."""
    import rs_rows as RR
    from league import obs as OBS
    from royalesim_redrive import base_key, deal_order
    royalesim, names, ids, unit_tok = ctx
    sub = royalesim.SUBTILE_PER_MILLITILE
    battle = payload["battle"]
    decks, forms, levels = [], [], []
    for side in ("team", "opponent"):
        players = battle[side]["players"]
        if len(players) != 1:
            return []
        deck, form, level = [], [], []
        for card in players[0]["deck"]:
            key, f = base_key(card["card_key"])
            name = names.get(key)
            if name is None or name not in ids:
                return []
            deck.append(name)
            form.append(f)
            level.append(int(card.get("level") or 11))
        decks.append(deck)
        forms.append(form)
        levels.append(level)
    focus_seats = [s for s in (0, 1) if focus <= frozenset(decks[s])]
    if not focus_seats:
        return []
    plays, presses = {0: [], 1: []}, {0: [], 1: []}
    for e in sorted(payload["events"], key=lambda e: (e["replay_tick_20hz"], e["source_index"])):
        seat = 0 if e["side"] == "team" else 1
        if e["kind"] == "play_card":
            u = e["coordinates"]["native_world_units"]
            plays[seat].append((int(e["replay_tick_20hz"]), names.get(base_key(e["card_key"])[0]),
                                int(u["x"]), int(u["y"])))
        elif e["kind"] == "activate_ability":
            c = {ids[n] for n in (names.get(base_key(k)[0]) for k in e.get("ability_source_candidates") or [])
                 if n in ids}
            if c:
                presses[seat].append((int(e["replay_tick_20hz"]), c))
    if not any(presses[s] for s in focus_seats):
        return []
    ys = sorted(y for _, _, _, y in plays[0]) or [0]
    team_seat = 0 if ys[len(ys) // 2] < 16_000 else 1
    dealt = []
    for seat in (0, 1):
        order = deal_order(decks[seat], [c for _, c, _, _ in plays[seat]])
        if order is None:
            return []
        dealt.append(order)
    perm = [[decks[s].index(c) for c in dealt[s]] for s in (0, 1)]
    rs = {0: team_seat, 1: 1 - team_seat}
    seat_of = {rs[0]: 0, rs[1]: 1}
    tower = max(1, min(16, int(np.median([lv for s in levels for lv in s]))))
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    b.reset(seed=0, decks=[[ids[c] for c in dealt[seat_of[t]]] for t in (0, 1)],
            shuffle=0, start_tick=0, elixir_milli=[6000, 6000], tower_hp=None, spawns=[],
            forms=[[forms[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            levels=[[levels[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            tower_levels=[tower, tower])
    focus_teams = {rs[s] for s in focus_seats}
    queue = sorted((t, rs[s], c, x, y) for s in (0, 1) for (t, c, x, y) in plays[s])
    bq = sorted((t, rs[s], tuple(c)) for s in (0, 1) for (t, c) in presses[s])
    press_ticks = {t: sorted(p[0] for p in bq if p[1] == t) for t in (0, 1)}
    mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}, "t0": 0}
    tracker = OBS.Tracker()
    out = []
    tick, i, j = 0, 0, 0
    end = min((queue[-1][0] if queue else 0) + 200, 6000)
    while tick <= end:
        s = json.loads(b.state_json())
        if s["game_over"]:
            break
        tracker.update(s["entities"], tick, sub)
        cmds = []
        while i < len(queue) and queue[i][0] <= tick:
            _, team, card, x, y = queue[i]
            i += 1
            cid = ids[card]
            if team_seat == 1:
                x, y = 18_000 - x, 32_000 - y
            hand = s["players"][team]["hand"]
            if cid not in hand:
                return out          # the re-drive has left the recording
            cmds.append((team, hand.index(cid), x * sub, y * sub))
            mem["seen"][team].add(cid + 2)
            mem["last"][team].append((cid + 2, tick))
        if tick % DECIDE == 0:
            for team in focus_teams:
                p = s["players"][team]
                bar = p["elixir_milli"] - 1000 * int(p.get("pending_cost", 0) or 0)
                mask = np.zeros(7, bool)
                mask[0] = True
                for k in range(4):
                    if k < len(p["hand"]) and p["hand"][k] >= 0 and bar >= p["hand_costs"][k] * 1000:
                        mask[1 + k] = True
                for k, row in enumerate((p.get("abilities") or [])[:2]):
                    if row[0] and not row[1] and bar >= row[2] * 1000:
                        mask[5 + k] = True
                if not mask[5:].any():
                    continue
                label = -1
                soon = [t for t in press_ticks[team] if tick <= t < tick + DECIDE]
                if soon:
                    cands = next(p[2] for p in bq if p[1] == team and p[0] == soon[0])
                    for k, row in enumerate((p.get("abilities") or [])[:2]):
                        if row[3] in cands and mask[5 + k]:
                            label = k
                out.append((OBS.build(s, team, mem, tick, tracker, unit_tok, sub), mask, label))
        while j < len(bq) and bq[j][0] <= tick:
            _, team, cands = bq[j]
            j += 1
            for k, row in enumerate(s["players"][team].get("abilities") or []):
                if row[3] in cands and row[0] and not row[1]:
                    cmds.append((team, 4 + k, 0, 0))
                    break
        nxt = min(queue[i][0] if i < len(queue) else end + 1, bq[j][0] if j < len(bq) else end + 1,
                  (tick // DECIDE + 1) * DECIDE)
        step = max(1, nxt - tick)
        b.step(cmds, step)
        tick += step
    return out


def _work(texts, focus, vocab_path):
    import rs_rows as RR
    from league import obs as OBS
    royalesim, names, ids, _ = RR._setup()
    OBS.setup(royalesim)
    vocab = json.loads(Path(vocab_path).read_text())
    unit_tok = np.asarray([vocab["units"].get(n, 0) for n in vocab["engine_units"]], np.int64)
    ctx = (royalesim, names, ids, unit_tok)
    rows = []
    for t in texts:
        try:
            rows += _decisions(json.loads(t), frozenset(focus), ctx)
        except Exception:
            pass
    if not rows:
        return None
    obs = {k: np.stack([r[0][k] for r in rows]) for k in OBS.KEYS}
    return obs, np.stack([r[1] for r in rows]), np.asarray([r[2] for r in rows], np.int64)


def collect(focus, games, workers, vocab_path):
    import pyarrow.parquet as pq
    import rs_rows as RR
    from royalesim_redrive import CORPUS, base_key
    _, names, _, _ = RR._setup()
    picked = []
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        for r in pq.read_table(part, columns=["game_mode", "payload_json"]).to_pylist():
            if r["game_mode"] not in RR.MODES:
                continue
            p = json.loads(r["payload_json"])
            if not any(e["kind"] == "activate_ability" for e in p["events"]):
                continue
            pl = [p["battle"][s]["players"] for s in ("team", "opponent")]
            if any(len(x) != 1 for x in pl):
                continue
            if any(focus <= {names.get(base_key(c["card_key"])[0]) for c in x[0]["deck"]} for x in pl):
                picked.append(r["payload_json"])
        if len(picked) >= games:
            break
    picked = picked[:games]
    print(f"{len(picked):,} games with presses", flush=True)
    chunks = [picked[k:k + 50] for k in range(0, len(picked), 50)]
    parts = []
    with ProcessPoolExecutor(workers) as pool:
        for n, f in enumerate(as_completed([pool.submit(_work, c, sorted(focus), vocab_path) for c in chunks]), 1):
            r = f.result()
            if r is not None:
                parts.append(r)
            if n % 10 == 0:
                print(f"  {n}/{len(chunks)} chunks", flush=True)
    obs = {k: np.concatenate([p[0][k] for p in parts]) for k in parts[0][0]}
    return obs, np.concatenate([p[1] for p in parts]), np.concatenate([p[2] for p in parts])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--focus", required=True, help="comma-separated cards the pressing player holds")
    ap.add_argument("--games", type=int, default=6000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--collect", action="store_true", help="only re-drive the replays and write the cache")
    args = ap.parse_args()

    from league import obs as OBS
    run = ROOT / "runs" / "league" / args.run
    focus = frozenset(args.focus.split(","))
    cache = run / "button_bc.npz"
    if args.collect:
        obs, mask, label = collect(focus, args.games, args.workers, run / "vocab.json")
        np.savez_compressed(cache, mask=mask, label=label, **obs)
        print(f"wrote {cache}: {len(label):,} decisions, {(label >= 0).sum():,} presses")
        return
    import torch
    from league.actor import _load_policy
    from league.model import gate_logq
    z = np.load(cache)
    obs = {k: z[k] for k in OBS.KEYS}
    mask, label = z["mask"], z["label"]
    pos = label >= 0
    print(f"{len(label):,} decisions with a pressable button, {pos.sum():,} presses "
          f"({pos.mean():.2%})", flush=True)

    dev = "cuda"
    net, meta = _load_policy(str(run / "hog" / "latest.pt"), dev)
    net.float()
    for name, prm in net.named_parameters():
        prm.requires_grad = name.startswith(("abil_in.", "button_head."))
    opt = torch.optim.Adam([p for p in net.parameters() if p.requires_grad], lr=args.lr)
    n = len(label)
    rng = np.random.default_rng(0)
    idx = rng.permutation(n)
    val, tr = idx[: n // 10], idx[n // 10:]

    def batch(ix):
        b = OBS.trim({k: torch.as_tensor(obs[k][ix]).to(dev) for k in OBS.KEYS})
        return b, torch.as_tensor(mask[ix]).to(dev), torch.as_tensor(label[ix]).to(dev)

    def loss_of(ix):
        b, m, y = batch(ix)
        gate, _, _ = net.heads(b)
        lq = gate_logq(gate.float(), m, DECIDE)
        p_btn = lq[:, 5:].exp().clamp(1e-6, 1 - 1e-6)            # per button
        any_btn = p_btn.sum(1).clamp(1e-6, 1 - 1e-6)
        hit = y >= 0
        lp = torch.where(hit, torch.log(p_btn.gather(1, y.clamp(min=0)[:, None])[:, 0]),
                         torch.log1p(-any_btn))
        return -lp.mean(), any_btn

    def evaluate():
        net.eval()
        tot, pr = 0.0, []
        with torch.no_grad():
            for k in range(0, len(val), 2048):
                l, a = loss_of(val[k:k + 2048])
                tot += float(l) * len(val[k:k + 2048])
                pr.append(a.cpu().numpy())
        pr = np.concatenate(pr)
        y = label[val] >= 0
        # Presses per decision the model would make vs people, and how much
        # more it presses where people did.
        return tot / len(val), float(pr.mean()), float(y.mean()), float(pr[y].mean() / max(1e-9, pr[~y].mean()))

    print("before: loss %.4f, model press rate %.4f vs people %.4f, lift %.2f" % evaluate(), flush=True)
    for ep in range(args.epochs):
        net.train()
        rng.shuffle(tr)
        for k in range(0, len(tr), 512):
            l, _ = loss_of(tr[k:k + 512])
            opt.zero_grad()
            l.backward()
            opt.step()
        print(f"epoch {ep}: loss %.4f, model press rate %.4f vs people %.4f, lift %.2f" % evaluate(), flush=True)

    blob = torch.load(run / "hog" / "latest.pt", map_location="cpu", weights_only=False)
    sd = blob["model"]
    for k, v in net.state_dict().items():
        if k.startswith(("abil_in.", "button_head.")):
            sd[k] = v.detach().cpu()
    back = run / "hog" / "pre_button"
    back.mkdir(exist_ok=True)
    for f in ("latest.pt", "parent.pt"):
        if not (back / f).exists():
            shutil.copy(run / "hog" / f, back / f)
        b2 = torch.load(run / "hog" / f, map_location="cpu", weights_only=False)
        for k in sd:
            if k.startswith(("abil_in.", "button_head.")):
                b2["model"][k] = sd[k]
        torch.save(b2, run / "hog" / f)
    shutil.copy(run / "hog" / "latest.pt", run / "hog" / "pool" / "000000.pt")
    print("buttons written to hog/latest.pt, parent.pt, pool/000000.pt", flush=True)


if __name__ == "__main__":
    main()
