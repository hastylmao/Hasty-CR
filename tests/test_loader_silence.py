"""Does the loader drop anything without saying so?

`load_gamedata` builds every unit inside a `try/except Exception: continue`, so
a unit whose spec fails to build does not error - it simply is not in the game
any more. That is not hypothetical here. Golemite, BalloonBomb and LavaPups
have no `spells` row, every lookup for them failed, and the death spawns were
skipped silently; a Golem that left nothing behind looked like a balance
question rather than a missing card.

A broad `except: continue` in a data loader is a decision to prefer a partial
game over a loud failure. That is defensible while nothing is failing, which is
exactly why it needs a test: the day something starts failing, nothing else
will mention it.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sim.gamedata as gamedata                               # noqa: E402


def test_no_unit_is_silently_dropped_while_loading():
    failures = []
    original = gamedata.build_unit_spec

    def recording(name, raw, level, rarity, rarities, projectiles):
        try:
            return original(name, raw, level, rarity, rarities, projectiles)
        except Exception as error:                            # noqa: BLE001
            failures.append(f"{name}: {type(error).__name__}: {error}")
            raise

    gamedata.build_unit_spec = recording
    try:
        gamedata._CHARACTER_CACHE.clear()
        cards = gamedata.load_gamedata(level=11)
    finally:
        gamedata.build_unit_spec = original
        gamedata._CHARACTER_CACHE.clear()

    assert cards, "no cards loaded at all"
    assert not failures, failures[:10]


def test_the_loader_still_produces_a_full_catalogue():
    """A count, so a collapse to a handful of cards cannot pass quietly.

    Deliberately a lower bound rather than an exact number: new cards ship
    regularly and this should not need editing for that, only for a loss.
    """
    cards = gamedata.load_gamedata(level=11)
    assert len(cards) >= 200, len(cards)
    deployable = [name for name, card in cards.items() if card.unit is not None]
    assert len(deployable) >= 170, len(deployable)
