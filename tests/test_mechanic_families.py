"""Do the declared mechanic families still actually fire?

Each family here is implemented and has focused tests elsewhere. What is missing
is the sweep: a card that quietly stops shielding, or expiring, or vanishing,
looks exactly like a card that never had the mechanic. That is how Golemite
disappeared, and how the Furnace ended up walking - in both cases the field was
parsed correctly and nothing read it.

These check every card that declares a family, not a chosen example, so adding
a card to the catalogue puts it under test without anyone remembering to.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import Point, TICK_MS                            # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
DECK = ["knight", "archers", "fireball", "musketeer",
        "cannon", "skeletons", "zap", "giant"]


def _units(field: str):
    return sorted(name for name, card in CARDS.items()
                  if card.unit is not None
                  and int(getattr(card.unit, field, 0) or 0) > 0)


SHIELDED = _units("shield_hitpoints")
TIMED = _units("lifetime_ms")
VANISHING = _units("invisible_after_ms")

# Hero Knight is the documented exception: its starting action clears the
# shield it inherits, and its ability restores the declared percentage. So it
# declares shield hitpoints and correctly deploys without them.
NO_SHIELD_ON_DEPLOY = {"knight_hero"}


@pytest.fixture(scope="module")
def lookup():
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    return match.battle.unit_lookup


def _spawn(card, lookup):
    battle = Battle()
    battle.unit_lookup = lookup
    entity = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    entity.deploy_remaining_ms = 0
    return battle, entity


def test_each_family_has_members():
    assert len(SHIELDED) >= 5, SHIELDED
    assert len(TIMED) >= 10, len(TIMED)
    assert VANISHING, VANISHING


@pytest.mark.parametrize("card", [n for n in SHIELDED
                                  if n not in NO_SHIELD_ON_DEPLOY])
def test_a_shielded_unit_deploys_with_its_shield(card, lookup):
    _, entity = _spawn(card, lookup)
    assert entity.shield_hitpoints > 0, card


@pytest.mark.parametrize("card", sorted(NO_SHIELD_ON_DEPLOY))
def test_hero_knight_deploys_without_the_shield_it_declares(card):
    """The exception, asserted so it stays deliberate.

    If `initial_shield_pct` stops being zero this is a mechanic change, not a
    detail, and the exemption above would start hiding it.
    """
    unit = CARDS[card].unit
    assert unit.shield_hitpoints > 0, card
    assert int(getattr(unit, "initial_shield_pct", 100) or 0) == 0, card


@pytest.mark.parametrize("card", TIMED)
def test_a_timed_unit_expires_on_schedule(card, lookup):
    """It must die, and not before its lifetime is up."""
    lifetime = int(CARDS[card].unit.lifetime_ms)
    battle, entity = _spawn(card, lookup)
    halfway = max(1, int((lifetime // 2) / TICK_MS))
    for _ in range(halfway):
        battle.step()
    assert entity.alive, f"{card} died before its {lifetime}ms lifetime"
    for _ in range(int((lifetime + 3000) / TICK_MS)):
        battle.step()
    assert not entity.alive, f"{card} outlived its {lifetime}ms lifetime"


@pytest.mark.parametrize("card", VANISHING)
def test_a_vanishing_unit_becomes_invisible(card, lookup):
    delay = int(CARDS[card].unit.invisible_after_ms)
    battle, entity = _spawn(card, lookup)
    assert not entity.invisible(battle.now_ms), f"{card} starts invisible"
    for _ in range(int((delay + 500) / TICK_MS)):
        battle.step()
    assert entity.invisible(battle.now_ms), (
        f"{card} declares invisible_after_ms={delay} and never vanished")
