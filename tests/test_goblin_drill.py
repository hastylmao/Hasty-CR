"""Goblin Drill: the burst when it surfaces, and the evolution's relocation.

Two separate holes, found together.

The drill declares `SpawnAreaObject = "GoblinDrillDamage"` - 33 damage in a
two-tile radius with a pushback, and `CrownTowerDamagePercent = -100` so it
cannot touch a crown tower. The loader read the *indirect* form of that
declaration, where an area names the action that spawns a character, and never
the direct one where a character names its area outright. So the drill surfaced
in silence and the swarm it was dropped on took nothing.

It is worse than one card, because a burrower is two rows: the digging form the
card actually places (`CHARACTER.GoblinDrillDig`) and what it becomes when it
arrives (`BUILDING.GoblinDrill`, named by `SpawnPathfindMorph`). The damage is
declared on the second and the simulator instantiates the first.

Fixing the direct form also caught Electro Wizard and Ice Wizard, whose deploy
shocks declare the same `-100` and were dealing full damage to crown towers - a
free hit on a very common play.

The evolution's relocation was a listed calibration gate, "submerge relocation
path, emergence displacement and collision". Almost all of it is declared on
`ActionGoblinDrillEvoRelocate`: `HideHpThresholds = [66, 33]`, `HideTime =
1000`, and two `HideActions` groups leaving two goblins behind and then one.
Only the destination is not, and the published behaviour supplies it - the
drill resurfaces where it was, unless it was placed beside a crown tower, in
which case it comes up ninety degrees around that tower.

  https://clashroyale.fandom.com/wiki/Goblin_Drill/Evolution

The one number nothing states is how close counts as "beside", which is why it
sits named as `Battle.DRILL_TOWER_REACH_MT` rather than buried in a condition.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena                                           # noqa: E402
from sim.arena import MT, Point, TICK_MS, distance              # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_characters, load_gamedata         # noqa: E402

CARDS = load_gamedata(level=11)
TABLE = load_characters(11)
DRILLS = ["goblin_drill", "goblin_drill_ev1"]


# ---------------------------------------------------------------- surfacing

@pytest.mark.parametrize("card", DRILLS)
def test_the_emergence_burst_is_read(card):
    unit = CARDS[card].unit
    assert unit.spawn_area_damage > 0, "the drill surfaces dealing nothing"
    assert unit.spawn_area_radius_mt == 2000
    assert unit.spawn_area_tower_percent == 0


@pytest.mark.parametrize("card", DRILLS)
def test_surfacing_clears_a_swarm_standing_on_it(card):
    battle = Battle()
    drill = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    drill.deploy_remaining_ms = 400
    swarm = []
    for index in range(4):
        skeleton = battle.add(make_unit(10 + index, CARDS["skeletons"].unit, -1,
                                        Point(9500 + index * 300, 20500)))
        skeleton.deploy_remaining_ms = 0
        skeleton.speed_mt_per_sec = 0
        skeleton.damage = 0
        swarm.append(skeleton)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    assert not any(s.alive for s in swarm), "the burst left the swarm standing"


@pytest.mark.parametrize("card", DRILLS)
def test_the_burst_does_not_reach_across_the_arena(card):
    battle = Battle()
    drill = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    drill.deploy_remaining_ms = 400
    far = battle.add(make_unit(9, CARDS["skeletons"].unit, -1, Point(9000, 24000)))
    far.deploy_remaining_ms = 0
    far.speed_mt_per_sec = 0
    far.damage = 0
    before = far.hitpoints
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    assert far.hitpoints == before


@pytest.mark.parametrize("card", DRILLS + ["electro_wizard", "ice_wizard"])
def test_a_deploy_burst_declared_minus_100_cannot_touch_a_crown_tower(card):
    """All four declare `CrownTowerDamagePercent = -100` and all four ignored it.

    Electro Wizard deploy-zapping a tower is a routine play, and it was worth
    free tower damage the game does not give.
    """
    assert CARDS[card].unit.spawn_area_tower_percent == 0
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 400
    tower = battle.add(make_unit(9, CARDS["cannon"].unit, -1, Point(9500, 20500)))
    tower.deploy_remaining_ms = 0
    tower.damage = 0
    tower.is_tower = True
    before = tower.hitpoints
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    assert tower.hitpoints == before, (
        f"{card} put {before - tower.hitpoints} into a crown tower its own "
        f"data forbids it from damaging")


# --------------------------------------------------------------- relocation

def test_only_the_evolution_relocates():
    relocating = {name for name, card in CARDS.items()
                  if card.unit is not None
                  and getattr(card.unit, "hide_hp_thresholds", ())}
    assert relocating == {"goblin_drill_ev1"}, sorted(relocating)


def test_the_declared_relocation_numbers_are_read():
    unit = CARDS["goblin_drill_ev1"].unit
    assert unit.hide_hp_thresholds == (66, 33)
    assert unit.hide_time_ms == 1000
    # Two goblins from the first hide group, one from the second.
    assert unit.hide_goblin_counts == (2, 1)
    assert unit.hide_spawn_character == "Goblin"


def _drill_under_fire(card, pos, seconds=25):
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    drill = battle.add(make_unit(1, CARDS[card].unit, 1, pos))
    drill.deploy_remaining_ms = 0
    shooter = battle.add(make_unit(2, CARDS["musketeer"].unit, -1,
                                   Point(pos.x + 3000, pos.y)))
    shooter.deploy_remaining_ms = 0
    shooter.speed_mt_per_sec = 0

    # The relocation happens inside the same step that starts the hide, so the
    # position has to be taken before stepping or the jump is invisible.
    jumps, goblins = [], 0
    for _ in range(int(seconds * 1000 / TICK_MS)):
        before_hides, before_pos = drill.hides_used, drill.pos
        battle.step()
        if not drill.alive:
            break
        if drill.hides_used > before_hides:
            jumps.append(distance(before_pos, drill.pos))
        goblins = max(goblins, len([e for e in battle.entities.values()
                                    if e.name == "goblin"]))
    return drill, jumps, goblins


def test_it_goes_under_exactly_twice_and_leaves_goblins():
    drill, _jumps, goblins = _drill_under_fire("goblin_drill_ev1",
                                               Point(9000, 20000))
    assert drill.hides_used == 2, (
        f"it hid {drill.hides_used} times against two declared thresholds")
    assert goblins > 0, "no goblins were left behind"


def test_the_base_drill_never_goes_under():
    drill, _jumps, goblins = _drill_under_fire("goblin_drill", Point(9000, 20000))
    assert drill.hides_used == 0
    assert goblins == 0


def test_it_is_unreachable_while_it_is_under():
    """A second under is a second of not being shot, which is the point."""
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    drill = battle.add(make_unit(1, CARDS["goblin_drill_ev1"].unit, 1,
                                 Point(9000, 20000)))
    drill.deploy_remaining_ms = 0
    shooter = battle.add(make_unit(2, CARDS["musketeer"].unit, -1,
                                   Point(12000, 20000)))
    shooter.deploy_remaining_ms = 0
    shooter.speed_mt_per_sec = 0

    seen_under = False
    for _ in range(int(25 * 1000 / TICK_MS)):
        battle.step()
        if not drill.alive:
            break
        if drill.hidden_until_ms:
            seen_under = True
            assert drill.untargetable, "it went under and stayed shootable"
    assert seen_under, "it never went under at all"


def test_out_in_the_open_it_comes_back_up_where_it_was():
    drill, jumps, _goblins = _drill_under_fire("goblin_drill_ev1",
                                               Point(9000, 20000))
    assert drill.hides_used == 2
    assert all(jump < 1 * MT for jump in jumps), (
        f"it moved {[round(j/MT, 2) for j in jumps]} tiles with no tower near it")


def test_beside_a_crown_tower_it_comes_up_a_quarter_turn_around_it():
    """The awkward part of the card: whatever was hitting it is now behind it."""
    tower = arena.ENEMY_PRINCESS["left"]
    drill, jumps, _goblins = _drill_under_fire("goblin_drill_ev1", tower)
    assert drill.hides_used >= 1
    assert jumps, "it never relocated at all"
    assert max(jumps) > 1 * MT, (
        f"hugging a tower it moved only {max(jumps)/MT:.2f} tiles")
    # A quarter turn keeps its distance from the tower.
    assert distance(tower, drill.pos) < Battle.DRILL_TOWER_REACH_MT
