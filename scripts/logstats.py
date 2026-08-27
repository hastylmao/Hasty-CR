"""Aggregate PLAY/BLOCK/SHIM/MATCH_RESULT counts from runner logs.

Kept deliberately dependency-free so any agent (or a plain python) can run it
against a block log and get a compact, token-cheap picture of a run.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path


PLAY = re.compile(r"PLAY #\d+ (\w+) grid=\((\d+),(\d+)\)")
SHIM = re.compile(r"SHIM ([a-z_0-9()\-,>]+)")
HEUR = re.compile(r"HEUR ([a-z_0-9()\-,>]+)")
BLOCK = re.compile(r"BLOCK (\w+)")
CAND = re.compile(r"CANDIDATE #\d+ card=(\w+)")
RESULT = re.compile(r"MATCH_RESULT screen=(\w+).*?duration=(\d+) towers=(\S+)")
ERROR = re.compile(r"ERROR (\w+)")


def summarize(paths):
    plays, blocks, shims, cands, errors = Counter(), Counter(), Counter(), Counter(), Counter()
    lanes = Counter()
    results = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
            m = PLAY.search(line)
            if m:
                plays[m.group(1)] += 1
                lanes[(int(m.group(2)), int(m.group(3)))] += 1
            for rx, sink in ((BLOCK, blocks), (CAND, cands), (ERROR, errors)):
                m = rx.search(line)
                if m:
                    sink[m.group(1)] += 1
            for rx in (SHIM, HEUR):
                m = rx.search(line)
                if m:
                    shims[m.group(1).split("(")[0]] += 1
            m = RESULT.search(line)
            if m:
                results.append(m.groups())
    return plays, blocks, shims, cands, errors, lanes, results


def main() -> int:
    paths = sys.argv[1:]
    if not paths:
        print("usage: logstats.py <log> [...]")
        return 2
    plays, blocks, shims, cands, errors, lanes, results = summarize(paths)
    total = sum(plays.values())
    print(f"== PLAYS total={total}")
    for name, count in plays.most_common():
        print(f"   {name:<12} {count:>4}  {100.0 * count / max(1, total):5.1f}%")
    print(f"== CANDIDATES total={sum(cands.values())}")
    for name, count in cands.most_common(12):
        print(f"   {name:<12} {count:>4}")
    print("== SHIM/HEUR notes")
    for name, count in shims.most_common(20):
        print(f"   {name:<34} {count:>4}")
    print("== BLOCKS")
    for name, count in blocks.most_common():
        print(f"   {name:<26} {count:>4}")
    print("== ERRORS")
    for name, count in errors.most_common():
        print(f"   {name:<26} {count:>4}")
    print("== TOP PLACEMENTS")
    for cell, count in lanes.most_common(10):
        print(f"   {cell} {count}")
    print(f"== MATCH RESULTS ({len(results)})")
    for screen, duration, towers in results:
        print(f"   {screen} dur={duration}s towers={towers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
