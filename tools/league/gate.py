"""Champion gate for a single-deck league run (2026-11-11).

Three real-engine runs in October each got worse on the held-out test and nothing
stopped them. Here a snapshot is kept only when it beats the frozen champion:

  train --gate-updates PPO updates -> stop the learner -> the newest weights
  ("candidate") play, in the real engine, both seats at gate temperature 0.1:
    (tiles of both seats at --gate-tile-temp 0.1, close to the live bot's argmax)
    * --gate-matches games against the champion (mirror match: both on the focus deck);
    * --bench-matches games against each benchmark: the held-out general model on
      ladder decks, and version 0 (mirror) once the champion is no longer version 0.
  Promote: head-to-head >= --promote and no benchmark more than --bench-tol below the
           champion's own result on it. The candidate becomes hog/champion.pt, which
           is also the learner's KL reference (--kl-ref champion.pt).
  Bad gate: head-to-head < 0.5 or a benchmark regression. After --rollback-after bad
           gates in a row the learner restarts from the champion's weights.
  Stop:    --max-gates gates in a row without a promotion (writes STOP_ALL).

Every candidate also goes to hog/pool/ (the snapshot opponents). Evaluation cannot
run while training on this PC (memory), hence the alternation.

Unverified choices, to revisit with data: --promote 0.54 (the plan says 53-55%),
--bench-tol 0.04 (about one standard error of the difference of two 400-game
results), --rollback-after 2. The mirror head-to-head measures the mirror matchup;
the held-out benchmark on ladder decks is the guard against winning only that.

Run through train_eval_cycle.py --gate. Files in runs/league/<run>/:
gates.jsonl (one line per gate), gate_state.json, hog/champion.pt, hog/v0.pt.
"""
import json
import os
import sys
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe" if os.name == "nt" else Path(sys.executable)


# Tile temperature of both seats in gate games (train_eval_cycle --gate-tile-temp).
# The live bot takes the best tile; 0.1 is close to that.
TILE_TEMP = 0.1


def evaluate(run, cand, opp, matches, mirror, envs, seed):
    """Candidate (focus deck, the run's levels) against `opp`, real engine, gate temp 0.1."""
    cmd = [str(PY), str(ROOT / "tools/league/actor.py"), "--run", str(run), "--actor", "99",
           "--ckpt", str(cand), "--eval", str(opp), "--eval-matches", str(matches), "--envs", str(envs),
           os.environ.get("HASTY_EVAL_ENGINE", "--real"), "--hog-share", "1", "--gate-temp", "0.1", "--seed", str(seed)]
    if TILE_TEMP > 0:
        cmd += ["--eval-tile-temp", str(TILE_TEMP)]
    # HASTY_GATE_SPLIT="time,card" (2026-11-23): judge the candidate with split decoding,
    # play-or-wait at `time`, card at `card`, as a run trained that way samples.
    sp = os.environ.get("HASTY_GATE_SPLIT")
    if sp:
        tt, ct = sp.split(",")
        cmd += ["--time-temp", tt, "--card-temp", ct]
    if mirror:
        cmd.append("--eval-mirror")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    lines = [l for l in r.stdout.splitlines() if l.startswith("{")]
    time.sleep(15)                           # let the engine server exit
    if not lines:
        return {"error": (r.stderr or "")[-600:]}
    res = json.loads(lines[-1])
    return {k: res.get(k) for k in ("matches", "win_rate", "ci95", "crown_diff", "seconds")}


def load_state(run):
    f = run / "gate_state.json"
    if f.exists():
        return json.loads(f.read_text())
    return {"gate": 0, "bad": 0, "since_promo": 0, "champion": "v0", "bench": {}}


def save_state(run, st):
    tmp = run / "gate_state.tmp"
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, run / "gate_state.json")


def hog_updates(run):
    f = run / "log.jsonl"
    if not f.exists():
        return 0
    return sum(1 for l in f.read_text().splitlines() if '"brain": "hog"' in l)


def rollback(run):
    """latest.pt <- the champion's weights (the update counter keeps running, so rows
    from the dropped weights are too old to train on); the optimiser state is dropped."""
    import torch
    hog = run / "hog"
    latest = torch.load(hog / "latest.pt", map_location="cpu", weights_only=False)
    champ = torch.load(hog / "champion.pt", map_location="cpu", weights_only=False)
    champ["version"] = latest.get("version", 0) + 1
    # The value head stays the trained one: version 0's is untrained, and after a
    # rollback the learner is past its value-only warm-up, so the policy would be
    # updated from a random value estimate. (The policy does not read this head.)
    for k, v in latest["model"].items():
        if k.startswith("ret_head."):
            champ["model"][k] = v
    torch.save(champ, hog / "latest.tmp")
    os.replace(hog / "latest.tmp", hog / "latest.pt")
    (hog / "opt.pt").unlink(missing_ok=True)


