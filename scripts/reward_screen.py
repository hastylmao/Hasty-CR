"""Detect and dismiss Clash Royale's post-match chest and card-reveal screens.

Why this exists
---------------
Winning a match can drop the client on a chest-opening screen. It has no close
button, and relaunching the app does not clear it because the reward is still
pending - the run was observed stuck on one for over five minutes, cycling
`POPUP no_close_button` and `RECOVER relaunched_app` and playing nothing. Left
alone it would have burned the whole unattended run.

Why tapping here is safe
------------------------
The test is that the **top band of the screen is verifiably empty**: no edges at
all, horizontally or vertically. Measured on captures from this emulator:

    chest screen / card reveal   0.00% - 0.01%  top-band edge density
    battle                       4.9%  - 14.1%
    lobby, home, resume dialog  12.7%  - 20.0%

So the bot taps a region it has just confirmed contains nothing. A shop page, a
special offer, or any dialog with a purchase button carries chrome across the
top and cannot pass this test - which is the point, because a blind tap on an
offer dialog is exactly the mistake this project must not make.

The centre point is only ever used as a second attempt *after* the same screen
has already passed the emptiness test, because a chest needs the chest itself
tapped to open, while a card reveal dismisses from anywhere.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# Device is 1080x1920. The top point sits inside the band this module verifies
# is empty; the centre point is the chest's "tap to open" affordance.
TOP_POINT = (540, 115)
CENTRE_POINT = (540, 960)

TOP_BAND_FRACTION = 0.12
EDGE_THRESHOLD = 18       # per-pixel luminance step that counts as an edge
MAX_TOP_EDGE_DENSITY = 1.5  # percent; measured classes are 0.01 vs 4.9 and up


def _edges(band: np.ndarray) -> tuple[float, float]:
    luma = band.mean(axis=2)
    horizontal = np.abs(np.diff(luma, axis=1))
    vertical = np.abs(np.diff(luma, axis=0))
    return (
        float((horizontal > EDGE_THRESHOLD).mean() * 100.0),
        float((vertical > EDGE_THRESHOLD).mean() * 100.0),
    )


def top_band_edges(image: Image.Image) -> tuple[float, float]:
    small = np.asarray(image.convert("RGB").resize((360, 640)), dtype=float)
    return _edges(small[: int(640 * TOP_BAND_FRACTION)])


def is_reward_screen(image: Image.Image) -> bool:
    """True only when the top band contains no UI whatsoever."""
    horizontal, vertical = top_band_edges(image)
    return horizontal < MAX_TOP_EDGE_DENSITY and vertical < MAX_TOP_EDGE_DENSITY


def advance_point(attempt: int) -> tuple[int, int]:
    """Alternate between the verified-empty band and the chest.

    Card reveals dismiss from anywhere, so the empty band clears them. A closed
    chest only opens when the chest is tapped, so every other attempt falls back
    to the centre - but only on a screen that already passed the emptiness test.
    """
    return TOP_POINT if attempt % 2 == 0 else CENTRE_POINT
