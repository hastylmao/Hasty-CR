"""The device-resolution boundary.

Raw screencap is uncompressed, so its cost is transfer: 1080x1920 is 8.3MB and
measured 406ms on this machine, while 540x960 is 2.07MB and measured 117ms -
and capture was 90% of the whole decision loop. Running the emulator at half
resolution roughly doubles the bot's reaction rate.

Everything downstream was calibrated against 1080x1920, so rather than
recalibrate `tower_hp`, `popup_guard`, the card crops and every tap constant,
the resolution is normalised in one place: frames upscale on the way in, taps
scale down on the way out. These tests pin that boundary, because a mistake in
it puts every tap in the wrong place.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))

import mumu_overnight_bot as guarded  # noqa: E402


def test_frames_are_normalised_to_the_calibrated_resolution():
    small = Image.new("RGB", (540, 960))
    assert guarded._normalise(small).size == (1080, 1920)
    assert guarded._device_size == (540, 960)


def test_a_native_frame_is_left_alone():
    native = Image.new("RGB", (1080, 1920))
    assert guarded._normalise(native).size == (1080, 1920)
    assert guarded._device_size == (1080, 1920)


def test_taps_scale_to_the_device(monkeypatch):
    sent = []

    def fake_adb(path, serial, *args, **kwargs):
        sent.append(args)
        return ""

    monkeypatch.setattr(guarded, "adb", fake_adb)

    guarded._normalise(Image.new("RGB", (540, 960)))
    guarded.tap(Path("adb"), "serial", (1080, 1920))
    assert sent[-1][-2:] == ("540", "960"), "a half-size device halves the tap"

    guarded._normalise(Image.new("RGB", (1080, 1920)))
    guarded.tap(Path("adb"), "serial", (540, 1490))
    assert sent[-1][-2:] == ("540", "1490"), "a native device taps unchanged"


def test_the_card_and_arena_geometry_still_line_up(monkeypatch):
    """The hand crops and the arena mapping both assume 1080x1920, so after
    normalisation they must agree with each other regardless of the device."""
    from brain.arena import to_pixels
    from brain.cards import hand_boxes

    guarded._normalise(Image.new("RGB", (540, 960)))
    boxes = hand_boxes(1080, 1920)
    assert len(boxes) == 4
    # Card slots sit below the arena, which ends around y=1455.
    assert all(box[1] > 1455 for box in boxes)
    assert to_pixels(4, 17)[1] < boxes[0][1]


def _frame_with_enemy_bar(fill_px, colour):
    """A canonical-size frame carrying one enemy bar filled to `fill_px`."""
    import numpy as np
    from PIL import Image
    import tower_hp

    px = np.zeros((1920, 1080, 3), dtype=np.uint8)
    px[:, :] = (120, 90, 70)  # arena floor, matched by neither bar colour
    x = tower_hp.ENEMY_BARS["right"]
    y0 = tower_hp.ENEMY_SEARCH_Y[0] + 10
    px[y0:y0 + 8, x:x + fill_px] = colour
    return Image.fromarray(px)


def test_enemy_bar_is_read_in_both_arena_colourings():
    """The enemy bar renders deep red in some arenas and bright pink in others.

    Reading only the deep red returned 0.0 for a tower sitting on 1980 of 3346
    hitpoints, which reads as "already destroyed" to every lane decision that
    depends on it. Both renderings must measure the same bar the same way.
    """
    import tower_hp

    for colour in ((200, 60, 60), (255, 156, 212)):
        full = tower_hp.ENEMY_BAR_FULL_WIDTH
        got = tower_hp.enemy_tower_fractions(_frame_with_enemy_bar(full, colour))
        assert got["right"] > 0.9, (colour, got)
        half = tower_hp.enemy_tower_fractions(_frame_with_enemy_bar(full // 2, colour))
        assert 0.4 < half["right"] < 0.6, (colour, half)


def test_a_full_enemy_bar_reads_as_a_full_tower():
    """The property 133 broke, checked directly instead of pinning a number.

    Both towers are full at the start of every match, and over 13384 logged
    readings the ally reader said exactly 1.000 in 3986 of them. The enemy
    reader managed 7, piling up at 0.91/0.89/0.87 instead: a full 118px fill
    divided by 133 is 0.887, which never reaches the >= 0.95 snap. Segmenting a
    live frame shows why - 206-215 is the tower's gold trim, the fill runs
    216-333, a dark border closes the element at 335. 133 was the trim, 119 is
    the track this function scans.
    """
    import tower_hp

    assert tower_hp.ENEMY_BAR_FULL_WIDTH == tower_hp.ALLY_BAR_FULL_WIDTH == 119
    for colour in ((200, 60, 60), (255, 156, 212)):
        frame = _frame_with_enemy_bar(tower_hp.ENEMY_BAR_FULL_WIDTH, colour)
        assert tower_hp.enemy_tower_fractions(frame)["right"] == 1.0, colour


def test_the_connection_lost_dialog_is_recognised_and_only_that():
    """The one popup with no close button, so the bot used to relaunch the app.

    A false positive here is a tap on a screen we have not identified, so the
    test checks the detector stays silent on a plain frame as well as finding
    the link on the real thing.
    """
    import numpy as np
    from PIL import Image
    import connection_lost as cl

    px = np.zeros((1920, 1080, 3), dtype=np.uint8)
    px[:, :] = (140, 110, 80)  # arena-ish background
    assert cl.find_reload(Image.fromarray(px)) is None

    x0, y0, x1, y1 = cl.PANEL
    px[y0 - 260:y1 + 160, x0 - 40:x1 + 60] = cl.SLAB
    assert cl.find_reload(Image.fromarray(px)) is None, "slab alone must not fire"

    tx0, ty0, tx1, ty1 = cl.RELOAD_BOX
    px[ty0 + 8:ty1 - 8, tx0 + 6:tx1 - 6] = (230, 232, 238)
    spot = cl.find_reload(Image.fromarray(px))
    assert spot is not None, "slab plus RELOAD text must fire"
    assert tx0 <= spot[0] <= tx1 and ty0 <= spot[1] <= ty1, spot