def baseline(run, a, st):
    """The champion's own benchmark results, measured once (gate 0)."""
    hog = run / "hog"
    if not (hog / "v0.pt").exists():
        shutil.copy(hog / "parent.pt", hog / "v0.pt")
    if not (hog / "champion.pt").exists():
        shutil.copy(hog / "v0.pt", hog / "champion.pt")
    if "heldout" not in st["bench"]:
        res = evaluate(run, hog / "champion.pt", ROOT / a.heldout, a.bench_matches, False, a.eval_envs, 4242)
        if res.get("win_rate") is None:
            raise RuntimeError(f"baseline evaluation failed: {res}")
        st["bench"] = {"heldout": res["win_rate"], "v0": 0.5}
        with (run / "gates.jsonl").open("a") as f:
            f.write(json.dumps({"gate": 0, "time": time.strftime("%Y-%m-%d %H:%M"), "baseline": "v0",
                                "heldout": res}) + "\n")
        save_state(run, st)


def gate(run, a, st):
    """One gate on hog/latest.pt. Returns the decision: promote / hold / bad / rollback / stop."""
    import torch
    hog = run / "hog"
    st["gate"] += 1
    version = torch.load(hog / "latest.pt", map_location="cpu", weights_only=False).get("version", 0)
    (hog / "gates").mkdir(exist_ok=True)
    cand = hog / "gates" / f"cand_{st['gate']:03d}_v{version}.pt"
    shutil.copy(hog / "latest.pt", cand)
    seed = 5000 + st["gate"]
    rec = {"gate": st["gate"], "time": time.strftime("%Y-%m-%d %H:%M"), "version": version,
           "champion": st["champion"]}
    rec["vs_champion"] = evaluate(run, cand, hog / "champion.pt", a.gate_matches, True, a.eval_envs, seed)
    rec["heldout"] = evaluate(run, cand, ROOT / a.heldout, a.bench_matches, False, a.eval_envs, 4242)
    if st["champion"] != "v0":
        rec["v0"] = evaluate(run, cand, hog / "v0.pt", a.bench_matches, True, a.eval_envs, 4243)
    h2h = rec["vs_champion"].get("win_rate")
    errors = [k for k in ("vs_champion", "heldout", "v0") if k in rec and rec[k].get("win_rate") is None]
    regress = [k for k in ("heldout", "v0") if k in rec and k not in errors
               and rec[k]["win_rate"] < st["bench"].get(k, 0.5) - a.bench_tol]
    rec["champion_bench"] = dict(st["bench"])
    if errors:
        decision = "error"                    # not counted as a gate result
        st["gate"] -= 1
    elif h2h >= a.promote and not regress:
        decision = "promote"
        shutil.copy(cand, hog / "champion.pt")
        st["champion"] = cand.name
        # The bar never goes down: a benchmark keeps the best result any champion had.
        # (Taking the new champion's own result let the held-out number slide by up
        # to --bench-tol at every promotion: league_mortar2 gate 1, 66.1% -> 62.4%.)
        old = dict(st["bench"])
        st["bench"] = {k: max(rec[k]["win_rate"], old.get(k, 0.0)) for k in ("heldout", "v0") if k in rec}
        st["bench"].setdefault("v0", h2h)     # first promotion: the champion it beat was v0
        st["bad"] = st["since_promo"] = 0
    else:
        st["since_promo"] += 1
        if h2h < 0.5 or regress:
            st["bad"] += 1
            decision = "bad"
        else:
            st["bad"] = 0
            decision = "hold"
        if st["bad"] >= a.rollback_after:
            rollback(run)
            st["bad"] = 0
            decision = "rollback"
        if st["since_promo"] >= a.max_gates:
            decision = "stop"
            (run / "STOP_ALL").touch()
    if decision != "error":
        # every judged candidate joins the snapshot opponents (PFSP picks the ones that still win)
        shutil.copy(cand, hog / "pool" / f"{version:06d}.pt")
    rec.update(decision=decision, regress=regress, errors=errors)
    with (run / "gates.jsonl").open("a") as f:
        f.write(json.dumps(rec) + "\n")
    save_state(run, st)
    print(json.dumps(rec), flush=True)
    return decision
