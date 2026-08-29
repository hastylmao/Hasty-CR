"""The VOD pipeline's arithmetic, which a happy-path run does not check.

Running the pipeline end to end proves it produces output. It does not prove
the output means anything: a pixel-to-tile transform that is wrong by a
constant still yields plausible-looking coordinates, a span grouper that merges
two matches still yields a span, and a tracker that swaps two Skeletons still
yields a speed. Each of those would corrupt a calibration number silently,
which is the specific failure this whole package exists to stop happening to
the simulator.

So the tests here are about the parts where being wrong is invisible.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

np = pytest.importorskip("numpy")

from tools.vod import calibrate, segment, track            # noqa: E402


# ------------------------------------------------------------------- spans

def test_contiguous_seconds_become_one_span():
    seconds = [float(t) for t in range(0, 120)]
    spans = segment.to_spans(seconds, 1.0)
    assert len(spans) == 1
    assert spans[0].start_s == 0.0
    assert spans[0].duration_s == pytest.approx(120.0)


def test_a_long_gap_splits_two_matches():
    first = [float(t) for t in range(0, 100)]
    second = [float(t) for t in range(200, 300)]
    spans = segment.to_spans(first + second, 1.0)
    assert len(spans) == 2, "a menu between two games must not be merged"
    assert spans[0].end_s < spans[1].start_s


def test_a_short_blink_does_not_split_a_match():
    """The detector misses a second here and there; that is not a menu."""
    seconds = [float(t) for t in range(0, 60) if t not in (17, 18, 41)]
    spans = segment.to_spans(seconds, 1.0)
    assert len(spans) == 1


def test_something_too_short_to_be_a_match_is_dropped():
    spans = segment.to_spans([float(t) for t in range(0, 20)], 1.0)
    assert spans == [], "20s of arena is a replay clip or a scoreboard"


# --------------------------------------------------------------- transform

def _synthetic_anchors(scale=50.0, ox=20.0, oy=80.0):
    """Pixel positions for known towers under a known affine."""
    return {name: (ox + tx * scale, oy + ty * scale)
            for name, (tx, ty) in track.TOWER_TILES.items()}


def test_the_transform_recovers_a_known_mapping():
    anchors = _synthetic_anchors()
    matrix = track.fit_transform(anchors)
    assert matrix is not None
    for name, (tx, ty) in track.TOWER_TILES.items():
        got = track.apply_transform(matrix, *anchors[name])
        assert got[0] == pytest.approx(tx, abs=1e-6)
        assert got[1] == pytest.approx(ty, abs=1e-6)


def test_a_different_framing_still_recovers_tiles():
    """A crop or a letterbox changes scale and offset, not the arena.

    This is the reason the transform is fitted per match instead of
    hardcoded: the same tile must come back from differently framed footage.
    """
    a = track.fit_transform(_synthetic_anchors(scale=50.0, ox=20.0, oy=80.0))
    b = track.fit_transform(_synthetic_anchors(scale=31.5, ox=-9.0, oy=140.0))
    point_a = (20.0 + 9.0 * 50.0, 80.0 + 20.0 * 50.0)
    point_b = (-9.0 + 9.0 * 31.5, 140.0 + 20.0 * 31.5)
    assert track.apply_transform(a, *point_a) == pytest.approx(
        track.apply_transform(b, *point_b), abs=1e-6)


def test_three_towers_are_enough_and_two_are_not():
    anchors = _synthetic_anchors()
    three = {k: anchors[k] for k in list(anchors)[:3]}
    two = {k: anchors[k] for k in list(anchors)[:2]}
    assert track.fit_transform(three) is not None
    assert track.fit_transform(two) is None, (
        "two points cannot determine an affine; fitting one would invent a "
        "scale and every distance would inherit it")


def test_the_residual_reports_a_bad_fit_rather_than_hiding_it():
    anchors = _synthetic_anchors()
    good = track.fit_transform(anchors)
    assert track.residual_tiles(good, anchors) < 1e-6

    # One tower mislocated by a long way, as a spell animation might cause.
    broken = dict(anchors)
    broken["enemy_left"] = (anchors["enemy_left"][0] + 400.0,
                            anchors["enemy_left"][1])
    fitted = track.fit_transform(broken)
    assert track.residual_tiles(fitted, broken) > 0.75, (
        "a fit this bad must exceed the rejection threshold, not pass quietly")


def test_no_transform_is_infinitely_wrong_not_zero():
    assert track.residual_tiles(None, {}) == float("inf")


# ----------------------------------------------------------------- sides

def test_side_is_assigned_across_the_river():
    dets = []
    anchors = _synthetic_anchors()
    for name, (px, py) in anchors.items():
        for _ in range(6):                      # enough for the median
            dets.append(track.Detection(
                0.0, "king-tower" if "king" in name else "queen-tower",
                0.9, px, py, 10, 10))
    dets.append(track.Detection(0.0, "hog-rider", 0.9,
                                anchors["enemy_left"][0],
                                anchors["enemy_left"][1] + 2 * 50.0, 8, 8))
    dets.append(track.Detection(0.0, "knight", 0.9,
                                anchors["ally_left"][0],
                                anchors["ally_left"][1] - 2 * 50.0, 8, 8))
    matrix, error = track.to_tiles(dets, height=1920.0)
    assert matrix is not None and error < 0.01
    hog = next(d for d in dets if d.name == "hog-rider")
    knight = next(d for d in dets if d.name == "knight")
    assert hog.side == "theirs", "row 9.5 is the opponent's half"
    assert knight.side == "ours", "row 22.5 is the recording player's half"


# ----------------------------------------------------------------- speeds

def _walk(card, start_y, speed, seconds, dt=0.1, x=9.0):
    rows = []
    steps = int(seconds / dt)
    for i in range(steps):
        rows.append({"kind": "det", "t": round(i * dt, 3), "name": card,
                     "conf": 0.9, "tile_x": x, "tile_y": start_y + speed * i * dt})
    return rows


def test_a_clean_walk_yields_its_own_speed():
    rows = _walk("hog-rider", 20.0, -2.0, 4.0)
    segs = list(calibrate.follow(rows, "hog-rider", 0.1))
    assert segs, "a clean four-second walk must produce a segment"
    assert segs[0].speed_tiles_s == pytest.approx(2.0, abs=0.05)


def test_a_unit_that_stops_to_fight_is_not_measured():
    """Its speed would be a blend of walking and standing, which is neither."""
    rows = _walk("knight", 20.0, -1.0, 2.0)
    held = rows[-1]["tile_y"]
    for i in range(20):
        rows.append({"kind": "det", "t": round(2.0 + i * 0.1, 3), "name": "knight",
                     "conf": 0.9, "tile_x": 9.0, "tile_y": held})
    segs = list(calibrate.follow(rows, "knight", 0.1))
    for seg in segs:
        assert seg.speed_tiles_s > 0.5, (
            "a segment must not average a walk together with standing still")


def test_a_crowd_of_one_class_is_refused_rather_than_guessed():
    """Three Skeletons on top of each other cannot be associated honestly."""
    rows = []
    for i in range(30):
        t = round(i * 0.1, 3)
        for offset in (0.0, 0.3, 0.6):          # inside CROWD_TILES
            rows.append({"kind": "det", "t": t, "name": "skeleton", "conf": 0.9,
                         "tile_x": 9.0 + offset, "tile_y": 20.0 - 0.1 * i})
    segs = list(calibrate.follow(rows, "skeleton", 0.1))
    assert not segs, "an ambiguous crowd must yield nothing, not a guess"


def test_a_teleporting_association_is_rejected():
    """Two different units of a class must not be stitched into one track."""
    rows = _walk("musketeer", 20.0, -0.6, 1.0)
    rows += _walk("musketeer", 5.0, -0.6, 1.0)    # far away, later
    for index, row in enumerate(rows[10:], start=10):
        row["t"] = round(index * 0.1, 3)
    segs = list(calibrate.follow(rows, "musketeer", 0.1))
    for seg in segs:
        assert seg.speed_tiles_s < track.__dict__.get("MAX", 99), "sanity"
        assert seg.speed_tiles_s == pytest.approx(0.6, abs=0.2), (
            "a 15-tile jump between two units must not become a speed")


# ------------------------------------------------------- inferred card plays

def _det(t, name, x, y, side="theirs"):
    return {"kind": "det", "t": t, "name": name, "conf": 0.9,
            "tile_x": x, "tile_y": y, "side": side}


def test_a_unit_standing_still_is_one_play_not_hundreds():
    """The bug that produced 121,841 plays from twenty matches.

    The recency test compared `now - t >= -1e-9`, true only when a remembered
    sighting lies in the FUTURE. Stored times are always past, so nothing was
    ever "recently seen" and every single detection became a fresh play.
    """
    from tools.vod import plays
    rows = [_det(round(i * 0.1, 2), "knight", 9.0, 20.0) for i in range(80)]
    found = plays.extract(rows)
    assert len(found) == 1, f"one knight standing still produced {len(found)} plays"


def test_a_fast_unit_is_not_recounted_as_it_travels():
    """A Hog covers three tiles inside the grace window.

    Comparing against where a unit *was*, with a fixed radius, lets anything
    fast outrun it and re-register. The radius has to grow with elapsed time.
    """
    from tools.vod import plays
    rows = [_det(round(i * 0.1, 2), "hog-rider", 9.0, 20.0 - i * 0.2)
            for i in range(60)]
    found = plays.extract(rows)
    assert len(found) == 1, (
        f"one hog crossing the arena produced {len(found)} plays")


def test_a_multi_unit_card_counts_once():
    """Three Skeletons are one card. Counting three triples its frequency."""
    from tools.vod import plays
    rows = []
    for i in range(40):
        t = round(i * 0.1, 2)
        for dx in (0.0, 0.6, 1.2):
            rows.append(_det(t, "skeleton", 9.0 + dx, 20.0))
    found = plays.extract(rows)
    assert len(found) == 1, f"one Skeletons card produced {len(found)} plays"
    assert found[0].count == 3, "the play should carry how many units landed"


def test_two_separate_plays_of_a_card_are_both_counted():
    """The suppression must not swallow a genuine second play."""
    from tools.vod import plays
    rows = [_det(round(i * 0.1, 2), "knight", 3.0, 20.0) for i in range(20)]
    rows += [_det(round(6.0 + i * 0.1, 2), "knight", 15.0, 20.0) for i in range(20)]
    found = plays.extract(rows)
    assert len(found) == 2, (
        "two knights, far apart and seconds apart, are two plays")


def test_interface_classes_are_never_plays():
    from tools.vod import plays
    rows = [_det(round(i * 0.1, 2), "tower-bar", 3.0, 6.0) for i in range(30)]
    rows += [_det(round(i * 0.1, 2), "clock", 9.0, 1.0) for i in range(30)]
    assert plays.extract(rows) == []
