"""Measure what the bot costs to run, split by who pays for it.

Two budgets that are easy to conflate:

* **Local** - the Ollama advisor on your own GPU. Unmetered; the only cost is
  latency inside the decision loop and electricity.
* **Cloud** - the billed agents: per-block reviews and lesson writing.

Only the second one competes with the quota that has been the constraint on
this project all along, and it turns out to be by far the smaller number.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain.advisor import KEEP_ALIVE, NUM_CTX, SCHEMA, Advisor  # noqa: E402

SNAPSHOT = {
    "elixir": 7.0, "enemy_elixir": 2.0, "multiplier": 1.0, "elapsed": 42,
    "ally_hp": [1.0, 0.5], "enemy_hp": [0.3, 1.0],
    "hand": ["hog_rider", "ice_golem", "cannon", "musketeer"],
    "enemies": [
        {"name": "giant", "lane": "left", "depth": 3},
        {"name": "musketeer", "lane": "left", "depth": 1},
    ],
}


def main() -> int:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    advisor = Advisor()
    prompt = advisor.build_prompt(SNAPSHOT)

    total_in = total_out = total_time = 0.0
    for index in range(runs):
        # Must mirror Advisor._ask exactly, or this measures a configuration
        # the bot never actually runs.
        body = json.dumps({
            "model": advisor.model, "prompt": prompt, "stream": False,
            "think": False, "format": SCHEMA, "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": 80, "temperature": 0.0, "num_ctx": NUM_CTX},
        }).encode("utf-8")
        request = urllib.request.Request(
            advisor.url, data=body, headers={"Content-Type": "application/json"}
        )
        started = time.monotonic()
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
        elapsed = time.monotonic() - started
        prompt_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)
        total_in += prompt_tokens
        total_out += output_tokens
        total_time += elapsed
        print(f"  call {index + 1}: {elapsed:.2f}s  in={prompt_tokens} out={output_tokens}")

    mean_in = total_in / runs
    mean_out = total_out / runs
    mean_time = total_time / runs
    per_call = mean_in + mean_out

    # The worker does the call and *then* sleeps `min_interval`, so one cycle
    # is the sum of the two, not the larger of them.
    interval = mean_time + advisor.min_interval
    calls_per_min = 60.0 / interval

    print(f"\nprompt {len(prompt)} chars")
    print(f"avg latency        {mean_time:.2f}s")
    print(f"avg tokens/call    {per_call:.0f}  (in {mean_in:.0f} / out {mean_out:.0f})")
    print(f"decode rate        {total_out / total_time:.0f} tok/s")
    print(f"\n-- LOCAL (your GPU, unmetered) --")
    print(f"calls/min          {calls_per_min:.0f}")
    print(f"tokens/sec         {per_call * calls_per_min / 60.0:.0f}")
    print(f"tokens/hour        {per_call * calls_per_min * 60.0 / 1000.0:.0f}k")

    print(f"\n-- CLOUD (billed agents) --")
    print("block review       1 agent session per 5 matches (~20 min of play)")
    print("lesson writing     1 agent session per 5 matches")
    print("Roughly 6 metered sessions per hour of play. The CLIs do not report")
    print("token counts, so this is a call rate rather than a measured total -")
    print("but it is bounded by wall-clock, not by how fast the bot plays.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
