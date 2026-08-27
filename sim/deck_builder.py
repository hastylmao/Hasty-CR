"""Build reproducible random decks from the public, resolvable card pool."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Mapping


def ladder_cards() -> set[str]:
    """Cards observed in real Path of Legends battle logs.

    Written by `scripts/sync_meta_decks.py` with its source and retrieval time.
    Absent or unreadable, this is empty and the published catalogue is the only
    gate - the behaviour before the deck pool existed.
    """
    path = Path(__file__).resolve().parents[1] / "data" / "meta_decks.json"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(name) for name in blob.get("ladder_cards", ())}


def playable_public_cards(cards: Mapping[str, object],
                          spells: Mapping[str, object]) -> list[str]:
    """Return client keys for public cards that can resolve in ``Match``.

    RoyaleAPI's public catalogue includes Party Rocket, whose current client
    spell graph is intentionally quarantined rather than faked. Excluding a
    card that would consume elixir and do nothing is safer than silently
    corrupting a supposedly random match. Mirror is included because Match
    owns its rule even though it has no ordinary SpellSpec.

    That catalogue is not the only gate any more, because it is stale. It
    carries 120 cards and none of the 2026 additions, so Ronin - present in
    roughly a tenth of real Path of Legends decks - was excluded along with
    Vines, Boss Bandit, Berserker, Goblin Demolisher, Suspicious Bush, Goblin
    Curse, Little Prince and Goblinstein. All nine are in the client data and
    all nine already worked; nothing but a third-party list was keeping them
    out, and an agent that never sees Ronin is not training against the ladder.

    So a card also qualifies if it has been observed in real ladder play, which
    is stronger evidence of being a public card than a snapshot is. The
    same-shaped safety still applies: it has to resolve into something Match
    can run, and `tests/test_cards_do_something.py` covers every card this
    returns, so a card that deploys and does nothing fails there.
    """
    from .card_catalog_audit import report as catalogue_report

    mapped = catalogue_report()["mapped"]
    candidates = set(mapped.values()) | ladder_cards()
    playable = []
    for local_key in sorted(candidates):
        spec = cards.get(local_key)
        if spec is None:
            continue
        if (local_key == "mirror" or local_key in spells
                or getattr(spec, "unit", None) is not None
                or getattr(spec, "additional_summons", ())):
            playable.append(local_key)
    return sorted(set(playable))


# The three special deck slots, from the March 2026 update: "1 Evo Slot, 1 Hero
# Slot, 1 Wild Slot", where "Use the Wild Slot to activate an Evolution, Hero,
# or Champion as you like".
#
#   https://supercell.com/en/games/clashroyale/blog/release-notes/march-update-2026/
#
# So at most three special cards, of which at most two Evolutions, at most two
# Heroes, and at most one Champion - a Champion can only occupy the Wild slot,
# there being no Champion slot of its own.
MAX_SPECIAL = 3
MAX_EVOLUTIONS = 2
MAX_HEROES = 2
MAX_CHAMPIONS = 1


def deck_slot_kind(card: object) -> str:
    """Which special slot a card needs: evolution, hero, champion, or none."""
    form = str(getattr(card, "form", "") or "")
    if form == "Evolution":
        return "evolution"
    if form == "HeroForm":
        return "hero"
    if str(getattr(card, "rarity", "")) == "Champion":
        return "champion"
    return ""


def deck_is_legal(cards: Mapping[str, object], deck) -> bool:
    """Does this deck fit the three special slots?"""
    counts = {"evolution": 0, "hero": 0, "champion": 0}
    for name in deck:
        kind = deck_slot_kind(cards.get(name))
        if kind:
            counts[kind] += 1
    return (sum(counts.values()) <= MAX_SPECIAL
            and counts["evolution"] <= MAX_EVOLUTIONS
            and counts["hero"] <= MAX_HEROES
            and counts["champion"] <= MAX_CHAMPIONS)


def random_public_deck(cards: Mapping[str, object], spells: Mapping[str, object],
                       rng: random.Random, size: int = 8) -> list[str]:
    """Sample a unique deck that a player could actually build.

    Sampling flat from the pool does not produce legal decks: eleven percent
    came out with more than one Champion, and one had four - Skeleton King,
    Little Prince, Boss Bandit and Archer Queen in the same eight. An opponent
    holding four Champions is not a deck the agent will ever meet, and training
    against one teaches it to answer a situation that cannot arise.

    The real meta decks in the pool are legal by construction, being taken from
    real battles; this is only for the random opponent and for tests.
    """
    if size < 1:
        raise ValueError("deck size must be positive")
    pool = playable_public_cards(cards, spells)
    if len(pool) < size:
        raise ValueError(f"only {len(pool)} playable public cards for a {size}-card deck")
    for _ in range(200):
        deck = rng.sample(pool, size)
        if deck_is_legal(cards, deck):
            return deck
    # Fall back to building one slot-aware rather than looping for ever.
    ordinary = [name for name in pool if not deck_slot_kind(cards.get(name))]
    if len(ordinary) < size:
        raise ValueError("not enough ordinary cards to build a legal deck")
    return rng.sample(ordinary, size)
