"""One imitation candidate from engine_bc rows, measured like version 1 (2026-11-13).

Version 1 (runs/league/mortar_exact_bc2/x_arch_c4.0_btn6.5.pt) came from four manual
steps; this runs them for one candidate so several can run unattended:

  1. fine-tune --start on --rows for --epochs (engine_bc.py --train-only);
  2. fit the wait shift at each of --scales (calibrate_wait.py) and add the hero
     button raise --button (version 0 and 1 use 6.5);
  3. --sweep-matches held-out games per scale on seed 4242, keep the best;
  4. 800 held-out games on seed 9001 (version 0: 66.75%, version 1: 72.9%) and
     800 mirror games against version 1 on seed 7008.

    .venvs\\buildabot\\Scripts\\python.exe tools/league/exact_cycle.py --name e8
        --rows runs/league/mortar_exact_bc3 --start runs/league/mortar_bc_f/v0.pt --epochs 8

Results: one line per candidate in runs/league/exact_cycle.jsonl. The scale is
picked on other seeds than the final 800 games. Never run while another training,
evaluation or the live bot runs.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
RUN = ROOT / "runs/league/league_mortar1"
HELDOUT = ROOT / "runs/league/HELDOUT_gen_real1.pt"
V1 = ROOT / "runs/league/mortar_exact_bc2/x_arch_c4.0_btn6.5.pt"
OUT = ROOT / "runs/league/exact_cycle.jsonl"


def evaluate(ckpt, opp, n, seed, mirror=False):
    cmd = [str(PY), str(ROOT / "tools/league/actor.py"), "--run", str(RUN), "--actor", "99", "--ckpt", str(ckpt),
           "--eval", str(opp), "--eval-matches", str(n), "--envs", "64", "--real", "--hog-share", "1",
           "--gate-temp", "0.1", "--eval-tile-temp", "0.1", "--seed", str(seed)] + (["--eval-mirror"] if mirror else [])
    for _ in range(2):                       # an evaluation that prints nothing is tried once more
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
        lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
        time.sleep(15)
        if lines:
            res = json.loads(lines[-1])
            return {k: res.get(k) for k in ("matches", "win_rate", "ci95", "crown_diff", "plays_per_game", "plays")}
    return {"error": (r.stderr or "")[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--rows", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--lr", default="5e-5")
    ap.add_argument("--kl", default="0.1")
    ap.add_argument("--scales", default="3.5,4.0,4.5")
    ap.add_argument("--sweep-matches", type=int, default=400)
    ap.add_argument("--button", type=float, default=6.5)
    ap.add_argument("--obs-v", type=int, default=5, help="observation version of the rows (7 = towers as tokens)")
    ap.add_argument("--no-train", action="store_true", help="the fine-tuned <rows>/<name>.pt exists already")
    a = ap.parse_args()
    rows = ROOT / a.rows
    rec = {"name": a.name, "rows": a.rows, "start": a.start, "epochs": a.epochs, "lr": a.lr, "kl": a.kl,
           "time": time.strftime("%Y-%m-%d %H:%M"), "files": len(list(rows.glob("rows_*.npz")))}
    if not a.no_train:
        r = subprocess.run([str(PY), str(ROOT / "tools/league/engine_bc.py"), "--start", a.start, "--out", a.rows,
                            "--obs-v", str(a.obs_v), "--name", a.name, "--epochs", str(a.epochs), "--lr", a.lr, "--kl", a.kl,
                            "--train-only"], capture_output=True, text=True, cwd=ROOT)
        rec["train"] = [l for l in r.stdout.splitlines() if "held-out" in l]
        print("\n".join(rec["train"]), flush=True)
    if not (rows / f"{a.name}.pt").exists():
        rec["error"] = "no fine-tuned model"
    else:
        import torch
        sweep = {}
        for sc in a.scales.split(","):
            c = rows / f"{a.name}_c{sc}.pt"
            r = subprocess.run([str(PY), str(ROOT / "tools/league/calibrate_wait.py"), "--ckpt", str(rows / f"{a.name}.pt"),
                                "--rows", a.rows, "--temp", "0.1", "--scale", sc, "--out", str(c)],
                               capture_output=True, text=True, cwd=ROOT)
            blob = torch.load(c, map_location="cpu", weights_only=False)
            blob["model"]["button_head.bias"] = blob["model"]["button_head.bias"] + a.button
            blob["meta"] = dict(blob["meta"], button_shift=a.button)
            torch.save(blob, c)
            sweep[sc] = dict(evaluate(c, HELDOUT, a.sweep_matches, 4242), shift=blob["meta"].get("wait_shift"))
            sweep[sc].pop("plays", None)
            print("sweep", sc, sweep[sc], flush=True)
        rec["sweep"] = sweep
        ok = {sc: v["win_rate"] for sc, v in sweep.items() if v.get("win_rate") is not None}
        if ok:
            best = max(ok, key=ok.get)
            cand = rows / f"{a.name}_c{best}.pt"
            rec.update(best_scale=best, ckpt=str(cand.relative_to(ROOT)).replace("\\", "/"))
            rec["heldout"] = evaluate(cand, HELDOUT, 800, 9001)
            rec["vs_v1"] = evaluate(cand, V1, 800, 7008, mirror=True)
    with OUT.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    sys.exit(main())
