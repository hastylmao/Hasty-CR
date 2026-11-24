"""Train a league run in cycles with an evaluation between them.

This PC cannot evaluate while training (memory), so the run alternates: train for
--hours, stop the learner with its STOP file, evaluate the newest hog snapshot
against a held-out opponent (both seats at the live gate temperature), log the
result, and train again. Stops for good when runs/league/<run>/STOP_ALL exists.

    python tools/league/train_eval_cycle.py --run league_hogreal --hours 2 -- <learner args>

Results: runs/league/<run>/cycle_evals.jsonl (one line per evaluation).

With --gate the evaluation is the champion gate of tools/league/gate.py: train
--gate-updates updates (or --hours, whichever comes first), gate, promote / roll
back / stop. Results: runs/league/<run>/gates.jsonl.
"""
import argparse
import json
import subprocess
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe" if os.name == "nt" else Path(sys.executable)


def newest_snapshot(run):
    snaps = sorted((run / "hog" / "pool").glob("*.pt"))
    return snaps[-1] if snaps else run / "hog" / "latest.pt"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--heldout", default="runs/league/HELDOUT_gen_real1.pt")
    ap.add_argument("--eval-run", default="runs/league/real_eval_hog")
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--gate", action="store_true", help="champion gate between training stretches (gate.py)")
    ap.add_argument("--gate-updates", type=int, default=20, help="focus-brain PPO updates between gates")
    ap.add_argument("--gate-matches", type=int, default=800, help="games against the champion")
    ap.add_argument("--bench-matches", type=int, default=400, help="games against each benchmark")
    ap.add_argument("--promote", type=float, default=0.54, help="head-to-head win rate that promotes")
    ap.add_argument("--bench-tol", type=float, default=0.04, help="benchmark drop below the champion's that fails")
    ap.add_argument("--rollback-after", type=int, default=2, help="bad gates in a row before rolling back")
    ap.add_argument("--max-gates", type=int, default=10, help="gates without a promotion before stopping")
    ap.add_argument("--eval-envs", type=int, default=64)
    ap.add_argument("--gate-tile-temp", type=float, default=0.1,
                    help="gate games: tile temperature of both seats (0 = sampled as in training)")
    ap.add_argument("learner_args", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    # Keep Windows from idle-sleeping while this runs (2026-10-21: the PC went to standby
    # overnight). Per-process request, released when the process exits; no setting changes.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # CONTINUOUS | SYSTEM_REQUIRED
    run = ROOT / "runs" / "league" / a.run
    extra = [x for x in a.learner_args if x != "--"]
    log = run / "cycle_evals.jsonl"
    out = open(ROOT / "runs" / "league" / f"{a.run}.out", "a")
    if a.gate:
        sys.path.insert(0, str(ROOT / "tools"))
        from league import gate as G
        G.TILE_TEMP = a.gate_tile_temp
        st = G.load_state(run)
        G.baseline(run, a, st)
    while not (run / "STOP_ALL").exists():
        (run / "STOP").unlink(missing_ok=True)
        n0 = G.hog_updates(run) if a.gate else 0
        learner = subprocess.Popen([str(PY), str(ROOT / "tools/league/learner.py"), "--name", a.run] + extra,
                                   stdout=out, stderr=subprocess.STDOUT, cwd=ROOT)
        t_end = time.time() + a.hours * 3600
        while time.time() < t_end and learner.poll() is None and not (run / "STOP_ALL").exists():
            if a.gate and G.hog_updates(run) - n0 >= a.gate_updates:
                break
            time.sleep(30)
        if learner.poll() is None:
            (run / "STOP").touch()
            try:
                learner.wait(timeout=900)
            except subprocess.TimeoutExpired:
                learner.kill()
        (run / "STOP").unlink(missing_ok=True)
        time.sleep(20)                       # let the engine servers exit
        if a.gate:
            if (run / "STOP_ALL").exists():
                break
            if G.hog_updates(run) == n0:
                raise SystemExit(f"the learner made no update; see runs/league/{a.run}.out")
            G.gate(run, a, st)
            continue
        snap = newest_snapshot(run)
        r = subprocess.run([str(PY), str(ROOT / "tools/league/actor.py"), "--run", a.eval_run, "--ckpt", str(snap),
                            "--eval", a.heldout, "--eval-matches", str(a.matches), "--envs", "32", os.environ.get("HASTY_EVAL_ENGINE", "--real")],
                           capture_output=True, text=True, cwd=ROOT)
        line = (r.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            res = json.loads(line)
        except ValueError:
            res = {"error": (r.stderr or "")[-400:]}
        res["snapshot"] = snap.name
        res["time"] = time.strftime("%Y-%m-%d %H:%M")
        with open(log, "a") as f:
            f.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    main()
