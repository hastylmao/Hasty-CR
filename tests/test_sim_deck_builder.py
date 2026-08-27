import random

from sim.deck_builder import playable_public_cards, random_public_deck
from sim.gamedata import load_gamedata
from sim.spells import load_spells


def test_random_public_deck_is_unique_reproducible_and_resolvable():
    cards, spells = load_gamedata(), load_spells()
    first = random_public_deck(cards, spells, random.Random(12))
    second = random_public_deck(cards, spells, random.Random(12))
    assert first == second
    assert len(first) == len(set(first)) == 8
    assert set(first) <= set(playable_public_cards(cards, spells))


def test_public_deck_pool_includes_mirror_but_excludes_quarantined_party_rocket():
    pool = playable_public_cards(load_gamedata(), load_spells())
    assert "mirror" in pool
    assert "goblin_party_rocket" not in pool
    # 119 from the published snapshot, plus twelve the snapshot cannot map -
    # ten it is too old to list (Ronin and friends) and two that ship under a
    # codename it would never match: Rune Giant as `giant_buffer`, Spirit
    # Empress as `merge_maiden__normal`. Not a floor: a change either way
    # should be looked at, because it means the snapshot moved or the
    # observed-deck sync did.
    assert len(pool) == 131, len(pool)
