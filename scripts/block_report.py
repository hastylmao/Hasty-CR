"""Turn a block of match records into one compact markdown report.

The review agents are billed per token, so the report is deliberately small and
numeric: aggregates first, then at most a handful of illustrative action lines.
Handing an agent raw logs costs many times more and reviews no better.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
MATCHES = ROOT / "tmp" / "live" / "matches"


def load(paths: List[Path]) -> List[dict]:
    records = []
    for path in paths:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return records


def parse_towers(text: str):
    """'0.18/1.00-0.00/0.00' -> ((0.18, 1.00), (0.00, 0.00))."""
    try:
        ours, theirs = text.split("-")
        a, b = (float(v) for v in ours.split("/"))
        c, d = (float(v) for v in theirs.split("/"))
        return (a, b), (c, d)
    except Exception:
        return (1.0, 1.0), (1.0, 1.0)


def crowns(record: dict):
    ours, theirs = parse_towers(record.get("towers", ""))
    return sum(1 for v in theirs if v <= 0.0), sum(1 for v in ours if v <= 0.0)


def build(records: List[dict], block: str) -> str:
    if not records:
        return f"# Block {block}\n\nNo match records found.\n"
    plays = Counter()
    tags = Counter()
    won = lost = drew = 0
    our_crowns = their_crowns = 0
    durations = []
    for record in records:
        plays.update(record.get("play_counts", {}))
        for line in record.get("actions", []):
            parts = line.split()
            if len(parts) >= 4:
                tags[parts[3]] += 1
        mine, theirs = crowns(record)
        our_crowns += mine
        their_crowns += theirs
        won += mine > theirs
        lost += theirs > mine
        drew += mine == theirs
        durations.append(record.get("duration_s", 0))

    total = sum(plays.values()) or 1
    hog = plays.get("hog_rider", 0)
    lines = [
        f"# Block {block} - {len(records)} matches",
        "",
        "## Result",
        f"- record: **{won}W {lost}L {drew}D**",
        f"- crowns: **{our_crowns} for / {their_crowns} against**",
        f"- mean match length: {sum(durations) // max(1, len(durations))}s",
        f"- cards played per match: {total / len(records):.1f}",
        "",
        "## Card mix",
        # 20% is the arithmetic ceiling: four other cards must be played before
        # a card returns, so no card can exceed one play in five. An earlier
        # "target 15-25%" was therefore partly unreachable and pushed several
        # reviews toward changes that could never have paid off.
        f"- **hog_rider share: {100.0 * hog / total:.1f}%**  "
        f"(realistic 12-18%; 20% is the hard ceiling)",
    ]
    for name, count in plays.most_common():
        lines.append(f"- {name}: {count} ({100.0 * count / total:.1f}%)")
    lines += ["", "## Decision tags (why each card was played)"]
    for tag, count in tags.most_common(18):
        lines.append(f"- {tag}: {count}")

    flips = sum(r.get("hand_flips", 0) for r in records)
    lines += [
        "",
        "## Perception",
        f"- card-slot flips: {flips} over {len(records)} matches "
        f"({flips / max(1, len(records)):.0f} per match)",
        "- a card cannot exceed **20%** of plays in an eight-card deck; a higher",
        "  share above means the hand is being misread, not a strategy finding.",
    ]

    lines += ["", "## Per-match"]
    for record in records:
        mine, theirs = crowns(record)
        lines.append(
            f"- m{record.get('index', '?')}: {mine}-{theirs} crowns, "
            f"{record.get('duration_s')}s, towers {record.get('towers')}, "
            f"{record.get('summary', '')}"
        )

    worst = min(records, key=lambda r: crowns(r)[0] - crowns(r)[1])
    lines += ["", f"## Worst match (m{worst.get('index')}) action trace", "```"]
    lines += worst.get("actions", [])[:60]
    lines += ["```", ""]
    return "\n".join(lines)


def main() -> int:
    block = sys.argv[1] if len(sys.argv) > 1 else "latest"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    paths = sorted(MATCHES.glob("*.json"))[-count:]
    report = build(load(paths), block)
    out_dir = ROOT / "tmp" / "live" / "reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest_block.md").write_text(report, encoding="utf-8")
    (out_dir / f"block_{block}.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
