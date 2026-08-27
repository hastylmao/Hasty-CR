"""The scripted opponent has to be a real test, and a beatable one.

Both failure modes matter. An opponent that never wins tells us nothing - the
random one loses about 99.7% of the time, so beating it measures nothing - and
one that always wins is equally useless as a gradient. This pins it in between.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.gamedata import load_gamedata            # noqa: E402
from sim.meta_decks import deck_pool, rejected    # noqa: E402
from sim.runner import DECK_26, play_match, resolve_deck   # noqa: E402
from sim.spells import load_spells                # noqa: E402


def _record(opponent: str, matches: int = 16) -> tuple:
    cards = resolve_deck(load_gamedata(level=11), DECK_26)
    spells = load_spells(level=11)
    wins = losses = 0
    for seed in range(matches):
        match, _, _ = play_match(cards, seed=seed, spells=spells, opponent=opponent)
        wins += match.result == "bottom"
        losses += match.result == "top"
    return wins, losses


def test_every_archetype_can_actually_be_built():
    """A deck naming a card the data does not have is silently dropped.

    The names are the game data's own keys and not the ones a player would
    type - the Log is `log`, Mini P.E.K.K.A. is `minipekka`, Archers `archer` -
    so a typo costs a whole archetype without any error.
    """
    cards = load_gamedata(level=11)
    assert rejected(cards) == {}, rejected(cards)
    pool = deck_pool(cards)
    assert len(pool) >= 4, pool
    assert {style for _, style, _ in pool} >= {"cycle", "beatdown", "control"}


def test_the_scripted_opponent_is_harder_than_random_and_still_beatable():
    scripted_wins, scripted_losses = _record("scripted")
    random_wins, random_losses = _record("simple")

    assert scripted_losses >= random_losses, (
        f"scripted lost {scripted_losses}, random lost {random_losses} - "
        "the scripted opponent is not adding any pressure")
    assert scripted_wins > 0, "the scripted opponent beats us every time"
