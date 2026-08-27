"""Measure PPO steady-state throughput against the number of parallel envs.

Wall-clock is the budget that matters for an overnight run, and more
environments is the standard lever for it - the cost is sample efficiency,
which is worth paying when the alternative is finishing fewer steps by
morning. There is a knee: this machine has 8 physical cores, each simulator
worker is a Python process, and past the core count the workers only take
time from each other.

Two details make the number honest:

* **The warmup rate is not the rate.** During value warmup the update is a
  value-only backward pass, and it runs at roughly twice the speed of a real
  PPO update. Measuring during warmup overstates a full run by 2x, so this
  passes `--value-warmup 0`.
* **The trainer's own rate is cumulative from process start**, so it carries
  worker spin-up forever. This reads the last stretch of the log and computes
  the rate over that window instead.

Checkpoints are not the point here, so every config writes to the same run
name and overwrites: the sweep costs one 242MB file, not one per config.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
LINE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) step\s+([\d,]+)")


def rate_over_tail(log: Path, window_s: float) -> tuple[float, int]:
    """Steps per second over the last `window_s` of logged progress."""
    samples = []
    for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
        found = LINE.match(raw)
        if found:
            stamp = datetime.strptime(found.group(1), "%Y-%m-%d %H:%M:%S")
            samples.append((stamp, int(found.group(2).replace(",", ""))))
    if len(samples) < 4:
        return 0.0, samples[-1][1] if samples else 0
    last_at, last_step = samples[-1]
    for stamp, step in reversed(samples):
        if (last_at - stamp).total_seconds() >= window_s:
            elapsed = (last_at - stamp).total_seconds()
            return (last_step - step) / elapsed, last_step
    first_at, first_step = samples[0]
    elapsed = max(1e-6, (last_at - first_at).total_seconds())
    return (last_step - first_step) / elapsed, last_step


def measure(envs: int, rollout: int, seconds: float, init: Path) -> float:
    out = ROOT / "tmp" / "rl" / "sweep.out"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")
    command = [
        str(PYTHON), "-m", "sim.train_ppo", "--name", "sweep",
        "--envs", str(envs), "--rollout", str(rollout),
        "--steps", "100000000", "--lr", "5e-5", "--entropy", "0.03",
        "--value-warmup", "0", "--target-kl", "0.02",
        "--eval-every", "1000000000", "--opponent", "meta",
    ]
    if init.exists():
        command += ["--init", str(init)]
    with out.open("w", encoding="utf-8") as stream:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stream,
                                   stderr=subprocess.STDOUT)
        try:
            time.sleep(seconds)
        finally:
            process.kill()
            process.wait(timeout=60)
    # Ignore the first third: workers spin up, and the first updates run
    # before the CPU is saturated.
    steady, reached = rate_over_tail(out, seconds * 0.5)
    print(f"  envs {envs:>3}  rollout {rollout:>4}  "
          f"{steady:6.0f} steps/s  (reached {reached:,})", flush=True)
    return steady


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--envs", type=int, nargs="+", default=[8, 12, 16, 20])
    parser.add_argument("--rollout", type=int, default=128)
    parser.add_argument("--seconds", type=float, default=150.0)
    parser.add_argument("--init", type=Path,
                        default=ROOT / "tmp" / "rl" / "clone_pilot.pt")
    args = parser.parse_args()

    print(f"throughput sweep: {args.seconds:.0f}s per config, "
          f"steady state (no value warmup)", flush=True)
    results = {}
    for envs in args.envs:
        results[envs] = measure(envs, args.rollout, args.seconds, args.init)

    best = max(results, key=results.get)
    print("\n  envs  steps/s  vs best")
    for envs, rate in sorted(results.items()):
        share = rate / results[best] if results[best] else 0.0
        print(f"  {envs:>4}  {rate:7.0f}  {share:6.0%}")
    hours = 14.0
    print(f"\nbest: {best} envs at {results[best]:.0f}/s "
          f"-> {results[best] * 3600 * hours / 1e6:.1f}M steps in {hours:.0f}h")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
