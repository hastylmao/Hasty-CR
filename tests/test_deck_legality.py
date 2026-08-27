"""A deck the game would not let you build is not a deck to train against.

Sampling eight cards flat from the playable pool produced decks no player could
field: eleven percent had more than one Champion, and one had four - Skeleton
King, Little Prince, Boss Bandit and Archer Queen together. An opponent holding
four Champions is a situation the agent will never meet on ladder, so learning
to answer it is worse than useless.

The rule is the March 2026 slot layout, from Supercell's own release notes:

    "There will now be: 1 Evo Slot, 1 Hero Slot, 1 Wild Slot"
    "Use the Wild Slot to activate an Evolution, Hero, or Champion as you like!"

  https://supercell.com/en/games/clashroyale/blog/release-notes/march-update-2026/

So three special cards at most; at most two Evolutions and at most two Heroes,
since each has one dedicated slot plus the Wild; and at most one Champion,
because a Champion has no slot of its own and can only take the Wild.

The 204 meta decks are legal by construction - they came from real battles -
which is a useful independent check that the rule as written here is the rule
the game actually enforces.
"""

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.deck_builder import (MAX_CHAMPIONS, MAX_EVOLUTIONS,  # noqa: E402
                              MAX_HEROES, MAX_SPECIAL, deck_is_legal,
                              deck_slot_kind, random_public_deck)
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.meta_decks import deck_pool                            # noqa: E402
from sim.runner import DECK_26                                  # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)


def test_the_slot_limits_are_the_published_ones():
    assert (MAX_SPECIAL, MAX_EVOLUTIONS, MAX_HEROES, MAX_CHAMPIONS) == (3, 2, 2, 1)


@pytest.mark.parametrize("card,expected", [
    ("knight_ev1", "evolution"),
    ("wizard_hero", "hero"),
    ("archer_queen", "champion"),
    ("knight", ""),
    ("fireball", ""),
])
def test_cards_are_classified_by_the_form_the_client_declares(card, expected):
    """`form` is Evolution or HeroForm; a Champion is a rarity, not a form."""
    assert deck_slot_kind(CARDS.get(card)) == expected


def test_a_deck_with_two_champions_is_rejected():
    champions = [n for n, c in CARDS.items() if deck_slot_kind(c) == "champion"]
    assert len(champions) >= 2, champions
    filler = [n for n in DECK_26 if not deck_slot_kind(CARDS.get(n))][:6]
    assert not deck_is_legal(CARDS, champions[:2] + filler)


def test_a_deck_with_one_champion_and_two_evolutions_is_allowed():
    """Two Evolutions take the Evo and Wild slots; the Champion takes the Hero one.

    I first wrote this expecting it to be illegal, reasoning that a Champion
    can only sit in the Wild slot and two Evolutions have already claimed it.
    That is wrong: the Hero and Wild slots are both shared with Champions, so a
    Champion can occupy the Hero slot. Three specials of any mix is the cap.
    """
    champion = next(n for n, c in CARDS.items() if deck_slot_kind(c) == "champion")
    evolutions = [n for n, c in CARDS.items() if deck_slot_kind(c) == "evolution"][:2]
    filler = [n for n in DECK_26 if not deck_slot_kind(CARDS.get(n))][:5]
    assert deck_is_legal(CARDS, [champion] + evolutions + filler)


def test_four_specials_is_over_the_cap_however_they_are_mixed():
    evolutions = [n for n, c in CARDS.items() if deck_slot_kind(c) == "evolution"][:2]
    heroes = [n for n, c in CARDS.items() if deck_slot_kind(c) == "hero"][:2]
    filler = [n for n in DECK_26 if not deck_slot_kind(CARDS.get(n))][:4]
    assert not deck_is_legal(CARDS, evolutions + heroes + filler)


def test_three_specials_of_mixed_kinds_fit():
    evolution = next(n for n, c in CARDS.items() if deck_slot_kind(c) == "evolution")
    hero = next(n for n, c in CARDS.items() if deck_slot_kind(c) == "hero")
    champion = next(n for n, c in CARDS.items() if deck_slot_kind(c) == "champion")
    filler = [n for n in DECK_26 if not deck_slot_kind(CARDS.get(n))][:5]
    assert deck_is_legal(CARDS, [evolution, hero, champion] + filler)


def test_random_decks_are_buildable():
    rng = random.Random(1)
    illegal = [d for d in (random_public_deck(CARDS, SPELLS, rng)
                           for _ in range(300))
               if not deck_is_legal(CARDS, d)]
    assert not illegal, illegal[:3]


def test_random_decks_are_still_eight_distinct_cards():
    rng = random.Random(2)
    for _ in range(100):
        deck = random_public_deck(CARDS, SPELLS, rng)
        assert len(deck) == 8 and len(set(deck)) == 8, deck


def test_every_real_ladder_deck_is_legal_under_this_rule():
    """The independent check: these came from real battles, so if the rule
    written here were wrong, some of them would fail it."""
    pool = deck_pool(CARDS)
    assert len(pool) > 100, len(pool)
    illegal = [(name, deck) for name, _style, deck in pool
               if not deck_is_legal(CARDS, deck)]
    assert not illegal, illegal[:3]


def test_our_own_deck_is_legal():
    assert deck_is_legal(CARDS, DECK_26)
