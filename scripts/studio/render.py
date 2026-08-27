"""Composite the mirror, the brain state and the log into one portrait canvas.

Everything is drawn into a fixed 1080x1920 QImage rather than sized to the
window.  Shorts and Reels both want exactly 9:16, and a canvas that tracks the
window would mean the recording changes shape if the window is nudged.  The
window shows a scaled copy; the recorder gets the full-resolution original.

Layout
------
Two columns above a caption zone.  The mirror takes the left, and everything the
bot is thinking takes a full-height column on the right; under the mirror sits
the current call and the raw brain log.

The decision stream used to be a band across the bottom, which is exactly where
a Reel or a Short prints its caption - so the one thing the video exists to show
was the first thing covered, and only about sixteen lines fitted anyway.  The
bottom `CAPTION_ZONE_H` pixels now carry nothing that has to be read.

`--layout game` trades column width for a bigger mirror, `--layout feed` does
the reverse.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from PyQt6.QtCore import QRect, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QImage, QPainter,
                         QPen)

from . import detect
from .feed import Event, LiveState

try:                                   # the exact tap mapping, if importable
    from scripts.brain import arena
except Exception:                      # pragma: no cover - studio still works
    arena = None

CANVAS = (1080, 1920)
PAD = 28
GAP = 14
HEADER_H = 58

# The bottom of a Reel or a Short belongs to the caption, not to us. Anything
# below this line is expected to be covered and carries nothing that has to be
# read - the decision stream lives beside the mirror instead of under it.
CAPTION_ZONE_H = 300

# What counts as a decision for the column and the current-call strip.
DECISION_KINDS = frozenset({"PLAY", "IDLE", "ERROR", "START", "END"})

# Fraction of the canvas width the live mirror takes. `balanced` was 0.62,
# which left the mirror smaller than the empty space beside it once the
# rail stopped needing the full column.
LAYOUTS = {"balanced": 0.68, "game": 0.76, "feed": 0.56}

# Neutral greys from the Tailwind zinc ramp, which is a published scale with
# even perceptual steps, rather than hand-mixed navy. One accent, used only for
# the thing the viewer is meant to look at: the decision the bot just made.
# The previous palette ran pink, gold, green, orange, blue and purple at once,
# which reads as decoration and leaves nothing to draw the eye.
BG = QColor("#09090b")          # zinc-950
SURFACE = QColor("#111113")
SURFACE_SOFT = QColor("#0d0d0f")
EDGE = QColor("#232326")
TEXT = QColor("#e4e4e7")        # zinc-200
DIM = QColor("#a1a1aa")         # zinc-400
FAINT = QColor("#52525b")       # zinc-600
ACCENT = QColor("#60a5fa")      # the single accent
OK = QColor("#a3a3a8")
WARN = QColor("#d4d4d8")
BAD = QColor("#f87171")         # kept: a failure must not read as ordinary

# Back-compat aliases; the module used these names throughout.
PANEL = SURFACE
PANEL_SOFT = SURFACE_SOFT
GOLD = TEXT

# Intent no longer gets its own hue. The family still varies the weight of the
# row so a push and a cycle are distinguishable, without six colours competing.
FAMILY_COLOURS = {
    "defend": DIM,
    "push": TEXT,
    "cycle": FAINT,
    "value": DIM,
    "chip": FAINT,
    "idle": FAINT,
    "system": FAINT,
    "error": BAD,
    "other": DIM,
}

MONO = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]
SANS = ["Segoe UI Semibold", "Segoe UI", "Arial"]


def font(size: int, families: Sequence[str] = MONO, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(list(families))
    f.setPixelSize(size)
    f.setBold(bold)
    return f


@dataclass(frozen=True)
class Layout:
    canvas: Tuple[int, int]
    header: QRect
    game: QRect
    rail: QRect
    feed: QRect
    # Set only by the `sim` preset: the simulator arena, beside the live
    # mirror. None in every other layout, and the studio draws it only when
    # it is not None, so adding it costs the existing layouts nothing.
    sim: Optional[QRect] = None

    @staticmethod
    def build(preset: str = "balanced", canvas: Tuple[int, int] = CANVAS) -> "Layout":
        """Two columns: the mirror on the left, everything the bot is thinking
        on the right, both above the caption zone.

        The decision stream used to sit in a band under the mirror, which is
        exactly where a Reel or Short prints its caption - so the one thing the
        video exists to show was the first thing covered. It is now a full
        column beside the mirror, and the strip under the mirror carries only
        the single current call, large enough to read at phone size.
        """
        width, height = canvas
        if preset == "sim":
            return Layout._side_by_side(canvas)
        fraction = LAYOUTS.get(preset, LAYOUTS["balanced"])
        game_w = int(round(width * fraction))
        game_h = int(round(game_w * 16 / 9))

        header = QRect(PAD, PAD, width - 2 * PAD, HEADER_H)
        game = QRect(PAD, header.bottom() + 1 + GAP, game_w, game_h)

        rail_x = game.right() + 1 + GAP
        rail_w = width - PAD - rail_x
        # The rail runs past the bottom of the mirror, down to the caption
        # line, because the decision list is the thing that wants the room.
        rail_bottom = height - CAPTION_ZONE_H
        rail = QRect(rail_x, game.top(), rail_w, rail_bottom - game.top())

        strip_y = game.bottom() + 1 + GAP
        feed = QRect(PAD, strip_y, game_w, max(0, rail_bottom - strip_y))
        return Layout(canvas, header, game, rail, feed)

    @staticmethod
    def _side_by_side(canvas: Tuple[int, int]) -> "Layout":
        """Live match and simulator together, decisions underneath.

        The other presets put the decision rail in a column beside the mirror,
        which works when there is one thing to watch. With two arenas there is
        no room for a side column at a size worth reading, so the rail moves
        below them and runs the full width - which suits it, being a list.

        Both arenas keep 9:16 exactly. Letterboxing one to fit a wider box
        would be the obvious shortcut and would make the two look like
        different games.
        """
        width, height = canvas
        each_w = (width - 2 * PAD - GAP) // 2
        each_h = int(round(each_w * 16 / 9))

        header = QRect(PAD, PAD, width - 2 * PAD, HEADER_H)
        top = header.bottom() + 1 + GAP
        game = QRect(PAD, top, each_w, each_h)
        sim = QRect(game.right() + 1 + GAP, top, each_w, each_h)

        rail_top = game.bottom() + 1 + GAP
        rail_bottom = height - CAPTION_ZONE_H
        rail = QRect(PAD, rail_top, width - 2 * PAD,
                     max(0, rail_bottom - rail_top))
        # No separate current-call strip in this layout: the rail is already
        # full width and the space under two arenas is not enough for both.
        feed = QRect(PAD, rail_bottom, width - 2 * PAD, 0)
        return Layout(canvas, header, game, rail, feed, sim)


@dataclass
class Telemetry:
    """Numbers about the studio itself, shown so the video can be trusted."""
    mirror_fps: float = 0.0
    render_ms: float = 0.0
    detector: str = "off"
    detector_ms: float = 0.0
    detections: int = 0
    recording: bool = False
    recorded_seconds: float = 0.0
    record_behind: float = 0.0
    surface: str = ""
    bot: str = ""
    mirror_stale: float = 0.0
    mirror_source: str = "window"


# --------------------------------------------------------------- primitives


def panel(p: QPainter, rect: QRect, fill: QColor = SURFACE, radius: int = 6,
          edge: Optional[QColor] = EDGE) -> None:
    """A flat surface with a hairline edge.

    Every block used to be a 14px-radius filled card, which at this density
    reads as a pile of chips rather than a layout. Squared-off surfaces and a
    single-pixel edge let the type do the separating.
    """
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(rect, radius, radius)
    if edge is not None:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(edge, 1))
        p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)


def label(p: QPainter, rect: QRect, text: str, f: QFont, colour: QColor,
          align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter) -> None:
    p.setPen(QPen(colour))
    p.setFont(f)
    p.drawText(rect, int(align), text)


def bar(p: QPainter, rect: QRect, fraction: float, colour: QColor,
        track: QColor = QColor("#1b2537")) -> None:
    fraction = max(0.0, min(1.0, fraction))
    radius = rect.height() // 2
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(track))
    p.drawRoundedRect(rect, radius, radius)
    if fraction <= 0:
        return
    filled = QRect(rect.left(), rect.top(),
                   max(rect.height(), int(rect.width() * fraction)), rect.height())
    p.setBrush(QBrush(colour))
    p.drawRoundedRect(filled, radius, radius)


def pill(p: QPainter, x: int, y: int, text: str, colour: QColor,
         f: Optional[QFont] = None) -> int:
    """Draw a status chip and return its right edge."""
    f = f or font(17, MONO, bold=True)
    metrics = QFontMetrics(f)
    width = metrics.horizontalAdvance(text) + 26
    height = 32
    rect = QRect(x, y, width, height)
    p.setPen(Qt.PenStyle.NoPen)
    fill = QColor(colour)
    fill.setAlpha(38)
    p.setBrush(QBrush(fill))
    p.drawRoundedRect(rect, 8, 8)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(colour, 1))
    p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
    label(p, rect, text, f, colour, Qt.AlignmentFlag.AlignCenter)
    return rect.right()


# ------------------------------------------------------------------ sections


def draw_header(p: QPainter, rect: QRect, state: LiveState,
                telemetry: Telemetry) -> None:
    panel(p, rect, PANEL_SOFT)
    inner = rect.adjusted(22, 0, -18, 0)
    label(p, QRect(inner.left(), inner.top(), 260, inner.height()),
          "HastyCR", font(30, SANS, bold=True), TEXT)
    label(p, QRect(inner.left() + 152, inner.top() + 4, 300, inner.height()),
          "studio", font(22, MONO), FAINT)

    # A frozen mirror still reports 60fps: PrintWindow keeps succeeding and
    # keeps returning the last frame DWM presented. Say so loudly, because the
    # failure is invisible in a recording until it is too late to redo the take.
    if telemetry.mirror_stale >= 1.5:
        chips: List[Tuple[str, QColor]] = [
            (f"MIRROR FROZEN {telemetry.mirror_stale:.0f}s", QColor("#f87171"))]
    elif telemetry.mirror_source == "adb":
        # Name the degraded source rather than showing a 60fps that is the
        # compositing rate and not the gameplay rate.
        chips = [("MIRROR via ADB", DIM)]
    else:
        chips = [(f"MIRROR {telemetry.mirror_fps:4.0f}fps",
                  DIM if telemetry.mirror_fps >= 45 else WARN)]
    # Always, whatever the mirror is doing. A window smaller than the panel it
    # is drawn into is being upscaled, and no amount of filtering puts detail
    # back: MuMu renders its Android surface at the size of that child window,
    # so 560x996 on screen is 560x996 of real pixels no matter what the device
    # resolution says. The fix is a bigger emulator window, which only the
    # person at the machine can do, and printing the number is more use than
    # quietly blurring.
    if telemetry.source_w:
        chips.append((f"SRC {telemetry.source_w}x{telemetry.source_h}",
                      WARN if telemetry.source_w < 1000 else FAINT))
    if telemetry.detector == "live":
        chips.append((f"YOLO {telemetry.detections:2d} obj", FAINT))
    else:
        chips.append((f"YOLO {telemetry.detector}", FAINT))
    # The clock only means anything during a battle; between matches it would
    # be the stale end time of the last one, so say so instead.
    if state.screen == "in_game":
        chips.append((f"MATCH {state.match_index}  "
                      f"{state.clock // 60}:{state.clock % 60:02d}", TEXT))
    else:
        chips.append((f"MATCH {state.match_index}  {state.screen[:9].upper()}", DIM))
    if telemetry.recording:
        seconds = int(telemetry.recorded_seconds)
        text = f"● REC {seconds // 60}:{seconds % 60:02d}"
        colour = QColor("#f87171")
        # An encoder that cannot keep up produces a short file, which is only
        # discovered after the take.  Say it on screen instead.
        if telemetry.record_behind > 1.0:
            text += f" -{telemetry.record_behind:.0f}s"
            colour = DIM
        chips.append((text, colour))

    x = rect.right() - 18
    for text, colour in reversed(chips):
        f = font(17, MONO, bold=True)
        width = QFontMetrics(f).horizontalAdvance(text) + 26
        x -= width
        pill(p, x, rect.top() + (rect.height() - 32) // 2, text, colour, f)
        x -= 10


def draw_game(p: QPainter, rect: QRect, frame: Optional[QImage],
              boxes: Sequence[detect.Box], marker: Optional[Tuple[float, float]],
              marker_age: float, show_labels: bool = True) -> None:
    panel(p, rect, QColor("#05070d"))
    p.save()
    p.setClipRect(rect)
    if frame is None or frame.isNull():
        label(p, rect, "waiting for the emulator surface…", font(22, MONO), DIM,
              Qt.AlignmentFlag.AlignCenter)
        p.restore()
        return

    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    # Fit rather than fill.  MuMu's surface is already 9:16 so this is a no-op
    # in normal use, but a `--frame` still or a resized emulator must not be
    # stretched: box coordinates are normalised to the *image*, so a stretched
    # mirror would put every box in the wrong place.
    scale = min(rect.width() / frame.width(), rect.height() / frame.height())
    drawn = QRect(0, 0, int(frame.width() * scale), int(frame.height() * scale))
    drawn.moveCenter(rect.center())
    p.drawImage(drawn, frame)
    rect = drawn

    for box in boxes:
        r, g, b = detect.palette_for(box.class_id)
        colour = QColor(r, g, b)
        x1 = rect.left() + box.x1 * rect.width()
        y1 = rect.top() + box.y1 * rect.height()
        x2 = rect.left() + box.x2 * rect.width()
        y2 = rect.top() + box.y2 * rect.height()
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(colour, 2))
        p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))
        if not show_labels:
            continue
        text = f"{box.label} {box.confidence:.2f}"
        f = font(14, MONO, bold=True)
        width = QFontMetrics(f).horizontalAdvance(text) + 10
        chip = QRectF(x1, max(rect.top(), y1 - 19), width, 18)
        p.setPen(Qt.PenStyle.NoPen)
        fill = QColor(colour)
        fill.setAlpha(210)
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(chip, 3, 3)
        label(p, chip.toRect(), " " + text, f, QColor("#06090f"))

    # Where the bot actually tapped, using the same measured pixel mapping the
    # bot taps through, so the ring cannot drift from the real placement.
    if marker is not None and marker_age < 1.6:
        nx, ny = marker
        cx = rect.left() + nx * rect.width()
        cy = rect.top() + ny * rect.height()
        for index in range(3):
            phase = marker_age - index * 0.18
            if phase < 0:
                continue
            radius = 16 + phase * 90
            colour = QColor(GOLD)
            colour.setAlpha(max(0, int(200 * (1 - phase / 1.6))))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(colour, 3))
            p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
    p.restore()

    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(EDGE, 1))
    p.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)


class Stack:
    """Vertical cursor for the rail, so sections cannot overlap or overflow."""

    def __init__(self, rect: QRect, gap: int = GAP):
        self.rect = rect
        self.y = rect.top()
        self.gap = gap

    def take(self, height: int) -> Optional[QRect]:
        if self.y + height > self.rect.bottom():
            return None
        block = QRect(self.rect.left(), self.y, self.rect.width(), height)
        self.y += height + self.gap
        return block


def _section(p: QPainter, rect: QRect, title: str) -> QRect:
    panel(p, rect)
    label(p, QRect(rect.left() + 16, rect.top() + 8, rect.width() - 32, 22),
          title, font(15, MONO, bold=True), FAINT)
    return rect.adjusted(16, 34, -16, -12)


def _rule(p: QPainter, x: int, y: int, width: int) -> None:
    p.setPen(QPen(EDGE, 1))
    p.drawLine(x, y, x + width, y)


def _kv(p: QPainter, rect: QRect, key: str, value: str,
        value_colour: QColor = TEXT, value_font_size: int = 17) -> None:
    """One label/value row. The key is quiet; the value carries the weight."""
    label(p, QRect(rect.left(), rect.top(), 120, rect.height()), key,
          font(14, MONO), FAINT)
    label(p, QRect(rect.left() + 118, rect.top(), rect.width() - 118, rect.height()),
          value, font(value_font_size, MONO, bold=True), value_colour)


def draw_rail(p: QPainter, rect: QRect, state: LiveState,
              boxes: Sequence[detect.Box], telemetry: Telemetry,
              events: Sequence[Event] = ()) -> None:
    """State at the top, then every decision the bot has made, newest first.

    This column is the point of the video, so it gets the height. Newest first
    matters: if anything is clipped it should be the oldest entry, not the one
    that just happened.
    """
    panel(p, rect, SURFACE_SOFT)
    inner = rect.adjusted(16, 14, -16, -14)
    y = inner.top()

    # ---- state, compact -------------------------------------------------
    label(p, QRect(inner.left(), y, inner.width(), 18), "STATE",
          font(13, MONO, bold=True), FAINT)
    y += 24

    _kv(p, QRect(inner.left(), y, inner.width(), 24), "elixir",
        f"{state.elixir:.0f}", TEXT, 19)
    label(p, QRect(inner.left() + 160, y, inner.width() - 160, 24),
          f"vs {state.enemy_elixir:.1f}", font(14, MONO), FAINT)
    y += 26
    bar(p, QRect(inner.left(), y, inner.width(), 4), state.elixir / 10.0, DIM)
    y += 16

    threat_colour = BAD if state.threat_value >= 20 else TEXT
    _kv(p, QRect(inner.left(), y, inner.width(), 22), "threat",
        str(state.threat), threat_colour)
    y += 24
    _kv(p, QRect(inner.left(), y, inner.width(), 22), "clock",
        f"{state.clock // 60}:{state.clock % 60:02d}")
    y += 24
    _kv(p, QRect(inner.left(), y, inner.width(), 22), "plays",
        f"{state.plays}")
    y += 24

    if state.hand:
        _kv(p, QRect(inner.left(), y, inner.width(), 22), "hand",
            ", ".join(card[:9] for card in state.hand[:2]), DIM, 14)
        y += 22
        if len(state.hand) > 2:
            label(p, QRect(inner.left() + 118, y, inner.width() - 118, 20),
                  ", ".join(card[:9] for card in state.hand[2:4]),
                  font(14, MONO), DIM)
            y += 20
    y += 10
    _rule(p, inner.left(), y, inner.width())
    y += 16

    # ---- decisions ------------------------------------------------------
    label(p, QRect(inner.left(), y, inner.width(), 18), "DECISIONS",
          font(13, MONO, bold=True), FAINT)
    label(p, QRect(inner.left(), y, inner.width(), 18),
          f"{len([e for e in events if e.kind in DECISION_KINDS])}",
          font(13, MONO), FAINT,
          Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    y += 24

    entry_h = 40
    room = max(0, (inner.bottom() - y) // entry_h)
    # Decisions only. The log also carries vision timings and screen
    # transitions - "ours=1 theirs=0 23ms" is not a decision, and filling the
    # column with them is how it ended up showing so little of what matters.
    decisions = [e for e in events if e.kind in DECISION_KINDS]
    # Newest first: the clipped end should be the oldest thing on screen.
    rows = decisions[-room:][::-1] if room else []

    for index, event in enumerate(rows):
        top = y + index * entry_h
        colour = FAMILY_COLOURS.get(event.family, DIM)
        if index == 0:
            # The one the viewer is meant to look at, and the only accent.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(96, 165, 250, 22)))
            p.drawRoundedRect(QRect(inner.left() - 6, top - 2,
                                    inner.width() + 12, entry_h - 4), 4, 4)
            p.setBrush(QBrush(ACCENT))
            p.drawRoundedRect(QRect(inner.left() - 6, top - 2, 3, entry_h - 4), 1, 1)
        label(p, QRect(inner.left() + 4, top, 74, 20), event.at[-8:],
              font(13, MONO), FAINT)
        label(p, QRect(inner.left() + 80, top, inner.width() - 80, 20),
              event.text.split("  ")[0][:22],
              font(16, MONO, bold=True), TEXT if index == 0 else DIM)
        detail = " ".join(event.text.split()[1:])[:30]
        label(p, QRect(inner.left() + 80, top + 19, inner.width() - 84, 18),
              detail, font(13, MONO), FAINT if index else colour)


def draw_feed(p: QPainter, rect: QRect, events: Sequence[Event],
              state: Optional[LiveState] = None) -> None:
    """The current call, then the raw log tail underneath it.

    The raw log is here because it is the thing that reads as the bot thinking
    out loud - the formatted decision column beside the mirror says *what* was
    played, and this says it in the brain's own words, timestamps and all.
    Losing it made the studio feel like a dashboard rather than a machine at
    work.

    It sits above the caption line, which is why it moved up here from the
    bottom band rather than staying where it was.
    """
    if rect.height() <= 0:
        return
    panel(p, rect, SURFACE)
    inner = rect.adjusted(22, 14, -22, -14)

    label(p, QRect(inner.left(), inner.top(), inner.width(), 18), "CURRENT CALL",
          font(13, MONO, bold=True), FAINT)

    plays = [e for e in events if e.kind in DECISION_KINDS]
    latest = plays[-1] if plays else None
    if latest is None:
        label(p, QRect(inner.left(), inner.top() + 34, inner.width(), 30),
              "waiting", font(26, MONO, bold=True), FAINT)
        head_h = 70
    else:
        card = (state.last_card if state and state.last_card
                else latest.text.split("  ")[0])
        label(p, QRect(inner.left(), inner.top() + 24, inner.width(), 34),
              card[:22], font(29, MONO, bold=True), TEXT)
        if state is not None and state.last_tag:
            label(p, QRect(inner.left(), inner.top() + 60, inner.width(), 20),
                  state.last_tag[:40], font(15, MONO), ACCENT)
            label(p, QRect(inner.left() + 300, inner.top() + 60, inner.width() - 300, 20),
                  f"{state.last_grid}  score {state.last_score:.0f}",
                  font(13, MONO), FAINT)
        head_h = 88

    y = inner.top() + head_h
    _rule(p, inner.left(), y, inner.width())
    y += 12

    label(p, QRect(inner.left(), y, inner.width(), 16), "BRAIN LOG",
          font(12, MONO, bold=True), FAINT)
    label(p, QRect(inner.left(), y, inner.width(), 16), "tmp/live/cr_bot.log",
          font(12, MONO), FAINT,
          Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    y += 20

    # Everything, not just decisions: the vision timings and screen changes are
    # the texture that makes this look like a running process.
    line_h = 19
    room = max(0, (inner.bottom() - y) // line_h)
    for index, event in enumerate(list(events)[-room:] if room else []):
        top = y + index * line_h
        newest = index == room - 1
        label(p, QRect(inner.left(), top, 74, line_h), event.at[-8:],
              font(13, MONO), FAINT)
        label(p, QRect(inner.left() + 78, top, 62, line_h), event.kind,
              font(13, MONO), DIM if newest else FAINT)
        label(p, QRect(inner.left() + 144, top, inner.width() - 144, line_h),
              event.text[:52], font(13, MONO), TEXT if newest else DIM)


# -------------------------------------------------------------------- canvas


def marker_for(grid: str) -> Optional[Tuple[float, float]]:
    """Normalise a logged `(x,y)` grid cell to 0..1 of the game surface."""
    if arena is None or not grid.startswith("("):
        return None
    try:
        x_text, y_text = grid.strip("()").split(",")
        px, py = arena.to_pixels(int(x_text), int(y_text))
    except (ValueError, TypeError):
        return None
    # arena.to_pixels is calibrated against a 1080x1920 frame.
    return px / 1080.0, py / 1920.0


def compose(canvas: QImage, layout: Layout, frame: Optional[QImage],
            state: LiveState, events: Sequence[Event],
            boxes: Sequence[detect.Box], telemetry: Telemetry,
            marker: Optional[Tuple[float, float]] = None,
            marker_age: float = 99.0, show_labels: bool = True,
            sim=None) -> None:
    p = QPainter(canvas)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        p.fillRect(0, 0, canvas.width(), canvas.height(), BG)
        draw_header(p, layout.header, state, telemetry)
        draw_game(p, layout.game, frame, boxes, marker, marker_age, show_labels)
        if layout.sim is not None:
            draw_sim(p, layout.sim, sim)
        draw_rail(p, layout.rail, state, boxes, telemetry, events)
        draw_feed(p, layout.feed, events, state)
    finally:
        p.end()


def draw_sim(p: QPainter, rect: QRect, sim) -> None:
    """The simulator arena, beside the live one.

    Labelled, because the whole reason both are on screen is that they are not
    the same thing, and at phone size two 9:16 arenas of the same game are easy
    to mistake for one feed shown twice.
    """
    head_h = 30
    head = QRect(rect.left(), rect.top(), rect.width(), head_h)
    body = QRect(rect.left(), rect.top() + head_h,
                 rect.width(), rect.height() - head_h)

    label(p, head, "SIMULATOR", font(16, MONO, bold=True), DIM)
    if sim is not None and getattr(sim, "ready", False):
        label(p, head, sim.status(), font(16), FAINT,
              Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        sim.draw(p, body)
    else:
        panel(p, body, SURFACE_SOFT)
        message = getattr(sim, "error", "") if sim is not None else "not started"
        label(p, body, message or "not started", font(14), FAINT,
              Qt.AlignmentFlag.AlignCenter)
    p.setPen(QPen(EDGE))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(body.adjusted(0, 0, -1, -1))


GOOD = QColor("#4ade80")        # a completed setup step, and nothing else


def draw_coach(p: QPainter, rect: QRect, advice, watch=()) -> None:
    """The 1v1 setup, as a checklist over the canvas.

    Drawn on top rather than beside: it only appears while the 1v1 toggle is
    on, and while it is on this is the most important thing in the window.
    It disappears the moment the bot is in a match and the checklist is done,
    because at that point the arena is what you want to be looking at.
    """
    panel(p, rect, SURFACE, radius=8)
    inner = rect.adjusted(22, 18, -22, -18)
    y = inner.top()

    label(p, QRect(inner.left(), y, inner.width(), 30), advice.headline,
          font(21, bold=True), TEXT)
    y += 40

    if advice.warning:
        badge = QRect(inner.left(), y, inner.width(), 34)
        panel(p, badge, QColor("#2a1416"), radius=5, edge=BAD)
        label(p, badge.adjusted(12, 0, -12, 0), advice.warning, font(13), BAD)
        y += 44

    for step in advice.steps:
        row = QRect(inner.left(), y, inner.width(), 26)
        if step.blocked:
            mark, colour = "!", BAD
        elif step.done:
            mark, colour = "v", GOOD
        else:
            mark, colour = "-", DIM
        label(p, QRect(row.left(), row.top(), 22, row.height()), mark,
              font(15, bold=True), colour)
        label(p, row.adjusted(26, 0, 0, 0), step.text, font(14),
              TEXT if not step.done else FAINT)
        y += 28

    if watch:
        y += 10
        _rule(p, inner.left(), y, inner.width())
        y += 12
        label(p, QRect(inner.left(), y, inner.width(), 22),
              "WORTH NOTING WHILE YOU PLAY", font(11, bold=True), FAINT)
        y += 24
        for line in watch:
            label(p, QRect(inner.left(), y, inner.width(), 22),
                  f"- {line}", font(13), DIM)
            y += 22
