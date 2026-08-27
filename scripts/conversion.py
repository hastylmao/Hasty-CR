"""Did our pushes actually connect?

Frequency of playing the win condition turned out not to predict crowns
(r = +0.16 over 25 blocks). This measures the next question down: after a
hog_rider goes in, does enemy tower HP actually fall?

Requires the `towers=` field on PLAY lines (added 2026-08-16 09:15), so it only
reports on blocks recorded after that.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PLAY = re.compile(r"PLAY #\d+ (\w+) .*towers=(\S+)")
WINDOW_PLAYS = 6  # how many later plays count as "after this push"


def enemy_hp(towers: str):
    try:
        _, theirs = towers.split("-")
        return [float(v) for v in theirs.split("/")]
    except (ValueError, IndexError):
        return None


def analyse(paths) -> None:
    connected = missed = pushes = 0
    damage_total = 0.0
    for path in paths:
        rows = []
        for name, towers in PLAY.findall(path.read_text(encoding="utf-8", errors="replace")):
            hp = enemy_hp(towers)
            if hp is not None and len(hp) == 2:
                rows.append((name, hp))
        for i, (name, hp) in enumerate(rows):
            if name != "hog_rider":
                continue
            pushes += 1
            after = rows[i + 1 : i + 1 + WINDOW_PLAYS]
            if not after:
                continue
            best = min(sum(h) for _, h in after)
            drop = sum(hp) - best
            if drop > 0.01:
                connected += 1
                damage_total += drop
            else:
                missed += 1
    if not pushes:
        print("no hog pushes with tower data yet (needs blocks recorded after 09:15)")
        return
    print(f"hog pushes analysed : {pushes}")
    print(f"  connected         : {connected}")
    print(f"  no damage follows : {missed}")
    if connected:
        print(f"  mean tower HP lost per connecting push: {damage_total / connected:.3f}")
    print(f"  conversion rate   : {100 * connected / max(1, connected + missed):.0f}%")


def stats(paths):
    """(pushes, connected) across the given logs."""
    connected = pushes = 0
    for path in paths:
        rows = []
        for name, towers in PLAY.findall(path.read_text(encoding="utf-8", errors="replace")):
            hp = enemy_hp(towers)
            if hp is not None and len(hp) == 2:
                rows.append((name, hp))
        for i, (name, hp) in enumerate(rows):
            if name != "hog_rider":
                continue
            pushes += 1
            after = rows[i + 1 : i + 1 + WINDOW_PLAYS]
            if after and sum(hp) - min(sum(h) for _, h in after) > 0.01:
                connected += 1
    return pushes, connected


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    root = Path(args[0] if args else "tmp/live/blocks")
    logs = sorted(root.glob("block_*.log"))
    if "--per-block" in sys.argv:
        print(f"{'block':<12}{'pushes':>8}{'connected':>11}{'rate':>7}")
        for log in logs:
            pushes, connected = stats([log])
            if pushes:
                print(
                    f"{log.stem:<12}{pushes:>8}{connected:>11}"
                    f"{100 * connected / pushes:>6.0f}%"
                )
        print()
    analyse(logs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
