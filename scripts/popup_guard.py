"""Detect and dismiss Supercell's blocking offer popups.

Overnight the lobby gets covered by Pass Royale / special-offer dialogs, which
read as an `unknown` screen and stall the runner indefinitely.  Recovery is
deliberately narrow: locate the red circular close button by colour and tap
that exact centroid.  Nothing here ever taps a confirm/purchase control, and
if the close button is not found the runner simply waits.
"""

from __future__ import annotations

import numpy as np

# The close button sits at the dialog's top-right corner, further right than
# the lobby's red notification badges (which centre around x=890).
SEARCH_BOX = (935, 1060, 200, 360)  # x0, x1, y0, y1 in 1080x1920 space
MIN_PIXELS = 700
# A solid badge fills most of its bounding box; the X is a cross inside a
# circle, so a large fill ratio means we found a badge and must not tap it.
SIZE_RANGE = (35, 95)
FILL_RANGE = (0.20, 0.58)


def find_close_button(full) -> tuple[int, int] | None:
    """Centroid of the red close button, or None if it is not on screen."""
    pixels = np.asarray(full)
    if pixels.shape[0] < 1900 or pixels.shape[1] < 1000:
        return None
    x0, x1, y0, y1 = SEARCH_BOX
    roi = pixels[y0:y1, x0:x1]
    r = roi[:, :, 0].astype(np.int16)
    g = roi[:, :, 1].astype(np.int16)
    b = roi[:, :, 2].astype(np.int16)
    # Supercell's close button is a saturated red circle; the surrounding
    # dialog art is orange/gold, so require red to dominate both channels.
    red = (r > 170) & (g < 95) & (b < 95) & (r - g > 90) & (r - b > 90)
    total = int(red.sum())
    if total < MIN_PIXELS:
        return None
    ys, xs = np.nonzero(red)
    width = int(xs.max() - xs.min()) + 1
    height = int(ys.max() - ys.min()) + 1
    low, high = SIZE_RANGE
    if not (low <= width <= high and low <= height <= high):
        return None
    if not 0.7 <= width / height <= 1.4:
        return None
    fill = total / (width * height)
    if not FILL_RANGE[0] <= fill <= FILL_RANGE[1]:
        return None
    return int(xs.mean()) + x0, int(ys.mean()) + y0
