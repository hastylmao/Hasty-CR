"""Does the studio put the bot's decisions where they can actually be seen?

The canvas is 9:16 because Reels and Shorts are, and both print their caption
across the bottom of the frame. The decision stream used to live in a band
under the mirror, which is exactly that strip - so the one thing the video
exists to show was the first thing covered, and only about sixteen lines fitted
anyway.

It is now a full-height column beside the mirror. These tests hold the two
properties that arrangement depends on: nothing that has to be read sits in the
caption zone, and the column is tall enough to be worth having.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")

from scripts.studio.render import (CANVAS, CAPTION_ZONE_H,  # noqa: E402
                                   DECISION_KINDS, LAYOUTS, Layout)


@pytest.mark.parametrize("preset", sorted(LAYOUTS))
def test_nothing_readable_sits_in_the_caption_zone(preset):
    layout = Layout.build(preset)
    safe_bottom = CANVAS[1] - CAPTION_ZONE_H
    for name in ("header", "game", "rail", "feed"):
        rect = getattr(layout, name)
        assert rect.bottom() <= safe_bottom, (
            f"{preset}: {name} reaches {rect.bottom()}, past the caption line "
            f"at {safe_bottom}")


@pytest.mark.parametrize("preset", sorted(LAYOUTS))
def test_the_decision_column_sits_beside_the_mirror(preset):
    """Beside, not below - that is the whole point of the rearrangement."""
    layout = Layout.build(preset)
    assert layout.rail.left() >= layout.game.right(), preset
    # And they overlap vertically, which is what "side by side" means.
    overlap = min(layout.rail.bottom(), layout.game.bottom()) - \
        max(layout.rail.top(), layout.game.top())
    assert overlap > layout.game.height() * 0.9, (preset, overlap)


@pytest.mark.parametrize("preset", sorted(LAYOUTS))
def test_the_decision_column_is_tall_enough_to_be_worth_having(preset):
    """At 40px an entry, the column should beat the old sixteen-line band."""
    layout = Layout.build(preset)
    entries = (layout.rail.height() - 260) // 40      # 260 for the state block
    assert entries >= 24, (preset, entries)


def test_the_mirror_keeps_its_aspect_ratio():
    """A stretched mirror would be worse than a small one."""
    for preset in LAYOUTS:
        game = Layout.build(preset).game
        assert abs(game.width() * 16 / 9 - game.height()) <= 2, preset


def test_the_column_shows_decisions_rather_than_every_log_line():
    """Vision timings and screen transitions are not decisions.

    Filling the column with `ours=1 theirs=0 23ms` is how it managed to be
    both crowded and uninformative.
    """
    assert "PLAY" in DECISION_KINDS
    assert "IDLE" in DECISION_KINDS
    assert "SCREEN" not in DECISION_KINDS
    assert "other" not in DECISION_KINDS
