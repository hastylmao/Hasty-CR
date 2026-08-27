"""Symmetry: the strongest single check a simulator can be given.

Clash Royale is a symmetric game. Two identical policies must therefore win
about half each, and any large deviation means the board itself favours a side
- a coordinate flip, a mirrored lane, a tower in the wrong place.

This caught a real bug. Placements were mirrored for the top player but its
*view* was not, so it read the board upside-down, defended the wrong half, and
lost 20-0. The win rate looked like evidence the policy was strong; it was
evidence the opponent was blind.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sim import arena  # noqa: E402
from sim.adapter import build_state, grid_to_point  # noqa: E402


@pytest.fixture(scope="module")
def cards():
    from sim.gamedata import load_gamedata
    from sim.runner import DECK_26, resolve_deck
    resolved = resolve_deck(load_gamedata(11), DECK_26)
    if len(resolved) < len(DECK_26):
        pytest.skip("game data not extracted on this machine")
    return resolved


def test_placement_mirrors_for_the_top_player():
    bottom = grid_to_point(4, 17, side=1)
    top = grid_to_point(4, 17, side=-1)
    assert bottom.x != top.x and bottom.y != top.y
    # A bridge push is near the river for both sides.
    assert abs(bottom.y - arena.RIVER_Y) < 2 * arena.MT
    assert abs(top.y - arena.RIVER_Y) < 2 * arena.MT


def test_each_side_sees_its_own_units_on_its_own_half(cards):
    from sim.match import Match
    match = Match(cards=cards, decks=(list(cards), list(cards)), seed=1)

    # Both players put a Hog at their own bridge.
    for side in (1, -1):
        match.players[side].hand = ["hog_rider"] + match.players[side].hand[:3]
        match.players[side].elixir = 10000
        assert match.play_card(side, "hog_rider", grid_to_point(4, 17, side))

    for side in (1, -1):
        state = build_state(match, side, cards)
        assert state.allies, f"side {side} should see its own Hog"
        for ally in state.allies:
            grid_y = 31 - ally.position.tile_y
            assert grid_y >= arena.RIVER_Y / arena.MT - 1, \
                f"side {side} sees its own unit on the wrong half"


def test_two_identical_policies_win_about_half_each(cards):
    """The headline check. A large skew means the board favours a side.

    The sample size has to be honest about binomial noise: at twelve matches a
    50/50 process produces 9-3 splits often enough that the test fails on luck.
    Forty matches puts three sigma at about +/-24 points, so the bounds below
    are wide enough not to cry wolf and tight enough to catch the 20-0 that a
    mirrored-view bug produced.
    """
    from sim.runner import play_match
    from sim.spells import load_spells

    spells = load_spells(11)
    bottom_wins = top_wins = 0
    for seed in range(40):
        match, _, _ = play_match(cards, seed=seed, spells=spells, opponent="brain")
        if match.result == "bottom":
            bottom_wins += 1
        elif match.result == "top":
            top_wins += 1

    decided = bottom_wins + top_wins
    if decided < 20:
        pytest.skip("too few decided matches to judge symmetry")
    share = bottom_wins / decided
    assert 0.25 <= share <= 0.75, (
        f"board favours one side: bottom won {bottom_wins}/{decided}")
