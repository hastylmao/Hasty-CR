"""What does a league model do in a fixed situation, in RoyaleSim?

    .venvs\\buildabot\\Scripts\\python.exe tools\\league\\scenario.py --ckpt runs\\league\\BEST_hog.pt --threat Balloon

Our Hog deck (team 1, high y, the seat live play uses) with a chosen hand;
one enemy unit spawned at our left bridge walking in. The model decides every
5 ticks with the 26-tick delay, exactly as in training; its greedy choices
(and the probabilities behind them) are printed for the first few seconds.
Used to tell a policy weakness (it does the same here) from a live
observation mismatch (it does better here than live).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default=str(ROOT / "runs/league/BEST_hog.pt"))
    ap.add_argument("--threat", default="Balloon")
    ap.add_argument("--x", type=int, default=3500, help="spawn x (world millitiles); 3500 = left lane")
    ap.add_argument("--elixir", type=int, default=7000)
    ap.add_argument("--seconds", type=float, default=6)
    args = ap.parse_args()
    import rs_rows as RR
    from league import obs as OBS
    from league.actor import _load_policy, DELAY, DECIDE, HOG, HOG_FORMS_HERO
    from league.model import gate_logq
    royalesim, names, ids, cat = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    F = OBS.setup(royalesim)
    run = ROOT / "runs/league/league_v8"
    vocab = json.loads((run / "vocab.json").read_text())
    unit_tok = np.asarray([vocab["units"].get(n, 0) for n in vocab["engine_units"]], np.int64)
    net, _ = _load_policy(args.ckpt, "cuda")
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    b.set_command_delay_ticks(DELAY, DELAY)
    enemy = ["Balloon", "Giant", "DarkPrince", "Firecracker", "ElectroWizard", "DarkWitch", "Fireball", "Bats"]
    enemy = [c for c in enemy if c in ids]
    while len(enemy) < 8:
        enemy.append("Knight")
    me = 1
    decks = [None, None]
    decks[me] = [ids[c] for c in HOG]
    decks[1 - me] = [ids[c] for c in enemy[:8]]
    forms = [[0] * 8, [0] * 8]
    forms[me] = HOG_FORMS_HERO
    threat = ids[args.threat]
    # Enemy (team 0, low y) unit at our bridge on the chosen lane, walking in.
    spawns = [(1 - me, threat, args.x * sub, 15500 * sub, -1)]
    b.reset(seed=1, decks=decks, shuffle=0, start_tick=600, elixir_milli=[5000, args.elixir],
            tower_hp=None, spawns=spawns, forms=forms, levels=[[16] * 8, [16] * 8], tower_levels=[16, 16])
    tracker = OBS.Tracker()
    mem = {"seen": {0: {threat + 2}, 1: set()}, "last": {0: [(threat + 2, 600)], 1: []}, "t0": 600}
    for step in range(int(args.seconds * 20 / DECIDE)):
        s = json.loads(b.state_json())
        tracker.update(s["entities"], s["tick"], sub)
        o = OBS.build(s, me, mem, s["tick"], tracker, unit_tok, sub)
        p = s["players"][me]
        mask = np.zeros(7, bool)
        mask[0] = True
        bar = p["elixir_milli"] - 1000 * int(p.get("pending_cost", 0) or 0)
        for k in range(4):
            mask[1 + k] = k < len(p["hand"]) and bar >= p["hand_costs"][k] * 1000
        bt = OBS.trim({k: torch.as_tensor(o[k][None]).cuda() for k in OBS.KEYS})
        with torch.no_grad():
            gate, cls, _ = net.heads(bt)
            lq = gate_logq(gate.float(), torch.as_tensor(mask[None]).cuda(), DECIDE)[0].cpu().numpy()
        pr = np.exp(lq)
        hand = [cat[c][0] for c in p["hand"]]
        line = f"t={s['tick']} elixir {p['elixir_milli'] / 1000:.1f} p_wait {pr[0]:.2f} " + \
               " ".join(f"{h}:{pr[1 + k]:.2f}" for k, h in enumerate(hand))
        threat_e = [e for e in s["entities"] if e[F["team"]] != me and e[F["tower_slot"]] < 0]
        if threat_e:
            ox, oy = OBS.own(threat_e[0][F["x"]] / sub, threat_e[0][F["y"]] / sub, me)
            line += f" | {args.threat} own ({ox / 1000:.1f},{oy / 1000:.1f})"
        a = int(np.argmax(pr))
        cmds = []
        if 1 <= a <= 4:
            card = p["hand"][a - 1]
            with torch.no_grad():
                tl = net.tile_logits(cls, torch.as_tensor([card + 2]).cuda())[0].float().cpu().numpy()
            legal = np.zeros(576, bool)
            for t in range(576):
                ox_, oy_ = (t % 18) * 1000 + 500, (t // 18) * 1000 + 500
                wx, wy = (ox_, 32_000 - oy_) if me == 0 else (18_000 - ox_, oy_)
                legal[t] = b.check_deploy(me, a - 1, wx * sub, wy * sub) == 0
            t = int(np.argmax(np.where(legal, tl, -1e9)))
            ox_, oy_ = (t % 18) * 1000 + 500, (t // 18) * 1000 + 500
            wx, wy = (ox_, 32_000 - oy_) if me == 0 else (18_000 - ox_, oy_)
            cmds.append((me, a - 1, wx * sub, wy * sub))
            line += f"  -> PLAY {cat[card][0]} own tile ({t % 18},{t // 18}) screen ({17 - t % 18},{t // 18})"
        print(line)
        b.step(cmds, DECIDE)


if __name__ == "__main__":
    main()
