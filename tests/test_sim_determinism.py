"""Does the same seed replay to the same match, exactly?

The simulator's stated contract is that positions are integer millitiles and
everything is integer arithmetic, so runs are reproducible. That contract is
load-bearing twice over. Reinforcement learning needs a stationary environment
to learn against, and every A/B comparison this project makes assumes a seed
means one match rather than a distribution.

A float leaking into a position or a set iteration order leaking into target
selection would break both, and would show up as training that plateaus for no
visible reason rather than as a failing assertion - so it is asserted here.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import load_gamedata                         # noqa: E402
from sim.runner import DECK_26, play_match, resolve_deck       # noqa: E402
from sim.spells import load_spells                             # noqa: E402

FULL = load_gamedata(level=11)
CARDS = resolve_deck(FULL, DECK_26)
SPELLS = load_spells(level=11)


def _fingerprint(seed: int) -> tuple:
    match, _, _ = play_match(CARDS, seed=seed, spells=SPELLS, opponent="brain")
    return (
        match.elapsed_ms,
        match.result,
        match.crowns_for(1),
        match.crowns_for(-1),
        len(match.battle.damage_log),
        tuple(match.battle.damage_log[-40:]),
        tuple(sorted((e.uid, e.name, e.pos.x, e.pos.y, e.hitpoints)
                     for e in match.battle.entities.values())),
    )


@pytest.mark.parametrize("seed", [1, 5])
def test_a_seed_replays_to_an_identical_match(seed):
    assert _fingerprint(seed) == _fingerprint(seed)


def test_positions_stay_integer_millitiles():
    """A float position is the way determinism usually leaks.

    It survives a same-process replay - the same float arithmetic repeats -
    and only diverges across machines or Python versions, which is the worst
    possible time to find out.
    """
    match, _, _ = play_match(CARDS, seed=3, spells=SPELLS, opponent="brain")
    offenders = [(e.name, e.pos.x, e.pos.y)
                 for e in match.battle.entities.values()
                 if not isinstance(e.pos.x, int) or not isinstance(e.pos.y, int)]
    assert not offenders, offenders


def test_different_seeds_do_not_all_produce_the_same_match():
    """Determinism must not have been bought by ignoring the seed."""
    assert _fingerprint(1) != _fingerprint(5)
