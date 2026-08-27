"""Can every public card actually be played without the engine falling over?

The fidelity tests drive one mechanic each, deliberately, and the archetype
decks exercise perhaps thirty cards between them. That leaves most of the
catalogue never played by anything: a card whose action graph raises would sit
undiscovered until a random-deck run happened to draw it, and the viewer would
look like it had frozen rather than reporting a traceback.

This is a smoke test, not a fidelity test. It asserts only that the card
deploys and the battle keeps ticking - it says nothing about whether the card
behaves correctly, which is what everything else here is for.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                         # noqa: E402
from sim.arena import TICK_MS                                 # noqa: E402
from sim.deck_builder import playable_public_cards            # noqa: E402
from sim.gamedata import load_gamedata                        # noqa: E402
from sim.match import Match                                   # noqa: E402
from sim.spells import load_spells                            # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
POOL = sorted(playable_public_cards(CARDS, SPELLS))
FILLER = ["knight", "archers", "fireball", "musketeer",
          "cannon", "skeletons", "zap", "giant"]


def test_the_pool_is_the_whole_public_catalogue():
    """Guards the parametrisation below from silently shrinking to nothing."""
    assert len(POOL) > 110, len(POOL)


@pytest.mark.parametrize("card", POOL)
def test_a_card_deploys_and_the_battle_keeps_running(card):
    deck = [card] + [name for name in FILLER if name != card][:7]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    # Enough elixir that the play cannot be refused for cost, so a refusal
    # means the card genuinely could not be placed there.
    match.players[1].elixir = 10_000
    match.play_card(1, card, grid_to_point(9, 22, 1))
    for _ in range(int(4 * 1000 / TICK_MS)):
        match.step()
    assert match.battle.now_ms > 0
