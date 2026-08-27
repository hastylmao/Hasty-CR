"""Collect one or more reference images of every enemy unit, from real matches.

Why harvest instead of downloading card art
-------------------------------------------
`vendor/ClashRoyaleBuildABot/clashroyalebuildabot/images/cards/` already holds
97 card portraits, and those are useful for identifying the *hand*. They are not
what a detector needs for the *arena*: a Musketeer card portrait looks nothing
like the 30-pixel sprite walking down the left lane at this resolution, from
this camera angle, at this emulator's scaling.

So the reference set is built from the real thing. The unit detector already
localises and labels enemy units every frame; this saves a crop per label, a
few examples each, from actual play. That is exactly the shape of data a YOLO
model needs later, and it costs nothing extra to collect because the detection
is happening anyway.

Files are tiny (a few KB each) and capped per class, so a full library of all
97 units is a handful of megabytes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "tmp" / "sprites"

# The detector reports a real bounding box, on the 368x652 frame it was run
# against. Deriving the crop from the unit's *tile* instead put the box on the
# arena floor: a sprite is drawn above the ground position it occupies, so
# tile-derived crops came back full of floor tiles and UI badges.
SOURCE_W, SOURCE_H = 368, 652
MARGIN = 0.18          # a little context around the unit
MAX_PER_CLASS = 6


class SpriteHarvester:
    def __init__(self, out_dir: Path | None = None, max_per_class: int = MAX_PER_CLASS):
        self.out_dir = Path(out_dir or DEFAULT_DIR)
        self.max_per_class = max_per_class
        self.counts: Dict[str, int] = {}
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._load_counts()

    def _load_counts(self) -> None:
        for path in self.out_dir.glob("*/"):
            if path.is_dir():
                self.counts[path.name] = len(list(path.glob("*.png")))

    def harvest(self, frame: Image.Image, detections) -> int:
        """Save a crop for each detection whose class is not yet full.

        `detections` is an iterable of (name, bbox) where bbox is the detector's
        (x0, y0, x1, y1) on the 368x652 frame.
        """
        saved = 0
        sx, sy = frame.width / SOURCE_W, frame.height / SOURCE_H
        for name, bbox in detections:
            if self.counts.get(name, 0) >= self.max_per_class:
                continue
            x0, y0, x1, y1 = (bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy)
            pad_x, pad_y = (x1 - x0) * MARGIN, (y1 - y0) * MARGIN
            box = (
                max(0, int(x0 - pad_x)), max(0, int(y0 - pad_y)),
                min(frame.width, int(x1 + pad_x)), min(frame.height, int(y1 + pad_y)),
            )
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                continue
            folder = self.out_dir / name
            folder.mkdir(parents=True, exist_ok=True)
            index = self.counts.get(name, 0)
            frame.crop(box).save(folder / f"{name}_{index:02d}.png", optimize=True)
            self.counts[name] = index + 1
            saved += 1
        return saved

    @property
    def complete(self) -> bool:
        return bool(self.counts) and all(
            count >= self.max_per_class for count in self.counts.values()
        )

    def write_index(self) -> Path:
        """A manifest pairing each collected class with its stats."""
        try:
            stats = json.loads(
                (ROOT / "scripts" / "brain" / "card_stats.json").read_text(encoding="utf-8")
            )
        except Exception:
            stats = {}
        index = {
            name: {
                "images": count,
                "dir": str((self.out_dir / name).relative_to(ROOT)),
                "stats": stats.get(name, {}),
            }
            for name, count in sorted(self.counts.items())
        }
        path = self.out_dir / "index.json"
        path.write_text(json.dumps(index, indent=1), encoding="utf-8")
        return path
