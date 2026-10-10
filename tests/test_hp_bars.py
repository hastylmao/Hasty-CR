"""Live hit points must come off the bars the game draws, not be assumed full.

The policy was trained on current hit points (`sim.env.observe`), and live
vision used to feed it every unit at full health - a Hog on its last 10% looked
like a fresh one. These tests pin down each step that closes that gap:

* reading a bar's fill, on real bars cropped from a real match;
* pairing each bar with the unit under it;
* knowing how long a troop's bar is, from the client's own bar class;
* holding a reading through a frame where the bar is missed;
* scaling the HP plane by the reading, for enemies and allies alike;
* and the whole path through `YoloVision.detect` and `apply`.

None of it needs the extracted game data, a detector checkpoint or an emulator.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts"),
             str(ROOT / "vendor" / "ClashRoyaleBuildABot")):
    if path not in sys.path:
        sys.path.insert(0, path)

from brain import hp_bars                                     # noqa: E402
from brain.tracker import NO_BAR_FRAMES, Tracker              # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "hp_bars"


def _real():
    from PIL import Image
    pixels = np.asarray(Image.open(FIXTURE / "river_fight.png").convert("RGB"))
    bars = json.loads((FIXTURE / "river_fight.json").read_text())["bars"]
    return pixels, bars


def _expected(bar) -> float | None:
    box = bar["box"]
    return hp_bars.expected_track_px(bar["unit"], box[3] - box[1])


# ------------------------------------------------------------ real bars


@pytest.mark.parametrize("key", ["hog_a", "hog_b", "hog_c", "hog_d", "cannon", "small_a"])
def test_real_bars_read_what_a_person_reads(key):
    """Hand readings were taken off zoomed crops, independently of the reader."""
    pixels, bars = _real()
    bar = bars[key]
    got = hp_bars.read_fraction(pixels, bar["box"], _expected(bar))
    assert got is not None
    assert abs(got - bar["fraction_by_hand"]) <= 0.05, (key, got)


@pytest.mark.parametrize("dx,dy,short", [(-3, 0, 0), (3, 0, 0), (0, -2, 0),
                                         (0, 2, 0), (0, 0, 8), (2, 1, 5)])
def test_a_loose_detector_box_still_reads(dx, dy, short):
    """Detector boxes jitter by a few pixels and are sometimes cut short."""
    pixels, bars = _real()
    for key, bar in bars.items():
        x1, y1, x2, y2 = bar["box"]
        box = (x1 + dx, y1 + dy, x2 + dx - short, y2 + dy)
        got = hp_bars.read_fraction(pixels, box, _expected(bar))
        assert got is not None and abs(got - bar["fraction_by_hand"]) <= 0.08, (
            key, dx, dy, short, got)


def test_a_hidden_bar_end_falls_back_to_the_troops_bar_length():
    """In a clump the right end is often under another bar or unit.

    Painting over the end shortens the dark run, so the measured track is far
    shorter than a Medium bar should be; the troop's known length takes over.
    """
    pixels, bars = _real()
    bar = bars["hog_b"]
    x1, y1, x2, y2 = (int(v) for v in bar["box"])
    covered = pixels.copy()
    covered[y1:y2, x2 - 14:x2 + 4] = (200, 190, 170)        # arena floor colour
    with_length = hp_bars.read_fraction(covered, bar["box"], _expected(bar))
    without = hp_bars.read_fraction(covered, bar["box"], None)
    assert abs(with_length - bar["fraction_by_hand"]) <= 0.06
    assert without - bar["fraction_by_hand"] > 0.1, (
        "without a known length the covered bar should over-read; if it does "
        "not, this test is not exercising the fallback")


# ------------------------------------------------------------ synthetic bars


def _draw(fraction, fill, empty, scale=1.0, length=2.0, size=(120, 400),
          outline=True):
    """Badge + track on arena floor, in the proportions measured in play."""
    frame = np.full(size + (3,), (200, 190, 170), np.uint8)
    h = int(round(31 * scale))
    x1, y1 = 40, 40
    badge_w = int(round(hp_bars.BADGE_WIDTH * h))
    frame[y1:y1 + h, x1:x1 + badge_w] = (200, 50, 70)      # badge
    if outline:                                            # its dark rim
        rim = max(1, int(round(0.05 * h)))
        frame[y1:y1 + h, x1 + badge_w - rim:x1 + badge_w] = (90, 30, 45)
    frame[y1 + 8:y1 + 14, x1 + 8:x1 + 22] = (250, 210, 60)  # level digits
    t0 = x1 + badge_w
    track = int(round(length * h))
    top, bottom = y1 + int(0.3 * h), y1 + int(0.7 * h)
    frame[top:bottom, t0:t0 + track] = (60, 25, 40)        # outline colour
    inner = track - int(round(hp_bars.OUTLINE * h))
    frame[top + 2:bottom - 2, t0:t0 + inner] = empty
    frame[top + 2:bottom - 2, t0:t0 + int(round(fraction * inner))] = fill
    return frame, (x1, y1, t0 + track, y1 + h)


@pytest.mark.parametrize("fill,empty", [
    ((205, 55, 75), (75, 35, 50)),      # enemy
    ((200, 240, 255), (40, 55, 95)),    # ally
    ((245, 245, 248), (75, 35, 50)),    # white flash right after a hit
    ((235, 175, 225), (75, 35, 50)),    # pink flash
])
@pytest.mark.parametrize("fraction", [0.05, 0.3, 0.55, 0.9])
@pytest.mark.parametrize("scale", [0.6, 1.0, 1.7])
@pytest.mark.parametrize("outline", [True, False])
def test_fill_is_read_by_brightness_whatever_its_colour(fill, empty, fraction,
                                                        scale, outline):
    frame, box = _draw(fraction, fill, empty, scale, outline=outline)
    got = hp_bars.read_fraction(frame, box, 2.0 * (box[3] - box[1]))
    assert abs(got - fraction) <= 0.04, (fill, fraction, scale, got)


# ------------------------------------------------------------ association


def test_each_bar_goes_to_the_unit_under_it():
    # three units in a clump, bars listed in a different order than units
    units = [(100, 120, 140, 170), (150, 110, 190, 160), (125, 150, 165, 200)]
    bars = [(150, 82, 205, 98), (100, 92, 155, 108), (125, 122, 180, 138)]
    assert hp_bars.match_bars(units, bars) == {0: 1, 1: 0, 2: 2}


def test_a_bar_far_from_every_unit_is_left_alone():
    units = [(100, 120, 140, 170)]
    assert hp_bars.match_bars(units, [(300, 300, 355, 316)]) == {}


def test_no_bar_means_full_and_a_bar_never_reads_full():
    frame, box = _draw(1.0, (205, 55, 75), (75, 35, 50))
    unit_under = hp_bars.UnitBox("hog_rider", (box[0] + 5, box[3] + 2,
                                               box[2] - 5, box[3] + 60))
    elsewhere = hp_bars.UnitBox("knight", (300, 10, 340, 60))
    got = hp_bars.unit_fractions(frame, [unit_under, elsewhere], [box])
    assert got[1] == hp_bars.FULL
    assert got[0] is not None and got[0] < hp_bars.FULL, (
        "a visible bar means the unit is hurt; 1.0 is reserved for no bar")


# ------------------------------------------------------------ bar lengths


@pytest.mark.parametrize("unit,expected", [
    ("goblin", "small"), ("archer", "small"), ("guard", "small"),
    ("ice_spirit", "small"), ("lava_pup", "small"),
    ("hog_rider", "medium"), ("knight", "medium"), ("musketeer", "medium"),
    ("royal_recruit", "medium"), ("dark_prince", "medium"), ("bandit", "medium"),
    ("night_witch", "medium"), ("ice_golem", "medium"),
    ("giant", "high"), ("golem", "high"), ("mega_knight", "high"),
    ("baby_dragon", "high"), ("elixir_golem_large", "high"),
    ("cannon", "building"), ("x_bow", "building"), ("furnace", "building"),
    ("tesla", "building"), ("goblin_cage", "medium"), ("cannon_cart", "building"),
])
def test_bar_class_comes_from_the_clients_table(unit, expected):
    assert hp_bars.bar_class(unit) == expected


def test_every_live_troop_has_a_bar_length():
    pytest.importorskip("clashroyalebuildabot.namespaces.units")
    from clashroyalebuildabot.namespaces.units import NAME2UNIT
    from brain.vision import EXTRA_UNITS
    names = {u.name for u in NAME2UNIT.values()} | {row[0] for row in EXTRA_UNITS}
    # Not troops with a bar of their own: a spell's rolling object, a thrown
    # snowball, and the duchess tower (a crown tower, read by `tower_hp`).
    # `brawler` and `royal_guardian` have no row in the published snapshot.
    exempt = {"barbarian_barrel", "giant_snowball", "dagger_duchess_tower",
              "brawler", "royal_guardian"}
    missing = sorted(n for n in names - exempt if hp_bars.bar_class(n) is None)
    assert not missing, f"no bar length for {missing}"


def test_bar_lengths_run_small_medium_high_building():
    t = hp_bars.TRACK_LENGTH
    assert t["small"] < t["medium"] < t["high"] <= t["building"]


# ------------------------------------------------------------ tracking


def _cell(x, y):
    from brain.arena import Cell
    return Cell(x, y)


def test_a_missed_bar_keeps_the_last_reading_until_it_stays_gone():
    tracker = Tracker()
    now = 0.0
    (track,) = tracker.update([("hog_rider", _cell(9, 10), 0.4)], now)
    assert track.hp == pytest.approx(0.4)
    assert NO_BAR_FRAMES >= 2, "a single missed detection must not reset health"
    for frame in range(1, NO_BAR_FRAMES):
        now += 0.3
        (track,) = tracker.update([("hog_rider", _cell(9, 10 + frame * 0.3), 1.0)], now)
        assert track.hp == pytest.approx(0.4), "one missed bar reset the unit to full"
    now += 0.3
    (track,) = tracker.update([("hog_rider", _cell(9, 11), 1.0)], now)
    assert track.hp == 1.0, "a bar gone for good means healed or misread; trust full"


def test_an_unreadable_bar_keeps_the_last_reading():
    tracker = Tracker()
    tracker.update([("knight", _cell(4, 8), 0.7)], 0.0)
    for step in range(1, 6):
        (track,) = tracker.update([("knight", _cell(4, 8), None)], step * 0.3)
    assert track.hp == pytest.approx(0.7)


def test_old_two_part_detections_still_track_as_full():
    (track,) = Tracker().update([("knight", _cell(4, 8))], 0.0)
    assert track.hp == 1.0


# ------------------------------------------------------------ the observation


@pytest.fixture
def fixed_traits(monkeypatch):
    """Max HP without the extracted game data: every unit has 1000."""
    from brain import rl_policy
    monkeypatch.setattr(rl_policy, "_unit_traits", lambda name: (1000.0, False, False))
    return rl_policy


def _obs(tracks):
    return SimpleNamespace(allies=[], tracks=tracks, elixir=5, elapsed=30,
                           multiplier=1, ally_hp={}, enemy_hp={}, hand={},
                           next_card="")


def test_the_hp_plane_carries_the_reading_for_enemies(fixed_traits):
    tracks = [SimpleNamespace(cell=_cell(9, 20), name="hog_rider", hp=0.25),
              SimpleNamespace(cell=_cell(3, 20), name="knight", hp=1.0)]
    planes = fixed_traits.observation_from_live(_obs(tracks))["planes"]
    assert planes[3, 31 - 20, 9] == pytest.approx(0.25)
    assert planes[3, 31 - 20, 3] == pytest.approx(1.0)
    assert planes[1].sum() == 2, "positions must not change"


def test_the_hp_plane_carries_the_reading_for_allies(fixed_traits):
    allies = [(_cell(9, 10), "hog_rider", 0.5), (_cell(2, 10), "knight")]
    planes = fixed_traits.observation_from_live(_obs([]), allies)["planes"]
    assert planes[2, 31 - 10, 9] == pytest.approx(0.5)
    assert planes[2, 31 - 10, 2] == pytest.approx(1.0), "two-part allies are full"


def test_ally_names_carry_their_reading(fixed_traits):
    det = SimpleNamespace(unit=SimpleNamespace(name="knight"),
                          position=SimpleNamespace(tile_x=4, tile_y=10),
                          hp_fraction=0.3)
    unread = SimpleNamespace(unit=SimpleNamespace(name="knight"),
                             position=SimpleNamespace(tile_x=6, tile_y=10),
                             hp_fraction=None)
    (_, _, hp), (_, _, hp2) = fixed_traits.ally_cells_with_names(
        SimpleNamespace(allies=[det, unread]))
    assert hp == pytest.approx(0.3) and hp2 == 1.0


# ------------------------------------------------------------ end to end


def test_detect_and_apply_carry_the_reading_through():
    """The real `YoloVision.detect` and `apply`, with a stub detector."""
    pytest.importorskip("clashroyalebuildabot.namespaces.units")
    import torch
    from PIL import Image
    from brain import vision

    frame, bar = _draw(0.35, (205, 55, 75), (75, 35, 50), size=(400, 400))
    unit = (bar[0] + 5, bar[3] + 3, bar[2] - 5, bar[3] + 70)
    lone = (300, 300, 340, 360)

    class Boxes:
        xyxy = torch.tensor([unit, bar, lone], dtype=torch.float32)
        conf = torch.tensor([0.9, 0.9, 0.9])
        cls = torch.tensor([0, 1, 2])

        def __len__(self):
            return 3

    class Model:
        def predict(self, *args, **kwargs):
            return [SimpleNamespace(boxes=Boxes())]

    v = object.__new__(vision.YoloVision)
    v.ready, v.confidence, v.imgsz, v.device, v.max_units = True, 0.4, 640, "cpu", 40
    v.side_floor, v.frames, v.detect_ms, v.last_counts = 0.55, 0, 0.0, (0, 0)
    v.unresolved, v.bars_seen = {}, 0
    v._model, v._names = Model(), {0: "hog-rider", 1: "bar", 2: "knight"}
    from clashroyalebuildabot.namespaces.units import NAME2UNIT
    v._units = {vision._key(u.name): u for u in NAME2UNIT.values()}
    v.sides = SimpleNamespace(crop=32, classify=lambda crops: [(1, 0.99)] * len(crops))

    ours, theirs = v.detect(Image.fromarray(frame))
    by_name = {seen.name: seen for seen in ours + theirs}
    assert by_name["hog_rider"].hp == pytest.approx(0.35, abs=0.04)
    assert by_name["knight"].hp == hp_bars.FULL
    assert v.bars_seen == 1

    state = SimpleNamespace(allies=[], enemies=[])
    assert v.apply(state, Image.fromarray(frame))
    hp = {d.unit.name: d.hp_fraction for d in state.enemies}
    assert hp["hog_rider"] == pytest.approx(0.35, abs=0.04)
    assert hp["knight"] == hp_bars.FULL
