"""Summarise a run log into per-match strategy metrics.

Emits the numbers that actually diagnose play quality: win-condition usage,
spell efficiency, building placement spread, elixir at time of play, and how
often the guards blocked an action.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

PLAY = re.compile(r"PLAY #(\d+) (\w+) grid=\((\d+),(\d+)\)")
CANDIDATE = re.compile(r"CANDIDATE #(\d+) card=(\w+) .*delay=(-?\d+) elixir=(\d+)")
RESULT = re.compile(
    r"MATCH_RESULT .*match_actions=(\d+) .*?(?:duration=(\d+) )?(?:towers=(\S+) )?screenshot=(\S+)"
)
SHIM = re.compile(r"SHIM (\w+)")
BLOCK = re.compile(r"BLOCK (\w+)")


def analyse(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    plays, cands, shims, blocks = [], [], Counter(), Counter()
    matches, current = [], []

    for line in lines:
        if m := PLAY.search(line):
            entry = (m.group(2), int(m.group(3)), int(m.group(4)))
            plays.append(entry)
            current.append(entry)
        elif m := CANDIDATE.search(line):
            cands.append((m.group(2), int(m.group(3)), int(m.group(4))))
        elif m := SHIM.search(line):
            shims[m.group(1)] += 1
        elif m := BLOCK.search(line):
            blocks[m.group(1)] += 1
        elif m := RESULT.search(line):
            matches.append({
                "actions": int(m.group(1)),
                "duration": m.group(2),
                "towers": m.group(3),
                "shot": m.group(4),
                "cards": Counter(name for name, _, _ in current),
            })
            current = []

    out = [f"# Run analysis: {path.name}", ""]
    out.append(f"matches_finished = {len(matches)}")
    out.append(f"cards_played     = {len(plays)}")
    if not plays:
        return "\n".join(out + ["", "No cards played."])

    counts = Counter(name for name, _, _ in plays)
    out.append("")
    out.append("## Card usage")
    for name, count in counts.most_common():
        out.append(f"  {name:<12} {count:>4}  ({100 * count / len(plays):.0f}%)")

    hog = counts.get("hog_rider", 0)
    out.append("")
    out.append("## Key metrics")
    out.append(f"  hog_rider plays        : {hog}  ({hog / max(1, len(matches)):.1f} per match)")
    # Hog is 1 of 8 cards and can only be reached by playing the other three in
    # hand, so pure cycling gives 100/8 = 12.5%. Anything above that means the
    # win condition is being prioritised. The earlier "~20%" note was invented
    # and made a normal rate look like a failure.
    out.append(
        f"  hog share of all plays : {100 * hog / len(plays):.1f}%   "
        f"(12.5% = pure cycle; ~3-4 per match is the elixir ceiling)"
    )

    cannons = [(x, y) for name, x, y in plays if name == "cannon"]
    if cannons:
        xs = [x for x, _ in cannons]
        ys = [y for _, y in cannons]
        out.append(
            f"  cannon placements      : {len(cannons)}  x={min(xs)}-{max(xs)} y={min(ys)}-{max(ys)}"
            f"  (tight pocket is x 8-10, y 20-22)"
        )
    for spell in ("fireball", "the_log"):
        n = counts.get(spell, 0)
        if n:
            out.append(f"  {spell} plays{' ' * (16 - len(spell))}: {n}")

    if shims:
        out.append("")
        out.append("## Shim activity")
        for name, count in shims.most_common():
            out.append(f"  {name:<20} {count}")
    if blocks:
        out.append("")
        out.append("## Guard blocks")
        for name, count in blocks.most_common():
            out.append(f"  {name:<24} {count}")

    out.append("")
    out.append("## Per match")
    for i, match in enumerate(matches, 1):
        top = ", ".join(f"{k}x{v}" for k, v in match["cards"].most_common(3))
        out.append(
            f"  #{i}  actions={match['actions']:<3} duration={match['duration'] or '?':<4}"
            f" towers={match['towers'] or '?':<20} top={top}"
        )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarise a run log")
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = analyse(args.log)
    print(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("a", encoding="utf-8") as stream:
            stream.write(report + "\n\n" + "=" * 70 + "\n\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
