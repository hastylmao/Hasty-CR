"""The replacement card classifier must be confident or silent, never wrong-and-sure."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain.cards import VENDOR_CARDS, CardClassifier, hand_boxes  # noqa: E402

DECK = ["cannon", "fireball", "hog_rider", "ice_golem", "ice_spirit",
        "musketeer", "skeletons", "the_log"]


@pytest.fixture(scope="module")
def classifier():
    instance = CardClassifier(DECK)
    if not instance.ready:
        pytest.skip("vendor card art not present")
    return instance


@pytest.mark.parametrize("name", DECK)
def test_each_card_identifies_its_own_art(classifier, name):
    image = Image.open(VENDOR_CARDS / f"{name}.jpg")
    assert classifier.classify_patch(image)[0] == name


@pytest.mark.parametrize("name", DECK)
def test_identification_survives_the_greyed_out_transform(classifier, name):
    """An unaffordable card is drawn desaturated and dimmed.  Normalised
    cross-correlation is invariant to exactly that linear change, which is why
    it replaced the upstream hardcoded scale-and-intercept hash."""
    image = Image.open(VENDOR_CARDS / f"{name}.jpg").convert("L").point(
        lambda v: int(v * 0.45 + 90)
    ).convert("RGB")
    assert classifier.classify_patch(image)[0] == name


def test_an_ambiguous_patch_is_reported_as_unknown(classifier):
    """Flat grey matches nothing in particular; guessing here is what produced
    impossible card shares in the block reports."""
    assert classifier.classify_patch(Image.new("RGB", (61, 73), (128, 128, 128)))[0] is None


def test_hand_boxes_scale_to_the_device_resolution():
    small = hand_boxes(368, 652)
    full = hand_boxes(1080, 1920)
    assert len(small) == len(full) == 4
    assert small[0][0] == 84                      # upstream CARD_INIT_X
    ratio = full[0][0] / small[0][0]
    assert 2.9 < ratio < 3.0                      # 1080/368
    for box in full:
        assert box[2] > box[0] and box[3] > box[1]
