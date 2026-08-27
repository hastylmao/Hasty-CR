"""Champion abilities fire once, and that is correct, however wrong it looks.

Everything about this reads like a bug. `ability_cooldown_ms` is a real field,
it is stored, it sets `ability_ready_at_ms` - and for every champion but one it
is zero, so a champion activates its ability once per deployment and never
again no matter how long it lives. The obvious reading is that somebody wired
half a mechanic and stopped.

It was checked, and the obvious reading is wrong. The August 2026 balance
changes (Season 86) made Hero and Champion abilities single-use, explicitly:
"Hero and Champion abilities will have their ability cooldowns updated just for
a single use from all abilities except Boss Bandit", affecting 8 of the 14
Heroes and 7 of the 8 Champions, with Goblinstein, Little Prince and Mighty
Miner given compensation buffs for living in a single-use world.

  https://royaleapi.com/blog/season-86-balance-wip-august-2026
  https://gamingonphone.com/news/clash-royale-august-2026-balance-changes-explained/

The cooldown numbers still on the wiki - Archer Queen 17s, Monk 17s, Skeleton
King 20s, Golden Knight 8s, Little Prince 30s, Mighty Miner 13s - are all
pre-August-2026 and would be wrong to implement today.

This file exists because the fix was written and had to be thrown away. Adding
a recharge is a one-line change, it makes the field look meaningful, and it
silently gives Boss Bandit unlimited Getaway Grenades. If a future balance
change brings cooldowns back, change these expectations deliberately and cite
it - do not let a plausible-looking cleanup do it by accident.
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

# Boss Bandit is the one exception the balance notes name: two Getaway Grenades
# separated by a three-second cooldown, not a charge that keeps coming back.
ACTIVATIONS = {
    "boss_bandit": 2,
    "archer_queen": 1,
    "golden_knight": 1,
    "skeleton_king": 1,
    "monk": 1,
    "little_prince": 1,
    "mighty_miner": 1,
}


def _activations_in(card: str, seconds: int) -> int:
    deck = [card] + [name for name in
                     ("knight", "archers", "musketeer", "cannon",
                      "skeletons", "giant", "hog_rider", "ice_golem")
                     if name != card][:7]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = card
    player.elixir = 10_000
    assert match.play_card(1, card, grid_to_point(9, 22, 1)), f"{card} was refused"
    for _ in range(60):
        match.step()
    champion = next((e for e in match.battle.entities.values()
                     if card.split("_")[0] in e.name), None)
    assert champion is not None, f"{card} never reached the board"

    used = 0
    for _ in range(int(seconds * 1000 / TICK_MS)):
        player.elixir = 10_000          # never the limiting factor
        if match.can_activate_ability(1, champion.uid):
            if match.activate_ability(1, champion.uid):
                used += 1
        match.step()
        if not champion.alive:
            break
    return used


@pytest.mark.parametrize("card,expected", sorted(ACTIVATIONS.items()))
def test_a_champion_gets_its_declared_number_of_activations(card, expected):
    """Forty-five seconds and unlimited elixir; only the rule stops them.

    Long enough that every pre-August-2026 cooldown - the longest was Little
    Prince at thirty seconds - would have produced a second activation.
    """
    used = _activations_in(card, seconds=45)
    assert used == expected, (
        f"{card} activated {used} times in 45 seconds against {expected}; "
        f"if a balance change restored ability cooldowns, update ACTIVATIONS "
        f"with the source, and check Boss Bandit did not become unlimited")


def test_the_party_cards_cooldown_is_read_but_not_applied():
    """`SuperHogJump` declares Cooldown 7000 in character_abilities.csv.

    It is the only ability in the client with a non-blank Cooldown besides
    Monk's party-mode MegaDeflect, which makes it the one place the single-use
    rule above might not hold. Super Hog Rider Terry is a party card and the
    August 2026 notes speak about ladder Heroes and Champions, so applying that
    7000 would be extending a rule past what the source says. It stays
    single-use until a party-mode reference states otherwise.
    """
    assert CARDS["super_hog_rider_terry"].unit.ability_cooldown_ms == 0
    assert _activations_in("super_hog_rider_terry", seconds=45) == 1


def test_boss_bandit_is_the_only_champion_with_a_cooldown():
    """Her two charges are what the cooldown field is for, and all it is for."""
    with_cooldown = {name for name, card in CARDS.items()
                     if card.unit is not None
                     and getattr(card.unit, "ability_cooldown_ms", 0) > 0}
    assert with_cooldown == {"boss_bandit"}, sorted(with_cooldown)
    assert CARDS["boss_bandit"].unit.ability_max_charges == 2
    assert CARDS["boss_bandit"].unit.ability_cooldown_ms == 3000


def test_her_two_grenades_are_separated_by_the_cooldown():
    """Not two in the same tick: the second waits out the three seconds."""
    assert _activations_in("boss_bandit", seconds=2) == 1
    assert _activations_in("boss_bandit", seconds=10) == 2
