"""A stronger card classifier for the hand.

The upstream detector reduces each card to an **8x8 greyscale hash** (64 values)
and then assigns all five slots at once with `linear_sum_assignment`. Two
consequences, both measured live:

* 64 greyscale values is not enough to separate eight cards reliably, and
* the one-to-one assignment couples the slots, so a single bad crop steals a
  card and forces wrong answers in the other slots too.

Live capture showed 50-96 slot flips per match - about two per card played -
with Ice Spirit reported at 22-32% of all plays, which is impossible in an
eight-card deck where a card cannot exceed 20%.

This classifier keeps the same reference art but:

* crops from the **full-resolution** frame rather than the 368x652 downscale,
* compares at 32x32 (16x the information),
* scores with **normalised cross-correlation**, which is invariant to the
  linear brightness and contrast change that "greyed out because you cannot
  afford it" applies - the exact effect the upstream multi-hash was trying to
  approximate with a hardcoded scale and intercept,
* scores each slot **independently**, and reports `None` when the best and
  second-best cards are too close, so an uncertain slot holds its previous
  value instead of inventing a new one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

VENDOR_CARDS = (
    Path(__file__).resolve().parents[2]
    / "vendor" / "ClashRoyaleBuildABot" / "clashroyalebuildabot" / "images" / "cards"
)

# CARD_CONFIG in upstream constants.py, expressed on the 368x652 screenshot.
_CARD_Y, _CARD_H = 543, 73
_CARD_X0, _CARD_W, _CARD_DX = 84, 61, 69
_SRC_W, _SRC_H = 368, 652

PATCH = 32
MIN_MARGIN = 0.04     # required gap between best and second-best correlation
MIN_SCORE = 0.30      # below this nothing is recognised at all


def hand_boxes(width: int, height: int) -> List[Tuple[int, int, int, int]]:
    """The four hand-card boxes, scaled to an arbitrary frame size."""
    sx, sy = width / _SRC_W, height / _SRC_H
    boxes = []
    for slot in range(4):
        x0 = _CARD_X0 + slot * _CARD_DX
        boxes.append((
            int(round(x0 * sx)), int(round(_CARD_Y * sy)),
            int(round((x0 + _CARD_W) * sx)), int(round((_CARD_Y + _CARD_H) * sy)),
        ))
    return boxes


def _signature(image: Image.Image) -> np.ndarray:
    """Zero-mean, unit-norm greyscale patch: the NCC-ready form."""
    patch = np.asarray(
        image.convert("L").resize((PATCH, PATCH), Image.Resampling.BILINEAR),
        dtype=np.float32,
    ).ravel()
    patch -= patch.mean()
    norm = np.linalg.norm(patch)
    return patch / norm if norm > 1e-6 else patch


class CardClassifier:
    def __init__(self, deck: List[str], cards_dir: Path | None = None):
        self.deck = list(deck)
        directory = Path(cards_dir or VENDOR_CARDS)
        self.references: Dict[str, np.ndarray] = {}
        for name in self.deck:
            path = directory / f"{name}.jpg"
            if path.exists():
                self.references[name] = _signature(Image.open(path))

    @property
    def ready(self) -> bool:
        return len(self.references) == len(self.deck)

    def classify_patch(self, image: Image.Image) -> Tuple[Optional[str], float]:
        """Best matching card for one crop, or None when it is ambiguous."""
        if not self.references:
            return None, 0.0
        signature = _signature(image)
        scored = sorted(
            ((float(np.dot(signature, ref)), name)
             for name, ref in self.references.items()),
            reverse=True,
        )
        best_score, best_name = scored[0]
        runner_up = scored[1][0] if len(scored) > 1 else -1.0
        if best_score < MIN_SCORE or (best_score - runner_up) < MIN_MARGIN:
            return None, best_score
        return best_name, best_score

    def classify_hand_scored(
        self, frame: Image.Image
    ) -> List[Tuple[Optional[str], float]]:
        """Four (card, correlation) slot readings from a full-resolution frame.

        The score is what lets a caller settle a duplicate: a Clash Royale hand
        holds four *distinct* cards, so when two slots name the same card the
        weaker correlation is the wrong one.
        """
        boxes = hand_boxes(frame.width, frame.height)
        return [self.classify_patch(frame.crop(box)) for box in boxes]

    def classify_hand(self, frame: Image.Image) -> List[Optional[str]]:
        """Four slot readings from a full-resolution frame."""
        return [name for name, _score in self.classify_hand_scored(frame)]
