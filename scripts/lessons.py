"""Turn measured outcomes into short lessons the advisor reads back.

The bandit in `brain/experience.py` already changes behaviour on its own. This
adds the part that makes the learning *legible*: the model is shown what
actually happened - "skeletons vs musketeer: 12 plays, killed it 9 times,
average +2.4 elixir" - and writes a handful of one-line lessons that are then
injected into its own prompt on every future decision.

It runs on the local model by default, so improving costs nothing but GPU time,
and it is capped hard: a short list of short lines. A prompt that grows without
limit would slow every decision in the loop, and a model given fifty rules
follows none of them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain.advisor import DEFAULT_MODEL, OLLAMA_URL  # noqa: E402
from brain.experience import ExperienceBook  # noqa: E402

LESSONS_PATH = ROOT / "scripts" / "brain" / "lessons.md"
MAX_LESSONS = 10
MAX_LINE = 110

SCHEMA = {
    "type": "object",
    "properties": {
        "lessons": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": MAX_LESSONS,
        }
    },
    "required": ["lessons"],
}

PROMPT = """You are reviewing measured results from a Clash Royale Hog 2.6 bot.
Deck: cannon, fireball, hog_rider, ice_golem, ice_spirit, musketeer, skeletons, the_log.

Each row is one of our cards played against an enemy unit, with what happened:
  n          = how many times
  kill_rate  = fraction of those where that enemy unit died
  mean       = average elixir-equivalent result (positive = we came out ahead)

{table}

Situation averages (positive = that card works well in that situation):
{situations}

Write at most {limit} lessons, each a single imperative sentence under {width} characters.

Rules for a good lesson:
- Say what to DO, not what the statistic was. "Answer a Musketeer with Skeletons rather
  than Ice Golem" is a lesson; "Use ice_spirit against knight for +2.56 mean" is not.
- Never quote the numbers back. Never use the internal situation codes such as
  "defend|big|air|contained" - they mean nothing to the player.
- Only claim a pairing where our card genuinely fights that unit. Ignore any row that
  looks like a coincidence of two things being on the field at once.
- A single lopsided row is noise. Prefer rows with more samples and a consistent result.
- Say nothing you cannot support. Returning two solid lessons beats ten padded ones,
  and an empty list is a perfectly good answer when the data is thin."""


def build_tables(book: ExperienceBook, minimum: int) -> tuple[str, str]:
    rows = book.top_matchups(minimum=minimum)
    if not rows:
        return "  (no matchup has enough samples yet)", "  (none yet)"
    worst = rows[:8]
    best = rows[-8:]
    lines = []
    for key, value in best + [r for r in worst if r not in best]:
        lines.append(
            f"  {key}: n={int(value['n'])} kill_rate={value['kill_rate']:.2f} "
            f"mean={value['mean_reward']:+.2f}"
        )
    situations = []
    for situation, cards in sorted(book.learned.items()):
        for card, (count, mean) in sorted(cards.items(), key=lambda kv: kv[1][1]):
            if count >= minimum:
                situations.append(f"  {situation} / {card}: n={int(count)} mean={mean:+.2f}")
    return "\n".join(lines), "\n".join(situations) or "  (none yet)"


def ask_model(prompt: str, model: str, url: str, timeout: float) -> list[str]:
    import urllib.request

    payload = json.dumps({
        "model": model, "prompt": prompt, "stream": False, "think": False,
        "format": SCHEMA, "options": {"num_predict": 500, "temperature": 0.2},
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.loads(response.read().decode("utf-8"))
    parsed = json.loads(body.get("response", "{}"))
    lessons = parsed.get("lessons", [])
    return [str(line).strip() for line in lessons if str(line).strip()]


def ask_agent(prompt: str, timeout: float) -> list[str]:
    """Write the lessons with a stronger model.

    Lessons are generated once per block, not inside the decision loop, so
    latency is irrelevant here and quality is not: the 4B model reliably
    produced "Use ice_spirit against knight for +2.56 mean", which is the
    statistic read back rather than advice anyone can act on.
    """
    import subprocess

    instruction = (
        prompt
        + "\n\nReturn ONLY a JSON object of the form {\"lessons\": [\"...\", \"...\"]}."
        " No markdown fences and no commentary. Do not read or write any file."
    )
    proc = subprocess.run(
        ["agy", "--dangerously-skip-permissions", "--model", "Gemini 3.1 Pro (High)",
         "--print-timeout", "10m", "--print", instruction],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    text = (proc.stdout or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"no JSON in agent reply: {text[:200]}")
    parsed = json.loads(text[start:end + 1])
    return [str(line).strip() for line in parsed.get("lessons", []) if str(line).strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Write lessons from measured outcomes")
    # Four is the point where a kill-rate stops being a coin flip. At two, the
    # first run produced "hog_rider vs ice_golem: 100% kill rate" from a single
    # coincidence.
    parser.add_argument("--min-samples", type=int, default=4)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--url", default=OLLAMA_URL)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--agent-timeout", type=float, default=700.0)
    parser.add_argument("--local-only", action="store_true",
                        help="skip the stronger agent and use Ollama directly")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    book = ExperienceBook()
    table, situations = build_tables(book, args.min_samples)
    prompt = PROMPT.format(table=table, situations=situations,
                           limit=MAX_LESSONS, width=MAX_LINE)
    if args.dry_run:
        print(prompt)
        return 0

    lessons: list[str] = []
    if not args.local_only:
        try:
            lessons = ask_agent(prompt, timeout=args.agent_timeout)
        except Exception as exc:
            print(f"LESSONS agent unavailable ({type(exc).__name__}); using local model")
    if not lessons:
        try:
            lessons = ask_model(prompt, args.model, args.url, args.timeout)
        except Exception as exc:
            print(f"LESSONS failed: {type(exc).__name__}: {exc}")
            return 1

    lessons = [line[:MAX_LINE] for line in lessons][:MAX_LESSONS]
    if not lessons:
        print("LESSONS none written (not enough evidence)")
        return 0

    LESSONS_PATH.write_text(
        "# Lessons learned from measured play\n"
        "# Written by scripts/lessons.py from brain/matchups.json. Do not hand-edit;\n"
        "# it is regenerated from outcomes and injected into the advisor prompt.\n\n"
        + "\n".join(f"- {line}" for line in lessons) + "\n",
        encoding="utf-8",
    )
    print(f"LESSONS wrote {len(lessons)} to {LESSONS_PATH}")
    for line in lessons:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
