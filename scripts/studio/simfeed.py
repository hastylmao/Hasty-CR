"""Run a simulator match inside the studio, beside the live one.

The point is a single frame that shows both halves of the project at once: the
bot playing a real ladder match, and the simulator it was trained in playing
its own, side by side.

**It reuses `sim/watch.py` rather than redrawing the arena.** That module is
six hundred lines of terrain, towers, unit sprites and hand tiles, and a second
implementation would drift from it immediately - the two would stop looking
like the same simulator, which is the one thing this view is for. `Watcher`
already draws its arena into an arbitrary rect, so the whole of it is reachable
from here with `_arena(painter, rect)`.

Three things are deliberately disabled on the embedded copy:

* **compose() and update()** - the standalone viewer paints its own 1080x1920
  canvas every frame. Here the studio owns the canvas, so that work is thrown
  away, and it is the expensive half of a tick.
* **quit on completion** - `Watcher.tick` calls `QGuiApplication.quit()` when
  it has played its quota of matches. Embedded, that would close the studio.
  `matches=0` means it keeps going, and the override makes it structural
  rather than a setting someone can change from the command line later.
* **recording** - the studio has its own recorder over the whole canvas.
"""

from __future__ import annotations

from argparse import Namespace
from typing import Optional

from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPainter


def _settings(speed: float, seed: int, opponent: str, skin: str) -> Namespace:
    """The argument surface `sim.watch.Watcher` expects.

    Built explicitly rather than by calling the module's parser: the parser
    exists to read a command line, and every default it holds is one this view
    would have to override anyway.
    """
    return Namespace(
        seed=seed,
        matches=0,              # never quit; see the module docstring
        level=11,
        speed=speed,
        fps=30,                 # the arena is half the width it is designed
                                # for, so frames past 30 buy nothing visible
        scale=0.48,
        opponent=opponent,
        random_decks=False,
        record=None,
        probe=None,
        rings=False,
        skin=skin,
    )


class SimFeed:
    """A headless `Watcher` that the studio draws wherever it likes.

    Construction is not free - it loads the card table and the spell table -
    so it is made once and kept. If loading fails the studio must still run:
    the simulator is an addition to the view, not something the live bot
    depends on, and `ready` says which happened.
    """

    def __init__(self, speed: float = 1.0, seed: int = 1,
                 opponent: str = "scripted", skin: str = "game"):
        self.error: str = ""
        self.watcher = None
        try:
            from sim.watch import Watcher

            class Embedded(Watcher):
                # The studio owns the canvas and the frame loop.
                def compose(self) -> None:
                    pass

                def update(self, *args) -> None:
                    pass

                def close(self) -> bool:
                    return False

            self.watcher = Embedded(_settings(speed, seed, opponent, skin))
        except Exception as exc:                # noqa: BLE001 - never fatal
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def ready(self) -> bool:
        return self.watcher is not None

    # ---------------------------------------------------------------- state

    def status(self) -> str:
        """A short line for the header: clock, crowns and matches played."""
        if not self.ready or self.watcher.match is None:
            return self.error or "starting"
        match = self.watcher.match
        seconds = int(match.elapsed_ms // 1000)
        return (f"m{self.watcher.played}  {seconds // 60}:{seconds % 60:02d}  "
                f"{match.crowns_for(1)}-{match.crowns_for(-1)}")

    def recent(self, limit: int = 14) -> list[str]:
        """The simulator's own decision log, newest last."""
        if not self.ready:
            return []
        return list(self.watcher.log)[-limit:]

    def results(self, limit: int = 6) -> list[str]:
        if not self.ready:
            return []
        return list(self.watcher.results)[-limit:]

    # --------------------------------------------------------------- drawing

    def draw(self, painter: QPainter, rect: QRect) -> None:
        if not self.ready or self.watcher.match is None:
            return
        painter.save()
        painter.setClipRect(rect)
        try:
            self.watcher._arena(painter, rect)
        finally:
            painter.restore()

    def stop(self) -> None:
        if self.ready:
            try:
                self.watcher.timer.stop()
            except Exception:                   # noqa: BLE001
                pass
