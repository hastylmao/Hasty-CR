"""Do both viewer skins actually paint a match?

The viewer is how a placement bug gets noticed at all, so a skin that throws
half way through a frame costs more than it looks: the window keeps running,
the canvas keeps the last good frame, and the failure reads as the simulator
having stopped rather than the painter having crashed.

These render real frames of a real match rather than checking that functions
exist. Qt is asked for an offscreen surface so this runs on a machine with no
display.
"""

import os
import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("PyQt6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _args(**overrides):
    base = dict(seed=3, matches=1, level=11, speed=8.0, fps=60, scale=0.48,
                opponent="brain", random_decks=False, record=None, probe=None,
                rings=False, skin="game")
    base.update(overrides)
    return Namespace(**base)


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtWidgets import QApplication
    return QGuiApplication.instance() or QApplication([])


def _render(app, **overrides):
    """Step a match a little way in, then paint one frame."""
    from sim.watch import Watcher

    watcher = Watcher(_args(**overrides))
    for _ in range(120):
        watcher.tick()
        if watcher.match is None:
            break
    watcher.compose()
    return watcher


@pytest.mark.parametrize("skin", ["game", "debug"])
def test_a_skin_paints_a_frame_of_a_real_match(app, skin):
    watcher = _render(app, skin=skin)
    image = watcher.canvas
    assert image.width() and image.height()
    # A frame that painted nothing is a uniform fill, which is what a painter
    # that threw on its first call leaves behind.
    corners = {image.pixel(4, 4), image.pixel(image.width() // 2,
                                              image.height() // 3),
               image.pixel(image.width() - 5, image.height() - 5)}
    assert len(corners) > 1, "the canvas is a flat fill; nothing was drawn"


def test_the_two_skins_do_not_paint_the_same_picture(app):
    game = _render(app, skin="game").canvas.copy()
    debug = _render(app, skin="debug").canvas.copy()
    assert game.size() == debug.size()
    band = game.height() // 3
    differing = sum(1 for y in range(0, band, 7)
                    for x in range(0, game.width(), 7)
                    if game.pixel(x, y) != debug.pixel(x, y))
    assert differing > 50, differing


def test_rings_are_available_in_the_game_skin(app):
    """The hitbox overlay is the reason this viewer exists; the pretty skin
    must not be a way to lose it."""
    plain = _render(app, skin="game", rings=False).canvas.copy()
    ringed = _render(app, skin="game", rings=True).canvas.copy()
    differing = sum(1 for y in range(0, plain.height(), 5)
                    for x in range(0, plain.width(), 5)
                    if plain.pixel(x, y) != ringed.pixel(x, y))
    assert differing > 0


def test_every_playable_public_card_has_artwork(app):
    """A card with no art is drawn as a blank tile, which reads as a bug.

    The client's internal names and the artwork's public names disagree more
    than the hand-written alias table admitted - Furnace ships as
    `firespirit_hut`, Executioner as `axe_man`, Sparky as `zap_machine` - and
    27 of 119 cards were blank. The mapping is read from the public snapshot
    rather than guessed, because a wrong guess puts another card's face on a
    unit, which is worse than a blank.
    """
    from sim.deck_builder import playable_public_cards
    from sim.gamedata import load_gamedata
    from sim.spells import load_spells
    from sim.watch import card_art

    cards = load_gamedata(level=11)
    spells = load_spells(level=11)
    pool = sorted(playable_public_cards(cards, spells))
    assert len(pool) > 110, len(pool)
    missing = {name for name in pool if card_art(name, name) is None}
    # The vendored artwork set is 139 cards and predates the 2026 additions the
    # ladder-evidence gate reopened. No art exists for these in either vendored
    # set, so they draw as blank tiles in the viewer. Named rather than hidden:
    # the point of this test is that a card which *should* have art has not
    # silently lost it.
    no_artwork_available = {
        "berserker", "boss_bandit", "goblin_curse", "goblin_demolisher",
        "goblin_machine", "goblinstein", "ronin", "suspicious_bush", "vines",
        # Both of these ship under a codename the artwork set never used:
        # Rune Giant as `giant_buffer`, Spirit Empress as `merge_maiden`.
        "giant_buffer", "merge_maiden__normal",
    }
    assert not (missing - no_artwork_available), sorted(missing - no_artwork_available)
    assert not (no_artwork_available - missing), (
        f"artwork appeared for {sorted(no_artwork_available - missing)}; "
        f"remove them from the exemption")
