"""The reward-screen detector must never fire on a screen that has chrome.

The whole safety argument for tapping is that the top band is *verified empty*
first, so a shop page or an offer dialog - both of which carry UI across the
top - cannot pass. These cases pin the separation measured from real captures
on this emulator.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reward_screen  # noqa: E402


def flat_gradient(size=(1080, 1920)) -> Image.Image:
    """A chest or card-reveal screen: smooth background, content low down."""
    width, height = size
    ramp = np.linspace(90, 190, height, dtype=float)[:, None]
    canvas = np.repeat(ramp, width, axis=1)
    canvas = np.stack([canvas, canvas * 0.5, canvas * 0.9], axis=2)
    canvas[760:1160, 340:740] = [150, 60, 200]      # the chest
    return Image.fromarray(canvas.astype(np.uint8))


def busy_top(size=(1080, 1920)) -> Image.Image:
    """Anything with chrome across the top: lobby, shop, offer dialog."""
    width, height = size
    rng = np.random.default_rng(0)
    canvas = np.full((height, width, 3), 120, dtype=np.uint8)
    for y in range(0, 300, 40):
        canvas[y:y + 18] = rng.integers(0, 255, 3, dtype=np.uint8)
    for x in range(0, width, 30):
        canvas[:300, x:x + 12] = rng.integers(0, 255, 3, dtype=np.uint8)
    return Image.fromarray(canvas)


def test_a_reward_screen_is_detected():
    assert reward_screen.is_reward_screen(flat_gradient())


def test_a_screen_with_top_chrome_is_never_treated_as_a_reward():
    image = busy_top()
    horizontal, vertical = reward_screen.top_band_edges(image)
    assert max(horizontal, vertical) > reward_screen.MAX_TOP_EDGE_DENSITY
    assert not reward_screen.is_reward_screen(image)


@pytest.mark.parametrize("name", ["snap.jpg", "snap2.jpg", "home.png", "monitor.png"])
def test_live_game_captures_are_not_reward_screens(name):
    path = ROOT / "tmp" / "live" / name
    if not path.exists():
        pytest.skip(f"{name} not captured on this machine")
    assert not reward_screen.is_reward_screen(Image.open(path)), name


def test_the_first_attempt_taps_the_verified_empty_band():
    assert reward_screen.advance_point(0) == reward_screen.TOP_POINT
    assert reward_screen.advance_point(1) == reward_screen.CENTRE_POINT
    assert reward_screen.TOP_POINT[1] < 1920 * reward_screen.TOP_BAND_FRACTION
