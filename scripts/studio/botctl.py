"""Start, stop and watch the bot from the studio.

Two decisions worth recording.

**Liveness comes from the process table, not from a handle we kept.**  The bot is
often started from `bot.cmd`, from a terminal, or by the watchdog, and a studio
that only knew about children it spawned itself would show "stopped" while a run
was plainly in progress.  Scanning for `cr_bot.py` / `supervisor.py` in process
command lines reports what is actually true, whoever started it.

**Launching goes through `run.ps1` rather than invoking Python directly.**  That
script does the pre-flight the bot depends on - reconnect ADB, re-apply
`wm size 540x960` for capture speed, check Ollama before promising an advisor -
and duplicating that here would mean two versions of it to keep in step.

The scan is polled on a background thread: enumerating every process costs tens
of milliseconds, which is most of a frame budget at 60fps.
"""

from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psutil

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "run.ps1"
LAUNCH_LOG = ROOT / "tmp" / "live" / "studio" / "launcher.log"

# Script -> label, most specific first.  Matched with the `scripts/` prefix
# attached, and confirmed against the process's working directory, because a
# bare name is not unique on this machine: an unrelated Clash of Clans bot runs
# its own `supervisor.py`, and matching that would have the studio report
# someone else's process as ours and refuse to start.
SIGNATURES = (("supervisor.py", "supervisor"), ("cr_bot.py", "match run"))

POLL_SECONDS = 2.0

# How long a launch is assumed to be in flight but invisible to the scan.
# `run.ps1` does its ADB and Ollama pre-flight before starting Python, so the
# process the scan looks for appears two to three seconds in; 8s is that with
# room for a cold disk, and it only ever delays a *second* start.
LAUNCH_SETTLE_SECONDS = 8.0


def _label_for(line: str) -> Optional[str]:
    for script, label in SIGNATURES:
        for prefix in ("scripts/", "scripts\\"):
            if prefix + script in line:
                return label
    return None


def _in_this_repo(process: psutil.Process, line: str) -> bool:
    """Best effort: the command line names this checkout, or the cwd is it."""
    if str(ROOT) in line:
        return True
    try:
        return Path(process.cwd()) == ROOT
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        # Unreadable cwd: the scripts/ prefix already ruled out the obvious
        # collision, so accept rather than report a live run as stopped.
        return True


@dataclass(frozen=True)
class BotState:
    running: bool = False
    mode: str = "stopped"
    pid: Optional[int] = None
    uptime: float = 0.0
    brain: str = ""
    detail: str = ""


def _scan() -> BotState:
    for process in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
        try:
            info = process.info
            name = (info.get("name") or "").lower()
            if not name.startswith("python"):
                continue
            line = " ".join(info.get("cmdline") or ())
            label = _label_for(line)
            if label and _in_this_repo(process, line):
                # Read the brain off the running command line rather than
                # remembering what we launched: the bot is often started from
                # bot.cmd, a terminal or the watchdog, and "which brain is
                # actually playing" is exactly the thing worth not guessing.
                brain = "rl" if "--rl" in line.split() else "rules"
                return BotState(True, label, info["pid"],
                                time.time() - info["create_time"], brain)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return BotState()


class BotController:
    """Poll the bot's liveness, and start or stop it on request."""

    def __init__(self):
        self.state = _scan()
        self.last_action = ""
        self._launched_at = 0.0
        self._pending: Optional[subprocess.Popen] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="botctl", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.state = _scan()
            except Exception as exc:                 # never take the UI down
                self.last_action = f"scan failed: {type(exc).__name__}: {exc}"
            self._stop.wait(POLL_SECONDS)

    # ---------------------------------------------------------------- actions

    def _launch(self, arguments: list[str], description: str) -> None:
        LAUNCH_LOG.parent.mkdir(parents=True, exist_ok=True)
        # Claim the slot before spawning.  See _guard_is_clear.
        self._launched_at = time.time()
        command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                   "-File", str(LAUNCHER), *arguments]
        try:
            # Detached with its own console-less process group: the bot must
            # outlive the studio, so closing the window mid-run does not end it.
            self._pending = subprocess.Popen(
                command, cwd=str(ROOT),
                stdout=LAUNCH_LOG.open("a", encoding="utf-8"),
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            self.last_action = description
        except Exception as exc:
            self.last_action = f"launch failed: {type(exc).__name__}: {exc}"

    def _guard_is_clear(self) -> bool:
        """Is it safe to start a bot right now?

        `self.state` is refreshed by a poller every POLL_SECONDS, and `run.ps1`
        takes two to three seconds to get as far as a `python.exe` the scan can
        see.  So the cached flag reads "stopped" for several seconds *after* a
        launch, and the two start buttons were both guarded on it alone.

        That is not theoretical.  On 2026-08-22 the studio launched `-Matches 5
        -Hours 2` at 17:03:00 and `-Forever` at 17:03:02; both cleared the guard,
        and two bots then drove the same emulator through the same serial for
        thirteen minutes.  They interleaved into one `cr_bot.log`, each played
        cards out of the other's hand, and the match files written in that window
        are unusable - hand_flips ran to 99 in a match against a clean-run
        baseline of 33, because from either bot's point of view the hand kept
        changing on its own.

        Two gates, because they fail in different ways: a launch we know about
        but the scan cannot see yet, and a re-scan so a bot started from a
        terminal or the watchdog in the last two seconds is also caught.
        """
        if time.time() - self._launched_at < LAUNCH_SETTLE_SECONDS:
            self.last_action = "a launch is still settling; try again"
            return False
        self.state = _scan()
        if self.state.running:
            self.last_action = "already running"
            return False
        return True

    # ------------------------------------------------------------------ brain
    #
    # Which policy decides the plays. `run.ps1` validates the checkpoint and
    # refuses to start rather than falling back to the rules, so a mistyped
    # path is visible instead of quietly playing the wrong brain.

    @staticmethod
    def _brain_arguments(brain: str, checkpoint: str = "") -> list[str]:
        if brain != "rl":
            return []
        arguments = ["-Brain", "rl"]
        if checkpoint:
            arguments += ["-Checkpoint", checkpoint]
        return arguments

    @staticmethod
    def _brain_label(brain: str) -> str:
        return "simulator-trained" if brain == "rl" else "rules + advisor"

    def start_supervisor(self, brain: str = "rules", checkpoint: str = "") -> None:
        """Blocks of 5 matches, reviewed and tuned between blocks, indefinitely."""
        if not self._guard_is_clear():
            return
        self._launch(["-Forever"] + self._brain_arguments(brain, checkpoint),
                     f"started supervisor ({self._brain_label(brain)})")

    def start_matches(self, matches: int, hours: float,
                      brain: str = "rules", checkpoint: str = "",
                      friendly: bool = False) -> None:
        """`friendly` plays without ever pressing Battle.

        For a 1v1 against a person: they start the match, the bot plays
        whatever it finds itself in. Without it the bot taps Battle in the
        lobby and drags itself into ladder between your friendlies.
        """
        if not self._guard_is_clear():
            return
        arguments = ["-Matches", str(int(matches)), "-Hours", f"{hours:g}"]
        arguments += self._brain_arguments(brain, checkpoint)
        if friendly:
            arguments.append("-NoQueue")
        self._launch(
            arguments,
            f"started {int(matches)} matches (cap {hours:g}h, "
            f"{self._brain_label(brain)}"
            f"{', friendly - you start the match' if friendly else ''})")

    def stop(self) -> None:
        # run.ps1 -Stop matches on the command line rather than on a pid, so it
        # also stops a bot this studio did not start.
        self._launch(["-Stop"], "stopping")
