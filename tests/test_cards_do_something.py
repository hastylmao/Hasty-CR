"""Does every playable card actually change the battle?

The widest net in the suite. `test_every_card_plays.py` asserts a card deploys
without raising; this asserts it *does* something - damage lands, a unit
appears, an area is created, or hitpoints move somewhere. A card that deploys
cleanly and then has no effect is the failure mode that cost this project the
most: twenty-five shooters were firing and dealing nothing at once, and every
test passed throughout.

Writing it took three attempts, all of them harness bugs that looked exactly
like engine bugs:

  * spells cast into our own half, where there is nothing to hit - reported as
    thirteen broken spells
  * the enemy unit placed at a grid coordinate that mirrors into *our* half,
    which `play_card` correctly refuses - reported as twelve broken spells
  * the enemy unit not in the enemy's hand, so the placement silently failed

Hence the assertions on the setup itself: a sweep that quietly tests nothing is
worse than no sweep, because it reads as evidence.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import TICK_MS, deploy_area_ok                   # noqa: E402
from sim.deck_builder import playable_public_cards              # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
POOL = sorted(playable_public_cards(CARDS, SPELLS))
FILLER = ["knight", "archers", "musketeer", "cannon",
          "skeletons", "giant", "hog_rider", "ice_golem"]

# Super Archers has no damage in any source; see test_ranged_damage.py.
NO_DECLARED_EFFECT = {"super_archer"}

# Cards that act on our own side, so they must be aimed at our unit.
ALLY_TARGETED = {"clone", "rage", "heal_spirit", "heal"}

# Routed as spells but they put a body on the board, so they follow the troop
# rule and go down on our half. Mirror replays whatever we last played; Royal
# Delivery drops a Recruit under its crate.
PLACES_A_UNIT = {"mirror", "royal_delivery"}


def _state(battle):
    alive = [e for e in battle.entities.values() if e.alive]
    return (len(battle.damage_log), len(alive), len(battle.areas),
            sum(e.hitpoints for e in alive))


def test_the_setup_places_both_sides():
    """Guards the sweep from passing because nothing was ever on the field."""
    point = grid_to_point(9, 20, -1)
    assert deploy_area_ok(point, -1), point
    assert deploy_area_ok(grid_to_point(9, 22, 1), 1)


@pytest.mark.parametrize("card", [c for c in POOL if c not in NO_DECLARED_EFFECT])
def test_a_card_changes_the_battle(card):
    deck = [card] + [name for name in FILLER if name != card][:7]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()

    enemy = match.players[-1]
    enemy.hand[0] = "skeletons"
    enemy.elixir = 10_000
    assert match.play_card(-1, "skeletons", grid_to_point(9, 20, -1)), (
        "the enemy unit was never placed, so there is nothing to act on")

    ours = match.players[1]
    ours.hand[0] = "knight"
    ours.elixir = 10_000
    match.play_card(1, "knight", grid_to_point(9, 22, 1))
    for _ in range(30):
        match.step()

    foes = [e for e in match.battle.entities.values()
            if e.alive and e.side == -1 and not e.is_tower]
    friends = [e for e in match.battle.entities.values()
               if e.alive and e.side == 1 and not e.is_tower]
    assert foes, "the enemy unit died before the card was played"

    # Only a spell may be aimed into the enemy half; a troop or building has to
    # go down on our own side, which is the game's rule and not a limitation of
    # the harness. Aiming everything at the enemy made ninety-nine cards look
    # broken when they were simply being refused.
    if card in PLACES_A_UNIT:
        aim = grid_to_point(9, 21, 1)
    elif CARDS[card].unit is None or card in SPELLS:
        aim = (friends or foes)[0].pos if card in ALLY_TARGETED else foes[0].pos
    else:
        aim = grid_to_point(9, 21, 1)

    ours.hand[0] = card
    ours.elixir = 10_000
    before = _state(match.battle)
    assert match.play_card(1, card, aim), f"{card} was refused at {aim}"
    for _ in range(int(12 * 1000 / TICK_MS)):
        match.step()

    assert _state(match.battle) != before, (
        f"{card} deployed and changed nothing in twelve seconds")
