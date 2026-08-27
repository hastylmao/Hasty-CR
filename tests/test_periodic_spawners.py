"""Does every declared periodic spawner actually produce its wave?

Huts, Tombstone and Witch are the familiar cases and they work. Two public
cards declare a spawner that produces nothing observable at all, and both fail
the same way, which is why they are pinned together.

Super Mini P.E.K.K.A declares `SpawnCharacter = SuperMiniPekkaPancakes`,
`SpawnNumber = 1`, `SpawnPauseTime = 3000`, `SpawnStartTime = 1000`. The
pancake is a `[BUILDING]` block with a `DeathAreaEffect` that heals - and no
`Hitpoints` field at all. The engine spawns it with zero hitpoints, so it is
dead the instant it exists, and its death area never fires: an injured ally
standing next to the card for thirty seconds heals nothing. Santa Hog Rider
declares the same shape with `SantaPresent`, whose buildings.csv row also
leaves Hitpoints empty and points at a boost pickup.

Both are real public cards - `super-mini-pekka` and `santa-hog-rider` are in
the RoyaleAPI snapshot - so this is a missing mechanic, not an internal row.

It is deliberately left unimplemented. Making the object persist, or firing its
death effect on arrival, are different mechanics with different balance, and
the shipped data does not say which: a pickup that waits to be walked over and
a bomb that goes off immediately both fit these fields. That is a question for
an observation, not for a guess. Remove the xfail when it is sourced.
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

SPAWNERS = sorted(
    name for name, card in CARDS.items()
    if card.unit is not None
    and str(getattr(card.unit, "spawn_character", "") or "")
    and int(getattr(card.unit, "spawn_pause_ms", 0) or 0) > 0)

# The two whose spawned object carries no hitpoints and no working effect.
INERT = {"super_mini_pekka", "super_hog_rider"}


@pytest.fixture(scope="module")
def lookup():
    match = Match(cards=CARDS, decks=(DECK, list(DECK)), seed=1, spells=SPELLS)
    return match.battle.unit_lookup


def _run(card, lookup, seconds=30):
    battle = Battle()
    battle.unit_lookup = lookup
    spawner = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    spawner.deploy_remaining_ms = 0
    ally = battle.add(make_unit(2, CARDS["knight"].unit, 1, Point(9100, 20000)))
    ally.deploy_remaining_ms = 0
    ally.hitpoints = ally.max_hitpoints // 2
    injured = ally.hitpoints
    for _ in range(int(seconds * 1000 / TICK_MS)):
        battle.step()
    # Settle before counting. An object spawned with zero hitpoints exists for
    # a fraction of a tick before it is reaped, and sampling on the wrong tick
    # counts that corpse as a wave.
    for _ in range(int(1000 / TICK_MS)):
        battle.step()
    produced = [entity for uid, entity in battle.entities.items()
                if uid not in (1, 2) and entity.alive]
    return {"spawned": produced, "healed": ally.hitpoints - injured,
            "areas": len(battle.areas)}


def test_there_are_spawners_to_check():
    assert len(SPAWNERS) > 10, len(SPAWNERS)


@pytest.mark.parametrize("card", [name for name in SPAWNERS if name not in INERT])
def test_a_spawner_produces_a_wave(card, lookup):
    result = _run(card, lookup)
    # Thirty seconds, because Barbarian Hut's SpawnPauseTime is 14000 and a
    # shorter window lands on its boundary.
    assert result["spawned"], f"{card} spawned nothing in thirty seconds"


@pytest.mark.parametrize("card", sorted(INERT))
@pytest.mark.xfail(strict=True, reason=(
    "Known gap: the spawned object has no Hitpoints in the shipped data, so "
    "the engine creates it already dead and its death effect never fires. "
    "Super Mini P.E.K.K.A's pancakes heal nothing; Santa Hog Rider's present "
    "does nothing. Both are real public cards. Whether the object should "
    "persist as a pickup or detonate on arrival is not answerable from these "
    "fields, so it is left for an observation rather than guessed."))
def test_the_inert_spawners_do_something(card, lookup):
    result = _run(card, lookup)
    assert result["spawned"] or result["healed"] or result["areas"], card


def test_the_inert_spawners_really_are_declared_spawners():
    """Guards the xfail from covering a card that simply has no spawner."""
    for card in INERT:
        unit = CARDS[card].unit
        assert str(getattr(unit, "spawn_character", "") or ""), card
        assert int(getattr(unit, "spawn_pause_ms", 0) or 0) > 0, card
