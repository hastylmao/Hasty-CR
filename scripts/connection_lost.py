"""Recognise Clash Royale's "Connection lost" dialog and find its RELOAD button.

This dialog appears when another device signs into the same account, and it is
the one popup `popup_guard` cannot handle: it has no X in the corner, only a
RELOAD text link. So `find_close_button` returned None, the bot sat on an
unrecognised screen for the full 75 seconds, and the recovery relaunched the
whole app - three times in five minutes when it started happening. Tapping
RELOAD is what a person would do and costs a second instead of two minutes.

Detection is deliberately narrow, because a false positive is a tap on a screen
we have not identified. It requires both halves of the signature: the dialog's
flat (29, 32, 36) slab filling the panel area, and light text where RELOAD sits.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
from PIL import Image

# Measured on a captured frame at the canonical 1080x1920.
SLAB = (29, 32, 36)
SLAB_TOLERANCE = 14
PANEL = (100, 950, 980, 1100)      # x0, y0, x1, y1 - dialog body, above the link
RELOAD_BOX = (140, 1115, 330, 1160)
MIN_SLAB_SHARE = 0.80
MIN_TEXT_PIXELS = 120


def find_reload(image: Image.Image) -> Optional[Tuple[int, int]]:
    """Centre of the RELOAD link, or None if this is not that dialog."""
    px = np.asarray(image.convert("RGB")).astype(int)
    if px.shape[0] < 1900 or px.shape[1] < 1000:
        return None
    r, g, b = px[:, :, 0], px[:, :, 1], px[:, :, 2]
    slab = ((abs(r - SLAB[0]) < SLAB_TOLERANCE)
            & (abs(g - SLAB[1]) < SLAB_TOLERANCE)
            & (abs(b - SLAB[2]) < SLAB_TOLERANCE))

    x0, y0, x1, y1 = PANEL
    if slab[y0:y1, x0:x1].mean() < MIN_SLAB_SHARE:
        return None

    tx0, ty0, tx1, ty1 = RELOAD_BOX
    text = (r > 190) & (g > 190) & (b > 190)
    region = text[ty0:ty1, tx0:tx1]
    if region.sum() < MIN_TEXT_PIXELS:
        return None

    ys, xs = np.nonzero(region)
    return (int(tx0 + xs.mean()), int(ty0 + ys.mean()))
