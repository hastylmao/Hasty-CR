"""Does a swarm card put down the number of bodies it says it does?

A miscount here is a pure balance error and completely silent: Skeletons with
three bodies instead of four still looks like Skeletons, and every defensive
measurement taken with them is quietly wrong. The engine has form for this
exact shape - spawned units that failed to resolve were skipped without a word,
so a Golem left nothing behind.

The count is primary plus secondary, because a card can summon two kinds at
once: Goblin Gang is three Goblins and three Spear Goblins, and checking only
the primary number reports it as wrong when it is right.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import TICK_MS                                   # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
DECK = ["knight", "archers", "fireball", "musketeer",
        "cannon", "skeletons", "zap", "giant"]

# Evolutions that deliberately add bodies beyond the declared count.
# Evolved Skeleton Army duplicates on deploy, so 15 declared becomes 16.
EXTRA_BODIES = {"skeleton_army_ev1": 1}

SWARMS = sorted(name for name, card in CARDS.items()
                if card.unit is not None
                and int(getattr(card, "summon_number", 1) or 1) > 1)


def _expected(name: str) -> int:
    card = CARDS[name]
    total = int(getattr(card, "summon_number", 1) or 1)
    total += int(getattr(card, "secondary_summon_number", 0) or 0)
    return total + EXTRA_BODIES.get(name, 0)


def _deploy(name: str):
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    if name not in player.hand:
        player.hand[0] = name
    player.elixir = 10_000
    assert match.play_card(1, name, grid_to_point(9, 22, 1)), name
    for _ in range(int(2 * 1000 / TICK_MS)):
        match.step()
    return [entity for entity in match.battle.entities.values()
            if entity.side == 1 and entity.alive and not entity.is_tower]


def test_there_are_swarm_cards_to_check():
    assert len(SWARMS) > 20, len(SWARMS)


@pytest.mark.parametrize("card", SWARMS)
def test_a_swarm_deploys_the_number_of_bodies_it_declares(card):
    bodies = _deploy(card)
    assert len(bodies) == _expected(card), (
        card, len(bodies), _expected(card),
        sorted(entity.name for entity in bodies))


def test_a_two_kind_summon_puts_down_both_kinds():
    """Goblin Gang is the case that makes the primary count misleading."""
    card = CARDS["goblin_gang"]
    # Derived from the card rather than written down: the primary is the
    # stabbing goblin variant, not the plain `goblin`, and asserting the name
    # would be asserting my memory of the client's naming.
    expected = {card.unit.name, card.secondary_unit.name}
    assert len(expected) == 2, expected
    names = {entity.name for entity in _deploy("goblin_gang")}
    assert names == expected, (names, expected)


def test_the_evolution_exception_is_real():
    """Guards the allowance above from hiding a genuine regression.

    If Evolved Skeleton Army stops adding a body, the entry in EXTRA_BODIES is
    covering a real change rather than a known mechanic.
    """
    base = len(_deploy("skeleton_army"))
    evolved = len(_deploy("skeleton_army_ev1"))
    assert evolved == base + EXTRA_BODIES["skeleton_army_ev1"], (base, evolved)
