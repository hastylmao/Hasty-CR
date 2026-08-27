"""Balloon Hero's Coffin Cadets, which bought an animation and nothing else.

Two elixir for an ability that did not exist. The loader never followed an
`ActionSpawn` of `ProjectileType` into the character its projectile carries, so
`SpawnCharacter = "SkeletonTrooper"` went unread and the activation simply
returned.

The action audit gated this one as a "logX10000 accelerated payload trajectory
and interception timing", which reads like something only a recording could
settle. It is a declared formula:

    [ACTION.BalloonHero_Skeletrooper_Speed_Up_Interval]
        StartCounterAt = 50
        Interval       = 150            # every 150ms
    [ACTION.BalloonHero_Skeletrooper_Speed_Increment]
        Value = "BalloonHero_Skeletrooper_Speed_Rampup + 2"
    [ACTION.BalloonHero_Skeletrooper_Speed_Up]
        SpeedOverride = "logX10000(max(5, BalloonHero_Skeletrooper_Speed_Rampup - 1)) / 80"

Integrating that gives the dive time. The single genuine unknown is which
logarithm `logX10000` means: natural log lands him in 0.9-1.5 seconds across
the ability's range, matching the published "after a 1-second delay", while
base ten would take 1.5-2.7. That choice moves *when* he lands and never
*where*, and the ability was doing nothing at all in the meantime.

Everything else is read from the file, and the published description agrees
with all of it:

  * a 6500 circle, `default_targets_no_towers_no_flying`, closest target with
    ties broken on highest current hitpoints
  * with nothing in range he lands under the balloon rather than being wasted
  * `StartPositionZOffset = 1000`, so even that straight-down landing is a fall
  * his landing burst - 2 tiles, and almost nothing to crown towers - which
    already worked once `SpawnAreaObject` was being read at all

  https://clashcoachai.com/guides/balloon-hero-coffin-cadets-guide
  https://royaleapi.com/blog/hero-balloon-april-2026?lang=en
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


def test_the_declared_drop_is_read():
    unit = CARDS["balloon_hero"].unit
    assert unit.ability_drop_character == "SkeletonTrooper"
    assert unit.ability_drop_radius_mt == 6500
    assert unit.ability_drop_height_mt == 1000


def test_only_this_card_drops_a_passenger():
    dropping = {name for name, card in CARDS.items()
                if card.unit is not None
                and getattr(card.unit, "ability_drop_character", "")}
    assert dropping == {"balloon_hero"}, sorted(dropping)


def test_the_dive_time_matches_the_published_delay():
    """"After a 1-second delay" - the integrated ramp, not a chosen constant."""
    near = Battle.paratrooper_flight_ms(3000)
    far = Battle.paratrooper_flight_ms(6500)
    assert 700 <= near <= 1300, near
    assert 1200 <= far <= 1900, far
    assert far > near, "a longer dive has to take longer"


def _drop(gap_mt):
    """Balloon Hero with a giant `gap_mt` away, or alone if gap is zero."""
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    hero = battle.add(make_unit(1, CARDS["balloon_hero"].unit, 1,
                                Point(9000, 20000)))
    hero.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = 0
    if gap_mt:
        giant = battle.add(make_unit(2, CARDS["giant"].unit, -1,
                                     Point(9000, 20000 + gap_mt)))
        giant.deploy_remaining_ms = 0
        giant.speed_mt_per_sec = 0
        giant.damage = 0
    resolved = battle.resolve_drop_target(hero)
    assert battle.schedule_paratrooper(hero)
    landed = None
    for tick in range(int(5 * 1000 / TICK_MS)):
        battle.step()
        troopers = [e for e in battle.entities.values()
                    if "trooper" in e.name.lower()]
        if troopers and landed is None:
            landed = (tick * TICK_MS, distance(hero.pos, troopers[0].pos))
    return battle, hero, resolved, landed


@pytest.mark.parametrize("gap", [3000, 6000])
def test_he_lands_on_a_target_in_range(gap):
    _battle, _hero, resolved, landed = _drop(gap)
    assert resolved is not None and resolved.name == "giant"
    assert landed is not None, "no trooper ever arrived"
    when, where = landed
    assert abs(where - gap) < 1 * MT, (
        f"landed {where/MT:.1f} tiles out against a target at {gap/MT:.1f}")
    assert when > 0, "he appeared instantly instead of diving"


def test_with_nothing_in_range_he_lands_under_the_balloon():
    """The elixir is spent either way; the trooper is not wasted."""
    _battle, _hero, resolved, landed = _drop(9000)   # outside the 6.5 circle
    assert resolved is None
    assert landed is not None, "the drop was thrown away"
    when, where = landed
    assert where < 1 * MT
    assert when > 0, "even a landing directly below is a fall"


def test_the_resolver_ignores_towers_and_air():
    """`default_targets_no_towers_no_flying`, which is why a Balloon over a
    tower still drops him onto the troops instead."""
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    hero = battle.add(make_unit(1, CARDS["balloon_hero"].unit, 1,
                                Point(9000, 20000)))
    hero.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = 0
    tower = battle.add(make_unit(2, CARDS["cannon"].unit, -1, Point(9500, 20500)))
    tower.deploy_remaining_ms = 0
    tower.is_tower = True
    flyer = battle.add(make_unit(3, CARDS["minions"].unit, -1, Point(9800, 20800)))
    flyer.deploy_remaining_ms = 0
    flyer.speed_mt_per_sec = 0
    ground = battle.add(make_unit(4, CARDS["giant"].unit, -1, Point(9000, 24000)))
    ground.deploy_remaining_ms = 0
    ground.speed_mt_per_sec = 0

    picked = battle.resolve_drop_target(hero)
    assert picked is not None
    assert picked.uid == ground.uid, (
        f"picked {picked.name}, and towers and air are both filtered out")


def test_ties_on_distance_go_to_the_healthier_target():
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    hero = battle.add(make_unit(1, CARDS["balloon_hero"].unit, 1,
                                Point(9000, 20000)))
    hero.deploy_remaining_ms = 0
    weak = battle.add(make_unit(2, CARDS["knight"].unit, -1, Point(9000, 23000)))
    tough = battle.add(make_unit(3, CARDS["giant"].unit, -1, Point(9000, 17000)))
    for unit in (weak, tough):
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
    picked = battle.resolve_drop_target(hero)
    assert picked is not None and picked.uid == tough.uid


def test_the_trooper_lands_hitting_and_barely_scratches_a_crown_tower():
    """His landing burst, which the client puts on the trooper itself."""
    trooper = TABLE["SkeletonTrooper"]
    assert trooper.spawn_area_damage > 0
    assert trooper.spawn_area_radius_mt == 2000
    assert trooper.spawn_area_tower_percent < 100


def test_the_ability_works_end_to_end_in_a_match():
    deck = ["balloon_hero", "knight", "archers", "musketeer",
            "cannon", "skeletons", "giant", "hog_rider"]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
    for _ in range(40):
        match.step()
    player = match.players[1]
    player.hand[0] = "balloon_hero"
    player.elixir = 10_000
    assert match.play_card(1, "balloon_hero", grid_to_point(9, 22, 1))
    for _ in range(80):
        match.step()
    hero = next(e for e in match.battle.entities.values()
                if "balloon" in e.name and e.side == 1)

    player.elixir = 10_000
    before = player.elixir
    assert match.can_activate_ability(1, hero.uid)
    assert match.activate_ability(1, hero.uid)
    assert player.elixir == before - hero.ability_cost * 1000

    for _ in range(int(4 * 1000 / TICK_MS)):
        match.step()
    ours = [e for e in match.battle.entities.values()
            if "trooper" in e.name.lower() and e.side == 1]
    assert ours, "two elixir bought nothing"
