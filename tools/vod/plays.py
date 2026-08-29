"""Recover what a strong player actually did, from unit tracks.

The detector sees units on the board, never a card being played. So a play has
to be inferred: a unit appearing where, a moment earlier, no unit of that class
was near. That inference is the whole of this module, and it is worth stating
its failure modes up front because they decide what the output can be used for.

**Multi-unit cards land as one play.** Skeletons is three units in a radius, and
counting three deploys would triple the card's apparent frequency and halve its
apparent cost. Simultaneous appearances of one class inside `CLUSTER_TILES` are
folded into a single event carrying a count.

**Spawner and death output is not a play.** A Tombstone emits Skeletons, a Golem
splits, a Barbarian Barrel ends as a Barbarian. Those appear exactly like a
deploy and no amount of looking at one frame distinguishes them. Two filters
reduce it: a play must appear in a *deployable* region for its side, and must
not appear within `SPAWNER_TILES` of a friendly building. Neither is complete,
so counts here are a lower bound on plays and an upper bound on distinct cards.

**A detector miss looks like a play.** If a unit is lost for several frames and
re-found, that reads as a new appearance. `REAPPEAR_GRACE_S` suppresses the
obvious cases; sustained occlusion in a crowded fight will still leak through.

What comes out is therefore good for *distributions* - where a card tends to be
placed, how long after the previous play, what tends to follow what - and bad
for reconstructing any single match exactly. That is the right shape for the
question it exists to answer, which is how a strong player uses the deck rather
than what happened in one game.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import statistics
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Same-class units appearing within this of each other at the same moment are
# one card, not several. Skeletons spawn inside about a tile.
CLUSTER_TILES = 2.0

# A unit of this class must have been absent from within this radius for at
# least REAPPEAR_GRACE_S to count as newly played.
NEAR_TILES = 2.5
REAPPEAR_GRACE_S = 2.5

# Fastest thing on the board, in tiles per second. The Hog is 2.0 and
# nothing in the game walks faster, so this bounds how far a unit seen
# a moment ago could legitimately have travelled.
MAX_TILES_PER_S = 2.5

# Anything appearing this close to a friendly building is assumed to be its
# output rather than a card.
SPAWNER_TILES = 2.0

# Structures and interface, never plays.
NOT_UNITS = frozenset({
    "king-tower", "queen-tower", "tower-bar", "king-tower-bar", "bar",
    "bar-level", "dagger-duchess-tower", "cannoneer-tower", "elixir", "clock",
    "text", "emote", "selected", "evolution-symbol", "dirt", "pad_belong",
    "skeleton-king-bar", "dagger-duchess-tower-bar", "pad_0",
})

# Cards that are buildings; used to spot spawner output near them.
BUILDING_CLASSES = frozenset({
    "cannon", "tesla", "inferno-tower", "bomb-tower", "mortar", "x-bow",
    "tombstone", "furnace", "goblin-hut", "barbarian-hut", "goblin-cage",
    "elixir-collector", "goblin-drill",
})


@dataclass
class Play:
    t: float
    card: str
    tile_x: float
    tile_y: float
    side: str
    count: int


def _load(path: Path):
    meta, rows = None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if "name" in record:
            if record.get("tile_x") is not None:
                rows.append(record)
        else:
            meta = record
    return meta or {}, rows


def extract(rows: list[dict]) -> list[Play]:
    """Infer plays from a single match's detections."""
    by_time: dict[float, list[dict]] = collections.defaultdict(list)
    for row in rows:
        if row["name"] not in NOT_UNITS:
            by_time[row["t"]].append(row)
    times = sorted(by_time)

    # Where each class was recently seen, so a reappearance is not a play.
    recent: dict[tuple[str, str], list[tuple[float, float, float]]] = \
        collections.defaultdict(list)
    buildings: list[tuple[float, float, str]] = []
    plays: list[Play] = []

    for t in times:
        here = by_time[t]
        for det in here:
            if det["name"] in BUILDING_CLASSES:
                buildings.append((det["tile_x"], det["tile_y"], det.get("side") or ""))

        fresh: list[dict] = []
        for det in here:
            key = (det["name"], det.get("side") or "")
            seen = recent[key]
            # Stored times are in the past, so the window is 0 <= t - now
            # <= grace. An earlier version wrote `now - t >= -1e-9`, which is
            # true only when the remembered sighting is in the FUTURE - so it
            # never matched, nothing was ever "recently seen", and every
            # detection became a play: 121,841 of them across twenty matches
            # against a real total near a thousand.
            # The radius has to grow with elapsed time. Comparing against
            # where a unit WAS means a fast one outruns a fixed radius and
            # re-registers as a new play: a Hog covers three tiles inside the
            # grace window. Allowing MAX_TILES_PER_S of travel asks the right
            # question - could the thing I saw then have got here by now?
            near = any(0.0 <= t - now <= REAPPEAR_GRACE_S
                       and math.dist((x, y), (det["tile_x"], det["tile_y"]))
                           <= NEAR_TILES + MAX_TILES_PER_S * (t - now)
                       for now, x, y in seen)
            if not near:
                fresh.append(det)

        # Fold simultaneous same-class appearances into one play.
        used = set()
        for i, det in enumerate(fresh):
            if i in used:
                continue
            group = [det]
            used.add(i)
            for j, other in enumerate(fresh):
                if j in used or other["name"] != det["name"]:
                    continue
                if math.dist((det["tile_x"], det["tile_y"]),
                             (other["tile_x"], other["tile_y"])) <= CLUSTER_TILES:
                    group.append(other)
                    used.add(j)
            cx = statistics.mean(g["tile_x"] for g in group)
            cy = statistics.mean(g["tile_y"] for g in group)
            side = det.get("side") or ""
            if any(math.dist((cx, cy), (bx, by)) <= SPAWNER_TILES and bs == side
                   for bx, by, bs in buildings):
                continue          # spawner output, not a card
            plays.append(Play(round(t, 2), det["name"], round(cx, 2),
                              round(cy, 2), side, len(group)))

        for det in here:
            key = (det["name"], det.get("side") or "")
            recent[key].append((t, det["tile_x"], det["tile_y"]))
            if len(recent[key]) > 400:
                del recent[key][:200]

    return plays


