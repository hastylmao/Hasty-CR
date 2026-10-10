"""Read the board with the trained detector instead of the upstream one.

The upstream BuildABot detector is what the bot has always played on, and its
mistakes are documented: spell particles filed as Bats, and a card classifier
unstable enough to report Ice Spirit as 26.5% of plays when the ceiling is 20%.
The detector trained here scores 0.949 precision / 0.926 recall / 0.959 mAP50
over 201 classes, and 0.973 on hog-rider specifically.

Two things had to be solved to make it usable as perception rather than as an
overlay.

**Whose unit is it.** The detector was trained with the dataset's side column
dropped, so it says "musketeer" and not whose. Guessing does not work - measured
over 3,150 val boxes, a blue-vs-red colour rule gets 66.7% overall but **52.8%**
on units in our own half, which is a coin flip in the only situation where the
answer changes the play. `scripts/train_side_classifier.py` trains a small
specialist on ~93k labelled crops instead; this module loads it and abstains
when it is missing rather than inventing a side.

**Where the unit is standing.** `arena.to_pixels` is calibrated against a
1080x1920 frame for placing taps, so inverting it converts a box back to a tile.
A sprite's ground position is the bottom-centre of its box, not the centre.

Everything else in the state - cards, elixir, tower HP, screen - still comes
from upstream. This replaces unit perception only.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from . import arena, hp_bars

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "tmp" / "yolo" / "runs"
SIDE_MODEL = ROOT / "tmp" / "yolo" / "side_classifier.pt"

# Scenery, UI and towers. The brain wants troops and buildings; a `tower-bar`
# in the enemy list would be read as a threat standing on our tower.
NOT_A_UNIT = frozenset({
    "king-tower", "queen-tower", "king-tower-bar", "tower-bar", "cannoneer-tower",
    "bar", "bar-level", "text", "dirt", "clock", "emote", "elixir", "blood",
    "ruins", "background", "skeleton-king-bar", "tower", "king-level",
    "small-text", "big-text", "arrow",
})

# Spells and the padding classes the dataset ships. Not units, and listed
# rather than left to fall through, so that "this class resolves to nothing"
# means "a card we cannot see" and can be reported as the fault it is.
NOT_A_UNIT_EITHER = frozenset(
    {f"pad_{n}" for n in range(45)} | {"pad_belong", "selected",
     "evolution-symbol", "arrows", "axe", "bomb", "clone", "earthquake",
     "fireball", "freeze", "goblin-ball", "graveyard", "goblin-barrel",
     "lightning", "mirror", "poison", "rage", "rocket", "royal-delivery",
     "the-log", "tesla-evolution-shock", "tornado", "zap", "zap-evolution",
     "dagger-duchess-tower-bar"})

# One card is two detector classes: the split stages of an Elixir Golem, and
# a Phoenix before and after it reforms.
CLASS_ALIASES = {
    "elixirgolembig": "elixirgolem", "elixirgolemmid": "elixirgolem",
    "phoenixbig": "phoenix",
}

# Cards the vendored unit table does not carry.
#
# `clashroyalebuildabot`'s NAME2UNIT holds 97 units; the detector knows 201
# classes. Everything added to the game after that table was written is
# therefore detected and then dropped, in two places - here and again in
# `apply` - with no log line and no counter. A Goblin Giant at 0.92 confidence
# standing next to our own Cannon went through both on 2026-08-31 and the
# policy saw an empty lane.
#
# Editing the vendored package would put the fix somewhere a re-vendor throws
# it away, so the extras live here and are merged over it.
EXTRA_UNITS = (
    # name, category, what it attacks, how it moves
    ("goblin_giant",         "TROOP",    "BUILDINGS", "GROUND"),
    ("elixir_golem",         "TROOP",    "BUILDINGS", "GROUND"),
    ("phoenix",              "TROOP",    "ALL",       "AIR"),
    ("goblin_brawler",       "TROOP",    "GROUND",    "GROUND"),
    ("skeleton_barrel",      "TROOP",    "BUILDINGS", "AIR"),
    ("barbarian_barrel",     "TROOP",    "GROUND",    "GROUND"),
    ("dagger_duchess_tower", "BUILDING", "ALL",       "GROUND"),
)


def _extra_units() -> dict:
    """`EXTRA_UNITS` as real `Unit` objects, keyed the way `_key` matches."""
    from clashroyalebuildabot.namespaces.units import (Target, Transport, Unit,
                                                       UnitCategory)
    built = {}
    for name, category, target, transport in EXTRA_UNITS:
        built[name] = Unit(name=name,
                           category=getattr(UnitCategory, category),
                           target=getattr(Target, target),
                           transport=getattr(Transport, transport))
    return built

# The frame the tap calibration in `arena` was measured against.
CALIBRATED_W, CALIBRATED_H = 1080, 1920


def _key(name: str) -> str:
    """Normalise a class name for matching across naming conventions.

    The dataset writes `mini-pekka` and `hog-rider`; BuildABot writes
    `minipekka` and `hog_rider`. Stripping every non-alphanumeric character
    makes both sides comparable without a hand-written table.
    """
    name = re.sub(r"-(evolution|evolution-symbol|symbol|skill|projectile)$", "", name)
    return re.sub(r"[^a-z0-9]", "", name.lower())


@dataclass(frozen=True)
class Seen:
    name: str
    tile_x: float
    tile_y: float
    confidence: float
    side: int                    # 0 = ours, 1 = theirs
    side_confidence: float
    # Share of hit points left, read off the bar above the unit (`hp_bars`).
    # 1.0 = no bar, so full; None = a bar that could not be read.
    hp: Optional[float] = 1.0


_HP_DETECTION = None


def hp_detection_class():
    """BuildABot's `UnitDetection` with a `hp_fraction` field.

    Upstream's class is a frozen dataclass, so the reading cannot be set on it
    after the fact. A subclass keeps every consumer that only knows
    `unit`/`position` working, and anything that wants health reads
    `getattr(detection, "hp_fraction", 1.0)`.
    """
    global _HP_DETECTION
    if _HP_DETECTION is None:
        from dataclasses import dataclass as _dataclass
        from clashroyalebuildabot.namespaces.units import UnitDetection

        @_dataclass(frozen=True)
        class HPUnitDetection(UnitDetection):
            hp_fraction: Optional[float] = 1.0

        _HP_DETECTION = HPUnitDetection
    return _HP_DETECTION


class SideClassifier:
    """Tiny CNN that answers ally-or-enemy for one cropped unit."""

    def __init__(self, path: Path = SIDE_MODEL, device: str = "cuda"):
        self.path = Path(path)
        self.ready = False
        self.accuracy = 0.0
        self.crop = 32
        self._model = None
        self._device = device
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            import torch
            from scripts.train_side_classifier import build_model
        except Exception:
            try:
                import torch
                import sys
                sys.path.insert(0, str(ROOT / "scripts"))
                from train_side_classifier import build_model
            except Exception:
                return
        try:
            blob = torch.load(self.path, map_location="cpu", weights_only=False)
            model = build_model()
            model.load_state_dict(blob["state_dict"])
            device = self._device if torch.cuda.is_available() else "cpu"
            self._model = model.to(device).eval()
            self._device = device
            self.crop = int(blob.get("crop", 32))
            self.accuracy = float(blob.get("accuracy", 0.0))
            self.ready = True
        except Exception:
            self._model = None

    def classify(self, crops: Sequence[np.ndarray]) -> List[Tuple[int, float]]:
        if not self.ready or not crops:
            return [(1, 0.0)] * len(crops)
        import torch

        batch = np.stack(crops).astype(np.float32) / 255.0
        tensor = torch.from_numpy(batch).permute(0, 3, 1, 2).to(self._device)
        with torch.no_grad():
            probabilities = torch.softmax(self._model(tensor), dim=1)
            confidence, predicted = probabilities.max(1)
        return list(zip(predicted.tolist(), confidence.tolist()))


def resolve_weights(explicit: Optional[Path] = None) -> Optional[Path]:
    if explicit:
        return explicit if explicit.exists() else None
    found = list(RUNS.glob("*/weights/best.pt"))
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


class YoloVision:
    """Detect units, decide whose they are, and place them on the grid."""

    def __init__(self, weights: Optional[Path] = None, confidence: float = 0.40,
                 imgsz: int = 640, device: str = "0", max_units: int = 40,
                 side_floor: float = 0.55):
        self.weights = resolve_weights(weights)
        self.confidence = confidence
        self.imgsz = imgsz
        self.device = device
        self.max_units = max_units
        self.side_floor = side_floor

        self.ready = False
        self.error = ""
        self.frames = 0
        self.detect_ms = 0.0
        self.last_counts = (0, 0)
        # Detector classes with no units.json entry: cards the
        # brain is blind to. Empty is the only acceptable value.
        self.unresolved: dict = {}
        # Health bars kept for `hp_bars` since start. Zero for a whole match
        # means the detector is not finding bars and every unit reads as full.
        self.bars_seen = 0

        self._model = None
        self._names: Dict[int, str] = {}
        self._units = {}
        self.sides = SideClassifier()
        self._load()

    def _load(self) -> None:
        if self.weights is None:
            self.error = "no detector checkpoint found"
            return
        try:
            from ultralytics import YOLO
            from clashroyalebuildabot.namespaces.units import NAME2UNIT
        except Exception as exc:
            self.error = f"import failed: {type(exc).__name__}: {exc}"
            return
        try:
            self._model = YOLO(str(self.weights))
            self._names = dict(self._model.names)
        except Exception as exc:
            self.error = f"load failed: {type(exc).__name__}: {exc}"
            return
        # Reuse upstream's unit registry rather than a private table: it carries
        # category/target/transport, and `BOOK.is_air` is keyed on these names.
        units = dict(NAME2UNIT)
        units.update(_extra_units())
        self._units = {_key(unit.name): unit for unit in units.values()}
        self.ready = True

    # ------------------------------------------------------------- geometry

    @staticmethod
    def _to_tile(px: float, py: float, width: int, height: int) -> Tuple[float, float]:
        """Pixel on the frame -> BuildABot's bottom-up tile coordinates."""
        px = px * CALIBRATED_W / max(1, width)
        py = py * CALIBRATED_H / max(1, height)
        grid_x = (px - arena._X0) / arena._XS
        grid_y = (py - arena._Y0) / arena._YS
        # `arena.to_grid` is `31 - tile_y`, so inverting gives tile_y here.
        return grid_x, 31.0 - grid_y

    # ---------------------------------------------------------------- detect

    def detect(self, frame) -> Tuple[List[Seen], List[Seen]]:
        """Return (ours, theirs) for one PIL frame."""
        if not self.ready:
            return [], []
        started = time.perf_counter()
        pixels = np.asarray(frame.convert("RGB"))
        height, width = pixels.shape[:2]
        try:
            result = self._model.predict(
                pixels[:, :, ::-1], imgsz=self.imgsz, conf=self.confidence,
                device=self.device, verbose=False, max_det=self.max_units)[0]
        except Exception as exc:
            self.error = f"predict failed: {type(exc).__name__}: {exc}"
            return [], []

        boxes = result.boxes
        if boxes is None or not len(boxes):
            self.detect_ms = (time.perf_counter() - started) * 1000.0
            self.last_counts = (0, 0)
            return [], []

        xyxy = boxes.xyxy.cpu().numpy()
        confidences = boxes.conf.cpu().numpy()
        classes = boxes.cls.cpu().numpy().astype(int)

        keep, crops, unit_boxes, bars = [], [], [], []
        size = self.sides.crop
        for (x1, y1, x2, y2), confidence, cls in zip(xyxy, confidences, classes):
            raw = self._names.get(int(cls), "")
            if raw == "bar":
                # Not a unit, but it is how much health the unit under it has.
                if confidence >= hp_bars.MIN_BAR_CONF:
                    bars.append((float(x1), float(y1), float(x2), float(y2)))
                continue
            if raw in NOT_A_UNIT:
                continue
            key = _key(raw)
            unit = self._units.get(CLASS_ALIASES.get(key, key))
            if unit is None:
                # Silence here cost a match. A Goblin Giant was detected at
                # 0.92 confidence standing next to our own Cannon and thrown
                # away, because `goblin-giant` had no entry in units.json -
                # and 78 of the model's 201 classes were in that state. The
                # policy saw an empty lane and held. Anything the detector can
                # name and this cannot resolve is a card we are blind to, so
                # it is counted and reported once rather than dropped.
                if raw not in NOT_A_UNIT_EITHER:
                    self.unresolved[raw] = self.unresolved.get(raw, 0) + 1
                continue
            # A sprite stands at the bottom-centre of its box; the box centre
            # sits somewhere around its chest and reads a tile too far forward.
            tile_x, tile_y = self._to_tile((x1 + x2) / 2.0, y2, width, height)
            keep.append((unit.name, tile_x, tile_y, float(confidence)))
            unit_boxes.append(hp_bars.UnitBox(
                unit.name, (float(x1), float(y1), float(x2), float(y2))))

            pad_w, pad_h = (x2 - x1) * 0.125, (y2 - y1) * 0.125
            cx1 = max(0, int(x1 - pad_w))
            cy1 = max(0, int(y1 - pad_h))
            cx2 = min(width, int(x2 + pad_w))
            cy2 = min(height, int(y2 + pad_h))
            patch = pixels[cy1:cy2, cx1:cx2]
            if patch.size == 0:
                patch = np.zeros((size, size, 3), np.uint8)
            crops.append(np.asarray(
                Image.fromarray(patch).resize((size, size), Image.BILINEAR)))

        verdicts = self.sides.classify(crops)
        health = hp_bars.unit_fractions(pixels, unit_boxes, bars)
        self.bars_seen += len(bars)
        ours: List[Seen] = []
        theirs: List[Seen] = []
        for (name, tile_x, tile_y, confidence), (side, side_confidence), hp in zip(
                keep, verdicts, health):
            # An unsure side is worse than a missing unit: putting one of ours
            # in the threat list invents a push, and putting one of theirs in
            # the ally list hides one. Below the floor, fall back to the half
            # the unit is standing on, which is right most of the time and
            # wrong only in the contested middle.
            if side_confidence < self.side_floor:
                side = 1 if tile_y > (31 - arena.RIVER_Y) else 0
            seen = Seen(name, tile_x, tile_y, confidence, int(side), side_confidence, hp)
            (theirs if side == 1 else ours).append(seen)

        self.frames += 1
        self.detect_ms = (time.perf_counter() - started) * 1000.0
        self.last_counts = (len(ours), len(theirs))
        return ours, theirs

    # ----------------------------------------------------------- state swap

    def apply(self, state, frame) -> bool:
        """Replace the state's unit lists in place. True if it ran."""
        if not self.ready:
            return False
        from clashroyalebuildabot.namespaces.units import NAME2UNIT, Position

        ours, theirs = self.detect(frame)
        # The same merge as `_units`: a name that resolves in
        # `detect` and not here would be dropped a step later.
        by_name = {unit.name: unit for unit in NAME2UNIT.values()}
        by_name.update(_extra_units())

        detection = hp_detection_class()

        def build(items: List[Seen]) -> list:
            out = []
            for seen in items:
                unit = by_name.get(seen.name)
                if unit is None:
                    continue
                out.append(detection(
                    unit=unit,
                    position=Position(bbox=(0, 0, 0, 0), conf=seen.confidence,
                                      tile_x=seen.tile_x, tile_y=seen.tile_y),
                    hp_fraction=seen.hp))
            return out

        state.allies = build(ours)
        state.enemies = build(theirs)
        return True
