"""Tower HP must be aggregated as a sum, not a minimum.

With a minimum, once one tower reached zero it could not go lower, so all
further damage was invisible and every subsequent Hog scored as a pure
four-elixir loss - producing a negative mean reward for the win condition in
matches the bot was winning.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from brain.policy import _tower_total  # noqa: E402


def test_damage_registers_after_the_first_tower_falls():
    before = {"left": 0.0, "right": 1.0}
    after = {"left": 0.0, "right": 0.6}
    assert _tower_total(before) - _tower_total(after) > 0

    # The old behaviour, kept here so the regression is unmistakable.
    assert min(before.values()) - min(after.values()) == 0


def test_damage_to_either_tower_counts():
    full = {"left": 1.0, "right": 1.0}
    left_hit = {"left": 0.5, "right": 1.0}
    right_hit = {"left": 1.0, "right": 0.5}
    assert _tower_total(full) - _tower_total(left_hit) == 0.5
    assert _tower_total(full) - _tower_total(right_hit) == 0.5


def test_a_missing_reading_does_not_look_like_total_destruction():
    assert _tower_total({}) == 2.0
