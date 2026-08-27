"""Dispatch a block review to whichever agent CLI is currently available.

Rationale for the ordering
--------------------------
Every CLI on this machine has its own five-hour quota window.  A single
reviewer therefore cannot keep an unattended run improving for two days.  Two
rosters exist:

* REVIEW_ROSTER  - routine per-block reviews.  Cheap models first, because a
  block review is a bounded, well-specified task and burning the strongest
  quota on it leaves nothing for the hard problems.
* TAKEOVER_ROSTER - used when the human-facing session has gone quiet and
  someone has to make judgement calls.  Strongest model first.

An agent that fails with a quota or rate-limit signature is benched for five
hours (its reset window) rather than retried into the same wall.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "tmp" / "live" / "agents_state.json"
PROMPT = ROOT / "scripts" / "review_prompt.md"
PYTHON = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"

BENCH_SECONDS = 5 * 3600
QUOTA_MARKERS = (
    "rate limit", "rate_limit", "quota", "usage limit", "too many requests",
    "429", "insufficient", "exhausted", "credit", "billing", "overloaded",
    "resource_exhausted", "out of tokens",
)


@dataclass
class AgentSpec:
    name: str
    argv: List[str]
    prompt_as_arg: bool = True     # False -> prompt is piped on stdin

    def command(self, prompt: str) -> List[str]:
        return [*self.argv, prompt] if self.prompt_as_arg else list(self.argv)


def _npm(binary: str) -> str:
    """npm shims on Windows are .cmd files; subprocess needs the full name."""
    for candidate in (
        Path(os.environ.get("APPDATA", "")) / "npm" / f"{binary}.cmd",
        Path(os.environ.get("APPDATA", "")) / "npm" / binary,
    ):
        if candidate.exists():
            return str(candidate)
    return binary


AGENTS = {
    "kimi": AgentSpec("kimi", [
        _npm("opencode"), "run", "-m", "opencode-go/kimi-k3", "--auto",
    ]),
    "gemini_pro": AgentSpec("gemini_pro", [
        "agy", "--dangerously-skip-permissions", "--print-timeout", "25m",
        "--model", "Gemini 3.1 Pro (High)", "--print",
    ]),
    "gemini_flash": AgentSpec("gemini_flash", [
        "agy", "--dangerously-skip-permissions", "--print-timeout", "25m",
        "--model", "Gemini 3.6 Flash (High)", "--print",
    ]),
    "claude": AgentSpec("claude", [
        "claude", "--dangerously-skip-permissions", "-p",
    ]),
}

# Gemini leads routine reviews: it returned a clean 97-row unit table first try,
# while the opencode agent spent fifty minutes retrying a 403 domain and blocked
# four blocks' worth of improvements behind it.  Claude stays last so the
# strongest quota is kept for takeover, not for a bounded per-block task.
REVIEW_ROSTER = ["gemini_pro", "kimi", "gemini_flash", "claude"]
TAKEOVER_ROSTER = ["claude", "kimi", "gemini_pro", "gemini_flash"]


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def available(name: str, state: dict) -> bool:
    return time.time() >= float(state.get(name, {}).get("benched_until", 0))


def bench(name: str, state: dict, reason: str) -> None:
    state.setdefault(name, {})
    state[name]["benched_until"] = time.time() + BENCH_SECONDS
    state[name]["reason"] = reason[:200]
    state[name]["benched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)


def looks_like_quota(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in QUOTA_MARKERS)


def run_agent(spec: AgentSpec, prompt: str, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        spec.command(prompt),
        cwd=str(ROOT),
        input=None if spec.prompt_as_arg else prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        shell=False,
    )


def tests_pass() -> tuple[bool, str]:
    proc = subprocess.run(
        [str(PYTHON), "-m", "pytest", "tests/test_brain.py", "-q"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def dispatch(prompt: str, roster: List[str], timeout: int, log) -> Optional[str]:
    """Try each available agent in turn, under a whole-dispatch deadline.

    Without the outer deadline a four-agent roster at a 15 minute per-agent
    timeout can spend an hour failing, which is longer than the block it is
    meant to be reviewing.
    """
    state = load_state()
    deadline = time.time() + timeout * 2
    for name in roster:
        if time.time() >= deadline:
            log("REVIEW dispatch deadline reached; giving up this block")
            break
        if not available(name, state):
            log(f"REVIEW skip {name} benched until "
                f"{time.strftime('%H:%M', time.localtime(state[name]['benched_until']))}")
            continue
        spec = AGENTS[name]
        log(f"REVIEW dispatch -> {name}")
        try:
            proc = run_agent(spec, prompt, min(timeout, max(60, int(deadline - time.time()))))
        except subprocess.TimeoutExpired:
            log(f"REVIEW {name} timed out after {timeout}s")
            continue
        except FileNotFoundError as exc:
            log(f"REVIEW {name} not installed: {exc}")
            bench(name, state, "not installed")
            continue
        blob = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0 and looks_like_quota(blob):
            log(f"REVIEW {name} out of quota; benching 5h")
            bench(name, state, blob[-200:])
            continue
        if proc.returncode != 0:
            log(f"REVIEW {name} exit={proc.returncode}: {blob[-400:]}")
            continue
        # An agent that exits 0 and prints nothing did nothing.  `agy` started
        # doing exactly this at 10:06 on 2026-08-21 and did it for nine blocks
        # straight, returning in ~12s each time; because the exit code was 0 it
        # was reported as "applied by gemini_pro; tests pass" and the roster
        # never fell through to kimi or claude, so the bot went unreviewed for
        # over two hours while the log claimed otherwise.  Silence is a
        # failure, not a review.
        if not blob.strip():
            log(f"REVIEW {name} exit=0 but produced no output; trying next agent")
            continue
        log(f"REVIEW {name} completed ({len(blob)} chars)")
        return name
    log("REVIEW no agent available")
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one block review")
    parser.add_argument("--block", default="0")
    parser.add_argument("--matches", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--roster", choices=["review", "takeover"], default="review")
    parser.add_argument("--log", type=Path, default=ROOT / "tmp" / "live" / "supervisor.log")
    args = parser.parse_args()

    def log(message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
        print(line, flush=True)
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    subprocess.run([str(PYTHON), "scripts/block_report.py", str(args.block),
                    str(args.matches)], cwd=str(ROOT), capture_output=True)

    # A clean commit before the review is what makes a bad review reversible.
    git("add", "-A")
    git("commit", "-m", f"pre-review snapshot block {args.block}")
    before = git("rev-parse", "HEAD").stdout.strip()

    prompt = PROMPT.read_text(encoding="utf-8").replace("<BLOCK>", str(args.block))
    prompt += f"\n\nThe current block identifier is {args.block}.\n"
    agent = dispatch(prompt, REVIEW_ROSTER if args.roster == "review" else TAKEOVER_ROSTER,
                     args.timeout, log)
    if agent is None:
        return 1

    # A reviewer has no memory of the run, so anything it tunes outside a
    # known-safe range is put back before the bot ever sees it.
    try:
        import config_guard
        for key, was, now in config_guard.check():
            log(f"REVIEW guard clamped {key}: {was} -> {now}")
    except Exception as exc:
        log(f"REVIEW guard failed: {type(exc).__name__}: {exc}")

    ok, output = tests_pass()
    if not ok:
        # Revert only what a reviewer is allowed to touch.  A `git reset --hard`
        # here would also throw away whatever the supervisor, the bot, or a
        # concurrently working agent had changed elsewhere in the tree.
        log(f"REVIEW tests FAILED after {agent}; reverting brain to {before[:8]}")
        log(output[-600:])
        git("checkout", before, "--", "scripts/brain", "tests")
        still_ok, _ = tests_pass()
        log(f"REVIEW post-revert tests {'pass' if still_ok else 'STILL FAILING'}")
        git("add", "-A")
        git("commit", "-m", f"revert failed review block {args.block} by {agent}")
        return 2
    git("add", "-A")
    git("commit", "-m", f"block {args.block} review by {agent}")
    log(f"REVIEW block {args.block} applied by {agent}; tests pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
