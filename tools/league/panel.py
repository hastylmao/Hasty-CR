"""Frozen paired panel: rate checkpoints the way the live bot plays (2026-11-23).

Why: the mirror gate promoted models that were no better live, and its held-out
guard was switched off (--bench-tol 1.0) in every run since league_ghost1. Several
reviews agreed promotion needs a fixed, varied set of opponents, the same games for
every candidate, and live decoding.

Each checkpoint plays every panel opponent in the real engine:
  * fixed seed per opponent, so two checkpoints meet the same deals and seats (paired);
  * gate temperature 0.1 and tile temperature 0.01 (about argmax, like live.py);
  * Mortar opponents (v80 and later) play the mirror; generalists play ladder decks.
Results go to runs/league/panel/results.jsonl, one line per (checkpoint, opponent).

  python tools/league/panel.py CKPT [CKPT ...] [--matches 200] [--name label]
  python tools/league/panel.py --table          # print the table of all results

Unverified choices: 200 games per opponent (a 3-point difference on one opponent is
not detectable at that size; the panel mean over 6 opponents is the number to use),
the opponent list, tile temperature 0.01 standing in for argmax.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "league"))
import gate  # noqa: E402

RUN = ROOT / "runs" / "league" / "panel"
PANEL = [  # (name, checkpoint, mirror, seed)
    ("v80", "runs/league/league_ghost2/hog/gates/cand_004_v80.pt", True, 7101),
    ("v120w", "runs/league/league_winonly1/hog/gates/cand_002_v120.pt", True, 7102),
    ("v190", "runs/league/league_joint1/hog/gates/cand_002_v190.pt", True, 7103),
    ("genC", "runs/league/uc_v3/genC.pt", False, 7104),
    ("genD", "runs/league/uc_v4/genD.pt", False, 7105),
    ("heldout", "runs/league/HELDOUT_gen_real1.pt", False, 7106),
]


def run_one(ckpt, label, matches, envs):
    out = RUN / "results.jsonl"
    done = set()
    if out.exists():
        for l in out.read_text().splitlines():
            r = json.loads(l)
            if r.get("matches_req") == matches and r.get("win_rate") is not None:
                done.add((r["label"], r["opp"]))
    gate.TILE_TEMP = 0.01
    for name, opp, mirror, seed in PANEL:
        if (label, name) in done:
            continue
        t = time.time()
        res = gate.evaluate(RUN, Path(ckpt).resolve(), ROOT / opp, matches, mirror, envs, seed)
        rec = dict(label=label, ckpt=str(ckpt), opp=name, matches_req=matches, time=time.strftime("%Y-%m-%d %H:%M"), **res)
        with open(out, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(label, name, res.get("win_rate"), res.get("ci95"), f"{time.time() - t:.0f}s", flush=True)


def table():
    rows = [json.loads(l) for l in (RUN / "results.jsonl").read_text().splitlines()]
    labels = list(dict.fromkeys(r["label"] for r in rows))
    opps = [p[0] for p in PANEL]
    print("label".ljust(14) + "".join(o.rjust(9) for o in opps) + "     mean")
    for lb in labels:
        wr = {r["opp"]: r.get("win_rate") for r in rows if r["label"] == lb and r.get("win_rate") is not None}
        vals = [wr.get(o) for o in opps]
        got = [v for v in vals if v is not None]
        mean = sum(got) / len(got) if got else float("nan")
        print(lb.ljust(14) + "".join((f"{v:9.3f}" if v is not None else "        -") for v in vals) + f"{mean:9.3f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ckpts", nargs="*")
    ap.add_argument("--name", default="", help="label (one checkpoint only)")
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--envs", type=int, default=48)
    ap.add_argument("--table", action="store_true")
    a = ap.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    if a.table:
        return table()
    for c in a.ckpts:
        run_one(c, a.name or Path(c).stem, a.matches, a.envs)
    table()


if __name__ == "__main__":
    main()
