"""Run bounded text-only peer reviews for the latest five-match block.

The reviewers receive metrics, recent log excerpts, and the policy files that
matter most. They do not receive raw frame dumps, which keeps cost and storage
bounded while still giving them enough context to spot bad control logic.
"""

from __future__ import annotations

import argparse
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import analyze_run
import conversion


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tmp" / "live" / "reviews"

PROVIDERS = {
    "claude": {
        "cmd": ["claude", "-p", "--model", "opus", "--permission-mode", "dontAsk"],
        "timeout": 180,
    },
    "opencode": {
        "cmd": [
            str(Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"),
            "run", "-m", "opencode-go/kimi-k3", "--auto",
        ],
        "timeout": 120,
    },
    "agy": {
        # Gemini 3.7 is not exposed by the installed CLI. Use the strongest
        # available Gemini model in low-effort mode for cheap review work.
        "cmd": ["agy", "--model", "Gemini 3.1 Pro (Low)", "--print"],
        "timeout": 120,
    },
}


def tail(path: Path, lines: int) -> str:
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(rows[-lines:])


def snippet(path: Path, max_lines: int = 260) -> str:
    rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if len(rows) > max_lines:
        rows = rows[:max_lines] + [f"... truncated after {max_lines} lines ..."]
    return "\n".join(rows)


def conversion_summary(block_dir: Path) -> str:
    logs = sorted(block_dir.glob("block_*.log"))
    pushes, connected = conversion.stats(logs[-10:])
    if not pushes:
        return "No recent Hog push conversion data."
    return f"Recent Hog pushes: {pushes}; connected: {connected}; rate: {100 * connected / pushes:.0f}%."


def build_prompt(log: Path) -> str:
    return textwrap.dedent(
        f"""
        You are a peer reviewer for a Python Clash Royale Hog 2.6 bot.

        Objective: identify the next high-leverage bug or conservative tuning
        change. Do not edit files. Keep this short: top 5 findings max, each
        with evidence and risk. Assume Hog 2.6 should pressure with Hog Rider,
        cycle cheaply, defend with Cannon/Musketeer, and use Fireball/Log only
        on value or tower finish.

        Current date: {datetime.now():%Y-%m-%d %H:%M:%S}
        Block under review: {log.name}
        True result screen classifier so far: 0 wins across recorded screens.
        {conversion_summary(log.parent)}

        ## Block metrics
        {analyze_run.analyse(log)}

        ## Recent log tail
        {tail(log, 140)}

        ## scripts/policy_shims.py
        {snippet(ROOT / "scripts" / "policy_shims.py")}

        ## scripts/mumu_katacr.py excerpt
        {snippet(ROOT / "scripts" / "mumu_katacr.py", 220)}
        """
    ).strip()


def run_provider(name: str, prompt_file: Path, out_dir: Path) -> int:
    spec = PROVIDERS[name]
    out_path = out_dir / f"{name}.txt"
    message = (
        f"Read {prompt_file} and produce the requested concise peer review. "
        "Do not edit files or run the bot."
    )
    try:
        proc = subprocess.run(
            spec["cmd"] + [message],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=spec["timeout"],
        )
        body = proc.stdout.strip()
        err = proc.stderr.strip()
        out_path.write_text(
            f"provider={name}\nexit={proc.returncode}\n\nSTDOUT\n{body}\n\nSTDERR\n{err}\n",
            encoding="utf-8",
        )
        return proc.returncode
    except Exception as exc:
        out_path.write_text(f"provider={name}\nERROR {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded AI peer reviews")
    parser.add_argument("log", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--providers",
        default="claude,opencode,agy",
        help="comma-separated provider names",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    block_out = args.out_dir / args.log.stem
    block_out.mkdir(parents=True, exist_ok=True)
    prompt = build_prompt(args.log)
    prompt_file = block_out / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    failures = 0
    for name in [p.strip() for p in args.providers.split(",") if p.strip()]:
        if name not in PROVIDERS:
            failures += 1
            (block_out / f"{name}.txt").write_text(f"unknown provider: {name}\n", encoding="utf-8")
            continue
        failures += 1 if run_provider(name, prompt_file, block_out) else 0
    return min(failures, 1)


if __name__ == "__main__":
    raise SystemExit(main())
