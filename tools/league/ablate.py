"""Short ablations of the gated run's training settings (2026-11-12).

Setting A of league_mortar1 lost about 5 points against the held-out model within
its first 10 policy updates (version 0: 66.75%, after 20 and 40 updates: 61.5% and
61.1%, 800 games each) while it gained in the mirror. This runs the same 10 updates
from version 0 with one setting changed at a time and measures each result the same
way: 800 games against the held-out model and 400 mirror games against version 0,
both seats at gate temperature 0.1, tiles at 0.1.

    .venvs\\buildabot\\Scripts\\python.exe tools/league/ablate.py --only ent0,noil

Each setting gets runs/league/abl_<name>/; results go to runs/league/ablate_mortar.jsonl.
The start is version 0's policy with the value head setting A had trained, so no
value-only warm-up is needed. Never run while another training or the live bot runs.
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
SRC = ROOT / "runs/league/league_mortar1"
OUT = ROOT / "runs/league/ablate_mortar.jsonl"

BASE = {"--actors": "2", "--envs": "72", "--rows": "150000", "--epochs": "2", "--batch": "512", "--lr": "2e-5",
        "--kl0": "0.02", "--kl1": "0.02", "--kl-ref": "champion.pt", "--warmup": "0", "--snapshot-every": "100000",
        "--obs-v": "5", "--learn": "hog", "--hog-share": "1", "--shape-w": "0.4", "--gate-temp": "0.3",
        "--ent": "0.003",
        "--opp-shares": "0.4,0.4,0.2", "--opp-il": "runs/league/league_hogreal/gen/parent.pt",
        "--opp-il-temp": "1.0", "--opp-gen": "runs/league/league_hogreal/gen/latest.pt", "--opp-gate-temp": "0.1",
        "--deck-shares": "0.3,0.3,0.4", "--il-dir": "runs/league/mortar_bc_f", "--il-w": "0.2", "--il-steps": "30"}
# name -> changes to BASE (None removes the option)
SETTINGS = {
    "ent0": {"--ent": "0"},                                   # no entropy bonus
    "noil": {"--il-dir": None, "--il-w": None, "--il-steps": None},   # no imitation step
    "lr5e6": {"--lr": "5e-6"},                                # a quarter of the step size
    "same": {},                                               # control: setting A again
    "temp01": {"--gate-temp": "0.1"},                         # train at the fielded temperature
    "kl02": {"--kl0": "0.2", "--kl1": "0.2"},                 # ten times the pull to the champion
    # 2026-11-12 afternoon: settings A and B gained only in the mirror and lost against the
    # held-out model under training-style decoding too, so the training games themselves
    # are suspected: the mirror share, and the Hog-era mid-match / defence starts.
    "nomirror": {"--opp-shares": "0.5,0.5,0"},                # no snapshot (mirror) opponents
    "nostarts": {"--tower-start": "0", "--threat-start": "0"},   # every game from the start
    # The two changes that hurt least, together; run with --updates 30 to see whether the
    # held-out result still slides as it did in setting B (lr 5e-6 alone: 62.4% at 30).
    "b_nostarts": {"--lr": "5e-6", "--tower-start": "0", "--threat-start": "0"},
}


def evaluate(run, ckpt, opp, n, seed, mirror):
    cmd = [str(PY), str(ROOT / "tools/league/actor.py"), "--run", str(run), "--actor", "99", "--ckpt", str(ckpt),
           "--eval", str(opp), "--eval-matches", str(n), "--envs", "64", "--real", "--hog-share", "1",
           "--gate-temp", "0.1", "--eval-tile-temp", "0.1", "--seed", str(seed)] + (["--eval-mirror"] if mirror else [])
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    time.sleep(15)
    if not lines:
        return {"error": (r.stderr or "")[-400:]}
    res = json.loads(lines[-1])
    return {k: res.get(k) for k in ("matches", "win_rate", "ci95", "crown_diff")}


def start_weights(dst):
    import torch
    v0 = torch.load(SRC / "hog/v0.pt", map_location="cpu", weights_only=False)
    trained = torch.load(SRC / "hog/gates/cand_002_v40.pt", map_location="cpu", weights_only=False)
    for k, v in trained["model"].items():
        if k.startswith("ret_head."):
            v0["model"][k] = v
    v0["version"] = 0
    (dst / "pool").mkdir(parents=True, exist_ok=True)
    for name in ("latest.pt", "parent.pt", "champion.pt", "pool/000000.pt"):
        torch.save(v0, dst / name)
    (dst / "meta.json").write_text(json.dumps(v0["meta"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(SETTINGS))
    ap.add_argument("--updates", type=int, default=10)
    a = ap.parse_args()
    for name in a.only.split(","):
        run = ROOT / "runs/league" / f"abl_{name}"
        shutil.rmtree(run, ignore_errors=True)
        run.mkdir(parents=True)
        for f in ("vocab.json", "focus_deck.json"):
            shutil.copy(SRC / f, run / f)
        start_weights(run / "hog")
        args = dict(BASE)
        for k, v in SETTINGS[name].items():
            if v is None:
                args.pop(k, None)
            else:
                args[k] = v
        cmd = [str(PY), str(ROOT / "tools/league/learner.py"), "--name", run.name, "--real"]
        for k, v in args.items():
            cmd += [k, v]
        out = open(run / "learner.out", "w")
        t0 = time.time()
        learner = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=ROOT)
        log = run / "log.jsonl"
        while learner.poll() is None and time.time() - t0 < 3600:
            if log.exists() and len(log.read_text().splitlines()) >= a.updates:
                break
            time.sleep(20)
        (run / "STOP").touch()
        try:
            learner.wait(timeout=900)
        except subprocess.TimeoutExpired:
            learner.kill()
        time.sleep(20)
        rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        rec = {"setting": name, "changes": SETTINGS[name], "updates": len(rows), "time": time.strftime("%Y-%m-%d %H:%M"),
               "train_minutes": round((time.time() - t0) / 60, 1)}
        if rows:
            last = rows[-1]
            rec.update({k: last.get(k) for k in ("entropy", "kl_parent", "act_rate", "button_rate", "il_nll")})
            rec["heldout"] = evaluate(run, run / "hog/latest.pt", ROOT / "runs/league/HELDOUT_gen_real1.pt", 800, 9001, False)
            rec["vs_v0"] = evaluate(run, run / "hog/latest.pt", SRC / "hog/v0.pt", 400, 9002, True)
        with OUT.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    sys.exit(main())
