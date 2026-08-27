"""Nothing to attack is not the same as nowhere to go.

Reported from the viewer as units standing around doing nothing. A sweep for
"alive, no target, and has not moved in six seconds" found 55 such observations
across twelve matches, every one of them a Fire Spirit frozen a stride past the
bridge.

The cause is an ordering bug in target acquisition. The movement fallback - the
nearest enemy building, which is what makes a Hog Rider walk at a tower instead
of standing still - is chosen *inside* the candidate loop, after
`is_valid_target` has already rejected the candidate:

    if not entity.is_valid_target(other, now_ms):
        continue                      # towers rejected here for spirits
    ...
    if other.is_building and ...:     # never reached
        fallback = other

The spirits carry `cannot_target_towers`, so `is_valid_target` throws out every
tower, so the fallback stays empty, so `target_uid` is None - and `_move` reads
`target_uid` for its destination. The unit stops where it stands.

The rule is real: a spirit cannot connect to a crown tower on its own. But it
is about *connecting*, not about pathing - in the game it still walks at the
tower. So the fix is a separate `walk_target_uid` that only `_move` reads,
leaving `target_uid` None so `_attack` still refuses. Both halves are checked
here, because a fix that let spirits hit towers would be worse than the freeze.
"""

import random
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import MT, Point, TICK_MS, distance                # noqa: E402
from sim.deck_builder import random_public_deck                   # noqa: E402
from sim.engine import Battle                                     # noqa: E402
from sim.entities import make_unit                                # noqa: E402
from sim.gamedata import load_gamedata                            # noqa: E402
from sim.match import Match                                       # noqa: E402
from sim.meta_decks import classify_style                         # noqa: E402
from sim.opponents import ScriptedOpponent                        # noqa: E402
from sim.runner import DECK_26, resolve_deck                      # noqa: E402
from sim.spells import load_spells                                # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)

# Every card the client bars from crown towers.
BARRED = sorted(name for name, card in CARDS.items()
                if card.unit is not None
                and getattr(card.unit, "cannot_target_towers", False))


def test_there_are_barred_cards_to_check():
    assert BARRED, "no card carries cannot_target_towers"


@pytest.mark.parametrize("card", BARRED)
def test_a_barred_unit_still_advances_on_a_tower(card):
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    tower = battle.add(make_unit(2, CARDS["cannon"].unit, -1, Point(9000, 12000)))
    tower.deploy_remaining_ms = 0
    tower.is_tower = True
    tower.damage = 0

    start = unit.pos
    for _ in range(int(15 * 1000 / TICK_MS)):
        battle.step()
        if not unit.alive:
            break
    moved = distance(start, unit.pos) / MT
    assert moved > 2, f"{card} moved {moved:.1f} tiles with a tower to walk at"


@pytest.mark.parametrize("card", BARRED)
def test_a_barred_unit_still_cannot_hurt_that_tower(card):
    """The half that matters more: walking there must not let it connect."""
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    tower = battle.add(make_unit(2, CARDS["cannon"].unit, -1, Point(9000, 12000)))
    tower.deploy_remaining_ms = 0
    tower.is_tower = True
    tower.damage = 0

    before = tower.hitpoints
    for _ in range(int(15 * 1000 / TICK_MS)):
        battle.step()
        if not unit.alive:
            break
    assert tower.hitpoints == before, (
        f"{card} is barred from crown towers and dealt "
        f"{before - tower.hitpoints}")
    assert unit.target_uid is None, (
        f"{card} acquired the tower as an attack target")


def test_a_barred_unit_still_prefers_a_real_target():
    """The walk destination must not outrank something it can actually fight."""
    battle = Battle()
    spirit = battle.add(make_unit(1, CARDS[BARRED[0]].unit, 1, Point(9000, 20000)))
    spirit.deploy_remaining_ms = 0
    knight = battle.add(make_unit(2, CARDS["knight"].unit, -1, Point(9000, 19000)))
    knight.deploy_remaining_ms = 0
    knight.speed_mt_per_sec = 0
    battle.add(make_unit(3, CARDS["cannon"].unit, -1, Point(9000, 12000)))

    for _ in range(20):
        battle.step()
        if not spirit.alive:
            return
    assert spirit.target_uid == knight.uid, (
        "it walked at the tower instead of fighting what was in front of it")


