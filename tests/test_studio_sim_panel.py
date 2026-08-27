"""The studio can show the live match and the simulator in one frame.

The point is a single recordable frame carrying both halves of the project.
Two things have to hold for that to be worth anything:

* the two arenas are the same shape, so neither is stretched and they read as
  the same game rather than two different ones; and
* adding the panel costs the existing layouts nothing, because the live mirror
  is what runs every day and the side-by-side view is for clips.

The simulator panel reuses `sim.watch.Watcher` rather than redrawing an arena.
That is checked here too: a second implementation would drift from the real
viewer, and then the thing on screen would stop being the simulator.
"""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PyQt6")

from PyQt6.QtCore import QRect                                    # noqa: E402
from PyQt6.QtGui import QImage, QPainter                          # noqa: E402
from PyQt6.QtWidgets import QApplication                          # noqa: E402

from studio import render                                         # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------- layout

def test_the_sim_layout_puts_two_arenas_side_by_side(app):
    layout = render.Layout.build("sim")
    assert layout.sim is not None
    assert layout.game.top() == layout.sim.top()
    assert layout.sim.left() > layout.game.right()
    assert layout.game.size() == layout.sim.size(), (
        "the two arenas are different sizes, so one is the 'real' one")


def test_both_arenas_are_exactly_9_by_16(app):
    """A letterboxed arena would look like a different game."""
    layout = render.Layout.build("sim")
    for name, rect in (("live", layout.game), ("sim", layout.sim)):
        ratio = rect.height() / rect.width()
        assert abs(ratio - 16 / 9) < 0.01, f"{name} is {ratio:.3f}, not 16/9"


def test_the_other_layouts_do_not_gain_a_sim_panel(app):
    for preset in ("balanced", "game", "feed"):
        assert render.Layout.build(preset).sim is None, preset


def test_nothing_overlaps_the_caption_zone(app):
    """The bottom of a Reel is the caption's, and this layout is for Reels."""
    layout = render.Layout.build("sim")
    floor = render.CANVAS[1] - render.CAPTION_ZONE_H
    assert layout.sim.bottom() < floor
    assert layout.rail.bottom() <= floor


def test_the_rail_still_has_room_to_be_read(app):
    layout = render.Layout.build("sim")
    assert layout.rail.height() > 300, (
        f"the decision rail is {layout.rail.height()}px tall; the two arenas "
        f"have squeezed out the thing that explains them")
    assert layout.rail.width() > render.CANVAS[0] * 0.9


def test_the_live_mirror_got_bigger_in_the_default_layout(app):
    """The mirror was smaller than the space beside it."""
    assert render.LAYOUTS["balanced"] >= 0.66


# --------------------------------------------------------------- the panel

def test_the_panel_reuses_the_real_simulator_viewer():
    source = (ROOT / "scripts" / "studio" / "simfeed.py").read_text(encoding="utf-8")
    assert "from sim.watch import Watcher" in source
    assert "_arena" in source, (
        "simfeed is drawing its own arena instead of the simulator's, so the "
        "two will drift")


def test_the_embedded_viewer_cannot_quit_the_studio():
    """`Watcher.tick` calls QGuiApplication.quit() when its matches run out."""
    source = (ROOT / "scripts" / "studio" / "simfeed.py").read_text(encoding="utf-8")
    assert "matches=0" in source
    assert "def close(self)" in source, (
        "Watcher.close is not overridden; a finished match would close the "
        "studio window")


def test_a_broken_simulator_does_not_take_the_studio_down(app):
    """The panel is an addition to the view, not something the bot needs."""
    from studio.simfeed import SimFeed
    import sim.watch
    original = sim.watch.Watcher

    class Exploding:
        def __init__(self, *a, **k):
            raise RuntimeError("no card data")

    sim.watch.Watcher = Exploding
    try:
        feed = SimFeed()
        assert not feed.ready
        assert "no card data" in feed.error
        assert feed.recent() == [] and feed.results() == []
        assert feed.status()
    finally:
        sim.watch.Watcher = original


def test_drawing_an_unready_panel_is_harmless(app):
    from studio.simfeed import SimFeed
    import sim.watch
    original = sim.watch.Watcher

    class Exploding:
        def __init__(self, *a, **k):
            raise RuntimeError("nope")

    sim.watch.Watcher = Exploding
    try:
        feed = SimFeed()
        canvas = QImage(200, 356, QImage.Format.Format_RGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        render.draw_sim(painter, QRect(0, 0, 200, 356), feed)  # must not raise
        painter.end()
    finally:
        sim.watch.Watcher = original


def test_the_panel_draws_the_arena_when_it_is_ready(app):
    from studio.simfeed import SimFeed
    feed = SimFeed(speed=1.0)
    if not feed.ready:
        pytest.skip(f"simulator unavailable: {feed.error}")
    try:
        layout = render.Layout.build("sim")
        canvas = QImage(*render.CANVAS, QImage.Format.Format_RGB32)
        canvas.fill(0)
        painter = QPainter(canvas)
        render.draw_sim(painter, layout.sim, feed)
        painter.end()

        # Something green and arena-shaped landed in the panel and nowhere else.
        inside = canvas.pixelColor(layout.sim.center())
        assert inside.green() > inside.blue(), (
            f"the sim panel centre is {inside.name()}, which is not grass")
        outside = canvas.pixelColor(layout.game.center())
        assert outside.alpha() and outside.green() < 40, (
            "the sim drew outside its own rect, over the live mirror")
    finally:
        feed.stop()
