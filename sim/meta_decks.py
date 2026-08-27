"""A pool of opponent decks, and a coarse style for each.

The simulator's long-standing weakness is that its only real opponent is our
own policy. A mirror defends exactly as well as we attack and never punishes
passivity, which is why the simulator could not price tempo and why its
strongest strategic recommendation froze the bot live. Playing against several
different archetypes is the cheapest way out of that: a beatdown deck asks
different questions of a Hog cycle than another Hog cycle does.

The archetypes and the style rule are adapted from vegetableleaf/ClashAI, whose
scripted bots pilot real meta decks with deck-agnostic heuristics. Decks are
filtered against our own card data on load, so a deck naming a card the
simulator cannot build is dropped rather than half-played.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

# Archetypes rather than a live meta snapshot: these have to be playable by the
# simulator, which knows troops and a handful of spells, not every mechanic.
# Card names are the game data's own keys, which are not always the ones a
# player would type: the Log is `log`, Mini P.E.K.K.A. is `minipekka`, and
# Archers are `archer`. Getting one wrong silently drops the whole deck, so
# deck_pool reports what it rejected rather than returning a shorter list.
ARCHETYPES: List[Tuple[str, str, List[str]]] = [
    ("hog_cycle", "cycle", ["hog_rider", "musketeer", "knight", "skeletons",
                   "ice_spirits", "cannon", "fireball", "log"]),
    ("beatdown", "beatdown", ["giant", "musketeer", "minipekka", "archer",
                  "minions", "fireball", "arrows", "knight"]),
    ("control", "control", ["valkyrie", "musketeer", "tesla", "skeletons",
                 "ice_spirits", "fireball", "archer", "knight"]),
    ("bridge_spam", "cycle", ["battle_ram", "ghost", "zap", "minions",
                     "skeletons", "musketeer", "knight", "fireball"]),
    ("giant_double", "beatdown", ["royal_giant", "musketeer", "knight", "skeletons",
                      "archer", "fireball", "cannon", "ice_spirits"]),
]

HEAVY_TANKS = {"golem", "lava_hound", "electro_giant", "goblin_giant", "pekka",
               "mega_knight", "giant", "royal_giant", "giant_skeleton",
               "elixir_golem"}


def classify_style(cards: Dict[str, object], deck: List[str]) -> str:
    """Coarse play style for a deck that does not declare one.

    The archetypes name their own style, because this rule is too blunt to
    separate them - a control deck averaging 3.0 elixir classifies as cycle.
    It exists for decks imported from elsewhere.

    Cheap decks cycle and chip, decks carrying a heavy tank save up and commit
    behind it, everything else plays reactively. It is a blunt rule on purpose:
    its job is to make opponents differ from each other, not to play well.
    """
    costs = [getattr(cards[name], "cost", 4) for name in deck if name in cards]
    average = sum(costs) / len(costs) if costs else 4.0
    if any(name in HEAVY_TANKS for name in deck):
        return "beatdown"
    if average <= 3.3:
        return "cycle"
    return "control"


def observed_decks() -> List[List[str]]:
    """Real ladder decks, most-played first, if they have been synced.

    Written by `scripts/sync_meta_decks.py` from public Path of Legends battle
    logs. The five hand-written archetypes below were always a stand-in - the
    module's own docstring calls them "archetypes rather than a live meta
    snapshot" - and five opponents is not a meta.
    """
    path = Path(__file__).resolve().parents[1] / "data" / "meta_decks.json"
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [list(deck) for deck in blob.get("decks", ()) if len(deck) == 8]


def deck_pool(cards: Dict[str, object],
              observed: bool = True) -> List[Tuple[str, str, List[str]]]:
    """(name, style, deck) for every deck this card data can actually build.

    Real observed decks first when they are available, then the hand-written
    archetypes for anything they do not cover. A deck naming a card the
    simulator cannot build is dropped rather than half-played, which is why
    this filters rather than trusting the file.
    """
    pool = []
    seen: set[tuple[str, ...]] = set()

    if observed:
        for index, deck in enumerate(observed_decks()):
            if any(card not in cards or cards[card] is None for card in deck):
                continue
            key = tuple(sorted(deck))
            if key in seen:
                continue
            seen.add(key)
            pool.append((f"ladder_{index:03d}", classify_style(cards, deck),
                         list(deck)))

    for name, style, deck in ARCHETYPES:
        if any(card not in cards or cards[card] is None for card in deck):
            continue
        key = tuple(sorted(deck))
        if key in seen:
            continue
        seen.add(key)
        pool.append((name, style or classify_style(cards, deck), list(deck)))
    return pool


def rejected(cards: Dict[str, object]) -> Dict[str, List[str]]:
    """Which archetypes were dropped and which cards were missing."""
    out = {}
    for name, _style, deck in ARCHETYPES:
        missing = [card for card in deck if card not in cards or cards[card] is None]
        if missing:
            out[name] = missing
    return out