def test_no_unit_freezes_across_a_batch_of_matches():
    """The sweep that found this, kept as the regression.

    Six seconds standing still with nothing to attack is not a slow unit, it is
    a unit with no destination.
    """
    full = load_gamedata(11)
    rng = random.Random(7)
    stuck: Counter = Counter()
    for index in range(6):
        top = random_public_deck(full, SPELLS, rng)
        cards = resolve_deck(full, sorted(set(DECK_26) | set(top)))
        match = Match(cards=cards, decks=(list(DECK_26), top),
                      seed=index, spells=SPELLS)
        opponent = ScriptedOpponent(cards, side=-1, deck=top,
                                    style=classify_style(full, top), seed=index)
        opponent.reset()
        last: dict = {}
        tick = 0
        while not match.finished and tick < 4000:
            match.step()
            tick += 1
            if tick % 10 == 0:
                opponent.act(match)
            if tick % 4:
                continue
            for entity in match.battle.entities.values():
                if (not entity.alive or entity.is_tower or entity.is_building
                        or entity.deploy_remaining_ms > 0):
                    continue
                seen = last.get(entity.uid)
                if seen is None or distance(seen[0], entity.pos) > 60:
                    last[entity.uid] = (entity.pos, tick)
                elif (tick - seen[1]) * TICK_MS > 6000 and entity.target_uid is None:
                    # Arrived is not stuck. A unit that walked to its
                    # destination and has nothing it may attack is behaving
                    # correctly - Ram Rider's rider is `target_only_troops`, so
                    # once the enemy troops are gone it stands at the tower with
                    # genuinely nothing to do. What this is looking for is a
                    # unit with somewhere to be that is not getting there.
                    destination = match.battle.get(entity.walk_target_uid)
                    arrived = (destination is not None
                               and distance(entity.pos, destination.pos)
                               <= entity.range_mt + destination.collision_radius_mt)
                    if not arrived:
                        stuck[entity.name] += 1
                    last[entity.uid] = (entity.pos, tick)
    assert not stuck, f"units frozen with nothing to attack: {dict(stuck)}"


# --------------------------------------------------------------------------
# The second freeze, reported from the viewer as units piling up at our own
# king tower. Different cause from the spirits above and a worse one: these
# units had a target, were in MOVING state, and stepped their full distance
# every single tick - while covering 0.08 tiles in six seconds.
#
# `_avoid_buildings` recomputed which way to go round an obstacle on every
# tick. A unit directly behind a building has both perpendiculars exactly
# sideways to where it wants to go, so both dot products are zero, the
# tie-break picks one, the unit shifts a little, the sign flips, and it shifts
# back. It is not stuck in the sense of not moving - it is moving hard and
# going nowhere, which is why "did it move" never caught it.
# --------------------------------------------------------------------------


def test_a_unit_behind_the_king_tower_gets_round_it():
    """The exact reproduction: a skeleton between our king tower and the wall."""
    from sim import arena
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck

    cards = resolve_deck(CARDS, DECK_26)
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)),
                  seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()

    start = Point(arena.ALLY_KING.x, arena.ALLY_KING.y + 1900)
    unit = match.battle.add(make_unit(0, cards["skeletons"].unit, 1, start))
    unit.deploy_remaining_ms = 0
    for _ in range(int(8 * 1000 / TICK_MS)):
        match.step()
        if not unit.alive:
            pytest.skip("it died before it could get anywhere")
    travelled = distance(start, unit.pos) / MT
    assert travelled > 5, (
        f"it covered {travelled:.2f} tiles in eight seconds; trapped behind "
        f"the king tower")


def test_the_chosen_side_is_held_until_the_building_is_cleared():
    """Hysteresis is the fix; without it the choice flips every tick."""
    from sim import arena
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck

    cards = resolve_deck(CARDS, DECK_26)
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)),
                  seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    start = Point(arena.ALLY_KING.x, arena.ALLY_KING.y + 1900)
    unit = match.battle.add(make_unit(0, cards["skeletons"].unit, 1, start))
    unit.deploy_remaining_ms = 0

    turns = set()
    for _ in range(int(3 * 1000 / TICK_MS)):
        match.step()
        if not unit.alive:
            break
        if unit.avoid_turn:
            turns.add(unit.avoid_turn)
    assert len(turns) <= 1, (
        f"it changed its mind about which way to go round: {turns}")


# Not asserted here: that a crowd splits around a building rather than all
# going the same way. They do all go the same way, and that is correct - they
# are following one flow field, so a queue rounding a tower on the same side is
# what the real game shows too. The tie-break on unit identity only decides the
# dead-astern case, which the flow field rarely produces.
