"""Does every champion and hero ability actually do something?

This is the check that would have caught Skeleton King, whose entire card is a
summon and whose ability `can_activate_ability` refused outright. Nothing else
could have: his hitpoints, damage, deploy time and skeletons were all correct,
so the card looked fine everywhere except in play.

The sweep is deliberately crude. Put the card down, put an enemy in front of
it, give it unlimited elixir, and ask whether the ability is offered and
accepted. A card that fails here is not necessarily wrong in detail - it is
inert, which is the failure this project keeps finding and keeps not noticing.

An enemy has to be on the board. Mega Minion Hero's warp resolves onto a
target and correctly refuses when there is nothing to warp to, so a sweep
against an empty arena reports it broken when it is behaving exactly right.
That was a false positive here before the enemy was added.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
FILLER = ["knight", "archers", "musketeer", "cannon",
          "skeletons", "giant", "hog_rider", "ice_golem"]

# Abilities declared in the client and not yet implemented. Empty as of the run
# that closed Balloon Hero and Super Hog Rider Terry - every champion and hero
# in the client now offers an ability and has it accepted.
#
# Keep the list and the strict xfail below rather than deleting them: the point
# is that a regression which makes an ability inert again shows up as a named
# card here, not as a card that quietly stops doing anything.
NOT_IMPLEMENTED: set[str] = set()


def _cards_with_abilities():
    return [name for name, card in sorted(CARDS.items())
            if card.unit is not None
            and (getattr(card.unit, "ability_cost", 0)
                 or getattr(card.unit, "ability_buff", ""))
            and (card.rarity == "Champion" or "hero" in name)]


ABILITY_CARDS = _cards_with_abilities()


def _activate(name: str):
    """Returns (offered, activated) with a real enemy on the board."""
    deck = [name] + [f for f in FILLER if f != name][:7]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()

    enemy = match.players[-1]
    enemy.hand[0] = "giant"
    enemy.elixir = 10_000
    assert match.play_card(-1, "giant", grid_to_point(9, 20, -1)), (
        "the enemy was never placed, so an ability needing a target has "
        "nothing to find and this sweep proves nothing")
    enemy.hand[0] = "skeletons"
    enemy.elixir = 10_000
    match.play_card(-1, "skeletons", grid_to_point(11, 22, -1))

    player = match.players[1]
    player.hand[0] = name
    player.elixir = 10_000
    assert match.play_card(1, name, grid_to_point(9, 22, 1)), f"{name} refused"
    for _ in range(80):
        match.step()

    unit = next((e for e in match.battle.entities.values()
                 if e.side == 1 and not e.is_tower), None)
    assert unit is not None, f"{name} never reached the board"
    player.elixir = 10_000
    offered = match.can_activate_ability(1, unit.uid)
    return offered, (match.activate_ability(1, unit.uid) if offered else False)


def test_there_are_champions_and_heroes_to_check():
    assert len(ABILITY_CARDS) > 15, ABILITY_CARDS


def test_no_ability_is_inert():
    """States the achievement rather than leaving it as an empty parametrise.

    With `NOT_IMPLEMENTED` empty the xfail below has no cases and pytest simply
    skips it, which reads the same whether every ability works or somebody
    deleted the list. This does not.
    """
    assert NOT_IMPLEMENTED == set(), (
        f"still inert: {sorted(NOT_IMPLEMENTED)}")


@pytest.mark.parametrize("card", [c for c in ABILITY_CARDS
                                  if c not in NOT_IMPLEMENTED])
def test_an_ability_is_offered_and_accepted(card):
    offered, activated = _activate(card)
    assert offered, (
        f"{card} was never offered its ability; if the loader found no "
        f"declared effect, read its ABILITY section - Skeleton King's whole "
        f"card was missing this way")
    assert activated, f"{card} was offered its ability and then refused it"


@pytest.mark.parametrize("card", sorted(NOT_IMPLEMENTED))
@pytest.mark.xfail(strict=True, reason="declared in the client, not implemented")
def test_the_known_gaps_are_still_gaps(card):
    """Strict, so implementing one of these fails here until it is removed.

    The point is that the list cannot quietly grow, and cannot quietly go
    stale either.
    """
    offered, activated = _activate(card)
    assert offered and activated
