"""Unattended run loop: play a block of matches, review, prune, repeat.

This is the process that has to survive two days without a human.  Everything
it does is therefore either idempotent or bounded:

* the bot runs with a hard wall-clock timeout as well as a match limit, so a
  hung emulator costs one block rather than the whole run,
* every block is committed to git before the reviewer touches anything, and a
  review that breaks the tests is reset rather than left in place,
* disk is pruned every block because the machine has limited free space and an
  unattended run that fills the disk takes the desktop down with it,
* a heartbeat file lets an outside watchdog (or a takeover agent) tell the
  difference between "working" and "wedged".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
LIVE = ROOT / "tmp" / "live"
STATE_PATH = LIVE / "supervisor_state.json"
LOG_PATH = LIVE / "supervisor.log"

KEEP_MATCH_FILES = 400
KEEP_BLOCK_LOGS = 40
MAX_LOG_MB = 25


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def write_state(**fields) -> None:
    state = {}
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    state.update(fields)
    state["heartbeat"] = datetime.now().isoformat(timespec="seconds")
    state["heartbeat_epoch"] = time.time()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")


def adb_ok(adb: Path, serial: str) -> bool:
    try:
        out = subprocess.run([str(adb), "devices"], capture_output=True, text=True,
                             timeout=60).stdout
        return f"{serial}\tdevice" in out
    except Exception:
        return False


def revive_adb(adb: Path, serial: str) -> bool:
    """The MuMu adb server drops the device after a suspend or a crash."""
    for args in (("connect", serial), ("kill-server",), ("start-server",),
                 ("connect", serial)):
        try:
            subprocess.run([str(adb), *args], capture_output=True, timeout=60)
        except Exception:
            pass
        time.sleep(2)
        if adb_ok(adb, serial):
            return True
    return False


def kill_tree(pid: int) -> None:
    """Kill a review and the agent CLI it spawned.

    Killing only the Python wrapper leaves the agent process holding its API
    session open, which is exactly the state that wedged the loop before.
    """
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=60)
    except Exception as exc:
        log(f"KILL failed for {pid}: {exc}")


def prune(free_gb_floor: float = 12.0) -> None:
    """Keep the run from ever being the reason the disk fills up."""
    frames = LIVE / "frames"
    removed = 0
    if frames.exists():
        for path in frames.glob("*"):
            try:
                path.unlink()
                removed += 1
            except Exception:
                pass

    for pattern, keep in (
        (LIVE / "matches", KEEP_MATCH_FILES),
        (LIVE / "katacr_results", 40),
        (LIVE / "blocks", KEEP_BLOCK_LOGS),
    ):
        if not pattern.exists():
            continue
        files = sorted(pattern.glob("*"), key=lambda p: p.stat().st_mtime)
        for path in files[:-keep] if len(files) > keep else []:
            try:
                path.unlink()
                removed += 1
            except Exception:
                pass

    for path in (LIVE / "cr_bot.log", LOG_PATH):
        try:
            if path.exists() and path.stat().st_size > MAX_LOG_MB * 1024 * 1024:
                tail = path.read_text(encoding="utf-8", errors="ignore")[-2_000_000:]
                path.write_text(tail, encoding="utf-8")
        except Exception:
            pass

    try:
        import shutil
        free_gb = shutil.disk_usage(str(ROOT)).free / 1e9
        log(f"PRUNE removed={removed} free={free_gb:.1f}GB")
        if free_gb < free_gb_floor:
            # Last resort: match screenshots are the only thing here big enough
            # to matter, and the JSON records keep the review loop working.
            for path in sorted((LIVE / "matches").glob("*.png"))[:-40]:
                path.unlink(missing_ok=True)
            log("PRUNE low disk: dropped older match screenshots")
    except Exception as exc:
        log(f"PRUNE stat failed: {exc}")


def play_block(adb: Path, serial: str, matches: int, timeout: int,
               rl: Path | None = None) -> int:
    cmd = [
        str(PYTHON), "scripts/cr_bot.py", "--adb", str(adb), "--serial", serial,
        "--max-matches", str(matches), "--hours", str(round(timeout / 3600.0, 3)),
        "--vision", "yolo",
        # Reference crops of units as they render on this device. Bounded at 6
        # per class by MAX_PER_CLASS, so this gathers roughly 1200 small files
        # and then stops - it is not a training set and running longer does not
        # make it one. The crops carry our own detector's labels, so they are
        # for looking at, never for training on.
        "--harvest-sprites",
    ]
    if rl is not None:
        # The learned policy decides on its own. The advisor is omitted rather
        # than passed and ignored: it can only reweight candidates a rule
        # engine produced, and there is no rule engine in this path.
        cmd += ["--rl", str(rl)]
    else:
        cmd += ["--advisor"]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout + 120)
        tail = ((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-6:]
        for line in tail:
            log(f"  bot| {line}")
        return proc.returncode
    except subprocess.TimeoutExpired:
        log("BLOCK bot timed out; killing")
        return 124


def main() -> int:
    parser = argparse.ArgumentParser(description="HastyCR unattended supervisor")
    parser.add_argument("--adb", type=Path,
                        default=Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"))
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--matches", type=int, default=5, help="matches per block")
    parser.add_argument("--block-timeout", type=int, default=2400)
    parser.add_argument("--review-timeout", type=int, default=900)
    parser.add_argument("--no-review", action="store_true")
    parser.add_argument("--max-blocks", type=int)
    parser.add_argument("--rl", type=Path,
                        help="play with a simulator-trained checkpoint instead "
                             "of the rules and the Qwen advisor")
    args = parser.parse_args()

    block = 0
    try:
        block = int(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("block", 0))
    except Exception:
        pass

    consecutive_failures = 0
    review_proc: subprocess.Popen | None = None
    review_started = 0.0
    log(f"SUPERVISOR start block={block} matches_per_block={args.matches}")
    write_state(block=block, status="starting", pid=None)

    while True:
        block += 1
        if args.max_blocks and block > args.max_blocks:
            log("SUPERVISOR max blocks reached")
            return 0

        if not adb_ok(args.adb, args.serial):
            log("ADB device missing; reviving")
            if not revive_adb(args.adb, args.serial):
                log("ADB revive failed; waiting 120s")
                write_state(block=block, status="adb_down")
                time.sleep(120)
                block -= 1
                continue

        write_state(block=block, status="playing", block_started=time.time())
        started = time.time()
        code = play_block(args.adb, args.serial, args.matches,
                          args.block_timeout, args.rl)
        elapsed = round(time.time() - started)
        log(f"BLOCK {block} finished exit={code} in {elapsed}s")

        # A block that ends in seconds means the bot is not actually playing
        # (no emulator, wrong screen, crash on import).  Back off instead of
        # spinning through a hundred empty blocks an hour.
        if elapsed < 60:
            consecutive_failures += 1
            wait = min(600, 30 * consecutive_failures)
            log(f"BLOCK suspiciously short; backing off {wait}s "
                f"(failure {consecutive_failures})")
            write_state(block=block, status="backoff", failures=consecutive_failures)
            time.sleep(wait)
            continue
        consecutive_failures = 0

        prune()

        # Turn the block's measured outcomes into lessons before the next one
        # starts. This runs on the local model, so it costs GPU time rather
        # than any agent's quota, and it is capped so a failure is a no-op.
        try:
            proc = subprocess.run(
                [str(PYTHON), "scripts/lessons.py"], cwd=str(ROOT),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=420,
            )
            summary = (proc.stdout or "").strip().splitlines()
            if summary:
                log(f"LESSONS {summary[0]}")
        except subprocess.TimeoutExpired:
            log("LESSONS timed out")
        except Exception as exc:
            log(f"LESSONS failed: {type(exc).__name__}: {exc}")

        # The review runs alongside the next block rather than in front of it.
        # A review takes as long as a block does, and an emulator sitting on the
        # lobby for twenty minutes out of every forty halves the data the review
        # loop has to work with.  The bot reads config.json live and reloads
        # policy.py on the next block, so a mid-block edit is picked up safely.
        if not args.no_review:
            if review_proc is not None and review_proc.poll() is None:
                # Skipping while a review is stuck means skipping *for ever*: a
                # hung reviewer once blocked four consecutive blocks and the bot
                # played twenty matches with nothing learned from any of them.
                age = time.time() - review_started
                if age > args.review_timeout * 2.5:
                    log(f"REVIEW previous stuck for {age:.0f}s; killing pid={review_proc.pid}")
                    kill_tree(review_proc.pid)
                    review_proc = None
                else:
                    log(f"REVIEW previous still running ({age:.0f}s); skipping this block")
            if review_proc is None or review_proc.poll() is not None:
                if review_proc is not None:
                    log(f"REVIEW previous finished exit={review_proc.returncode}")
                review_proc = subprocess.Popen(
                    [str(PYTHON), "scripts/review.py", "--block", str(block),
                     "--matches", str(args.matches), "--timeout", str(args.review_timeout)],
                    cwd=str(ROOT),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                review_started = time.time()
                log(f"REVIEW block {block} dispatched async pid={review_proc.pid}")

        write_state(block=block, status="idle", last_block_seconds=elapsed)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("SUPERVISOR interrupted")
        sys.exit(0)
