"""Compare what the recordings show against what the simulator predicts.

The first thing worth measuring is movement speed, for three reasons. It is
directly observable - a unit's tile position over consecutive frames, nothing
inferred. It is directly comparable - `speed_mt_per_sec` is a number the engine
already has for every card. And it is load-bearing: the body-block gap that
started all this comes down to a Hog at 2 tiles/s outrunning Skeletons at 1.06,
so if either of those speeds is wrong, the conclusion drawn from them is too.

Method, and its limits, stated up front:

* A unit is followed by nearest-neighbour association between frames of the
  same class. That is adequate for an isolated unit crossing a lane and
  unreliable in a crowd, so segments where same-class units come within a tile
  of each other are dropped rather than guessed at.
* Speed is the median of per-frame displacements over a segment, not the
  endpoints. A detection box jitters by a fraction of a tile; a median over
  twenty frames is stable where a difference of two is not.
* Only segments where the unit moved consistently in one direction are used.
  A unit that stopped to fight, got knocked back, or was pulled has a speed
  that means something else.

What this cannot see: anything about a unit that is never detected, any timing
finer than the sample interval, and the difference between a unit walking and a
unit being pushed. Those are named here so a number that came out of this is
not later read as more than it is.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Detector class name -> the card name the simulator knows it by. Only the ones
# that are unambiguous single units; a name that maps to several cards, or to a
# unit whose speed changes (charging, raged), is deliberately absent.
DETECTOR_TO_CARD = {
    "hog-rider": "hog_rider",
    "knight": "knight",
    "musketeer": "musketeer",
    "skeleton": "skeletons",
    "ice-spirit": "ice_spirit",
    "ice-golem": "ice_golem",
    "giant": "giant",
    "mini-pekka": "mini_pekka",
    "valkyrie": "valkyrie",
    "wizard": "wizard",
    "baby-dragon": "baby_dragon",
    "bomber": "bomber",
    "archer": "archer",
    "goblin": "goblin",
    "spear-goblin": "spear_goblin",
    "barbarian": "barbarian",
    "minion": "minion",
    "prince": "prince",
    "dark-prince": "dark_prince",
    "royal-giant": "royal_giant",
    "electro-wizard": "electro_wizard",
    "mega-minion": "mega_minion",
    "battle-healer": "battle_healer",
    "royal-hog": "royal_hog",
    "firecracker": "firecracker",
    "dart-goblin": "dart_goblin",
    "hunter": "hunter",
    "executioner": "executioner",
    "bowler": "bowler",
    "witch": "witch",
    "lumberjack": "lumberjack",
    "miner": "miner",
    "bandit": "bandit",
    "golem": "golem",
    "pekka": "pekka",
}

# A segment must be at least this long to yield a speed. Short segments are
# dominated by box jitter.
MIN_SEGMENT_FRAMES = 8

# Two detections of the same class closer than this are ambiguous to associate.
CROWD_TILES = 1.2

# Frame-to-frame movement above this is an association error, not a unit.
MAX_JUMP_TILES = 1.5

# A segment whose direction reverses is a fight or a knockback, not a walk.
MIN_DIRECTION_CONSISTENCY = 0.85

# Below this many clean segments, a per-card number is not evidence of
# anything. Named as a constant rather than left to whoever reads the table,
# because the entire purpose of this package is to stop unmeasured numbers
# entering the engine, and a table that looks authoritative at n=3 is exactly
# how one would.
SOLID_SEGMENTS = 20


@dataclass
class Segment:
    card: str
    frames: int
    seconds: float
    tiles: float
    speed_tiles_s: float
    source: str


def read_tracks(path: Path) -> tuple[dict, list[dict]]:
    meta: dict = {}
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") == "meta":
            meta = record
        elif record.get("kind") == "det":
            rows.append(record)
    return meta, rows


def _by_time(rows: list[dict]) -> dict[float, list[dict]]:
    frames: dict[float, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("tile_x") is None:
            continue
        frames[row["t"]].append(row)
    return frames


def follow(rows: list[dict], card_class: str, dt: float) -> Iterator[Segment]:
    """Nearest-neighbour tracks for one class, split where they get ambiguous."""
    frames = _by_time(rows)
    times = sorted(frames)
    open_tracks: list[list[tuple[float, float, float]]] = []

    for t in times:
        here = [r for r in frames[t] if r["name"] == card_class]
        # A crowd of the same class cannot be associated honestly; end the
        # tracks rather than invent a correspondence.
        ambiguous = False
        for i, a in enumerate(here):
            for b in here[i + 1:]:
                if math.dist((a["tile_x"], a["tile_y"]),
                             (b["tile_x"], b["tile_y"])) < CROWD_TILES:
                    ambiguous = True
        if ambiguous:
            for finished in open_tracks:
                yield from _segment_from(finished, card_class, dt)
            open_tracks = []
            continue

        used = set()
        for trail in open_tracks:
            last_t, last_x, last_y = trail[-1]
            best, best_d = None, MAX_JUMP_TILES
            for index, candidate in enumerate(here):
                if index in used:
                    continue
                d = math.dist((last_x, last_y),
                              (candidate["tile_x"], candidate["tile_y"]))
                if d < best_d:
                    best, best_d = index, d
            if best is None:
                yield from _segment_from(trail, card_class, dt)
                trail.clear()
            else:
                used.add(best)
                trail.append((t, here[best]["tile_x"], here[best]["tile_y"]))
        open_tracks = [tr for tr in open_tracks if tr]
        for index, candidate in enumerate(here):
            if index not in used:
                open_tracks.append([(t, candidate["tile_x"], candidate["tile_y"])])

    for trail in open_tracks:
        yield from _segment_from(trail, card_class, dt)


def _segment_from(trail, card_class: str, dt: float) -> Iterator[Segment]:
    if len(trail) < MIN_SEGMENT_FRAMES:
        return
    steps = []
    dys = []
    for (t0, x0, y0), (t1, x1, y1) in zip(trail, trail[1:]):
        gap = t1 - t0
        if gap <= 0:
            continue
        steps.append(math.dist((x0, y0), (x1, y1)) / gap)
        dys.append(y1 - y0)
    if len(steps) < MIN_SEGMENT_FRAMES - 1 or not dys:
        return
    forward = sum(1 for d in dys if d > 0)
    consistency = max(forward, len(dys) - forward) / len(dys)
    if consistency < MIN_DIRECTION_CONSISTENCY:
        return                      # fought, kited or knocked back
    speed = statistics.median(steps)
    if speed <= 0.05:
        return                      # standing still
    yield Segment(card=DETECTOR_TO_CARD.get(card_class, card_class),
                  frames=len(trail),
                  seconds=trail[-1][0] - trail[0][0],
                  tiles=math.dist(trail[0][1:], trail[-1][1:]),
                  speed_tiles_s=speed,
                  source=card_class)


def measure(track_files: list[Path]) -> dict[str, list[Segment]]:
    found: dict[str, list[Segment]] = defaultdict(list)
    for path in track_files:
        meta, rows = read_tracks(path)
        dt = 1.0 / float(meta.get("track_fps", 10.0))
        classes = {r["name"] for r in rows} & set(DETECTOR_TO_CARD)
        for card_class in classes:
            for seg in follow(rows, card_class, dt):
                found[seg.card].append(seg)
    return found


def simulator_speeds() -> dict[str, float]:
    """Tiles per second as the ENGINE moves a unit, not as the card declares it.

    These differ by a factor of 16.667 and reading the wrong one is not a
    rounding error: a Hog Rider's card says 120 and the entity the engine
    actually steps says 2000 millitiles a second, so `speed_mt_per_sec` off
    the card is 0.12 tiles/s where the truth is 2.0. The first version of this
    function did exactly that and reported the simulator as twenty times
    slower than the footage, which reads as a spectacular finding and is
    entirely an own goal.

    So the unit is built the way a match builds it and asked afterwards.
    """
    from sim import arena
    from sim.entities import make_unit
    from sim.gamedata import load_gamedata

    cards = load_gamedata(level=11)
    speeds = {}
    for name in sorted(set(DETECTOR_TO_CARD.values())):
        try:
            spec = cards[name].unit
            entity = make_unit(0, spec, 1, arena.tile(9, 20))
        except (KeyError, AttributeError, TypeError):
            continue
        if entity.speed_mt_per_sec:
            speeds[name] = entity.speed_mt_per_sec / 1000.0
    return speeds


def report(found: dict[str, list[Segment]], min_segments: int = 5) -> str:
    sim = simulator_speeds()
    lines = ["card              n   observed   simulator   diff",
             "-" * 56]
    rows = []
    for card, segs in found.items():
        if len(segs) < min_segments:
            continue
        observed = statistics.median(s.speed_tiles_s for s in segs)
        expected = sim.get(card)
        if expected is None:
            continue
        rows.append((abs(observed - expected) / expected, card, len(segs),
                     observed, expected))
    thin = 0
    for _rel, card, n, observed, expected in sorted(rows, reverse=True):
        diff = (observed - expected) / expected * 100.0
        flag = ""
        if n < SOLID_SEGMENTS:
            flag = "   preliminary"
            thin += 1
        lines.append(f"{card:<16} {n:>3}   {observed:>6.2f}      "
                     f"{expected:>6.2f}   {diff:>+6.1f}%{flag}")
    if len(lines) == 2:
        lines.append("(no card had enough clean segments yet)")
    lines.append("")
    lines.append("Observed is the median over segments where one unit of that "
                 "class walked")
    lines.append("uninterrupted, in tiles per second. Simulator is the speed "
                 "the engine steps")
    lines.append("a unit at, not the raw card value - those differ by 16.667x.")
    if thin:
        lines.append("")
        lines.append(f"{thin} row(s) are marked preliminary: fewer than "
                     f"{SOLID_SEGMENTS} clean segments.")
        lines.append("Do not read a calibration finding off those. A real "
                     "engine error biases one")
        lines.append("direction across cards; disagreeing signs at low n is "
                     "what association")
        lines.append("noise and partially-blocked walks look like.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tracks", type=Path, default=ROOT / "data" / "vod" / "tracks")
    ap.add_argument("--min-segments", type=int, default=5)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    files = sorted(args.tracks.glob("*.jsonl"))
    if not files:
        raise SystemExit(f"no track files in {args.tracks}")
    print(f"{len(files)} match files")
    found = measure(files)
    text = report(found, args.min_segments)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {card: [s.__dict__ for s in segs] for card, segs in found.items()}
        args.out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
