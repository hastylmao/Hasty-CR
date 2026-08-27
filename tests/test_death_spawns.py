"""Does every declared death spawn actually do something when the unit dies?

This is the documented failure that made a Golem leave nothing behind: Golemite,
BalloonBomb and LavaPups have no `spells` row, so every lookup for them failed
and the spawn was skipped silently. It looked like a balance question rather
than a missing card.

The invariant is deliberately "something happens", not "an entity appears".
Twenty-two cards declare a death spawn and four of them - Balloon, Hero
Balloon, Bomb Tower, Giant Skeleton - name a bomb, which the engine resolves as
delayed death damage rather than a unit that stands around. Asserting an entity
would fail on all four while the mechanic works correctly, which is a worse
test than none.
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

DECLARED = sorted(
    name for name, card in CARDS.items()
    if card.unit is not None
    and str(getattr(card.unit, "death_spawn_character", "") or ""))


@pytest.fixture(scope="module")
def lookup():
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    return match.battle.unit_lookup


def test_there_are_death_spawns_to_check():
    assert len(DECLARED) > 15, len(DECLARED)


@pytest.mark.parametrize("card", DECLARED)
def test_a_declared_death_spawn_leaves_something_behind(card, lookup):
    """Either a unit or damage - both are real answers, silence is not."""
    battle = Battle()
    battle.unit_lookup = lookup
    dying = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    dying.deploy_remaining_ms = 0
    victim = battle.add(make_unit(2, CARDS["knight"].unit, -1,
                                  Point(9200, 20000)))
    victim.deploy_remaining_ms = 0
    victim.damage = 0                       # let it stand still and be hit
    before_hp = victim.hitpoints
    known = {1, 2}

    dying.hitpoints = 0
    for _ in range(int(5 * 1000 / TICK_MS)):
        battle.step()

    spawned = [entity for uid, entity in battle.entities.items()
               if uid not in known]
    damaged = before_hp - victim.hitpoints
    assert spawned or damaged > 0, (
        f"{card} declares death spawn "
        f"{CARDS[card].unit.death_spawn_character!r} and neither spawned a "
        f"unit nor dealt damage")


def test_the_bombs_resolve_as_damage_rather_than_a_unit(lookup):
    """Pins the shape, so a change from damage to a unit is noticed.

    If one of these ever starts spawning a real entity it is a mechanic
    change, not a detail - the bomb would become targetable.
    """
    for card in ("balloon", "giant_skeleton", "bomb_tower"):
        battle = Battle()
        battle.unit_lookup = lookup
        dying = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
        dying.deploy_remaining_ms = 0
        victim = battle.add(make_unit(2, CARDS["knight"].unit, -1,
                                      Point(9200, 20000)))
        victim.deploy_remaining_ms = 0
        victim.damage = 0
        before_hp = victim.hitpoints
        dying.hitpoints = 0
        for _ in range(int(5 * 1000 / TICK_MS)):
            battle.step()
        assert before_hp - victim.hitpoints > 0, card
        assert not [uid for uid in battle.entities if uid not in (1, 2)], card
