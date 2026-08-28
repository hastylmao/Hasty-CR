"""Turn detections into unit tracks in arena coordinates.

A detection is a box in pixels, and pixels are not comparable to anything the
simulator knows. The simulator thinks in tiles: an 18x32 grid with the river at
row 16 and crown towers at fixed positions. So every measurement this package
exists to make - how fast a Hog crosses, how long a body block costs, how far a
push travels before it dies - needs the pixel-to-tile transform first.

Hardcoding it would be wrong within one video. These are phone recordings from
different sessions, and framing shifts: a crop, a different device aspect, a
letterbox from an editor. Any of those silently biases every distance.

So the transform is *measured per match*, from the towers. Their tile positions
are known exactly - `arena.ENEMY_PRINCESS`, `ALLY_PRINCESS`, the two kings -
and the detector finds them at 0.9 confidence. Four known points in tile space
matched to four found points in pixel space determine the mapping, and taking
the median over many frames makes it robust to a frame where one tower is
obscured by a spell.

The mapping is deliberately affine rather than a full homography. The camera is
fixed and orthographic; there is no perspective to undo, and an unconstrained
homography fitted to noisy boxes bends the arena in ways an affine cannot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

# Tile positions the towers occupy, from sim/arena.py. The top of the frame is
# the opponent's side in every recording of a player's own screen.
TOWER_TILES = {
    "enemy_left": (3.5, 7.5),
    "enemy_right": (14.5, 7.5),
    "enemy_king": (9.5, 3.5),
    "ally_left": (3.5, 24.5),
    "ally_right": (14.5, 24.5),
    "ally_king": (9.5, 28.5),
}

# Classes that are structures rather than fighting units. Tracked separately:
# they anchor the transform and carry hit points, but they never move.
STRUCTURE_CLASSES = frozenset({
    "king-tower", "queen-tower", "tower-bar", "king-tower-bar",
    "dagger-duchess-tower", "cannoneer-tower", "bar", "bar-level",
})

# Not units either: UI furniture the detector was trained to find so it could
# be ignored.
UI_CLASSES = frozenset({"elixir", "clock", "text", "emote", "selected",
                        "evolution-symbol", "dirt", "pad_belong"})


@dataclass
class Detection:
    t: float                # seconds from the start of the span
    name: str
    conf: float
    cx: float               # pixel centre
    cy: float
    w: float
    h: float
    tile_x: Optional[float] = None
    tile_y: Optional[float] = None
    side: Optional[str] = None      # "ours" (bottom) or "theirs" (top)


def _boxes(result) -> Iterator[tuple[str, float, float, float, float, float]]:
    names = result.names
    for box in result.boxes:
        conf = float(box.conf)
        x1, y1, x2, y2 = (float(v) for v in box.xyxy[0])
        yield names[int(box.cls)], conf, (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1


def tower_anchors(detections: list[Detection], height: float) -> dict:
    """Median pixel position of each identifiable tower across a whole span.

    Identity comes from geometry, not from the class name: the detector says
    "queen-tower" without saying which of the four, so they are separated by
    which half of the frame they sit in and which side of centre. That is
    unambiguous because crown towers never move.
    """
    kings = [d for d in detections if d.name == "king-tower"]
    princesses = [d for d in detections if d.name == "queen-tower"]
    if not kings or len(princesses) < 2:
        return {}

    mid_y = height / 2.0
    xs = [d.cx for d in princesses]
    mid_x = float(np.median(xs)) if xs else 0.0

    buckets: dict[str, list[Detection]] = {k: [] for k in TOWER_TILES}
    for d in princesses:
        top = d.cy < mid_y
        left = d.cx < mid_x
        key = ("enemy_" if top else "ally_") + ("left" if left else "right")
        buckets[key].append(d)
    for d in kings:
        buckets["enemy_king" if d.cy < mid_y else "ally_king"].append(d)

    anchors = {}
    for key, found in buckets.items():
        if len(found) >= 5:          # enough to trust a median
            anchors[key] = (float(np.median([d.cx for d in found])),
                            float(np.median([d.cy for d in found])))
    return anchors


def fit_transform(anchors: dict) -> Optional[np.ndarray]:
    """Least-squares affine taking pixels to tiles, from >=3 known towers."""
    if len(anchors) < 3:
        return None
    src, dst = [], []
    for key, (px, py) in anchors.items():
        src.append([px, py, 1.0])
        dst.append(list(TOWER_TILES[key]))
    a = np.asarray(src, dtype=np.float64)
    b = np.asarray(dst, dtype=np.float64)
    solution, *_ = np.linalg.lstsq(a, b, rcond=None)
    return solution                       # 3x2


def apply_transform(matrix: np.ndarray, cx: float, cy: float) -> tuple[float, float]:
    tile = np.asarray([cx, cy, 1.0]) @ matrix
    return float(tile[0]), float(tile[1])


def residual_tiles(matrix: np.ndarray, anchors: dict) -> float:
    """How far the fitted transform misses the towers it was fitted to.

    Reported rather than assumed. A fit that puts a known tower two tiles from
    where it belongs is not a transform, and any distance measured through it
    would be wrong by the same amount in a way nothing downstream could see.
    """
    if matrix is None or not anchors:
        return float("inf")
    errors = []
    for key, (px, py) in anchors.items():
        got = apply_transform(matrix, px, py)
        want = TOWER_TILES[key]
        errors.append(((got[0] - want[0]) ** 2 + (got[1] - want[1]) ** 2) ** 0.5)
    return float(np.mean(errors))


def detect_span(model, video: Path, start_s: float, end_s: float,
                fps: float = 10.0, conf: float = 0.35) -> list[Detection]:
    """Run the detector across one match at `fps` samples a second."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return []
    out: list[Detection] = []
    step = 1.0 / fps
    t = start_s
    while t < end_s:
        capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = capture.read()
        if not ok:
            break
        result = model.predict(frame, conf=conf, verbose=False)[0]
        for name, c, cx, cy, w, h in _boxes(result):
            out.append(Detection(round(t - start_s, 3), name, round(c, 3),
                                 cx, cy, w, h))
        t += step
    capture.release()
    return out


def to_tiles(detections: list[Detection], height: float) -> tuple[Optional[np.ndarray], float]:
    """Fill in tile coordinates in place. Returns the transform and its error."""
    anchors = tower_anchors(detections, height)
    matrix = fit_transform(anchors)
    error = residual_tiles(matrix, anchors)
    if matrix is None:
        return None, error
    for d in detections:
        if d.name in UI_CLASSES:
            continue
        tx, ty = apply_transform(matrix, d.cx, d.cy)
        d.tile_x, d.tile_y = round(tx, 3), round(ty, 3)
        if d.name not in STRUCTURE_CLASSES:
            # Row 16 is the river. Below it is the recording player's half.
            d.side = "ours" if ty >= 16.0 else "theirs"
    return matrix, error


def write_jsonl(path: Path, video_id: str, span_index: int,
                detections: list[Detection], meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps({"kind": "meta", "video_id": video_id,
                                 "span": span_index, **meta}) + "\n")
        for d in detections:
            if d.name in UI_CLASSES:
                continue
            handle.write(json.dumps({"kind": "det", **asdict(d)}) + "\n")
