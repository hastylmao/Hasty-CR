"""Watch the simulator play, instead of reading its log.

Everything else in `sim/` is headless because it is built to play thousands of
matches unattended. That is the right default and a poor way to develop: a
placement bug, a unit that never reaches the bridge, a Hog walking into the same
Cannon every time - all obvious in two seconds of video and nearly invisible in
a column of numbers.

The arena is 18x32 tiles, which is exactly 9:16, so this reuses the studio's
canvas size and its H.264 recorder. A simulated match can be recorded the same
way a live one is.

    python -m sim.watch                        one match, real speed
    python -m sim.watch --speed 4              four times faster
    python -m sim.watch --matches 5 --seed 7
    python -m sim.watch --record clip.mp4      straight to video
    python -m sim.watch --random-decks         random public-card decks
    python -m sim.watch --opponent random      ours 2.6, theirs random each match
    python -m sim.watch --opponent scripted    ours 2.6, theirs a real ladder deck
    python -m sim.watch --skin debug           the flat hitbox diagram

Both seats are the hand-written brain unless --opponent simple. With
--random-decks, both use the generic legal-placement policy because the live
brain is specialized for Hog cycle. Blue is the bottom player and red the top,
as in the real game.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from PyQt6.QtCore import QRect, QRectF, Qt, QTimer          # noqa: E402
from PyQt6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QImage,  # noqa: E402
                         QPainter, QPainterPath, QPen)
from PyQt6.QtWidgets import QApplication, QWidget           # noqa: E402

from sim import arena as sim_arena                          # noqa: E402

CANVAS = (1080, 1920)
PAD, GAP, HEADER_H = 24, 12, 88

BG = QColor("#080b14")
PANEL = QColor("#101828")

CARD_ART_DIR = ROOT / "vendor" / "ClashRoyaleBuildABot" / "clashroyalebuildabot" / "images" / "cards"
_ART_CACHE: dict = {}

def _card_of_unit() -> dict:
    """unit name -> the card that produces it, for art lookup.

    Swarm cards matter here: the entity is called `skeleton` while the artwork
    is filed under `skeletons`.
    """
    try:
        from .gamedata import load_gamedata
        return {c.unit.name: name for name, c in load_gamedata(level=11).items()
                if c.unit is not None}
    except Exception:
        return {}


CARD_OF_UNIT = _card_of_unit()



_PUBLIC_STEMS: dict | None = None


def _public_art_stem(name: str | None) -> str | None:
    """The public card name for a client name, as the snapshot records it.

    `card_catalog_audit` already maps every public card onto its local row
    through the client's `sc_key`. Inverted, that is an authoritative table
    from the simulator's internal name to the name the artwork is filed under.
    """
    global _PUBLIC_STEMS
    if _PUBLIC_STEMS is None:
        try:
            from .card_catalog_audit import report
            _PUBLIC_STEMS = {local: public.replace("-", "_")
                             for public, local in report()["mapped"].items()}
        except Exception:
            _PUBLIC_STEMS = {}
    return _PUBLIC_STEMS.get(name) if name else None


def card_art(unit_name: str, card_name: str | None = None):
    """The card's artwork for a unit, or None when we have none for it.

    Dots told you where something was and nothing about what it was. The
    artwork is the same set the detector uses, so a unit on the field looks
    like the card that produced it. Cards are 252x313 with a frame, so the
    centre square is taken and the border dropped.
    """
    key = (unit_name, card_name)
    if key in _ART_CACHE:
        return _ART_CACHE[key]

    from PyQt6.QtGui import QPixmap

    # The three naming systems do not agree. The card file calls the Ice Spirit
    # card `ice_spirits`, the artwork is filed as `ice_spirit`, and an Ice
    # Golem's death spawn is `ice_golemite` with no card of its own. So try the
    # obvious names, then the singular/plural of each, then a short alias table
    # for spawned units that will never match anything by name.
    aliases = {
        "ice_golemite": "ice_golem",
        "golemite": "golem",
        "lava_pup": "lava_hound",
        "phoenix_egg": "phoenix",
        "phoenix_small": "phoenix",
        "battle_ram_unit": "battle_ram",
        "goblin_barrel_unit": "goblin_barrel",
    }
    stems = []
    for base in (unit_name, card_name, aliases.get(unit_name)):
        if not base:
            continue
        stems.append(base)
        stems.append(base[:-1] if base.endswith("s") else base + "s")
    # Then the client's own identity for the card. The internal names and the
    # artwork's public names disagree far more than the alias table above
    # admits - Furnace ships as `firespirit_hut`, Executioner as `axe_man`,
    # Sparky as `zap_machine` - which left 27 of 119 playable cards drawn as
    # blank tiles. The public snapshot already maps one to the other through
    # `sc_key`, so this is read rather than guessed: guessing here would put
    # the wrong card's face on a unit, which is worse than a blank.
    for base in (unit_name, card_name):
        public = _public_art_stem(base)
        if public:
            stems.append(public)

    art = None
    for stem in stems:
        if not stem:
            continue
        for suffix in (".jpg", ".png"):
            path = CARD_ART_DIR / f"{stem}{suffix}"
            if path.exists():
                pix = QPixmap(str(path))
                if not pix.isNull():
                    side = min(pix.width(), pix.height())
                    art = pix.copy((pix.width() - side) // 2,
                                   max(0, (pix.height() - side) // 2 - 10),
                                   side, side)
                break
        if art is not None:
            break
    _ART_CACHE[key] = art
    return art


STRIKE_LINGER_MS = 120   # how long a hit stays drawn
EDGE = QColor("#1e293b")
TEXT = QColor("#e2e8f0")
DIM = QColor("#64748b")
GOLD = QColor("#f2b53c")
OURS = QColor("#4aa3ff")
THEIRS = QColor("#ff6b6b")
GRASS = QColor("#2f3a2c")
RIVER = QColor("#1f4d6b")

# The game skin. The debug skin above is a diagram: flat fills chosen so a
# hitbox reads clearly against them. These are chosen so the board reads as a
# place, which is a different job - the arena in the real game is a lit lawn
# with a tiled mow pattern, a river with shallow banks, and stone towers.
LAWN_LIGHT = QColor("#5f9b4a")
LAWN_DARK = QColor("#548c42")
LAWN_EDGE = QColor("#3d6a2f")
WATER_DEEP = QColor("#2a6f97")
WATER_SHALLOW = QColor("#4fa3c7")
WATER_FOAM = QColor("#bfe6f2")
BANK = QColor("#8a6b45")
PLANK = QColor("#a9763f")
PLANK_DARK = QColor("#7d5327")
STONE = QColor("#c9c2b4")
STONE_DARK = QColor("#8f887b")
ELIXIR = QColor("#c04ed6")
ELIXIR_DARK = QColor("#3a1046")
HP_GREEN = QColor("#4ad34a")
HP_BACK = QColor("#231f2b")

MONO = ["Cascadia Mono", "Consolas", "DejaVu Sans Mono"]


def font(size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def text(p: QPainter, rect: QRect, s: str, f: QFont, colour: QColor, align=None) -> None:
    p.setPen(QPen(colour))
    p.setFont(f)
    default = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    p.drawText(rect, int(align or default), s)


def area_display_fields(area: list) -> tuple:
    """Return the stable visual prefix of a variable-length area record."""
    if len(area) < 5:
        raise ValueError("area record is missing its visual fields")
    return tuple(area[:5])


class Watcher(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.canvas = QImage(*CANVAS, QImage.Format.Format_RGB32)
        self.canvas.fill(BG)

        from sim.gamedata import load_gamedata
        from sim.runner import DECK_26, BrainPolicy, SimpleOpponent, resolve_deck
        from sim.spells import load_spells

        self._full = load_gamedata(level=args.level)
        self.cards = resolve_deck(self._full, DECK_26)
        self.spells = load_spells(level=args.level)
        self.deck = DECK_26
        self._brain, self._simple = BrainPolicy, SimpleOpponent
        self._deck_rng = random.Random(args.seed)

        # Opponent decks. Watching a mirror is watching the same deck twice and
        # tells you nothing about how the bot handles anything else, so the
        # viewer can field the archetype pool the same way play_match does.
        self._pool = []
        if args.opponent == "scripted":
            from sim.meta_decks import deck_pool
            self._pool = deck_pool(self._full)

        self.match = None
        self.bottom = self.top = None
        self.log: List[str] = []
        self.results: List[str] = []
        self.played = 0
        self.turn = 0
        self.next_decision = 0
        self.carry = 0.0
        self.recorder = None

        self._new_match()
        if args.record:
            from studio.recorder import Recorder
            self.recorder = Recorder(Path(args.record), CANVAS, fps=args.fps)
            print(f"recording to {args.record}")

        self.setWindowTitle("HastyCR - simulator")
        self.resize(int(CANVAS[0] * args.scale), int(CANVAS[1] * args.scale))
        self.setStyleSheet("background:#080b14;")
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(max(1, round(1000 / args.fps)))
        self.last = time.perf_counter()

    # ------------------------------------------------------------------ sim

    def _new_match(self) -> None:
        from sim.match import Match

        self.played += 1
        if self.args.random_decks:
            from sim.deck_builder import random_public_deck

            bottom_deck = random_public_deck(self._full, self.spells, self._deck_rng)
            top_deck = random_public_deck(self._full, self.spells, self._deck_rng)
            cards = {name: self._full[name] for name in set(bottom_deck + top_deck)}
            self.deck = bottom_deck
            self.opponent_name = "random_public"
            self.match = Match(cards=cards, decks=(bottom_deck, top_deck),
                               seed=self.args.seed + self.played, spells=self.spells)
            # The live brain is specialized for its Hog-cycle card names.
            # Generic public decks use the legal-placement policy rather than
            # silently never playing unfamiliar cards.
            self.bottom = self._simple(cards, side=1, seed=self.args.seed + self.played)
            self.top = self._simple(cards, side=-1, seed=self.args.seed + self.played + 99)
            self.bottom.reset()
            self.top.reset()
            self.log = [f"match {self.played}   seed {self.args.seed + self.played}",
                        "US: " + ", ".join(bottom_deck),
                        "THEM: " + ", ".join(top_deck)]
            self.turn = 0
            self.next_decision = 0
            return

        top_deck = list(self.deck)
        self.opponent_name = "mirror"
        cards = self.cards
        style = "cycle"
        if self.args.opponent == "random":
            # Ours stays Hog cycle, theirs is a fresh random public deck each
            # match. Different question from --random-decks, which randomises
            # both seats: this is "does our deck hold up against anything",
            # which is what a 2.6 pilot actually has to answer.
            from sim.deck_builder import random_public_deck
            from sim.meta_decks import classify_style

            top_deck = random_public_deck(self._full, self.spells, self._deck_rng)
            style = classify_style(self._full, top_deck)
            self.opponent_name = f"random/{style}"
            cards = dict(self.cards)
            for card in top_deck:
                if card not in cards:
                    cards[card] = self._full[card]
        elif self._pool:
            name, style, top_deck = self._pool[self.played % len(self._pool)]
            self.opponent_name = name if name == style else f"{name}/{style}"
            cards = dict(self.cards)
            for card in top_deck:
                if card not in cards:
                    cards[card] = self._full[card]

        self.match = Match(cards=cards, decks=(list(self.deck), list(top_deck)),
                           seed=self.args.seed + self.played, spells=self.spells)
        self.bottom = self._brain(cards, side=1)
        if self.args.opponent == "random" or self._pool:
            from sim.opponents import ScriptedOpponent
            self.top = ScriptedOpponent(cards, side=-1, deck=top_deck,
                                        style=style, seed=self.args.seed + self.played)
        elif self.args.opponent == "brain":
            self.top = self._brain(cards, side=-1)
        else:
            self.top = self._simple(cards, side=-1, seed=self.args.seed + 99)
        self.bottom.reset()
        self.top.reset()
        self.log = [f"match {self.played}   seed {self.args.seed + self.played}",
                    "US: " + ", ".join(self.deck),
                    "THEM: " + ", ".join(top_deck)]
        self.turn = 0
        self.next_decision = 0

    def tick(self) -> None:
        now = time.perf_counter()
        # Cap the step so a stall does not fast-forward the match.
        elapsed = min(0.25, now - self.last)
        self.last = now

        if self.match is not None and not self.match.finished:
            self.carry += elapsed * 1000.0 * self.args.speed
            steps = int(self.carry // sim_arena.TICK_MS)
            self.carry -= steps * sim_arena.TICK_MS
            for _ in range(min(steps, 200)):
                if self.match.finished:
                    break
                self.match.step()
                if self.match.elapsed_ms >= self.next_decision:
                    self.next_decision = self.match.elapsed_ms + 500
                    self.turn += 1
                    # Alternate who resolves first, as the headless runner does.
                    order = ((self.bottom, self.top) if self.turn % 2
                             else (self.top, self.bottom))
                    for policy in order:
                        played = policy.act(self.match)
                        if played and policy is self.bottom:
                            card, x, y, tag = played
                            if card == "ability":
                                self.log.append(
                                    f"{self.match.elapsed_ms / 1000:5.1f}s "
                                    f"ABILITY {tag}")
                            else:
                                self.log.append(
                                    f"{self.match.elapsed_ms / 1000:5.1f}s {card:<11s}"
                                    f"({x:2d},{y:2d}) {tag}")
        elif self.match is not None and self.match.finished:
            self.results.append(f"m{self.played}: {self.match.result} "
                                f"{self.match.crowns_for(1)}-{self.match.crowns_for(-1)}")
            print(self.results[-1], flush=True)
            if self.args.matches and self.played >= self.args.matches:
                self.close()
                QGuiApplication.quit()
                return
            self._new_match()

        self.compose()
        if self.recorder is not None:
            self.recorder.submit(self._array().copy())
        self.update()

    def _array(self):
        import numpy as np

        pointer = self.canvas.bits()
        pointer.setsize(self.canvas.sizeInBytes())
        stride = self.canvas.bytesPerLine() // 4
        return np.frombuffer(pointer, dtype=np.uint8).reshape(
            self.canvas.height(), stride, 4)[:, : self.canvas.width(), :]

    # -------------------------------------------------------------- drawing

    def compose(self) -> None:
        width, height = CANVAS
        game_w = 756
        game = QRect(PAD, PAD + HEADER_H + GAP, game_w, int(game_w * 16 / 9))
        rail_x = game.right() + 1 + GAP
        rail = QRect(rail_x, game.top(), width - PAD - rail_x, game.height())
        feed_y = game.bottom() + 1 + GAP
        feed = QRect(PAD, feed_y, width - 2 * PAD, height - PAD - feed_y)

        p = QPainter(self.canvas)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.fillRect(0, 0, width, height, BG)
            self._header(p, QRect(PAD, PAD, width - 2 * PAD, HEADER_H))
            self._arena(p, game)
            self._rail(p, rail)
            self._feed(p, feed)
        finally:
            p.end()

    def _panel(self, p: QPainter, rect: QRect, fill: QColor = PANEL) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(rect, 14, 14)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(EDGE, 1))
        p.drawRoundedRect(QRectF(rect).adjusted(.5, .5, -.5, -.5), 14, 14)

    def _header(self, p: QPainter, rect: QRect) -> None:
        self._panel(p, rect, QColor("#0c1220"))
        m = self.match
        seconds = m.elapsed_ms // 1000
        text(p, rect.adjusted(22, 0, 0, 0), "simulator", font(34, True), GOLD)
        phase = ("triple" if m.elapsed_ms >= 240_000 else
                 "double" if m.elapsed_ms >= 120_000 else "single")
        label = (f"match {self.played}   {seconds // 60}:{seconds % 60:02d}   {phase}"
                 f"   vs {getattr(self, 'opponent_name', 'mirror')}"
                 f"   crowns {m.crowns_for(1)}-{m.crowns_for(-1)}"
                 f"   x{self.args.speed:g}")
        text(p, rect.adjusted(0, 0, -22, 0), label, font(20), TEXT,
             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def _terrain(self, p: QPainter, rect: QRect, tile_w: float, tile_h: float,
                 at) -> None:
        """The board itself: mown lawn, river with banks, planked bridges.

        The geometry here is read from `sim.arena` rather than repeated, so the
        picture cannot drift from the board the engine actually pathfinds over.
        That matters more than it sounds: the river band used to sit entirely
        on one side of the halfway line, and a viewer drawing its own guess at
        the river would have hidden exactly that bug.
        """
        river_top = rect.top() + (sim_arena.RIVER_TOP / sim_arena.MT) * tile_h
        river_bottom = rect.top() + (sim_arena.RIVER_BOTTOM / sim_arena.MT) * tile_h

        # Mown lawn. Two shades in a checker, one tile per square, with the
        # halves tinted apart so the seat is readable at a glance.
        p.setPen(Qt.PenStyle.NoPen)
        for ty in range(32):
            for tx in range(18):
                shade = LAWN_LIGHT if (tx + ty) % 2 == 0 else LAWN_DARK
                if ty < 16:
                    shade = shade.darker(108)
                x, y = at(tx, ty)
                p.setBrush(QBrush(shade))
                p.drawRect(QRectF(x, y, tile_w + 1, tile_h + 1))

        # River. Deep in the middle, shallow at the edges, foam on the waterline.
        p.setBrush(QBrush(BANK))
        p.drawRect(QRectF(rect.left(), river_top - tile_h * 0.18,
                          rect.width(), (river_bottom - river_top) + tile_h * 0.36))
        p.setBrush(QBrush(WATER_SHALLOW))
        p.drawRect(QRectF(rect.left(), river_top, rect.width(),
                          river_bottom - river_top))
        p.setBrush(QBrush(WATER_DEEP))
        inset = (river_bottom - river_top) * 0.22
        p.drawRect(QRectF(rect.left(), river_top + inset, rect.width(),
                          (river_bottom - river_top) - inset * 2))
        p.setPen(QPen(WATER_FOAM, 2))
        p.drawLine(int(rect.left()), int(river_top), int(rect.right()), int(river_top))
        p.drawLine(int(rect.left()), int(river_bottom),
                   int(rect.right()), int(river_bottom))

        # Bridges, on the arena's own bridge centres and crossable width.
        p.setPen(Qt.PenStyle.NoPen)
        half = sim_arena.BRIDGE_HALF_WIDTH / sim_arena.MT
        for centre_mt in sim_arena.BRIDGE_X:
            centre = centre_mt / sim_arena.MT
            x, _ = at(centre - half, 0)
            width = tile_w * half * 2
            top = river_top - tile_h * 0.35
            height = (river_bottom - river_top) + tile_h * 0.7
            # Individually drawn boards with a gap between them, rather than
            # one filled block: a solid rectangle with lines scored across it
            # read as a crate sitting on the water.
            p.setBrush(QBrush(QColor(0, 0, 0, 55)))
            p.drawRect(QRectF(x + 2, top + 3, width, height))
            boards = max(4, int(height / max(5.0, tile_h * 0.30)))
            board_h = height / boards
            for index in range(boards):
                py = top + index * board_h
                p.setBrush(QBrush(PLANK if index % 2 == 0 else PLANK.darker(108)))
                p.drawRect(QRectF(x, py, width, board_h - 1.5))
            # Stringers along both edges, thin, so the deck still reads as open.
            p.setBrush(QBrush(PLANK_DARK))
            p.drawRect(QRectF(x - 2, top, 4, height))
            p.drawRect(QRectF(x + width - 2, top, 4, height))

        # Where we may place a card. In the real game this is shaded the
        # moment a card is picked up; here it is always faint, because the
        # single most common placement bug is a legal-zone error and an
        # invisible boundary makes it unfalsifiable by eye.
        our_top = rect.top() + (sim_arena.RIVER_BOTTOM / sim_arena.MT) * tile_h
        p.setBrush(QBrush(QColor(74, 163, 255, 26)))
        p.drawRect(QRectF(rect.left(), our_top, rect.width(),
                          rect.bottom() - our_top))

        # A hairline round the whole lawn, so the board has an edge.
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(LAWN_EDGE, 3))
        p.drawRect(QRectF(rect).adjusted(1.5, 1.5, -1.5, -1.5))
        p.setPen(Qt.PenStyle.NoPen)

    def _tower(self, p: QPainter, box: QRectF, colour: QColor, tower,
               king: bool) -> None:
        """A stone tower with a team roof, crenellations and a health bar.

        A rubble pile is drawn where one has fallen, because a destroyed tower
        is not the same as an empty tile: the lane it opens is the whole point
        of the game, and a blank square read as "nothing was ever here".
        """
        alive = tower.alive
        stone = STONE if alive else STONE_DARK.darker(150)
        p.setPen(Qt.PenStyle.NoPen)

        if not alive:
            p.setBrush(QBrush(stone.darker(120)))
            for index, (dx, dy, scale) in enumerate(
                    ((0.18, 0.62, 0.30), (0.52, 0.70, 0.24), (0.34, 0.48, 0.20),
                     (0.70, 0.55, 0.18))):
                lump = box.width() * scale
                p.drawEllipse(QRectF(box.left() + box.width() * dx,
                                     box.top() + box.height() * dy,
                                     lump, lump * 0.7))
            p.setBrush(QBrush(QColor(colour.red(), colour.green(),
                                     colour.blue(), 40)))
            p.drawRect(box)
            return

        # The tower proper: a stone shaft with a crenellated parapet and a
        # team-coloured roof sitting on it. Drawn from the parapet down so the
        # merlons are never hidden behind the roof.
        shaft = QRectF(box.left() + box.width() * 0.14,
                       box.top() + box.height() * 0.34,
                       box.width() * 0.72, box.height() * 0.66)
        p.setBrush(QBrush(stone.darker(135)))
        p.drawRect(QRectF(shaft).adjusted(-4, 4, 4, 0))
        p.setBrush(QBrush(stone))
        p.drawRect(shaft)
        p.setBrush(QBrush(stone.darker(112)))
        p.drawRect(QRectF(shaft.left(), shaft.top(),
                          shaft.width() * 0.30, shaft.height()))

        p.setPen(QPen(stone.darker(122), 1))
        for index in range(1, 4):
            cy = shaft.top() + shaft.height() * index / 4
            p.drawLine(int(shaft.left()), int(cy), int(shaft.right()), int(cy))
        p.setPen(Qt.PenStyle.NoPen)

        # Parapet: a lintel with merlons standing on it.
        parapet = QRectF(box.left() + box.width() * 0.06,
                         box.top() + box.height() * 0.26,
                         box.width() * 0.88, box.height() * 0.11)
        p.setBrush(QBrush(stone.lighter(106)))
        p.drawRect(parapet)
        p.setBrush(QBrush(stone.darker(118)))
        p.drawRect(QRectF(parapet.left(), parapet.bottom() - 2,
                          parapet.width(), 2))
        merlons = 5 if king else 4
        step = parapet.width() / (merlons * 2 - 1)
        p.setBrush(QBrush(stone.lighter(110)))
        for index in range(merlons):
            p.drawRect(QRectF(parapet.left() + index * step * 2,
                              parapet.top() - step * 0.85, step, step * 0.9))

        # Team roof, and a gold crown on the king.
        roof = QRectF(box.left() + box.width() * 0.24,
                      box.top() + box.height() * 0.04,
                      box.width() * 0.52, box.height() * 0.20)
        p.setBrush(QBrush(colour.darker(150)))
        p.drawRoundedRect(roof, 5, 5)
        p.setBrush(QBrush(colour))
        p.drawRoundedRect(QRectF(roof).adjusted(2, 2, -2, -5), 4, 4)
        p.setBrush(QBrush(colour.lighter(135)))
        p.drawRoundedRect(QRectF(roof).adjusted(5, 4, -5, -roof.height() * 0.62),
                          3, 3)
        if king:
            crown = roof.width() * 0.34
            p.setBrush(QBrush(GOLD))
            p.drawEllipse(QRectF(roof.center().x() - crown / 2,
                                 roof.top() - crown * 0.72, crown, crown))
            p.setBrush(QBrush(GOLD.darker(130)))
            p.drawEllipse(QRectF(roof.center().x() - crown * 0.22,
                                 roof.top() - crown * 0.50,
                                 crown * 0.44, crown * 0.44))

        # An arrow slit in team colour, so the shaft is not a blank slab.
        slit = QRectF(shaft.center().x() - shaft.width() * 0.11,
                      shaft.top() + shaft.height() * 0.20,
                      shaft.width() * 0.22, shaft.height() * 0.40)
        p.setBrush(QBrush(colour.darker(230)))
        p.drawRoundedRect(slit, slit.width() * 0.5, slit.width() * 0.5)

        # Health, drawn the way the game does it: a bar above the tower, dark
        # backed, with the number on it rather than beside it.
        frac = max(0.0, tower.hitpoints / max(1, tower.max_hitpoints))
        bar = QRectF(box.left() - box.width() * 0.06,
                     box.top() - box.height() * 0.26,
                     box.width() * 1.12, box.height() * 0.19)
        p.setBrush(QBrush(HP_BACK))
        p.drawRoundedRect(bar, 3, 3)
        fill = QRectF(bar).adjusted(2, 2, -2, -2)
        fill.setWidth(max(0.0, fill.width() * frac))
        p.setBrush(QBrush(colour.lighter(115) if frac > 0.3 else QColor("#e0533f")))
        p.drawRoundedRect(fill, 2, 2)
        text(p, QRect(int(bar.left()), int(bar.top()), int(bar.width()),
                      int(bar.height())),
             str(int(tower.hitpoints)), font(max(10, int(bar.height() * 0.82)), True),
             TEXT, Qt.AlignmentFlag.AlignCenter)

    def _arena(self, p: QPainter, rect: QRect) -> None:
        game_skin = self.args.skin == "game"
        self._panel(p, rect, GRASS)
        m = self.match
        tile_w = rect.width() / 18.0
        tile_h = rect.height() / 32.0

        def at(tx: float, ty: float):
            return rect.left() + tx * tile_w, rect.top() + ty * tile_h

        if game_skin:
            p.save()
            p.setClipRect(rect)
            self._terrain(p, rect, tile_w, tile_h, at)
            p.restore()
        else:
            river_y = rect.top() + 16 * tile_h
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(RIVER))
            p.drawRect(QRectF(rect.left(), river_y - tile_h * 0.5,
                              rect.width(), tile_h))
            p.setBrush(QBrush(QColor("#7a5a34")))
            for bridge in (3, 14):
                x, _ = at(bridge - 0.5, 0)
                p.drawRect(QRectF(x, river_y - tile_h * 0.6, tile_w * 2, tile_h * 1.2))

        for side in (1, -1):
            colour = OURS if side > 0 else THEIRS
            for lane, tower in m.towers[side].items():
                tx, ty = sim_arena.to_tiles(tower.pos)
                x, y = at(tx, ty)
                size = tile_w * (2.6 if lane == "king" else 2.2)
                box = QRectF(x - size / 2, y - size / 2, size, size)
                if game_skin:
                    self._tower(p, box, colour, tower, lane == "king")
                    continue
                p.setBrush(QBrush(colour.darker(220 if tower.alive else 400)))
                p.setPen(QPen(colour if tower.alive else DIM, 2))
                p.drawRoundedRect(box, 5, 5)
                if tower.alive:
                    frac = max(0.0, tower.hitpoints / max(1, tower.max_hitpoints))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QBrush(QColor("#1b2537")))
                    p.drawRect(QRectF(box.left(), box.top() - 9, size, 6))
                    p.setBrush(QBrush(colour))
                    p.drawRect(QRectF(box.left(), box.top() - 9, size * frac, 6))
                    # Say which tower it is and what it has left. A row of
                    # identical boxes is the hardest thing on screen to read,
                    # and the hitpoints are the number every decision turns on.
                    text(p, QRect(int(box.left()), int(box.top() + 4),
                                  int(size), 16),
                         "KING" if lane == "king" else lane.upper(),
                         font(12, True), colour.lighter(160),
                         Qt.AlignmentFlag.AlignHCenter)
                    text(p, QRect(int(box.left()), int(box.center().y() - 9),
                                  int(size), 18),
                         str(int(tower.hitpoints)), font(15, True), TEXT,
                         Qt.AlignmentFlag.AlignHCenter)
                else:
                    text(p, QRect(int(box.left()), int(box.center().y() - 9),
                                  int(size), 18),
                         "DOWN", font(13, True), DIM,
                         Qt.AlignmentFlag.AlignHCenter)

        # Lingering spell areas - a Poison sitting for eight seconds, a
        # Graveyard dripping skeletons. These were invisible on screen, so a
        # unit melting in the middle of nowhere had no explanation.
        # Area records carry optional scheduler state after the five common
        # fields (selected targets, remaining waves/volleys). Renderers only
        # need the common prefix; unpacking the whole record made the viewer
        # crash as soon as Void, Lightning, Earthquake or a volley spell added
        # that source-backed state.
        for area in m.battle.areas:
            spec, centre, side, expires_ms, _next_tick = area_display_fields(area)
            cx, cy = at(*sim_arena.to_tiles(centre))
            radius_px = tile_w * spec.radius_mt / sim_arena.MT
            colour = OURS if side > 0 else THEIRS
            p.setBrush(QBrush(QColor(colour.red(), colour.green(), colour.blue(), 28)))
            p.setPen(QPen(colour.darker(120), 1, Qt.PenStyle.DashLine))
            p.drawEllipse(QRectF(cx - radius_px, cy - radius_px,
                                 radius_px * 2, radius_px * 2))
            left = max(0, (expires_ms - m.battle.now_ms)) / 1000.0
            text(p, QRect(int(cx - 60), int(cy - 8), 120, 16),
                 f"{spec.name} {left:.1f}s", font(11), colour.lighter(150),
                 Qt.AlignmentFlag.AlignHCenter)

        # Non-homing shots, drawn along the path they were launched on. The
        # engine cannot say whether these hit: the client declares them
        # non-homing and there is no measured collision rule yet, so they are
        # held in `unmodelled_projectiles` rather than resolved as homing.
        # Drawing them makes the single largest gap in this simulator visible
        # instead of leaving it as a line in an audit - a Princess whose
        # arrows visibly pass through a Skeleton is the whole problem, on
        # screen, in one frame.
        now = m.battle.now_ms
        for shot in m.battle.unmodelled_projectiles:
            launch, arrival = shot["launch_ms"], shot["arrival_ms"]
            if not launch <= now <= arrival:
                continue
            span = max(1, arrival - launch)
            travelled = (now - launch) / span
            sx, sy = at(*sim_arena.to_tiles(sim_arena.Point(*shot["start"])))
            ax, ay = at(*sim_arena.to_tiles(sim_arena.Point(*shot["aim"])))
            px = sx + (ax - sx) * travelled
            py = sy + (ay - sy) * travelled
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#f2b53c"), 1, Qt.PenStyle.DotLine))
            p.drawLine(int(sx), int(sy), int(ax), int(ay))
            p.setPen(QPen(QColor("#1a1204"), 1))
            p.setBrush(QBrush(GOLD))
            head = max(3.0, tile_w * 0.16)
            p.drawEllipse(QRectF(px - head, py - head, head * 2, head * 2))

        # Every hit that landed in the last fraction of a second, drawn as a
        # line from attacker to target. The gap between a unit's strikes is its
        # hit speed, and without this the rhythm is invisible - it reads as a
        # continuous stream rather than one blow every second.
        recent = [row for row in m.battle.damage_log
                  if m.battle.now_ms - row[0] <= STRIKE_LINGER_MS]
        for _, src_uid, tgt_uid, _ in recent:
            src = m.battle.entities.get(src_uid)
            tgt = m.battle.entities.get(tgt_uid)
            if src is None or tgt is None or not src.alive:
                continue
            sx, sy = at(*sim_arena.to_tiles(src.pos))
            gx, gy = at(*sim_arena.to_tiles(tgt.pos))
            p.setPen(QPen((OURS if src.side > 0 else THEIRS).lighter(160), 2))
            p.drawLine(int(sx), int(sy), int(gx), int(gy))

        for entity in m.battle.entities.values():
            if not entity.alive or entity.is_tower:
                continue
            tx, ty = sim_arena.to_tiles(entity.pos)
            x, y = at(tx, ty)
            colour = OURS if entity.side > 0 else THEIRS
            # Draw the unit at its real collision radius rather than a fixed
            # blob. These circles are the hitboxes the engine actually uses -
            # a Giant is visibly wider than a Skeleton, and that width is what
            # extends how far something can be hit from, since reach is range
            # plus the *target's* radius.
            radius = max(3.0, tile_w * entity.collision_radius_mt / sim_arena.MT)
            # A unit that has not finished deploying is drawn hollow. It is
            # inert for about a second after it lands - long enough to be the
            # difference between a Cannon that stops a push and one that gets
            # free hits taken off it - and drawing it solid made the delay look
            # like it did not exist.
            deploying = entity.deploy_remaining_ms > 0
            box = QRectF(x - radius, y - radius, radius * 2, radius * 2)
            # Health bars and status marks hang off the drawn body, which in
            # the game skin is the portrait disc rather than the hitbox. Using
            # the hitbox for both left the bar visibly beside small units.
            body_half = radius

            # Draw the card's artwork where we have it. The sprite is allowed to
            # be bigger than the hitbox, because at this scale a true-size
            # Skeleton is a few pixels and unreadable - the hitbox is still
            # drawn as a ring on top, so nothing about the geometry is lost.
            art = card_art(entity.name, CARD_OF_UNIT.get(entity.name))
            if art is not None and game_skin:
                # Round portrait on a team disc, with a shadow on the grass.
                # The square-with-dotted-ellipse treatment below is a diagram
                # of the hitbox; this is meant to read as a unit standing on a
                # lawn, so the hitbox moves behind --rings instead.
                sprite = max(radius * 2, tile_w * 1.25)
                body_half = sprite / 2
                target = QRectF(x - sprite / 2, y - sprite / 2, sprite, sprite)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(0, 0, 0, 60)))
                p.drawEllipse(QRectF(x - radius, y + radius * 0.55,
                                     radius * 2, radius * 0.8))
                p.setBrush(QBrush(colour.darker(150)))
                p.drawEllipse(QRectF(target).adjusted(-3, -3, 3, 3))
                if deploying:
                    p.setOpacity(0.5)
                p.save()
                clip = QPainterPath()
                clip.addEllipse(target)
                p.setClipPath(clip)
                p.drawPixmap(target.toRect(), art)
                p.restore()
                p.setOpacity(1.0)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(colour.lighter(125), 3,
                              Qt.PenStyle.DashLine if deploying
                              else Qt.PenStyle.SolidLine))
                p.drawEllipse(target)
                if self.args.rings:
                    p.setPen(QPen(colour.lighter(170), 1, Qt.PenStyle.DotLine))
                    p.drawEllipse(box)
            elif art is not None:
                sprite = max(radius * 2, tile_w * 1.15)
                target = QRectF(x - sprite / 2, y - sprite / 2, sprite, sprite)
                if deploying:
                    p.setOpacity(0.45)
                p.drawPixmap(target.toRect(), art)
                p.setOpacity(1.0)
                # side colour and the real hitbox, over the art
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(colour.lighter(140), 3,
                              Qt.PenStyle.DashLine if deploying else Qt.PenStyle.SolidLine))
                p.drawRect(target)
                p.setPen(QPen(colour.lighter(170), 1, Qt.PenStyle.DotLine))
                p.drawEllipse(box)
            else:
                if deploying:
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.setPen(QPen(colour.darker(120), 2, Qt.PenStyle.DashLine))
                else:
                    p.setBrush(QBrush(colour))
                    p.setPen(QPen(colour.lighter(150), 2 if entity.flying else 1))
                # Fliers are squares so they are separable at a glance.
                p.drawRect(box) if entity.flying else p.drawEllipse(box)
            # Ranged attackers get a faint ring at their own range, so a shot
            # that looks impossibly long can be read off the screen instead of
            # argued about. The ring is the unit's range only; the extra reach
            # against a big target is that target's radius, drawn on the target.
            if self.args.rings and entity.range_mt > 1200:
                reach_px = tile_w * entity.range_mt / sim_arena.MT
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(colour.darker(130), 1, Qt.PenStyle.DotLine))
                p.drawEllipse(QRectF(x - reach_px, y - reach_px,
                                     reach_px * 2, reach_px * 2))
                p.setBrush(QBrush(colour))
                p.setPen(QPen(colour.lighter(150), 1))
            frac = entity.hitpoints / max(1, entity.max_hitpoints)
            if frac < 0.999:
                p.setPen(Qt.PenStyle.NoPen)
                height = 5 if game_skin else 4
                top = y - body_half - height - 3
                p.setBrush(QBrush(HP_BACK if game_skin else QColor("#101828")))
                p.drawRoundedRect(QRectF(x - body_half, top,
                                         body_half * 2, height), 2, 2)
                p.setBrush(QBrush(colour.lighter(130)))
                p.drawRoundedRect(QRectF(x - body_half, top,
                                         body_half * 2 * frac, height), 2, 2)
            # What is being done to it right now: frozen, slowed, hasted,
            # vanished, mid-dash. Without these a unit standing still in the
            # middle of a fight looks like a bug rather than a freeze.
            marks = []
            if entity.buffed(m.battle.now_ms):
                if entity.buff_speed_pct <= -100:
                    marks.append("FROZEN")
                elif entity.buff_speed_pct < 0:
                    marks.append(f"SLOW{entity.buff_speed_pct}%")
                if entity.buff_hit_speed_pct > 0:
                    marks.append(f"RAPID+{entity.buff_hit_speed_pct}%")
                if entity.buff_heal_per_second > 0:
                    marks.append("HEAL")
            if entity.invisible(m.battle.now_ms):
                marks.append("UNSEEN")
            if entity.dashing:
                marks.append("DASH")
            if marks:
                text(p, QRect(int(x - 60), int(y - body_half - 24), 120, 14),
                     " ".join(marks), font(10, True), QColor("#7dd3fc"),
                     Qt.AlignmentFlag.AlignHCenter)

            if not game_skin:
                text(p, QRect(int(x - 45), int(y + body_half + 1), 90, 14),
                     entity.name[:12], font(11), TEXT,
                     Qt.AlignmentFlag.AlignHCenter)

    def _elixir_bar(self, p: QPainter, rect: QRect, elixir: float,
                    colour: QColor) -> None:
        """The segmented purple bar, which is how the game shows elixir.

        Ten segments rather than a smooth fill, because what a player reads off
        it is a whole number - whether the next card is affordable - and a
        continuous bar makes 3.9 and 4.0 look the same.
        """
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ELIXIR_DARK))
        p.drawRoundedRect(rect, 6, 6)
        gap = 2.0
        seg_w = (rect.width() - gap * 9) / 10.0
        for index in range(10):
            left = rect.left() + index * (seg_w + gap)
            filled = min(1.0, max(0.0, elixir - index))
            cell = QRectF(left, rect.top() + 2, seg_w, rect.height() - 4)
            p.setBrush(QBrush(QColor(255, 255, 255, 18)))
            p.drawRoundedRect(cell, 3, 3)
            if filled > 0:
                lit = QRectF(cell)
                lit.setWidth(cell.width() * filled)
                p.setBrush(QBrush(ELIXIR))
                p.drawRoundedRect(lit, 3, 3)
        # The count sits past the right end rather than over the segments: on
        # top of a lit segment it was unreadable at exactly the moment it
        # mattered, which is a full bar.
        text(p, QRect(int(rect.right()) + 6, int(rect.top()), 52,
                      int(rect.height())),
             f"{elixir:.1f}", font(max(12, int(rect.height() * 0.72)), True),
             ELIXIR.lighter(140), Qt.AlignmentFlag.AlignVCenter)

    def _hand_tiles(self, p: QPainter, rect: QRect, side: int = 1) -> None:
        """The four cards in hand as tiles with their art and elixir cost.

        Drawn for either seat. Watching only our own hand hides half of why a
        match went the way it did - whether the answer they just played was the
        one card they were holding or one of four.
        """
        m = self.match
        hand = list(m.players[side].hand[:4])
        gap = 8
        tile_w = (rect.width() - gap * 3) / 4.0
        tile_h = min(rect.height(), tile_w * 1.22)
        for index in range(4):
            left = rect.left() + index * (tile_w + gap)
            box = QRectF(left, rect.top(), tile_w, tile_h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#243049")))
            p.drawRoundedRect(box, 7, 7)
            if index >= len(hand):
                continue
            name = hand[index]
            art = card_art(name, name)
            inner = QRectF(box).adjusted(3, 3, -3, -3)
            if art is not None:
                p.save()
                clip = QPainterPath()
                clip.addRoundedRect(inner, 5, 5)
                p.setClipPath(clip)
                p.drawPixmap(inner.toRect(), art)
                p.restore()
            else:
                text(p, inner.toRect(), name[:9], font(11), TEXT,
                     Qt.AlignmentFlag.AlignCenter)

            # `self.cards` is only the resolved deck, so with --random-decks
            # every cost lookup missed and the badges disappeared from cards
            # that are not in Hog 2.6. The full table is the one that always
            # has the card.
            cost = getattr(self.cards.get(name), "cost", None)
            if cost is None:
                cost = getattr(self._full.get(name), "cost", None)
            if cost is None:
                cost = getattr(self.spells.get(name), "cost", None)
            if cost is not None:
                badge = min(tile_w * 0.42, 26.0)
                spot = QRectF(box.left() + 2, box.bottom() - badge - 1,
                              badge, badge)
                p.setBrush(QBrush(ELIXIR))
                p.setPen(QPen(ELIXIR_DARK, 2))
                p.drawEllipse(spot)
                text(p, spot.toRect(), str(int(cost)),
                     font(max(10, int(badge * 0.62)), True), TEXT,
                     Qt.AlignmentFlag.AlignCenter)
            # An unaffordable card is dimmed, which is the read a player makes
            # constantly and the one the bot's action mask encodes.
            if cost is not None and m.players[1].elixir / 1000.0 < cost:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(6, 8, 16, 130)))
                p.drawRoundedRect(box, 7, 7)

    def _rail(self, p: QPainter, rect: QRect) -> None:
        if self.args.skin == "game":
            return self._rail_game(p, rect)
        m = self.match
        y = rect.top()
        for side, label, colour in ((1, "US", OURS), (-1, "THEM", THEIRS)):
            box = QRect(rect.left(), y, rect.width(), 96)
            self._panel(p, box)
            inner = box.adjusted(16, 10, -16, -10)
            elixir = m.players[side].elixir / 1000.0
            text(p, QRect(inner.left(), inner.top(), inner.width(), 22),
                 label, font(15, True), DIM)
            text(p, QRect(inner.left(), inner.top() + 22, inner.width(), 30),
                 f"{elixir:.1f}", font(28, True), colour)
            track = QRect(inner.left(), inner.top() + 58, inner.width(), 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor("#1b2537")))
            p.drawRoundedRect(track, 4, 4)
            p.setBrush(QBrush(colour))
            p.drawRoundedRect(QRect(track.left(), track.top(),
                                    int(track.width() * min(1.0, elixir / 10)), 8), 4, 4)
            y += 96 + GAP

        box = QRect(rect.left(), y, rect.width(), 150)
        self._panel(p, box)
        inner = box.adjusted(16, 10, -16, -10)
        text(p, QRect(inner.left(), inner.top(), inner.width(), 22),
             "OUR HAND", font(15, True), DIM)
        for index, card in enumerate(m.players[1].hand[:4]):
            text(p, QRect(inner.left(), inner.top() + 24 + index * 24, inner.width(), 22),
                 f"{index + 1}  {card}", font(17), TEXT)
        y += 150 + GAP

        box = QRect(rect.left(), y, rect.width(), max(80, rect.bottom() - y))
        self._panel(p, box)
        inner = box.adjusted(16, 10, -16, -10)
        text(p, QRect(inner.left(), inner.top(), inner.width(), 22),
             "RESULTS", font(15, True), DIM)
        for index, line in enumerate(self.results[-9:]):
            text(p, QRect(inner.left(), inner.top() + 24 + index * 22, inner.width(), 20),
                 line, font(14), TEXT)

    def _rail_game(self, p: QPainter, rect: QRect) -> None:
        """The side rail in game dress: elixir, hand, crowns, then results.

        Same information as the debug rail. The difference is that elixir and
        the hand are shown the way a player reads them - a segmented bar and
        four card tiles - because those two are what every placement decision
        is made from, and a decimal in a box does not carry that.
        """
        m = self.match
        y = rect.top()

        for side, label, colour in ((1, "US", OURS), (-1, "THEM", THEIRS)):
            box = QRect(rect.left(), y, rect.width(), 86)
            self._panel(p, box)
            inner = box.adjusted(14, 10, -14, -10)
            elixir = m.players[side].elixir / 1000.0
            text(p, QRect(inner.left(), inner.top(), inner.width(), 20),
                 label, font(14, True), DIM)
            crowns = m.crowns_for(side)
            text(p, QRect(inner.left(), inner.top(), inner.width(), 20),
                 "*" * crowns if crowns else "", font(15, True), GOLD,
                 Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._elixir_bar(p, QRect(inner.left(), inner.top() + 28,
                                      inner.width() - 56, 26), elixir, colour)
            y += 86 + GAP

        for side, label in ((1, "OUR HAND"), (-1, "THEIR HAND")):
            box = QRect(rect.left(), y, rect.width(), 116)
            self._panel(p, box)
            inner = box.adjusted(14, 8, -14, -8)
            text(p, QRect(inner.left(), inner.top(), inner.width(), 18),
                 label, font(13, True), DIM)
            self._hand_tiles(p, QRect(inner.left(), inner.top() + 20,
                                      inner.width(), inner.height() - 20),
                             side=side)
            y += 116 + GAP

        box = QRect(rect.left(), y, rect.width(), max(80, rect.bottom() - y))
        self._panel(p, box)
        inner = box.adjusted(16, 10, -16, -10)
        text(p, QRect(inner.left(), inner.top(), inner.width(), 22),
             "RESULTS", font(15, True), DIM)
        for index, line in enumerate(self.results[-9:]):
            text(p, QRect(inner.left(), inner.top() + 24 + index * 22,
                          inner.width(), 20),
                 line, font(14), TEXT)

    def _feed(self, p: QPainter, rect: QRect) -> None:
        self._panel(p, rect, QColor("#0c1220"))
        text(p, QRect(rect.left() + 20, rect.top() + 8, rect.width() - 40, 22),
             "OUR DECISIONS", font(15, True), QColor("#334155"))
        body = rect.adjusted(20, 34, -20, -12)
        visible = max(1, body.height() // 25)
        rows = self.log[-visible:]
        for index, line in enumerate(rows):
            colour = TEXT if index == len(rows) - 1 else QColor("#94a3b8")
            text(p, QRect(body.left(), body.top() + index * 25, body.width(), 25),
                 line, font(19), colour)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BG)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        scale = min(self.width() / CANVAS[0], self.height() / CANVAS[1])
        target = QRect(0, 0, int(CANVAS[0] * scale), int(CANVAS[1] * scale))
        target.moveCenter(self.rect().center())
        painter.drawImage(target, self.canvas)
        painter.end()

    def closeEvent(self, event) -> None:
        self.timer.stop()
        if self.recorder is not None:
            self.recorder.close()
            print(f"saved {self.args.record}")
        super().closeEvent(event)


def main() -> int:
    parser = argparse.ArgumentParser(description="Watch the simulator play")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--matches", type=int, default=0, help="0 keeps going")
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--scale", type=float, default=0.48)
    parser.add_argument("--opponent",
                        choices=("brain", "simple", "scripted", "random"),
                        default="brain")
    parser.add_argument("--random-decks", action="store_true",
                        help="sample two 8-card decks from all resolvable public cards")
    parser.add_argument("--record", type=Path)
    parser.add_argument("--probe", type=int, help="render N frames, save a still, exit")
    parser.add_argument("--rings", action="store_true",
                        help="draw each ranged unit's attack range and hitbox")
    parser.add_argument("--skin", choices=("game", "debug"), default="game",
                        help="game dresses the board like the real arena; "
                             "debug is the flat diagram, which is easier to "
                             "read a hitbox off")
    args = parser.parse_args()

    app = QGuiApplication.instance() or QApplication([])
    window = Watcher(args)
    window.show()
    if args.probe:
        frames = {"n": 0}

        def stop_when_done():
            frames["n"] += 1
            if frames["n"] >= args.probe:
                out = ROOT / "tmp" / "live" / "studio" / "sim_watch.png"
                out.parent.mkdir(parents=True, exist_ok=True)
                window.canvas.save(str(out))
                print(f"still {out}", flush=True)
                window.close()
                QGuiApplication.quit()

        window.timer.timeout.connect(stop_when_done)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
