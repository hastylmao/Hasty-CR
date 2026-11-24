"""Shift a league model's wait bias so that it plays at a low gate temperature.

An imitation model copies how often humans wait (most decisions), so near-greedy
decoding (gate temperature 0.1, what the live bot and the gate use) never plays a
card: version 0 of the Mortar deck scored 0% over 200 real-engine games at 0.1 and
0.3 and 19.5% at 1.0 (2026-11-12); the Golem clone did the same in October.

This finds the one number b for which the model, decoded at --temp, plays as often
as the humans did on imitation rows (engine_bc rows_*.npz; their waits were
subsampled to WAIT_KEEP and are weighted back), and writes a copy of the checkpoint
with wait_head.bias lowered by b * --scale. Nothing else in the model changes.

    .venvs\\buildabot\\Scripts\\python.exe tools/league/calibrate_wait.py --ckpt runs/league/mortar_bc_f/v0.pt
        --rows runs/league/mortar_bc_f --temp 0.1 --out runs/league/mortar_bc_f/v0c.pt
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--temp", type=float, default=0.1)
    ap.add_argument("--scale", type=float, default=1.0, help="multiplies the fitted shift (to test sensitivity)")
    ap.add_argument("--files", type=int, default=14, help="row files used (every 20th: engine_bc's held-out ones)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import torch
    from league.actor import DECIDE
    from league.engine_bc import WAIT_KEEP
    from league.model import LeaguePolicy, gate_logq
    from league.obs import KEYS, trim
    dev = "cuda"
    blob = torch.load(ROOT / a.ckpt, map_location="cpu", weights_only=False)
    m = blob["meta"]
    net = LeaguePolicy(m["n_cards"], m["n_units"], d=m["d"], layers=m["layers"], heads=m["heads"],
                       obs_v=m.get("obs_v", 1))
    net.load_state_dict(blob["model"])
    net.to(dev).eval()
    gates, masks, acts = [], [], []
    for f in sorted((ROOT / a.rows).glob("rows_*.npz"))[::20][:a.files]:
        d = dict(np.load(f))
        for s in range(0, len(d["a"]), 1024):
            b = trim({k: torch.as_tensor(d[k][s:s + 1024]).to(dev) for k in KEYS})
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                g, _, _ = net.heads(b)
            gates.append(g.float().cpu())
            masks.append(torch.as_tensor(d["mask"][s:s + 1024]))
            acts.append(torch.as_tensor(d["a"][s:s + 1024]))
    gate, mask, act = torch.cat(gates), torch.cat(masks), torch.cat(acts)
    # Rows where a card could be played; a kept wait stands for 1 / WAIT_KEEP waits.
    can = mask[:, 1:5].any(1)
    w = torch.where(act == 0, 1.0 / WAIT_KEEP, 1.0)[can]
    human = float((w * (act[can] > 0)).sum() / w.sum())

    def rate(shift):
        g = gate[can].clone()
        g[:, 0] -= shift
        lq = gate_logq(g / a.temp, mask[can], DECIDE)
        return float((w * (1 - lq[:, 0].exp())).sum() / w.sum())

    lo, hi = -20.0, 20.0
    for _ in range(50):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if rate(mid) < human else (lo, mid)
    shift = (lo + hi) / 2
    used = shift * a.scale
    print(f"rows {int(can.sum()):,}  human play rate per decision {human:.4f}  model at temp {a.temp}: "
          f"{rate(0.0):.4f} before, {rate(used):.4f} after  fitted shift {shift:.3f}  applied {used:.3f}")
    blob["model"]["wait_head.bias"] = blob["model"]["wait_head.bias"] - used
    blob["meta"] = dict(m, wait_shift=used, wait_shift_temp=a.temp)
    torch.save(blob, ROOT / a.out)
    print("saved", a.out)


if __name__ == "__main__":
    main()
