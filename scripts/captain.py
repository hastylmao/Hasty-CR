"""Leadership handoff: make sure *someone* is still steering this run.

The owner is away for two days and every agent CLI on this machine has its own
five-hour quota window, so "the lead agent stopped responding" is the expected
case, not the exceptional one.  This process runs on a timer, checks whether the
current lead has checked in recently, and if not promotes the next agent in the
roster and hands it the standing brief.

Priority order is the owner's: Claude first, then Kimi via opencode, then
Gemini via antigravity.  A benched agent (quota exhausted) is skipped and
retried after its window.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "tmp" / "live"
CAPTAIN_PATH = LIVE / "captain.json"
LOG_PATH = LIVE / "captain.log"
BRIEF = ROOT / "docs" / "AUTONOMOUS_BRIEF.md"

import review as review_mod  # noqa: E402  (same directory, shares the agent roster)

SILENT_SECONDS = 2 * 3600


SHIFT_PROMPT = """You are now the lead agent for the HastyCR autonomous run. The previous
lead ({previous}) has not checked in for {silent_minutes} minutes, so you are taking over.

Read `docs/AUTONOMOUS_BRIEF.md` first - it is the standing brief and explains the whole
system, the coordinate conventions, and the rules for changing anything.

Your shift, in order:

1. Check that the loop is alive:
   - `tmp/live/supervisor_state.json` heartbeat should be under 20 minutes old.
   - A `python.exe ... scripts/supervisor.py` process should exist.
   - If the supervisor is dead, start it:
     `powershell -NoProfile -ExecutionPolicy Bypass -File scripts\\watchdog.ps1`
2. Read `tmp/live/reviews/latest_block.md` and the last 3 files in `tmp/live/matches/`.
3. Judge how the bot is playing. The scoreboard, in priority order, is: crowns for
   minus crowns against; Hog Rider share of cards played (target 15-25%); cards played
   per match; elixir wasted on `defend_fallback_*` plays.
4. Make **at most three** targeted improvements. Prefer `scripts/brain/config.json`
   over `scripts/brain/policy.py`. Verify any game mechanic with web search before
   relying on it - your Clash Royale knowledge is out of date.
5. Run `.venvs\\buildabot\\Scripts\\python.exe -m pytest tests\\test_brain.py -q`.
   If it fails, fix or revert. Never leave the tree failing.
6. Append a dated entry to `docs/RUN_JOURNAL.md` saying what you observed, what you
   changed, and what the next agent should look at.

Do not stop the supervisor. Do not delete anything under `tmp/live/matches/`.
When finished, print CAPTAIN_SHIFT_DONE.
"""


def log(message: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def load_captain() -> dict:
    try:
        return json.loads(CAPTAIN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"lead": "claude_session", "checked_in": 0.0, "shifts": 0}


def save_captain(data: dict) -> None:
    CAPTAIN_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPTAIN_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")


def check_in(who: str) -> None:
    data = load_captain()
    data["lead"] = who
    data["checked_in"] = time.time()
    data["checked_in_human"] = datetime.now().isoformat(timespec="seconds")
    save_captain(data)
    log(f"CHECKIN {who}")


def supervisor_alive() -> bool:
    try:
        state = json.loads((LIVE / "supervisor_state.json").read_text(encoding="utf-8"))
        return time.time() - float(state.get("heartbeat_epoch", 0)) < 20 * 60
    except Exception:
        return False


def ensure_supervisor() -> None:
    if supervisor_alive():
        return
    log("SUPERVISOR heartbeat stale; invoking watchdog")
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(ROOT / "scripts" / "watchdog.ps1")],
        cwd=str(ROOT), capture_output=True, timeout=300,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote a lead agent if the current one went quiet")
    parser.add_argument("--check-in", help="record a check-in for this agent and exit")
    parser.add_argument("--silent-seconds", type=int, default=SILENT_SECONDS)
    parser.add_argument("--timeout", type=int, default=2400)
    parser.add_argument("--force", action="store_true", help="run a shift regardless of silence")
    args = parser.parse_args()

    if args.check_in:
        check_in(args.check_in)
        return 0

    ensure_supervisor()

    data = load_captain()
    silent = time.time() - float(data.get("checked_in", 0))
    if silent < args.silent_seconds and not args.force:
        log(f"LEAD {data.get('lead')} active ({silent / 60:.0f} min ago); nothing to do")
        return 0

    previous = data.get("lead", "unknown")
    prompt = SHIFT_PROMPT.format(previous=previous, silent_minutes=int(silent / 60))
    if BRIEF.exists():
        prompt += "\n---\n" + BRIEF.read_text(encoding="utf-8")

    log(f"LEAD {previous} silent for {silent / 60:.0f} min; promoting a successor")
    agent = review_mod.dispatch(prompt, review_mod.TAKEOVER_ROSTER, args.timeout, log)
    if agent is None:
        log("HANDOFF failed: no agent available; loop continues on the supervisor alone")
        return 1

    data["lead"] = agent
    data["checked_in"] = time.time()
    data["checked_in_human"] = datetime.now().isoformat(timespec="seconds")
    data["shifts"] = int(data.get("shifts", 0)) + 1
    data["previous"] = previous
    save_captain(data)
    log(f"HANDOFF complete: {previous} -> {agent} (shift {data['shifts']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
