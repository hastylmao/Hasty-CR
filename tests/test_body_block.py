"""A body-block costs a push time; it does not end it.

Found by watching the bot play a person. It kept answering a Hog Rider with an
Ice Golem, which does nothing in the real game - and in here was a *perfect*
answer. Measured before the fix, a Hog that reaches a tower in 4.6 seconds
never arrived at all against a single Skeleton, Ice Golem or Musketeer. One
elixir permanently stopped a win condition.

The cause was that separation pushes purely along the line between two
centres. Head-on, that line is the direction of travel, so the unit stepped
forward and was shoved back by the same amount every tick, and the pair
settled into a stable standstill. No amount of tuning the push fixes it: the
geometry is degenerate, there is no sideways to slide along.

The fix is steering, in the same place and the same shape as the existing
building avoidance - a unit walks *around* an enemy it is not allowed to
attack. A unit that can attack its blocker still stops and fights, so the
asymmetry falls out on its own: a Skeleton holds its ground against a Hog and
the Hog rounds it.

This matters beyond looking right. Every policy trained before the fix learned
to defend with cheap bodies, because in here that beat everything.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena                                            # noqa: E402
from sim.engine import Battle                                    # noqa: E402
from sim.entities import make_tower, make_unit                   # noqa: E402
from sim.gamedata import load_gamedata                           # noqa: E402

from sim.runner import DECK_26, resolve_deck                     # noqa: E402

# Through `resolve_deck`, not the raw table: the loader does not key
# everything under the name this project plays it as - `ice_golem` is simply
# absent from it - and `ClashEnv` resolves the same way.
WANTED = sorted(set(DECK_26) | {"knight", "giant", "battle_ram", "archers"})
CARDS = resolve_deck(load_gamedata(level=11), WANTED)
PRINCESS = (3052, 109, 800, 7500)


def playable(name: str) -> bool:
    spec = CARDS.get(name)
    return spec is not None and getattr(spec, "unit", None) is not None


def seconds_to_connect(attacker: str, blocker: str | None,
                       limit_s: float = 30.0) -> float | None:
    """When the attacker first damages our tower, or None if it never does."""
    battle = Battle()
    tower = battle.add(make_tower(100, 1, arena.ALLY_PRINCESS["right"], *PRINCESS))
    unit = battle.add(make_unit(1, CARDS[attacker].unit, -1, arena.tile(14, 13)))
    unit.deploy_remaining_ms = 0
    if blocker:
        body = battle.add(make_unit(2, CARDS[blocker].unit, 1, arena.tile(14, 18)))
        body.deploy_remaining_ms = 0
    start = tower.hitpoints
    for tick in range(int(limit_s * 20)):
        battle.step()
        if tower.hitpoints < start:
            return tick * 0.05
    return None


@pytest.fixture(scope="module")
def unopposed() -> float:
    plain = seconds_to_connect("hog_rider", None)
    assert plain is not None, "a hog with nothing in its way must reach the tower"
    return plain


@pytest.mark.parametrize("blocker", ["skeletons", "ice_golem", "musketeer",
                                     "knight"])
def test_a_cheap_body_never_stops_a_hog_outright(blocker, unopposed):
    """Each of these blocked it for ever before the steering fix."""
    reached = seconds_to_connect("hog_rider", blocker)
    assert reached is not None, (
        f"a single {blocker} stopped a Hog Rider permanently - the deadlock is back")
    delay = reached - unopposed
    assert delay < 3.0, f"{blocker} delayed the hog by {delay:.1f}s, which is a stop"


@pytest.mark.parametrize("blocker", ["skeletons", "ice_golem", "musketeer"])
def test_but_it_does_cost_the_push_something(blocker, unopposed):
    """Walking through a body must not be free either."""
    reached = seconds_to_connect("hog_rider", blocker)
    assert reached - unopposed > 0.05, (
        f"{blocker} cost the hog nothing at all; a shove should take time")


def test_a_building_still_stops_a_building_targeter():
    """The Cannon is the actual answer, and has to keep working."""
    assert seconds_to_connect("hog_rider", "cannon") is None, (
        "a Cannon must hold a Hog Rider - that is the card")


@pytest.mark.parametrize("attacker", ["knight", "musketeer"])
def test_a_unit_that_can_fight_its_blocker_stops_and_fights(attacker):
    """Steering must not turn every melee trade into a walk-past."""
    assert CARDS[attacker].unit.target_only_buildings is False
    assert seconds_to_connect(attacker, "knight") is None, (
        f"{attacker} walked around a knight instead of fighting it")


@pytest.mark.parametrize("card", ["hog_rider", "giant"])
def test_every_building_targeter_rounds_a_body_it_cannot_hit(card):
    """Not a Hog quirk: it is the class of win conditions."""
    assert CARDS[card].unit.target_only_buildings
    plain = seconds_to_connect(card, None, limit_s=40.0)
    blocked = seconds_to_connect(card, "knight", limit_s=40.0)
    assert plain is not None and blocked is not None, (
        f"{card} was stopped permanently by a knight")


@pytest.mark.xfail(reason="charging units are not steered yet - Battle Ram "
                          "carries charge_speed_multiplier 200 and is still "
                          "held permanently by a single Knight. Out of scope "
                          "for the 2.6 deck, which has no charging card, but "
                          "it is the same deadlock and Prince, Dark Prince "
                          "and Ram Rider will share it",
                   strict=True)
def test_a_charging_unit_is_also_not_stopped_for_ever():
    plain = seconds_to_connect("battle_ram", None, limit_s=40.0)
    blocked = seconds_to_connect("battle_ram", "knight", limit_s=40.0)
    assert plain is not None and blocked is not None


def test_the_blocker_is_not_damaged_by_a_unit_that_cannot_target_it():
    """It is walked around, not chewed through - the rule is targeting."""
    battle = Battle()
    battle.add(make_tower(100, 1, arena.ALLY_PRINCESS["right"], *PRINCESS))
    hog = battle.add(make_unit(1, CARDS["hog_rider"].unit, -1, arena.tile(14, 13)))
    hog.deploy_remaining_ms = 0
    body = battle.add(make_unit(2, CARDS["ice_golem"].unit, 1, arena.tile(14, 18)))
    body.deploy_remaining_ms = 0
    full = body.hitpoints
    for _ in range(120):
        battle.step()
    assert body.hitpoints == full, "the hog attacked something it cannot target"
