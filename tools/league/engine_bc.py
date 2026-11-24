"""Imitation fine-tune of a league brain on pro replays re-driven in the real engine.

RL in the engine (three setups, 2026-10-18..21) kept lowering the held-out result, so
this improves the model the way ClashAI's measured gains came: better inputs and
faithful imitation data. Every replay with the focus cards is re-driven in the
extracted engine (realsim.RealBattle: the real game's mechanics), the obs_v 6 input
(with unit cues: stun / slow / rage / damage over time, attack clock, buffs) is built at
every decision of the focus player, and labelled with what the pro did in that window:
wait, a card and its tile, or an ability press. The model (obs_v 5 upgraded to 6: the
new inputs start at zero weight) is fine-tuned on that with a KL anchor to its start.

    .venvs\\buildabot\\Scripts\\python.exe tools/league/engine_bc.py --start runs/league/league_hogreal/hog/latest_v8final.pt
        --focus HogRider,Musketeer,Cannon --out runs/league/hog_bc6 [--games 4000] [--collect-only]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools"), str(ROOT / "tools" / "league")]

DECIDE = 5
WAIT_KEEP = 0.1
# Set by main() and handed to the workers (_work): rows only from seats whose deck
# shares >= MIN_OVERLAP cards with OVERLAP, and only from the winner's seat.
OVERLAP, MIN_OVERLAP, WINNERS_ONLY = frozenset(), 0, False
OBS_V = 6
TILE_ONLY = False     # --tile-only: train the tile head on the rows' tiles, no gate target


def _own_tile(x, y, team):
    ox, oy = (x, 32_000 - y) if team == 0 else (18_000 - x, y)
    return int(max(0, min(17, ox // 1000)) + 18 * max(0, min(31, oy // 1000)))


def _decisions(payload, focus, ctx, b):
    """(obs, mask, action, tile, tmask) for every focus-player decision.
    action: 0 wait, 1-4 hand slot, 5-6 ability button."""
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
            if name is None or name not in ids or name not in b.eids:
                return []
            deck.append(name)
            form.append(f)
            level.append(int(card.get("level") or 11))
        decks.append(deck)
        forms.append(form)
        levels.append(level)
    focus_seats = [s for s in (0, 1) if focus <= frozenset(decks[s])
                   and len(OVERLAP & frozenset(decks[s])) >= MIN_OVERLAP]
    if WINNERS_ONLY:
        # battle.result is the "team" side's: seat 0 = team, seat 1 = opponent.
        res = battle.get("result")
        won = 0 if res == "victory" else 1 if res == "defeat" else -1
        focus_seats = [s for s in focus_seats if s == won]
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
            # The scrape does not say which unit was pressed and its converter lists
            # only "-hero" cards, so a champion's press had no candidate and was lost.
            # An empty set means "whichever button is available" (see the press loop).
            presses[seat].append((int(e["replay_tick_20hz"]), c))
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
    b.set_command_delay_ticks(0, 0)          # replay ticks are when the play landed
    b.reset(seed=0, decks=[[ids[c] for c in dealt[seat_of[t]]] for t in (0, 1)],
            shuffle=0, start_tick=0, elixir_milli=None, tower_hp=None, spawns=[],
            forms=[[forms[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            levels=[[levels[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            tower_levels=[tower, tower])
    focus_teams = {rs[s] for s in focus_seats}
    queue = sorted((t, rs[s], c, x, y) for s in (0, 1) for (t, c, x, y) in plays[s])
    bq = sorted((t, rs[s], tuple(c)) for s in (0, 1) for (t, c) in presses[s])
    mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}, "t0": 0}
    tracker = OBS.Tracker()
    out = []
    tick, i, j = 0, 0, 0
    end = min((queue[-1][0] if queue else 0) + 200, 6000)
    # HASTY_EXACT_ONLY=1 (2026-11-16): keep a game only when the re-drive stays on the
    # recording to its last play and the engine, run on to its own end, gives the
    # recorded winner. On 300 generic games that was 151; the rest are boards that were
    # never played. The scrape has no tower hit points, so this is a necessary test only.
    exact_only = os.environ.get("HASTY_EXACT_ONLY") == "1"
    while tick <= end:
        s = json.loads(b.state_json())
        if s["game_over"]:
            if exact_only and i < len(queue):
                return []
            break
        tracker.update(s["entities"], tick, sub)
        if tick % DECIDE == 0 and tick >= 60:
            for team in focus_teams:
                p = s["players"][team]
                bar = p["elixir_milli"] - 1000 * int(p.get("pending_cost", 0) or 0)
                mask = np.zeros(7, bool)
                mask[0] = True
                for k in range(4):
                    if k < len(p["hand"]) and bar >= p["hand_costs"][k] * 1000:
                        mask[1 + k] = True
                for k, row in enumerate((p.get("abilities") or [])[:2]):
                    if row[0] and not row[1] and bar >= row[2] * 1000:
                        mask[5 + k] = True
                act, tile, tmask = 0, -1, np.zeros(576, bool)
                nxt = [q for q in queue[i:] if q[1] == team and tick <= q[0] < tick + DECIDE]
                if nxt:
                    _, _, card, x, y = nxt[0]
                    cid = ids[card]
                    if team_seat == 1:
                        x, y = 18_000 - x, 32_000 - y
                    if cid not in p["hand"]:
                        # The re-drive's hand differs from the recording here, so the pro's play
                        # cannot be labelled. Skip the row: counting it as a wait taught passivity
                        # (hog_bc6, 2026-10-22: 1% held-out).
                        continue
                    if cid in p["hand"]:
                        act = 1 + p["hand"].index(cid)
                        mask[act] = True
                        tile = _own_tile(x, y, team)
                        for t in range(576):
                            ox, oy = (t % 18) * 1000 + 500, (t // 18) * 1000 + 500
                            wx, wy = (ox, 32_000 - oy) if team == 0 else (18_000 - ox, oy)
                            tmask[t] = b.check_deploy(team, act - 1, wx * sub, wy * sub) == 0
                        tmask[tile] = True
                else:
                    soon = [q for q in bq[j:] if q[1] == team and tick <= q[0] < tick + DECIDE]
                    if soon:
                        for k, row in enumerate((p.get("abilities") or [])[:2]):
                            if row[3] in soon[0][2]:
                                act = 5 + k
                                mask[act] = True
                out.append((OBS.build(s, team, mem, tick, tracker, unit_tok, sub, obs_v=OBS_V), mask, act, tile,
                            np.packbits(tmask)))
        cmds = []
        while i < len(queue) and queue[i][0] <= tick:
            _, team, card, x, y = queue[i]
            i += 1
            cid = ids[card]
            if team_seat == 1:
                x, y = 18_000 - x, 32_000 - y
            hand = s["players"][team]["hand"]
            if cid not in hand:
                return [] if exact_only else out          # the re-drive has left the recording
            # straight to the engine (RealBattle.step would drop an off-tile play)
            b._sync()
            b._play(team, b.deck[team].index(cid), int(x), int(y), b.eng.t)
            mem["seen"][team].add(cid + 2)
            mem["last"][team].append((cid + 2, tick))
        while j < len(bq) and bq[j][0] <= tick:
            _, team, cands = bq[j]
            j += 1
            rows = list(enumerate(s["players"][team].get("abilities") or []))
            ready = [k for k, row in rows if row[0]]
            pick = ([k for k in ready if rows[k][1][3] in cands] or ready
                    or [k for k, row in rows if row[3] in cands])
            if pick:
                b._ability(team, pick[0])
        nxt_t = min(queue[i][0] if i < len(queue) else end + 1, bq[j][0] if j < len(bq) else end + 1,
                    (tick // DECIDE + 1) * DECIDE)
        step = max(1, nxt_t - tick)
        b.step([], step)
        tick += step
    if exact_only:
        s = json.loads(b.state_json())
        while not s["game_over"] and tick < 9800:
            b.step([], 20)
            tick += 20
            s = json.loads(b.state_json())
        want = {"victory": rs[0], "win": rs[0], "defeat": rs[1], "loss": rs[1]}.get(battle.get("result"), -1)
        if not s["game_over"] or s.get("winner") != want:
            return []
    return out


def _work(texts, focus, vocab_path, dest=None, opts=None):
    global OVERLAP, MIN_OVERLAP, WINNERS_ONLY, OBS_V
    if opts:
        OVERLAP, MIN_OVERLAP, WINNERS_ONLY = frozenset(opts[0]), opts[1], opts[2]
        if len(opts) > 3:
            OBS_V = opts[3]          # workers are fresh processes: without this they built obs_v 6 rows
    import rs_rows as RR
    import realsim
    from league import obs as OBS
    royalesim, names, ids, _ = RR._setup()
    OBS.setup(royalesim)
    vocab = json.loads(Path(vocab_path).read_text())
    unit_tok = np.asarray([vocab["units"].get(n, 0) for n in vocab["engine_units"]], np.int64)
    ctx = (royalesim, names, ids, unit_tok)
    b = realsim.RealBattle()
    rows = []
    for t in texts:
        try:
            rows += _decisions(json.loads(t), frozenset(focus), ctx, b)
        except Exception:
            pass
    b.close()
    # Keep every play and press, a tenth of the waits (weighted x10 in training).
    rng = np.random.default_rng(len(rows))
    rows = [r for r in rows if r[2] > 0 or rng.random() < WAIT_KEEP]
    if not rows:
        return None
    obs = {k: np.stack([r[0][k] for r in rows]) for k in OBS.KEYS}
    res = (obs, np.stack([r[1] for r in rows]), np.asarray([r[2] for r in rows], np.int64),
           np.asarray([r[3] for r in rows], np.int64), np.stack([r[4] for r in rows]))
    if dest is None:
        return res
    # Written here, not sent back: pickling a chunk's arrays to the parent ran out of memory.
    o, m, a, tl, tm = res
    np.savez(dest, mask=m, a=a, tile=tl, tmask=tm, **o)
    return len(a)


def _wanted(p, focus, names, base_key):
    """Does this replay have a seat the options ask for (focus cards, deck overlap, winner)?"""
    pl = [p["battle"][s]["players"] for s in ("team", "opponent")]
    if any(len(x) != 1 for x in pl):
        return False
    res = p["battle"].get("result")
    won = 0 if res == "victory" else 1 if res == "defeat" else -1
    for seat, x in enumerate(pl):
        deck = {names.get(base_key(c["card_key"])[0]) for c in x[0]["deck"]}
        if focus <= deck and len(OVERLAP & deck) >= MIN_OVERLAP and (not WINNERS_ONLY or seat == won):
            return True
    return False


def collect(focus, games, workers, vocab_path, out, replays=None):
    import rs_rows as RR
    from royalesim_redrive import base_key
    _, names, _, _ = RR._setup()
    picked = []
    if replays:      # pre-exported payloads, one JSON per line (the training venv has no pyarrow)
        for line in open(replays, encoding="utf-8"):
            p = json.loads(line)
            if _wanted(p, focus, names, base_key):
                picked.append(line)
            if len(picked) >= games:
                break
    else:
        import pyarrow.parquet as pq
        from royalesim_redrive import CORPUS
        picked = _from_corpus(focus, games, names, base_key, RR, pq, CORPUS)
    picked = picked[:games]
    print(f"{len(picked):,} games with {sorted(focus)}", flush=True)
    return _run(picked, focus, workers, vocab_path, out)


def _from_corpus(focus, games, names, base_key, RR, pq, CORPUS):
    picked = []
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        for r in pq.read_table(part, columns=["game_mode", "payload_json"]).to_pylist():
            if r["game_mode"] not in RR.MODES:
                continue
            p = json.loads(r["payload_json"])
            if _wanted(p, focus, names, base_key):
                picked.append(r["payload_json"])
        if len(picked) >= games:
            break
    return picked


def _run(picked, focus, workers, vocab_path, out):
    """Chunks of 25 games; each chunk's rows go to rows_<chunk>.npz, so a rerun skips
    finished chunks, and a crashed worker pool is restarted on what is left."""
    from concurrent.futures.process import BrokenProcessPool
    chunks = [picked[k:k + 25] for k in range(0, len(picked), 25)]
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for attempt in range(20):
        todo = [n for n in range(len(chunks)) if not (out / f"rows_{n:05d}.npz").exists()
                and not (out / f"empty_{n:05d}").exists()]
        if not todo:
            break
        print(f"attempt {attempt + 1}: {len(todo)} of {len(chunks)} chunks left", flush=True)
        try:
            with ProcessPoolExecutor(workers) as pool:
                futs = {pool.submit(_work, chunks[n], sorted(focus), vocab_path,
                                    str(out / f"rows_{n:05d}.npz"),
                                    (sorted(OVERLAP), MIN_OVERLAP, WINNERS_ONLY, OBS_V)): n for n in todo}
                for k, f in enumerate(as_completed(futs), 1):
                    n = futs[f]
                    if f.result() is None:
                        (out / f"empty_{n:05d}").touch()
                    if k % 5 == 0:
                        done = len(list(out.glob("rows_*.npz")))
                        print(f"  {done}/{len(chunks)} chunks done, {time.time() - t0:.0f}s", flush=True)
        except (BrokenProcessPool, MemoryError):
            print("  a worker died; restarting the pool on the chunks left", flush=True)
            time.sleep(20)
    return len(list(out.glob("rows_*.npz")))


def train(start, out, epochs, lr, kl_w, batch, cue_only=False, name="hog_bc6"):
    import torch
    import torch.nn.functional as F
    from league import obs as OBS
    from league.model import from_league, gate_logq
    dev = "cuda"
    net, meta, version = from_league(start, obs_v=OBS_V)
    ref, _, _ = from_league(start, obs_v=OBS_V)
    net.to(dev).train()
    ref.to(dev).eval()
    files = sorted(out.glob("rows_*.npz"))
    # Streamed one chunk file at a time (all rows at once did not fit in memory);
    # every 20th file is held out.
    hold_files = files[::20]
    train_files = [f for f in files if f not in hold_files]
    print(f"{len(files)} chunk files ({len(train_files)} train / {len(hold_files)} held out)", flush=True)
    params = list(net.parameters())
    if cue_only:
        # Only the new cue inputs learn (unit_in columns 12..17); every weight the
        # league run trained stays frozen, so imitation cannot erase its RL gains.
        for q in params:
            q.requires_grad_(False)
        w = net.unit_in.weight
        w.requires_grad_(True)
        keep = torch.zeros_like(w)
        keep[:, 12:] = 1
        w.register_hook(lambda g: g * keep)
        params = [w]
    opt = torch.optim.AdamW(params, lr=lr, weight_decay=0.0)

    def load(f):
        try:
            return dict(np.load(f))
        except Exception as exc:              # a chunk cut off by a crashed worker
            print(f"skipping {f.name}: {exc}", flush=True)
            return None

    def batch_of(cat, idx):
        b = OBS.trim({k: torch.as_tensor(cat[k][idx]).to(dev) for k in OBS.KEYS})
        mask = torch.as_tensor(cat["mask"][idx]).to(dev)
        a = torch.as_tensor(cat["a"][idx]).to(dev)
        tile = torch.as_tensor(cat["tile"][idx]).to(dev)
        tm = torch.as_tensor(np.unpackbits(cat["tmask"][idx], axis=1)[:, :576].astype(bool)).to(dev)
        return b, mask, a, tile, tm

    def loss_of(b, mask, a, tile, tm, grad=True):
        with torch.autocast("cuda", dtype=torch.bfloat16):
            gate, cls, _ = net.heads(b)
            with torch.no_grad():
                rgate, _, _ = ref.heads(b)
        lq = gate_logq(gate.float(), mask, DECIDE)
        lq_ref = gate_logq(rgate.float(), mask, DECIDE)
        nll = -lq.gather(1, a[:, None])[:, 0]
        nll = nll * torch.where(a == 0, 1.0 / WAIT_KEEP, 1.0)     # waits were subsampled
        p = lq.exp()
        kl = (p * (lq - lq_ref).masked_fill(~mask, 0)).sum(1)
        played = (a >= 1) & (a <= 4) & (tile >= 0)
        tl_loss = torch.zeros((), device=dev)
        acc = torch.zeros((), device=dev)
        if played.any():
            slot = (a[played] - 1).clamp(0, 3)
            card = b["hand"][played].gather(1, slot[:, None])[:, 0]
            with torch.autocast("cuda", dtype=torch.bfloat16):
                tl = net.tile_logits(cls[played], card).float()
            tl = tl.masked_fill(~tm[played], -1e9)
            tl_loss = F.cross_entropy(tl, tile[played])
            acc = (tl.argmax(1) == tile[played]).float().mean()
        if TILE_ONLY:
            # search labels: only the tile is a target; the KL term holds the gate where it was
            return tl_loss + kl_w * kl.mean(), nll.mean(), tl_loss, acc
        return nll.mean() / 5 + tl_loss + kl_w * kl.mean(), nll.mean(), tl_loss, acc

    def evaluate():
        net.eval()
        parts = []
        with torch.no_grad():
            for f in hold_files:
                d = load(f)
                if d is None:
                    continue
                n = len(d["a"])
                parts += [loss_of(*batch_of(d, np.arange(s, min(n, s + batch)))) for s in range(0, n, batch)]
        return (np.mean([float(p[1]) for p in parts]), np.mean([float(p[2]) for p in parts]),
                np.mean([float(p[3]) for p in parts]))

    g, t_ce, acc = evaluate()
    print(f"start: held-out gate nll {g:.4f} tile ce {t_ce:.3f} tile acc {acc:.3f}", flush=True)
    for ep in range(epochs):
        rng = np.random.default_rng(ep)
        for fi in rng.permutation(len(train_files)):
            d = load(train_files[fi])
            if d is None:
                continue
            net.train()
            order = rng.permutation(len(d["a"]))
            for s in range(0, len(order), batch):
                loss, *_ = loss_of(*batch_of(d, order[s:s + batch]))
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
        g, t_ce, acc = evaluate()
        print(f"epoch {ep + 1}: held-out gate nll {g:.4f} tile ce {t_ce:.3f} tile acc {acc:.3f}", flush=True)
    blob = {"model": net.state_dict(), "meta": dict(meta, obs_v=OBS_V, league=True), "version": version}
    torch.save(blob, out / f"{name}.pt")
    print("saved", out / f"{name}.pt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--focus", default="HogRider,Musketeer,Cannon")
    ap.add_argument("--vocab", default="runs/league/league_hogreal/vocab.json")
    ap.add_argument("--out", default="runs/league/hog_bc6")
    ap.add_argument("--games", type=int, default=4000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--kl", type=float, default=0.1)
    ap.add_argument("--batch", type=int, default=512)
    ap.add_argument("--replays", default="", help="JSONL of replay payloads (export with --export under py -3.12)")
    ap.add_argument("--export", default="", help="write the focus deck's payloads from the corpus to this JSONL and stop")
    ap.add_argument("--cue-only", action="store_true", help="train only the cue-input weights")
    ap.add_argument("--name", default="hog_bc6", help="saved model file name (without .pt)")
    ap.add_argument("--overlap", default="", help="deck cards; with --min-overlap: a seat counts only when its deck "
                                                    "shares that many of them (an archetype, not one exact list)")
    ap.add_argument("--min-overlap", type=int, default=0)
    ap.add_argument("--winners-only", action="store_true", help="rows only from the seat that won the game")
    ap.add_argument("--obs-v", type=int, default=6, help="observation version of the trained model")
    ap.add_argument("--tile-only", action="store_true",
                    help="rows are placement-search labels (actor.py --search-labels): tile loss + KL anchor only")
    ap.add_argument("--collect-only", action="store_true")
    ap.add_argument("--train-only", action="store_true")
    a = ap.parse_args()
    global OVERLAP, MIN_OVERLAP, WINNERS_ONLY, OBS_V, TILE_ONLY
    TILE_ONLY = a.tile_only
    OVERLAP, MIN_OVERLAP, WINNERS_ONLY, OBS_V = frozenset(filter(None, a.overlap.split(","))), a.min_overlap, \
        a.winners_only, a.obs_v
    out = ROOT / a.out
    if a.export:
        import pyarrow.parquet as pq
        from royalesim_redrive import CORPUS, base_key
        import rs_rows as RR
        _, names, _, _ = RR._setup()
        picked = _from_corpus(frozenset(filter(None, a.focus.split(","))), a.games, names, base_key, RR, pq, CORPUS)
        with open(ROOT / a.export, "w", encoding="utf-8") as f:
            for t in picked:
                f.write(t.replace(chr(10), " ") + chr(10))
        print(f"exported {len(picked):,} games to {a.export}")
        return
    if not a.train_only:
        collect(frozenset(filter(None, a.focus.split(","))), a.games, a.workers, str(ROOT / a.vocab), out,
                str(ROOT / a.replays) if a.replays else None)
    if not a.collect_only:
        train(ROOT / a.start, out, a.epochs, a.lr, a.kl, a.batch, a.cue_only, a.name)


if __name__ == "__main__":
    main()
