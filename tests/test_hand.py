"""Hand smoothing: a slot must agree with itself before the bot acts on it."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain.hand import HandTracker  # noqa: E402


def test_a_stable_hand_is_reported_as_is():
    tracker = HandTracker()
    hand = ["the_log", "musketeer", "ice_spirit", "cannon"]
    for _ in range(3):
        stable = tracker.update(hand)
    assert stable == {0: "the_log", 1: "musketeer", 2: "ice_spirit", 3: "cannon"}


def test_a_one_frame_misread_does_not_change_the_slot():
    """The captured failure: slot 2 read ice_spirit, then hog_rider, then blank
    across three frames with no card played and elixir unchanged."""
    tracker = HandTracker()
    good = ["the_log", "musketeer", "ice_spirit", "cannon"]
    tracker.update(good)
    tracker.update(good)
    flipped = ["the_log", "musketeer", "hog_rider", "cannon"]
    stable = tracker.update(flipped)
    assert stable[2] == "ice_spirit", "one bad frame must not flip the slot"
    stable = tracker.update(["the_log", "musketeer", "blank", "cannon"])
    assert stable[2] == "ice_spirit"


def test_a_genuine_change_is_adopted_once_it_persists():
    tracker = HandTracker()
    for _ in range(4):
        tracker.update(["the_log", "musketeer", "ice_spirit", "cannon"])
    tracker.confirm_played(2)          # we played that slot
    for _ in range(2):
        stable = tracker.update(["the_log", "musketeer", "hog_rider", "cannon"])
    assert stable[2] == "hog_rider"


def test_an_unreadable_slot_is_reported_as_absent():
    tracker = HandTracker()
    for _ in range(4):
        stable = tracker.update(["the_log", "musketeer", "blank", "cannon"])
    assert 2 not in stable
    assert stable[0] == "the_log"


def test_flips_are_counted_so_perception_drift_is_visible():
    tracker = HandTracker()
    tracker.update(["cannon", "cannon", "cannon", "cannon"])
    tracker.update(["cannon", "cannon", "hog_rider", "cannon"])
    assert tracker.flips == 1
