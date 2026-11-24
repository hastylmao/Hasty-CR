"""Evaluate each new Hog snapshot of a league run, unattended.

    .venvs\\buildabot\\Scripts\\python.exe tools\\league\\watch.py --name league_v4

For every hog/pool/*.pt not yet scored (the parent, 000000, first, as the
baseline), two fixed tests against the ORIGINAL general model (gen/pool/000000.pt,
never trained, so the yardstick does not move):

* ordinary: full matches from the start, Hog vs ladder decks;
* tower:    matches that start with one enemy princess already down, the
            situation the replays rarely reach (second princess / pocket).

Results go to runs/league/<name>/evals.jsonl. Stops with the run's STOP file.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"


GATE_TEMP = "0.1"


def run_eval(run, ckpt, opp, n, extra):
    out = subprocess.run([str(PY), str(ROOT / "tools/league/actor.py"), "--run", str(run), "--envs", "100",
                          "--eval", str(opp), "--ckpt", str(ckpt), "--eval-matches", str(n),
                          "--hog-share", "1", "--seed", "4242", "--gate-temp", GATE_TEMP, *extra],
                         capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in out.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"error": out.stderr[-500:]}


def promote(run, snap, rec):
    """Copy `snap` to runs/league/BEST_hog.pt when it clearly beats the current
    best: its ordinary 95% lower bound above the best's win rate, and its
    second-crown rate not more than 3 points worse."""
    import shutil
    if (run / "focus_deck.json").exists():
        return                  # another deck's run: never replaces the Hog best
    o, t = rec["ordinary"], rec["tower"]
    if o.get("win_rate") is None or t.get("two_crowns_rate") is None:
        return
    best_file = ROOT / "runs" / "league" / "best.json"
    best = json.loads(best_file.read_text()) if best_file.exists() else None
    if best and not (o["ci95"][0] > best["ordinary"] and t["two_crowns_rate"] >= best["two_crowns"] - 0.03):
        return
    shutil.copy(snap, ROOT / "runs" / "league" / "BEST_hog.pt")
    best_file.write_text(json.dumps({"run": run.name, "snapshot": snap.name, "time": rec["time"],
                                     "ordinary": o["win_rate"], "ordinary_ci95": o["ci95"],
                                     "two_crowns": t["two_crowns_rate"]}, indent=1))
    with (ROOT / "runs" / "league" / "NOTES.md").open("a") as fh:
        fh.write(f"- {rec['time']} auto-promoted {run.name} {snap.name} to BEST_hog.pt: "
                 f"ordinary {o['win_rate']} {o['ci95']}, 2nd-crown {t['two_crowns_rate']}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="league_v4")
    ap.add_argument("--matches", type=int, default=300)
    ap.add_argument("--gate-temp", default="0.1",
                    help="decoding temperature of the evaluated brain; 1.0 for decks whose imitation "
                         "waits on most decisions (Golem: 0% at 0.1, 52% at 1.0, same snapshot)")
    args = ap.parse_args()
    global GATE_TEMP
    GATE_TEMP = args.gate_temp
    run = ROOT / "runs" / "league" / args.name
    opp = run / "gen" / "pool" / "000000.pt"
    log = run / "evals.jsonl"
    done = set()
    if log.exists():
        for l in log.read_text().splitlines():
            try:
                done.add(json.loads(l)["snapshot"])
            except (ValueError, KeyError):
                pass
    while True:
        snaps = sorted((run / "hog" / "pool").glob("*.pt"))
        todo = [p for p in snaps if p.name not in done]
        if not todo:
            time.sleep(60)
            continue
        snap = todo[-1] if snaps[0].name in done else snaps[0]   # newest, after the baseline
        ordinary = run_eval(run, snap, opp, args.matches, [])
        tower = run_eval(run, snap, opp, args.matches // 2, ["--eval-tower"])
        # Harder, moving yardstick: the newest snapshot of the general brain,
        # which trains alongside Hog. Reported, not used for promotion.
        gens = sorted((run / "gen" / "pool").glob("*.pt"))
        hard = run_eval(run, snap, gens[-1], args.matches // 2, []) if gens else {}
        rec = {"snapshot": snap.name, "time": time.strftime("%Y-%m-%d %H:%M"),
               "ordinary": {k: ordinary.get(k) for k in ("win_rate", "ci95", "crown_diff", "error")},
               "tower": {k: tower.get(k) for k in ("win_rate", "ci95", "crown_diff", "two_crowns_rate", "error")},
               "vs_latest_gen": {"gen": gens[-1].name if gens else None,
                                 **{k: hard.get(k) for k in ("win_rate", "ci95", "error")}}}
        with log.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)
        done.add(snap.name)
        promote(run, snap, rec)


if __name__ == "__main__":
    sys.exit(main())