def report(all_plays: list[Play], min_plays: int = 20) -> str:
    lines = []
    per_card = collections.defaultdict(list)
    for p in all_plays:
        per_card[p.card].append(p)

    lines.append("WHERE A CARD GETS PLAYED  (tile y: 0 is their king, 31 is yours)")
    lines.append(f"{'card':<18}{'n':>6}{'median x':>10}{'median y':>10}"
                 f"{'own half':>10}")
    lines.append("-" * 54)
    for card, ps in sorted(per_card.items(), key=lambda kv: -len(kv[1])):
        if len(ps) < min_plays:
            continue
        mx = statistics.median(p.tile_x for p in ps)
        my = statistics.median(p.tile_y for p in ps)
        own = sum(1 for p in ps if p.tile_y >= 16) / len(ps)
        lines.append(f"{card:<18}{len(ps):>6}{mx:>10.1f}{my:>10.1f}{own:>9.0%}")

    gaps = []
    ordered = sorted(all_plays, key=lambda p: (p.side, p.t))
    for a, b in zip(ordered, ordered[1:]):
        if a.side == b.side and 0 < b.t - a.t < 30:
            gaps.append(b.t - a.t)
    if gaps:
        lines.append("")
        lines.append("PACE")
        lines.append(f"  median gap between plays : {statistics.median(gaps):.1f}s")
        lines.append(f"  plays per minute         : {60 / statistics.median(gaps):.1f}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tracks", type=Path, default=ROOT / "data" / "vod" / "tracks")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "vod" / "plays.jsonl")
    ap.add_argument("--min-plays", type=int, default=20)
    args = ap.parse_args()

    files = sorted(args.tracks.glob("*.jsonl"))
    if not files:
        raise SystemExit(f"no track files in {args.tracks}")

    everything: list[Play] = []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for path in files:
            meta, rows = _load(path)
            plays = extract(rows)
            everything.extend(plays)
            for p in plays:
                handle.write(json.dumps({"match": path.stem, **asdict(p)}) + "\n")

    print(f"{len(files)} matches -> {len(everything):,} inferred plays")
    print(f"wrote {args.out}\n")
    print(report(everything, args.min_plays))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
