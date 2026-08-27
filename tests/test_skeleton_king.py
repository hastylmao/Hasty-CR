"""Skeleton King's ability, which the simulator did not have at all.

His whole card is the summon. He is a two-elixir ability on a four-elixir body,
and the ability raises six to sixteen skeletons depending on how many souls he
has banked. In the simulator `can_activate_ability` refused him outright: the
loader looked for a buff, a dash or a guard on his ability, found an
`AreaEffectObject` it had no handling for, and left every field blank, so the
activation gate saw a champion with no declared effect and said no.

Nothing failed. His hitpoints and damage were right, his skeletons existed as a
character, and he simply stood there being a mediocre four-elixir troop.

Every number is declared:

    [ABILITY.SkeletonKing]
        AreaEffectObject   = "SkeletonKingGraveyard"
        ResurrectBaseCount = 6      # StatsTags: min_skeleton_count
        SpawnLimit         = 16
        ResurrectOwnTroops = true
        ResurrectEnemies   = true

    [AEO.SkeletonKingGraveyard]
        SpawnCharacter     = "SkeletonKingSkeleton"
        SpawnInitialDelay  = 250
        SpawnInterval      = 250
        SpawnMinRadius     = 2500
        SpawnMaxRadius     = 3500

and the published description agrees on all of it: six at no souls, sixteen at
the maximum of ten, one at a time every 0.25 seconds in a ring around him, a
soul for every troop that dies while he is in the arena.

  https://clashroyale.fandom.com/wiki/Skeleton_King
  https://liquipedia.net/clashroyale/Skeleton_King

The staggering is not decoration. A swarm arriving over four seconds can be
answered mid-summon; one that appears at once cannot, and modelling it as an
instant drop would make the card meaningfully stronger than it is.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import MT, Point, TICK_MS, distance              # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_characters, load_gamedata         # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
TABLE = load_characters(11)
SPELLS = load_spells(level=11)
SKELETON = "skeleton_king_skeleton"


def _king_alone(souls: int = 0):
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    king = battle.add(make_unit(1, CARDS["skeleton_king"].unit, 1,
                                Point(9000, 20000)))
    king.deploy_remaining_ms = 0
    king.speed_mt_per_sec = 0
    king.souls = souls
    return battle, king


def _raised(battle):
    return [e for e in battle.entities.values() if e.name == SKELETON]


def test_the_declared_numbers_are_read():
    unit = CARDS["skeleton_king"].unit
    assert unit.ability_summon_character == "SkeletonKingSkeleton"
    assert unit.ability_summon_base_count == 6
    assert unit.ability_summon_max_count == 16
    assert unit.ability_summon_interval_ms == 250
    assert (unit.ability_summon_min_radius_mt,
            unit.ability_summon_max_radius_mt) == (2500, 3500)


@pytest.mark.parametrize("souls,expected", [
    (0, 6),      # the declared floor
    (1, 7),
    (4, 10),
    (10, 16),    # ten souls is the published maximum
    (25, 16),    # and it caps rather than overflowing
])
def test_souls_decide_how_many_rise(souls, expected):
    battle, king = _king_alone(souls)
    assert battle.schedule_ability_summon(king)
    for _ in range(int(8 * 1000 / TICK_MS)):
        battle.step()
    assert len(_raised(battle)) == expected


def test_they_arrive_one_at_a_time_rather_than_all_at_once():
    """Four seconds for sixteen, at the declared quarter-second interval."""
    battle, king = _king_alone(souls=10)
    battle.schedule_ability_summon(king)
    counts = []
    for _tick in range(int(6 * 1000 / TICK_MS)):
        battle.step()
        counts.append(len(_raised(battle)))
    assert counts[int(0.5 * 1000 / TICK_MS)] < 6, (
        "the whole graveyard landed in the first half second")
    assert counts[-1] == 16
    # Sixteen at 250ms apart after a 250ms delay is a shade under four seconds.
    first_full = next(i for i, n in enumerate(counts) if n == 16)
    assert 3.0 <= first_full * TICK_MS / 1000 <= 5.0, first_full * TICK_MS / 1000


def test_they_rise_in_a_ring_around_him_not_on_top_of_him():
    battle, king = _king_alone(souls=10)
    battle.schedule_ability_summon(king)
    for _ in range(int(8 * 1000 / TICK_MS)):
        battle.step()
    spans = [distance(king.pos, e.pos) for e in _raised(battle)]
    assert spans
    # Placed in the declared 2.5-3.5 tile band; separation may nudge them.
    assert min(spans) > 1.5 * MT, f"closest skeleton at {min(spans)/MT:.2f} tiles"
    assert max(spans) < 5.5 * MT, f"furthest skeleton at {max(spans)/MT:.2f} tiles"


def test_a_death_anywhere_banks_a_soul():
    """Either side's troop, and no radius: he is in the arena, that is enough."""
    battle, king = _king_alone()
    victim = battle.add(make_unit(2, CARDS["skeletons"].unit, -1,
                                  Point(2000, 30000)))
    victim.deploy_remaining_ms = 0
    assert king.souls == 0
    victim.hitpoints = 0          # `alive` is derived from hitpoints
    battle.step()
    assert king.souls == 1, "a troop died across the arena and no soul was banked"


def test_souls_stop_at_the_cap():
    battle, king = _king_alone()
    for index in range(20):
        victim = battle.add(make_unit(100 + index, CARDS["skeletons"].unit, -1,
                                      Point(2000, 30000)))
        victim.deploy_remaining_ms = 0
        victim.hitpoints = 0
        battle.step()
    assert king.souls == 10, f"banked {king.souls}, and ten is the maximum"


def test_a_tower_falling_is_not_a_soul():
    battle, king = _king_alone()
    tower = battle.add(make_unit(3, CARDS["cannon"].unit, -1, Point(9000, 28000)))
    tower.deploy_remaining_ms = 0
    tower.is_tower = True
    tower.hitpoints = 0
    battle.step()
    assert king.souls == 0


def test_the_ability_is_offered_and_spends_its_elixir_in_a_real_match():
    """The gate that refused him, checked end to end."""
    deck = ["skeleton_king", "knight", "archers", "musketeer",
            "cannon", "skeletons", "giant", "hog_rider"]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = "skeleton_king"
    player.elixir = 10_000
    assert match.play_card(1, "skeleton_king", grid_to_point(9, 22, 1))
    for _ in range(80):
        match.step()
    king = next(e for e in match.battle.entities.values()
                if e.name == "skeleton_king")

    assert match.can_activate_ability(1, king.uid), (
        "his ability is his card and the gate refused it")
    player.elixir = 10_000
    before = player.elixir
    assert match.activate_ability(1, king.uid)
    assert player.elixir == before - king.ability_cost * 1000

    # Count everything that ever rose, not what survived: they are 82-hitpoint
    # skeletons walking at a tower, and some are dead before the last one lands.
    risen = set()
    for _ in range(int(6 * 1000 / TICK_MS)):
        match.step()
        risen.update(e.uid for e in match.battle.entities.values()
                     if e.name == SKELETON and e.side == 1)
    assert len(risen) >= 6, f"only {len(risen)} skeletons rose, and six is the floor"


def test_the_skeletons_belong_to_whoever_raised_them():
    battle, king = _king_alone(souls=3)
    battle.schedule_ability_summon(king)
    for _ in range(int(6 * 1000 / TICK_MS)):
        battle.step()
    raised = _raised(battle)
    assert raised
    assert all(e.side == king.side for e in raised)
