"""Can anything that is not a real card end up in a deck?

One of this project's standing rules is that internal-only rows such as
`warm_spell` or `tri_wizards` are not cards, and the public snapshot is the
allowlist. That rule exists because the client ships plenty of rows that parse
perfectly and are not playable: party-mode skins, hero-form spells, the global
effects behind tower activation, and scenario NPCs.

Several of them do resolve as spells, and should - the engine needs their
definitions to run the effects they belong to. What must never happen is one of
them reaching a deck, where it would spend elixir on a card no opponent can
have and quietly make every measured result about a game nobody plays.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.card_catalog_audit import report as catalog_report     # noqa: E402
from sim.deck_builder import playable_public_cards              # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
POOL = set(playable_public_cards(CARDS, SPELLS))

# The pool holds the simulator's internal names and the snapshot holds public
# ones - `axe_man` against `executioner`. `card_catalog_audit` already bridges
# the two through the client's own `sc_key`, so the comparison is made there
# rather than by matching strings and hoping.
PUBLIC_LOCAL = set(catalog_report()["mapped"].values())

# Rows that parse but are not cards. Each is here because it was seen resolving.
INTERNAL_ONLY = ["merge_maiden", "tri_wizards", "warm_spell",
                 "goblin_party_rocket", "global_clone", "global_lightning",
                 "barb_log_hero"]


def test_no_internal_only_row_can_be_put_in_a_deck():
    deckable = [name for name in INTERNAL_ONLY if name in POOL]
    assert not deckable, deckable


def test_every_playable_card_is_public_by_snapshot_or_by_ladder_evidence():
    """The snapshot alone is no longer the gate, because it is stale.

    RoyaleAPI's catalogue carries 120 cards and none of the 2026 additions, so
    gating on it excluded Ronin - present in roughly a tenth of real Path of
    Legends decks - along with Vines, Boss Bandit, Berserker, Goblin
    Demolisher, Suspicious Bush, Goblin Curse, Little Prince and Goblinstein.
    All were in the client data and all already worked.

    A card now qualifies either by being in the snapshot or by having been
    observed in real ladder play, which is the stronger evidence of the two.
    Anything qualifying by neither is a stray and still fails here.

    Mirror is the standing exception: a rule rather than a card, carrying no
    stats, so it never matches a snapshot key by lookup.
    """
    from sim.deck_builder import ladder_cards

    evidenced = PUBLIC_LOCAL | ladder_cards() | {"mirror"}
    strays = sorted(name for name in POOL if name not in evidenced)
    assert not strays, strays


def test_the_pool_did_not_collapse():
    """Guards the two tests above from passing by having nothing to check."""
    assert len(POOL) > 110, len(POOL)
