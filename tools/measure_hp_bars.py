"""Measure each troop's health-bar length from recorded detections.

Every `bar` detection in `data/vod/tracks` is paired with the unit just under
it, using the same rule as `scripts/brain/hp_bars.match_bars`. Its track
length is the box width minus the square badge, in badge heights, so the
number holds at any resolution:

    track / badge = width / height - 0.962

Detector boxes carry padding, which inflates short bars more than long ones.
Against pixel-exact lengths in a real screenshot the recorded values fit
`recorded = 0.80 * true + 0.55`, and that correction is applied to `true`.

    python tools/measure_hp_bars.py [--min-n 30] [--json out.json]

One-hit units (Skeleton, Ice Spirit) almost never show a bar, so what lands
on them is mostly their neighbours' bars; read those rows with that in mind.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACKS = ROOT / "data" / "vod" / "tracks"
NOT_A_UNIT = {
    "king-tower", "queen-tower", "tower-bar", "king-tower-bar", "bar",
    "bar-level", "text", "clock", "emote", "elixir", "dagger-duchess-tower-bar",
    "cannoneer-tower", "dagger-duchess-tower", "skeleton-king-bar",
    "small-text", "big-text", "king-level", "dirt", "blood", "ruins",
}
BADGE = 0.962
SLOPE, OFFSET = 0.80, 0.55


def measure(tracks: Path = TRACKS, min_conf: float = 0.6) -> dict:
    per_unit = collections.defaultdict(list)
    for path in sorted(glob.glob(str(tracks / "*.jsonl"))):
        frames = collections.defaultdict(list)
        with open(path, encoding="utf-8") as stream:
            for line in stream:
                det = json.loads(line)
                if det.get("kind") == "det" and det.get("conf", 0) >= min_conf:
                    frames[round(det["t"], 2)].append(det)
        for dets in frames.values():
            bars = [d for d in dets if d["name"] == "bar"]
            units = [d for d in dets if d["name"] not in NOT_A_UNIT]
            for bar in bars:
                best, best_score = None, None
                for unit in units:
                    dy = (unit["cy"] - unit["h"] / 2) - (bar["cy"] + bar["h"] / 2)
                    dx = abs(unit["cx"] - bar["cx"])
                    if not (-1.5 * bar["h"] <= dy <= 1.5 * bar["h"]) or dx > 0.6 * bar["w"]:
                        continue
                    score = abs(dy) + dx
                    if best_score is None or score < best_score:
                        best, best_score = unit, score
                if best is not None and bar["h"] > 0:
                    per_unit[best["name"]].append(bar["w"] / bar["h"] - BADGE)
    return per_unit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-n", type=int, default=30)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    out = {}
    for name, values in sorted(measure().items(),
                               key=lambda kv: statistics.median(kv[1])):
        if len(values) < args.min_n:
            continue
        recorded = statistics.median(values)
        true = (recorded - OFFSET) / SLOPE
        out[name] = {"n": len(values), "recorded": round(recorded, 3),
                     "track_badge_heights": round(true, 2)}
        print(f"{name:26s} n={len(values):6d}  track = {true:.2f} badge heights")
    if args.json:
        args.json.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
