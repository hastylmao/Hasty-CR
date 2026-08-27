"""Run PPO unattended and restart it if the policy collapses.

The first long run against the deck pool died quietly. Entropy reached 0.00 by
a million steps, the policy went deterministic, it stopped playing its win
condition entirely, and it lost thirteen of sixteen evals - while the shaped
return kept climbing, which is exactly what optimising the proxy instead of the
game looks like. Nothing failed, nothing crashed, and it would have burned five
hours if no one had looked.

So this looks. It launches the trainer, watches the entropy it prints, and if
entropy stays flat on the floor for long enough to be a collapse rather than a
dip, it kills the run and starts a new one with a larger entropy bonus.

**It restarts from scratch, not from the checkpoint.** Resuming a collapsed
policy just re-collapses it: the weights are already committed to the
degenerate strategy, and a bigger entropy term applied to them does not undo
that. Losing the steps is the cheaper mistake.

Measured on this project, entropy_coef 0.01 collapses and 0.03 holds at
0.46-0.59 with return still improving. The ladder below starts where the
evidence is and doubles from there.

    python scripts/train_watchdog.py -- --envs 12 --steps 30000000
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable

# Entropy printed by the trainer. Below the floor for `PATIENCE` consecutive
# readings counts as collapse rather than a dip - PPO entropy is noisy, and a
# single low line means nothing.
ENTROPY = re.compile(r"entropy\s+([0-9.]+)")
STEP = re.compile(r"step\s+([0-9,]+)")
FLOOR = 0.08
PATIENCE = 40

# Where to go next when a run collapses. Starts at the value measured to work.
LADDER = [0.03, 0.06, 0.12, 0.25]


def stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def note(message: str, log: Path) -> None:
    line = f"{stamp()} watchdog: {message}"
    print(line, flush=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def run_once(entropy: float, passthrough: list[str], name: str,
             log: Path, floor: float = FLOOR,
             patience: int = PATIENCE) -> tuple[bool, int]:
    """Run the trainer. Returns (collapsed, last step seen)."""
    command = [PYTHON, "-m", "sim.train_ppo",
               "--entropy", str(entropy), "--name", name] + passthrough
    note(f"starting {name} with entropy {entropy}", log)
    process = subprocess.Popen(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1)

    recent: deque[float] = deque(maxlen=patience)
    last_step = 0
    run_log = log.with_name(f"{name}.log")
    with run_log.open("w", encoding="utf-8") as handle:
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            found_step = STEP.search(line)
            if found_step:
                last_step = int(found_step.group(1).replace(",", ""))
            found = ENTROPY.search(line)
            if not found:
                continue
            recent.append(float(found.group(1)))
            if len(recent) == patience and max(recent) < floor:
                note(f"collapsed: entropy below {floor} for {patience} "
                     f"readings at step {last_step:,}", log)
                process.kill()
                process.wait(timeout=60)
                return True, last_step
    process.wait()
    return False, last_step


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="hog26")
    parser.add_argument("--ladder", default=",".join(str(x) for x in LADDER),
                        help="entropy values to try, in order")
    parser.add_argument("--floor", type=float, default=FLOOR)
    parser.add_argument("--patience", type=int, default=PATIENCE)
    parser.add_argument("rest", nargs=argparse.REMAINDER,
                        help="arguments passed straight to sim.train_ppo")
    args = parser.parse_args()
    passthrough = [a for a in args.rest if a != "--"]

    log = ROOT / "tmp" / "rl" / "watchdog.log"
    log.parent.mkdir(parents=True, exist_ok=True)

    ladder = [float(x) for x in args.ladder.split(",") if x.strip()]
    for attempt, entropy in enumerate(ladder):
        name = args.name if attempt == 0 else f"{args.name}_e{entropy}"
        # `--resume` is honoured on the first attempt only. Carrying it into a
        # restart would reload the very checkpoint that just collapsed, which
        # is the one thing this is here to avoid. Resuming a healthy run that
        # was interrupted is a different situation and a good reason to pass
        # it; resuming a collapsed one is not.
        attempt_args = passthrough
        if attempt > 0 and "--resume" in attempt_args:
            index = attempt_args.index("--resume")
            attempt_args = attempt_args[:index] + attempt_args[index + 2:]
            note("dropping --resume: the checkpoint to resume is the "
                 "collapsed one", log)
        collapsed, last_step = run_once(entropy, attempt_args, name, log,
                                        args.floor, args.patience)
        if not collapsed:
            note(f"{name} finished at step {last_step:,}", log)
            return 0
        if attempt + 1 < len(ladder):
            note(f"restarting from scratch at entropy {ladder[attempt + 1]} "
                 f"(a collapsed policy is not worth resuming)", log)
            time.sleep(5)
    note("every entropy on the ladder collapsed; stopping rather than "
         "burning more hours", log)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
