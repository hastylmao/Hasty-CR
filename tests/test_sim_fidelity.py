"""Does the battle engine reproduce the numbers in the card data?

The simulator has been trustworthy about mechanics and untrustworthy about
strategy, and that split is only worth anything if the mechanics are actually
pinned. Each test drives one mechanic in isolation and compares the engine
against the card file, so a regression shows up as a failing number rather than
as a strategy result that quietly stops meaning anything.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.arena import MT, Point, TICK_MS, distance          # noqa: E402
from sim.engine import Battle                                # noqa: E402
from sim.entities import make_tower, make_unit, speed_to_mt_per_sec  # noqa: E402
from sim.gamedata import load_gamedata                       # noqa: E402

ALL = load_gamedata(level=11)


def _spawn(battle, name, side, x, y, uid, ready=True):
    entity = battle.add(make_unit(uid, ALL[name].unit, side,
                                  Point(int(x * MT), int(y * MT))))
    if ready:
        entity.deploy_remaining_ms = 0
    return entity


def _run(battle, seconds):
    for _ in range(int(seconds * 1000 / TICK_MS)):
        battle.step()


def test_attack_cadence_matches_the_card_data():
    """A 1000ms hit speed must mean a hit every 1000ms, not every 1050ms.

    The cooldown was tested before being decremented, which spent one extra
    tick per cycle. Being a fixed tick rather than a fixed share, it cost a
    Giant about 3% of its damage and Skeletons about 17% - a thumb on the scale
    in exactly the swarm-versus-tank comparisons this engine is used for.
    """
    battle = Battle()
    musketeer = _spawn(battle, "musketeer", 1, 9, 20, uid=1)
    target = _spawn(battle, "giant", -1, 9, 21, uid=2)
    musketeer.speed_mt_per_sec = target.speed_mt_per_sec = 0
    target.damage = 0                      # let the shooter live long enough
    _run(battle, 6)

    spec = ALL["musketeer"].unit
    times = [t for t, src, _, _ in battle.damage_log if src == 1]
    assert times, "the musketeer never fired"

    # damage_log records when a shot *lands*, and shots travel. The first
    # arrives a load time after the unit engages plus the flight time for one
    # tile, rounded up to the tick. The cadence itself is unaffected: the gap
    # between arrivals is the hit speed, because every shot flies the same way.
    flight = 1000 * MT // spec.projectile_speed_mt_per_sec
    assert times[0] - spec.load_time_ms <= flight + TICK_MS, (times[:3], flight)
    assert times[0] >= spec.load_time_ms, times[:3]
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(gap == spec.hit_speed_ms for gap in gaps), gaps


@pytest.mark.parametrize("target_name", ["knight", "giant"])
def test_attack_reach_is_own_range_plus_the_target_hitbox(target_name):
    """Range is measured to the edge of the target, not its centre.

    This is why a Giant can be hit from further away than a Knight, and it is
    the mechanic behind the Cannon losing to a Musketeer live.
    """
    spec = ALL["musketeer"].unit
    reach = (spec.range_mt + ALL[target_name].unit.collision_radius_mt) / MT

    for offset, should_hit in ((reach - 0.25, True), (reach + 0.40, False)):
        battle = Battle()
        shooter = _spawn(battle, "musketeer", 1, 9, 20, uid=1)
        target = _spawn(battle, target_name, -1, 9, 20 + offset, uid=2)
        shooter.speed_mt_per_sec = target.speed_mt_per_sec = 0
        before = target.hitpoints
        _run(battle, 3)
        assert (target.hitpoints < before) is should_hit, (offset, reach)


def test_a_musketeer_kills_a_cannon_without_being_touched():
    """The live fault, reproduced from the card data alone.

    Cannon reaches 5.5 tiles and Musketeer 6.0, so the Musketeer stops at the
    edge of its own reach - outside the Cannon's - and never takes a hit. The
    bot was answering Musketeers with Cannons and losing them for nothing.
    """
    battle = Battle()
    musketeer = _spawn(battle, "musketeer", 1, 9, 20, uid=1)
    cannon = _spawn(battle, "cannon", -1, 9, 30, uid=2)

    for _ in range(int(60 * 1000 / TICK_MS)):
        battle.step()
        if not cannon.alive:
            break

    assert not cannon.alive, "the musketeer failed to kill the cannon"
    assert musketeer.hitpoints == musketeer.max_hitpoints, musketeer.hitpoints
    reach = (ALL["musketeer"].unit.range_mt
             + ALL["cannon"].unit.collision_radius_mt) / MT
    assert distance(musketeer.pos, cannon.pos) / MT == pytest.approx(reach, abs=0.2)


def test_splash_hits_inside_its_radius_and_spares_what_is_outside():
    battle = Battle()
    wizard = _spawn(battle, "wizard", 1, 9, 20, uid=1)
    wizard.speed_mt_per_sec = 0
    radius = ALL["wizard"].unit.splash_radius_mt / MT

    near = _spawn(battle, "knight", -1, 9, 23, uid=2)
    far = _spawn(battle, "knight", -1, 9 + radius * 3, 23, uid=3)
    near.speed_mt_per_sec = far.speed_mt_per_sec = 0
    near.damage = far.damage = 0
    near_before, far_before = near.hitpoints, far.hitpoints

    _run(battle, 4)
    assert near.hitpoints < near_before, "splash missed the unit beside the target"
    assert far.hitpoints == far_before, "splash reached a unit outside its radius"


def test_a_unit_cannot_act_until_its_deploy_time_has_passed():
    """Everything takes about a second to land, which is why placing a Cannon
    on top of a push gives the push free hits."""
    battle = Battle()
    knight = _spawn(battle, "knight", 1, 9, 20, uid=1, ready=False)
    _spawn(battle, "giant", -1, 9, 26, uid=2)
    start = knight.pos

    deploy_ms = ALL["knight"].unit.deploy_time_ms
    assert deploy_ms > 0
    _run(battle, (deploy_ms - 100) / 1000.0)
    assert distance(start, knight.pos) / MT < 0.05, "moved before it had landed"

    _run(battle, 1.5)
    assert distance(start, knight.pos) / MT > 0.2, "never started moving"


def test_movement_speed_matches_the_card_data():
    """Measured while it is actually walking.

    A bare battle has no towers, and sight range is only a few tiles, so a unit
    with nothing in view has nowhere to go and correctly stands still. The
    target therefore sits just inside sight, and the window ends before the
    Knight closes to attack range and stops. It has to be a unit that targets
    troops at all - a Hog Rider only ever walks towards buildings, so with none
    on the field it correctly stands still and measures nothing.
    """
    battle = Battle()
    knight = _spawn(battle, "knight", 1, 9, 25, uid=1)
    _spawn(battle, "giant", -1, 9, 21, uid=2)
    start = knight.pos

    seconds = 1.5
    _run(battle, seconds)
    tiles = distance(start, knight.pos) / MT
    per_second = speed_to_mt_per_sec(ALL["knight"].unit.speed_mt_per_sec) / 1000.0
    assert tiles == pytest.approx(per_second * seconds, rel=0.12), (tiles, per_second)


def test_a_prince_charges_and_its_first_hit_is_the_special_damage():
    """Walk far enough and the next hit is roughly double.

    Without this the Prince was simply a slow Knight in the simulator, which
    matters because the bot has to answer one. The charge is also why pulling a
    Prince off its line is worth doing: interrupted before it covers the
    distance, it never lands the big hit at all.
    """
    spec = ALL["prince"].unit
    assert spec.charge_range_mt > 0 and spec.damage_special > spec.damage

    # Inside the Prince's 5.5 tile sight - out of sight it has nothing to walk
    # towards and never charges - but far enough to cover the 2.5 tiles first.
    battle = Battle()
    prince = _spawn(battle, "prince", 1, 9, 20, uid=1)
    knight = _spawn(battle, "knight", -1, 9, 25, uid=2)
    knight.speed_mt_per_sec = 0

    for _ in range(int(40 * 1000 / TICK_MS)):
        battle.step()
        hits = [row for row in battle.damage_log if row[1] == 1]
        if hits:
            assert prince.charging is False, "the charge should be spent on the hit"
            assert hits[0][3] == spec.damage_special, hits[0]
            return
    raise AssertionError("the prince never landed a hit")


def test_a_prince_stopped_short_never_gets_its_charge():
    """It has to cover the ground first."""
    battle = Battle()
    prince = _spawn(battle, "prince", 1, 9, 20, uid=1)
    _spawn(battle, "knight", -1, 9, 21, uid=2)
    prince.speed_mt_per_sec = 0                 # pinned in place, never walks

    _run(battle, 5)
    assert not prince.charging
    hits = [row for row in battle.damage_log if row[1] == 1]
    assert hits, "the prince never attacked"
    assert all(row[3] == ALL["prince"].unit.damage for row in hits), hits[:3]


def test_a_shield_absorbs_before_hitpoints():
    spec = ALL["dark_prince"].unit
    assert spec.shield_hitpoints > 0

    battle = Battle()
    dark_prince = _spawn(battle, "dark_prince", 1, 9, 20, uid=1)
    _spawn(battle, "musketeer", -1, 9, 21, uid=2)
    dark_prince.speed_mt_per_sec = 0
    full = dark_prince.hitpoints

    for _ in range(int(20 * 1000 / TICK_MS)):
        battle.step()
        if dark_prince.shield_hitpoints > 0:
            assert dark_prince.hitpoints == full, "hitpoints fell while the shield held"
        if dark_prince.hitpoints < full:
            assert dark_prince.shield_hitpoints == 0
            return
    raise AssertionError("the dark prince was never damaged")


def test_a_troop_does_not_aggro_something_it_cannot_see():
    """Sight range is what stops a unit engaging across the arena.

    Target selection used to pick the globally nearest enemy with no distance
    limit, so a unit by one tower would lock onto a troop by the other purely
    because nothing closer existed. Watching a match makes it obvious; the
    numbers never showed it.
    """
    battle = Battle()
    spirit = _spawn(battle, "musketeer", 1, 3, 26, uid=1)
    sight = spirit.sight_range_mt / MT
    far = _spawn(battle, "knight", -1, 15, 26, uid=2)   # across the arena
    far.speed_mt_per_sec = 0
    assert distance(spirit.pos, far.pos) / MT > sight, "the test target is not far enough"

    _run(battle, 2)
    assert spirit.target_uid != far.uid, "engaged a troop beyond its sight range"


def test_out_of_sight_a_unit_still_walks_towards_a_building():
    """The reason the old rule existed, kept: a Hog crosses the map to a tower."""
    from sim.entities import make_tower

    battle = Battle()
    hog = _spawn(battle, "hog_rider", 1, 9, 26, uid=1)
    tower = battle.add(make_tower(2, -1, Point(9 * MT, 6 * MT),
                                  hitpoints=3346, damage=100,
                                  hit_speed_ms=800, range_mt=7500))
    assert distance(hog.pos, tower.pos) / MT > hog.sight_range_mt / MT
    start = hog.pos

    _run(battle, 3)
    assert hog.target_uid == tower.uid, "did not head for the tower"
    assert distance(start, hog.pos) > 0, "stood still instead of advancing"


def test_ground_troops_cannot_walk_through_a_tower():
    """Buildings were left out of collision entirely, so units passed through."""
    from sim.entities import make_tower

    battle = Battle()
    king = battle.add(make_tower(1, -1, Point(9 * MT, 20 * MT),
                                 hitpoints=5000, damage=0,
                                 hit_speed_ms=1000, range_mt=100, king=True))
    walker = _spawn(battle, "knight", 1, 9, 26, uid=2)
    walker.target_uid = king.uid

    closest = 99.0
    for _ in range(int(20 * 1000 / TICK_MS)):
        battle.step()
        closest = min(closest, distance(walker.pos, king.pos) / MT)

    floor = (walker.collision_radius_mt + king.collision_radius_mt) / MT
    assert closest >= floor - 0.15, (closest, floor)


def test_contact_trace_exposes_the_simulator_assumption_for_live_comparison():
    from sim.entities import make_tower

    battle = Battle(trace_contacts=True)
    tower = battle.add(make_tower(
        1, -1, Point(9 * MT, 20 * MT), hitpoints=5000, damage=0,
        hit_speed_ms=1000, range_mt=100, king=True))
    first = _spawn(battle, "knight", 1, 9, 20, uid=2)
    second = _spawn(battle, "knight", 1, 9, 20, uid=3)
    for unit in (first, second):
        unit.target_uid = None
        unit.speed_mt_per_sec = 0
    battle._separate([tower, first, second])

    kinds = {event["kind"] for event in battle.contact_trace}
    assert kinds == {"building_contact", "troop_contact"}
    troop_event = next(event for event in battle.contact_trace
                       if event["kind"] == "troop_contact")
    assert troop_event["required_gap_mt"] == (
        first.collision_radius_mt + second.collision_radius_mt)
    assert troop_event["resolved_overlap_mt"] > 0


def test_opponents_engaged_with_each_other_are_still_pushed_apart():
    """Fighting is not a licence to occupy the same ground.

    Two opposing units that had each other targeted used to be exempted from
    separation entirely - "let engaged units touch" - so a fight was two bodies
    sunk into one another by half a tile. The exemption is gone.

    It costs them no reach: attack range is a unit's own range plus the
    *target's* collision radius, so a melee unit sitting at exactly the
    separation distance is still in range.
    """
    battle = Battle(trace_contacts=True)
    first = _spawn(battle, "knight", 0, 8, 20, uid=1)
    second = _spawn(battle, "knight", 1, 8, 20, uid=2)
    first.target_uid = second.uid
    second.target_uid = first.uid

    battle._separate([first, second])

    assert not [item for item in battle.contact_trace
                if item["kind"] == "engaged_contact_exempt"]
    needed = first.collision_radius_mt + second.collision_radius_mt
    assert distance(first.pos, second.pos) >= needed - 2, (
        first.pos, second.pos, needed)
    # And they can still reach each other to fight.
    assert first.is_valid_target(second, battle.now_ms)


def test_tower_hitboxes_match_the_building_data():
    """Both towers were built at a flat 1500 millitiles.

    buildings.csv gives every PrincessTower variant CollisionRadius 1000 and
    every KingTower variant 1400. It matters because reach is range plus the
    *target's* radius, so an oversized princess tower could be attacked from
    half a tile further away than the game allows - and it is the tower that
    every push is trying to reach.
    """
    from sim.entities import KING_COLLISION_MT, PRINCESS_COLLISION_MT, make_tower

    assert PRINCESS_COLLISION_MT == 1000
    assert KING_COLLISION_MT == 1400

    princess = make_tower(1, 1, Point(9 * MT, 25 * MT), 3346, 119, 800, 7500)
    king = make_tower(2, 1, Point(9 * MT, 29 * MT), 5735, 109, 1000, 7000, king=True)
    assert princess.collision_radius_mt == PRINCESS_COLLISION_MT
    assert king.collision_radius_mt == KING_COLLISION_MT


def test_a_lone_ice_golem_reaches_the_tower_and_lands_one_hit():
    """Checked in a real match, and the strongest anchor in this file.

    A level 11 Ice Golem walked into a level 12 princess tower, survived to
    reach it, and got exactly one swing in before dying. The simulator had it
    dying three tiles short, which took five separate faults to explain: units
    moved at three quarters speed, towers had no windup and no projectile
    flight, tower hitboxes were half a tile too wide, and a unit's own load
    time only counted down once it had already arrived.

    One hit is 85 damage. More than that and something has drifted in the
    attacker's favour; none at all and it is back to dying short.
    """
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=11), DECK_26)
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=3,
                  spells=load_spells(level=11))
    match.players[1].hand = ["ice_golem"] + list(DECK_26)[:3]
    match.players[1].elixir = 10_000

    tower = match.towers[-1]["left"]
    before = tower.hitpoints
    assert match.play_card(1, "ice_golem", grid_to_point(3, 20, 1))

    golem = [e for e in match.battle.entities.values()
             if e.side > 0 and not e.is_tower][-1]
    seconds = 0.0
    while golem.alive and seconds < 90:
        match.step()
        seconds += TICK_MS / 1000.0

    dealt = before - tower.hitpoints
    assert dealt > 0, "the ice golem died before reaching the tower"
    # One swing, and then the blast it leaves when it dies. The blast carries no
    # CrownTowerDamagePercent in the data, so unlike a spell it hits the tower
    # at full value. What was watched in the real game was the swing; the death
    # damage lands on top of it.
    spec = cards["ice_golem"].unit
    assert dealt == spec.damage + spec.death_damage, (
        dealt, spec.damage, spec.death_damage)


def _battle_with_spawns():
    """A battle that can build the units other units produce."""
    from sim.engine import Battle
    from sim.gamedata import load_characters, to_snake_case

    characters = load_characters(11)

    def lookup(character):
        key = to_snake_case(character)
        card = ALL.get(key)
        if card is not None and card.unit is not None:
            return card.unit
        return characters.get(key)

    battle = Battle()
    battle.unit_lookup = lookup
    return battle


def test_a_dying_unit_explodes_on_enemies_and_spares_its_own_side():
    """An Ice Golem is not a small tank - it leaves a blast behind it."""
    spec = ALL["ice_golemite"].unit
    assert spec.death_damage > 0 and spec.death_damage_radius_mt > 0

    battle = _battle_with_spawns()
    dying = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    enemy = battle.add(make_unit(2, ALL["musketeer"].unit, -1, Point(9 * MT, 21 * MT)))
    ally = battle.add(make_unit(3, ALL["musketeer"].unit, 1, Point(9 * MT, 19 * MT)))
    for entity in (dying, enemy, ally):
        entity.deploy_remaining_ms = 0
    enemy_before, ally_before = enemy.hitpoints, ally.hitpoints

    dying.hitpoints = 0
    battle.step()

    assert enemy_before - enemy.hitpoints == spec.death_damage
    assert ally.hitpoints == ally_before, "the blast hit its own side"


def test_a_golem_leaves_golemites_behind():
    """Spawned units are not cards, so the card table alone can never find them."""
    battle = _battle_with_spawns()
    spec = ALL["golem"].unit
    assert spec.death_spawn_character and spec.death_spawn_count == 2

    golem = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    golem.deploy_remaining_ms = 0
    golem.hitpoints = 0
    battle.step()

    children = [e for e in battle.entities.values() if e.uid != 1]
    assert len(children) == 2, [e.name for e in children]
    assert all(child.side == 1 for child in children)
    assert all(child.name == "golemite" for child in children), children[0].name


def test_a_spawner_building_produces_waves_on_its_own_timer():
    battle = _battle_with_spawns()
    spec = ALL["tombstone"].unit
    assert spec.spawn_pause_ms > 0 and spec.spawn_count > 0

    hut = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    hut.deploy_remaining_ms = 0

    _run(battle, spec.spawn_start_ms / 1000.0 - 0.2)
    assert len(battle.entities) == 1, "spawned before its start time"

    _run(battle, (spec.spawn_pause_ms * 2) / 1000.0 + 1.0)
    produced = len(battle.entities) - 1
    assert produced >= spec.spawn_count, produced


def test_an_ice_spirit_freezes_for_exactly_its_buff_time_and_dies_doing_it():
    """Three mechanics that only make sense together.

    The freeze is on the projectile (TargetBuff Freeze, BuffTime 1100), the
    buff itself is SpeedMultiplier and HitSpeedMultiplier at -100, and the
    spirit is Kamikaze so it lands one hit and dies. Miss the Kamikaze and it
    survives to re-freeze its victim for ever; miss the projectile carrying the
    buff and the card is a cheap body that does 43 damage.
    """
    spec = ALL["ice_spirits"].unit
    assert spec.target_buff == "Freeze" and spec.buff_time_ms > 0
    assert spec.kamikaze

    battle = Battle()
    spirit = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    victim = battle.add(make_unit(2, ALL["knight"].unit, -1, Point(9 * MT, 21 * MT)))
    for entity in (spirit, victim):
        entity.deploy_remaining_ms = 0

    frozen_ms = 0
    for _ in range(int(4000 / TICK_MS)):
        battle.step()
        if victim.buffed(battle.now_ms):
            frozen_ms += TICK_MS

    assert not spirit.alive, "a kamikaze unit must die on its own hit"
    assert abs(frozen_ms - spec.buff_time_ms) <= 2 * TICK_MS, frozen_ms
    assert victim.buff_speed_pct == -100


def test_a_shot_still_lands_after_its_shooter_dies():
    """A Kamikaze unit is dead before its own projectile arrives.

    Dropping shots whose attacker had gone deleted the Ice Spirit's entire
    contribution - damage and freeze together - while looking like correct play.
    """
    battle = Battle()
    spirit = battle.add(make_unit(1, ALL["ice_spirits"].unit, 1, Point(9 * MT, 20 * MT)))
    victim = battle.add(make_unit(2, ALL["knight"].unit, -1, Point(9 * MT, 21 * MT)))
    for entity in (spirit, victim):
        entity.deploy_remaining_ms = 0
    before = victim.hitpoints

    _run(battle, 4)
    assert not spirit.alive
    assert victim.hitpoints < before, "the shot died with its shooter"


def test_the_log_pushes_what_it_can_and_leaves_heavies_alone():
    """Knockback is most of why the Log is played, and it did nothing.

    `pushback_mt` was parsed out of the data and never applied, so a Hog Rider
    the Log rolled over kept walking. 21 units carry IgnorePushback - Giant,
    P.E.K.K.A., Golem, Prince - and shoving those would make the card far
    better on defence than it is.
    """
    from sim.spells import apply_spell, load_spells

    log = load_spells(11)["the_log"]
    assert log.pushback_mt > 0

    def push(card_name):
        battle = Battle()
        spec = ALL[card_name].unit
        entity = battle.add(make_unit(1, spec, -1, Point(9 * MT, 20 * MT)))
        entity.deploy_remaining_ms = 0
        start = entity.pos
        apply_spell(battle, log, Point(9 * MT, 21 * MT), side=1)
        _run(battle, 0.5)
        return spec, distance(start, entity.pos)

    spec, moved = push("hog_rider")
    assert not spec.ignore_pushback
    assert abs(moved - log.pushback_mt) <= 60, moved

    spec, moved = push("giant")
    assert spec.ignore_pushback
    assert moved == 0, "a Giant should shrug off the Log"


def test_a_miner_tunnels_anywhere_and_cannot_be_hit_on_the_way():
    """The 4th most common card the bot faces, and it was an ordinary troop.

    Three things make a Miner: it deploys outside the normal area, it takes
    time to get there proportional to the distance, and nothing can touch it
    until it surfaces. Miss any one and the defence gets a chance it never has
    in a real game.
    """
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(level=11), DECK_26))
    cards["miner"] = ALL["miner"]
    assert cards["miner"].unit.burrow_speed_mt_per_sec > 0

    deck = list(DECK_26)
    match = Match(cards=cards, decks=(deck, deck), seed=3, spells=load_spells(11))
    match.players[1].hand = ["miner"] + deck[:3]
    match.players[1].elixir = 10_000

    # deep in the enemy half, where no ordinary troop may be placed
    assert match.play_card(1, "miner", grid_to_point(3, 6, 1)), "burrower was refused"
    miner = [e for e in match.battle.entities.values() if e.name == "miner"][0]
    tower = match.towers[-1]["left"]

    assert miner.underground
    assert not tower.is_valid_target(miner), "the tower could hit it underground"

    seconds = 0.0
    while miner.underground and seconds < 20:
        match.step()
        seconds += TICK_MS / 1000.0
    assert 0.5 < seconds < 10, seconds
    assert tower.is_valid_target(miner), "still untargetable after surfacing"


def test_an_ordinary_troop_still_cannot_be_placed_in_the_enemy_half():
    """The exception is for burrowers only."""
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=11), DECK_26)
    deck = list(DECK_26)
    match = Match(cards=cards, decks=(deck, deck), seed=3, spells=load_spells(11))
    match.players[1].hand = ["knight"] + deck[:3] if "knight" in cards else list(deck)
    match.players[1].elixir = 10_000
    card = match.players[1].hand[0]
    assert not match.play_card(1, card, grid_to_point(3, 6, 1))


@pytest.mark.parametrize("card", ["boss_bandit", "mega_knight"])
def test_a_dasher_crosses_untouchable_and_lands_its_dash_damage(card):
    """The point of a dash is that a spell aimed at her misses.

    Without it these were fast melee units, which gets the whole family of
    counters wrong. The dash triggers between DashMinRange and DashMaxRange,
    lands DashDamage rather than an ordinary hit, and then goes on cooldown so
    it cannot happen every swing.
    """
    spec = ALL[card].unit
    assert spec.dash_max_range_mt > 0 and spec.dash_damage > spec.damage

    battle = Battle()
    dasher = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    victim = battle.add(make_unit(2, ALL["musketeer"].unit, -1, Point(9 * MT, 25 * MT)))
    for entity in (dasher, victim):
        entity.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = 0
    before = victim.hitpoints

    untouchable_ms = 0
    first_hit = None
    for _ in range(int(6000 / TICK_MS)):
        battle.step()
        if dasher.untargetable:
            untouchable_ms += TICK_MS
        if first_hit is None and victim.hitpoints < before:
            first_hit = before - victim.hitpoints
        if not victim.alive:
            break

    assert first_hit == spec.dash_damage, (first_hit, spec.dash_damage)
    assert untouchable_ms > 0, "was targetable for the whole dash"
    assert not dasher.dashing, "still dashing after arriving"


def test_a_dasher_does_not_dash_from_point_blank():
    """DashMinRange exists so it cannot be used as a normal attack."""
    spec = ALL["boss_bandit"].unit
    battle = Battle()
    dasher = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    victim = battle.add(make_unit(2, ALL["musketeer"].unit, -1, Point(9 * MT, 21 * MT)))
    for entity in (dasher, victim):
        entity.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = 0
    before = victim.hitpoints

    _run(battle, 3)
    dealt = before - victim.hitpoints
    assert dealt > 0, "never attacked at all"
    assert dealt % spec.dash_damage != 0 or dealt == spec.damage, dealt


def test_the_spell_table_is_found_by_name_not_by_hand():
    """A hand-written table listed five spells and mis-pointed two of them.

    arrowsspell.toml and zapspell.toml do not exist, so those two failed the
    file check and were skipped in silence - the simulator ran on two spells
    while claiming four. Resolving by the card's own name finds nineteen and
    cannot rot the same way.
    """
    from sim.spells import load_spells

    spells = load_spells(11)
    assert len(spells) >= 18, sorted(spells)
    for expected in ("fireball", "zap", "arrows", "rocket", "lightning",
                     "poison", "tornado", "graveyard", "freeze", "snowball"):
        assert expected in spells, (expected, sorted(spells))


def test_arrows_uses_the_audited_full_spell_result_not_one_projectile():
    """Arrows' client section is one volley projectile, not its card damage.

    Supercell's current balance notes give 75 level-11 Crown Tower damage and
    its prior radius update gives 3.5 tiles.  The source registry turns that
    into the complete 375-damage spell; reading the raw `Damage = 48` field
    directly would make Arrows six-to-eight times too weak depending on which
    internal projectile entries happen to land.
    """
    from sim.entities import make_tower
    from sim.spells import apply_spell, load_spells

    battle = Battle()
    troop = _spawn(battle, "knight", -1, 9, 20, 1)
    tower = battle.add(make_tower(2, -1, Point(9 * MT, 22 * MT),
                                  hitpoints=3346, damage=0,
                                  hit_speed_ms=1000, range_mt=7500))
    troop.deploy_remaining_ms = 0
    arrows = load_spells(11)["arrows"]
    assert (arrows.damage, arrows.radius_mt, arrows.damage_to(tower)) == (366, 3500, 75)

    troop_before, tower_before = troop.hitpoints, tower.hitpoints
    apply_spell(battle, arrows, Point(9 * MT, 20 * MT), side=1)
    _run(battle, 0.6)
    assert troop.hitpoints == troop_before - 366
    assert tower.hitpoints == tower_before - 75


def test_spell_combat_numbers_scale_with_the_requested_card_level():
    """Spells and troops must use the same client rarity growth curve."""
    from sim.spells import load_spells

    spells = load_spells(11)
    # These use the client's cumulative per-level multiplier table. Rounding
    # every intermediate 10% step instead drifts Fireball to 700 and Zap to
    # 194, while the current level-11 values are 689 and 192.
    assert spells["fireball"].damage == 689
    assert spells["zap"].damage == 192
    assert spells["goblin_curse"].damage_per_second == 35


def test_published_spell_overrides_scale_for_mirror_level():
    """A mirrored spell is a level higher, including externally audited stats."""
    from sim.spells import load_spells

    level_11 = load_spells(11)
    level_12 = load_spells(12)
    assert level_12["fireball"].tower_damage_override == 189
    assert level_12["rage"].damage == 197
    assert level_12["dark_magic"].damage_by_target_count[0] == 766


def test_rage_damages_enemies_and_buffs_only_friendlies():
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    friend = _spawn(battle, "knight", 1, 9, 20, 1)
    enemy = _spawn(battle, "knight", -1, 9, 20, 2)
    rage = load_spells(11)["rage"]
    before = enemy.hitpoints

    apply_spell(battle, rage, Point(9 * MT, 20 * MT), side=1)
    assert enemy.hitpoints == before - 179
    assert not friend.buffed(battle.now_ms), "the area has not ticked yet"
    battle.step()
    assert friend.buff_speed_pct == 30
    assert friend.buff_hit_speed_pct == 30
    assert enemy.buff_speed_pct == 0


def test_rage_card_resolves_as_a_spell_not_a_permanent_bottle():
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["rage"] = ALL["rage"]
    deck = list(DECK_26)
    match = Match(cards=cards, decks=(deck, deck), seed=2,
                  spells=load_spells(11))
    match.players[1].hand = ["rage"] + deck[:3]
    match.players[1].elixir = 10_000
    count = len(match.battle.entities)

    assert match.play_card(1, "rage", grid_to_point(3, 4, 1))
    assert len(match.battle.entities) == count, "spawned the client RageBottle"


def test_earthquake_hits_ground_and_deals_its_building_multiplier():
    from sim.entities import make_tower
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    ground = _spawn(battle, "giant", -1, 9, 20, 1)
    air = _spawn(battle, "minions", -1, 9, 20, 2)
    building = battle.add(make_tower(3, -1, Point(9 * MT, 20 * MT),
                                     hitpoints=5000, damage=0,
                                     hit_speed_ms=1000, range_mt=0))
    building.is_tower = False
    quake = load_spells(11)["earthquake"]
    hp = (ground.hitpoints, air.hitpoints, building.hitpoints)

    apply_spell(battle, quake, Point(9 * MT, 20 * MT), side=1)
    battle.step()
    assert ground.hitpoints == hp[0] - 82
    assert air.hitpoints == hp[1]
    assert building.hitpoints == hp[2] - 287


def test_launched_spell_keeps_its_cast_point_while_targets_move():
    """Fireball prediction must be learned rather than made an instant hit."""
    from sim.spells import cast_spell, load_spells

    battle = _battle_with_spawns()
    victim = _spawn(battle, "giant", -1, 9, 20, 1)
    victim.speed_mt_per_sec = 0
    origin = Point(9 * MT, 28 * MT)
    fireball = load_spells(11)["fireball"]
    before = victim.hitpoints

    cast_spell(battle, fireball, victim.pos, side=1, origin=origin)
    assert victim.hitpoints == before
    assert battle.spell_impacts, "the projectile landed at cast time"
    victim.pos = Point(2 * MT, 20 * MT)
    _run(battle, 2)
    assert victim.hitpoints == before, "the projectile followed a moving target"


def test_royal_delivery_lands_after_three_seconds_then_deploys_recruit():
    from sim.spells import cast_spell, load_spells

    battle = _battle_with_spawns()
    victim = _spawn(battle, "giant", -1, 9, 20, 1)
    victim.speed_mt_per_sec = 0
    delivery = load_spells(11)["royal_delivery"]
    before = victim.hitpoints

    cast_spell(battle, delivery, victim.pos, side=1)
    _run(battle, 2.95)
    assert victim.hitpoints == before
    assert not any(e.name == "delivery_recruit" for e in battle.entities.values())
    battle.step()
    assert victim.hitpoints == before - 384
    recruits = [e for e in battle.entities.values() if e.name == "delivery_recruit"]
    assert len(recruits) == 1
    # The resolving 50 ms simulation step has already elapsed.
    assert recruits[0].deploy_remaining_ms == 200


def test_a_spell_that_makes_units_makes_units():
    """A Goblin Barrel is three goblins and no damage at all."""
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    barrel = load_spells(11)["goblin_barrel"]
    assert barrel.spawn_character and barrel.spawn_count == 3

    apply_spell(battle, barrel, Point(9 * MT, 8 * MT), side=1)
    spawned = [e.name for e in battle.entities.values()]
    assert len(spawned) == 3, spawned
    assert all(name == "goblin" for name in spawned), spawned


@pytest.mark.parametrize("spell,expected_pct", [("freeze", -100), ("snowball", -30)])
def test_a_spell_hands_out_its_buff(spell, expected_pct):
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    victim = battle.add(make_unit(1, ALL["knight"].unit, -1, Point(9 * MT, 20 * MT)))
    victim.deploy_remaining_ms = 0

    spec = load_spells(11)[spell]
    apply_spell(battle, spec, Point(9 * MT, 20 * MT), side=1)
    assert victim.buffed(battle.now_ms), spell
    assert victim.buff_speed_pct == expected_pct, (spell, victim.buff_speed_pct)


@pytest.mark.parametrize("spell", ["poison", "tornado", "earthquake"])
def test_a_lingering_spell_keeps_hurting_what_stands_in_it(spell):
    """Applied once on landing, Poison is a weak Fireball.

    The card is eight seconds of 36 a second. The damage and the slow are not
    in the area's own section at all - they are in a BUFF section beside it,
    which is why every lingering spell loaded as an inert circle.
    """
    from sim.spells import apply_spell, load_spells

    spec = load_spells(11)[spell]
    assert spec.damage_per_second > 0 and spec.life_duration_ms > 0

    battle = _battle_with_spawns()
    victim = battle.add(make_unit(1, ALL["giant"].unit, -1, Point(9 * MT, 20 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = 0
    before = victim.hitpoints

    apply_spell(battle, spec, Point(9 * MT, 20 * MT), side=1)
    _run(battle, (spec.life_duration_ms + 1000) / 1000.0)

    dealt = before - victim.hitpoints
    expected = spec.damage_per_second * spec.life_duration_ms // 1000
    assert abs(dealt - expected) <= spec.damage_per_second, (dealt, expected)


def test_a_lingering_spell_stops_when_it_expires():
    """It must not keep ticking for the rest of the match."""
    from sim.spells import apply_spell, load_spells

    spec = load_spells(11)["poison"]
    battle = _battle_with_spawns()
    victim = battle.add(make_unit(1, ALL["giant"].unit, -1, Point(9 * MT, 20 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = 0

    apply_spell(battle, spec, Point(9 * MT, 20 * MT), side=1)
    _run(battle, (spec.life_duration_ms + 1000) / 1000.0)
    settled = victim.hitpoints
    _run(battle, 5)
    assert victim.hitpoints == settled, "poison outlived its duration"


def test_a_graveyard_drips_skeletons_for_its_whole_life():
    from sim.spells import apply_spell, load_spells

    spec = load_spells(11)["graveyard"]
    assert spec.area_spawn_character == "Skeleton"

    battle = _battle_with_spawns()
    apply_spell(battle, spec, Point(9 * MT, 10 * MT), side=1)
    _run(battle, (spec.life_duration_ms + 500) / 1000.0)

    spawned = [e.name for e in battle.entities.values()]
    assert len(spawned) == 12, spawned
    assert all(name == "skeleton" for name in spawned), sorted(set(spawned))


def test_three_skeletons_dropped_centrally_split_between_lanes():
    """Good players get most of the card's value out of exactly this.

    The formation radius was hard-coded at 350 millitiles, half the 700 that
    Skeletons and Barbarians both carry as SummonRadius on their card row - a
    field on the spell rather than the character, which is why it was never
    read. At half spacing the squad clumped and all three chased one tower.
    """
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(11), DECK_26)
    assert cards["skeletons"].summon_radius_mt == 700

    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=3,
                  spells=load_spells(11))
    match.players[1].hand = ["skeletons"] + list(DECK_26)[:3]
    match.players[1].elixir = 10_000

    # the true centre line, which no whole grid cell sits on
    assert match.play_card(1, "skeletons", Point(9 * MT, 17 * MT + MT // 2))
    _run(match.battle, 0)
    for _ in range(int(1600 / TICK_MS)):
        match.step()

    left, right = match.towers[-1]["left"], match.towers[-1]["right"]
    picked = set()
    for entity in match.battle.entities.values():
        if entity.name != "skeleton":
            continue
        target = match.battle.get(entity.target_uid)
        picked.add("left" if target is left else "right" if target is right else "other")
    assert picked == {"left", "right"}, picked


def test_a_unit_walks_around_a_building_in_its_way():
    """Making buildings solid without this left units grinding into them.

    A Royal Giant behind a tower simply stopped, where the real game walks it
    round. This is not a pathfinder - it only asks whether something solid it
    did not come for is directly ahead, and steps sideways if so.
    """
    from sim.entities import make_tower

    battle = Battle()
    blocker = battle.add(make_tower(1, 1, Point(9 * MT, 20 * MT), 3346, 119, 800, 7500))
    goal = battle.add(make_tower(2, 1, Point(9 * MT, 14 * MT), 3346, 119, 800, 7500))
    giant = battle.add(make_unit(3, ALL["royal_giant"].unit, -1, Point(9 * MT, 26 * MT)))
    giant.deploy_remaining_ms = 0
    giant.target_uid = goal.uid
    start = distance(giant.pos, goal.pos)

    _run(battle, 30)
    assert distance(giant.pos, goal.pos) < start - 3 * MT, "stuck on the blocker"


def test_the_river_is_terrain_and_the_bridges_are_the_way_through():
    """Crossing is a property of the map, not a rule in the movement code.

    The engine used to detour units to a bridge explicitly. Now the river is
    simply impassable and the bridges are not, so a unit crosses at a bridge
    because there is nowhere else to cross.
    """
    from sim import pathfind

    assert not pathfind.walkable(9, 15), "mid-lane river should be impassable"
    assert not pathfind.walkable(9, 16)
    assert pathfind.walkable(3, 15), "left bridge should be walkable"
    assert pathfind.walkable(14, 16), "right bridge should be walkable"

    # a route exists from deep in one half to deep in the other
    field = pathfind.distance_field(3, 7)
    assert field[26][9] > 0, "no route across the river at all"


def test_a_path_across_the_river_goes_through_a_bridge():
    from sim import pathfind
    from sim.arena import MT

    pos = Point(9 * MT + 500, 26 * MT + 500)
    goal = Point(3 * MT + 500, 7 * MT + 500)
    seen = []
    for _ in range(120):
        step = pathfind.next_step(pos, goal)
        if step is None:
            break
        seen.append((step.x // MT, step.y // MT))
        pos = step
    crossed = [(tx, ty) for tx, ty in seen if ty in (15, 16)]
    assert crossed, "never crossed the river"
    assert all(pathfind.walkable(tx, ty) for tx, ty in crossed), crossed


def test_a_royal_ghost_cannot_be_targeted_while_it_is_invisible():
    """A spell aimed at a vanished Ghost hits nothing. That is the card."""
    spec = ALL["ghost"].unit
    assert spec.invisible_after_ms > 0

    battle = Battle()
    ghost = battle.add(make_unit(1, spec, 1, Point(9 * MT, 20 * MT)))
    hunter = battle.add(make_unit(2, ALL["musketeer"].unit, -1, Point(9 * MT, 23 * MT)))
    for entity in (ghost, hunter):
        entity.deploy_remaining_ms = 0
    ghost.speed_mt_per_sec = hunter.speed_mt_per_sec = 0

    locked_ms = 0
    for _ in range(int(4000 / TICK_MS)):
        battle.step()
        if hunter.target_uid == ghost.uid:
            locked_ms += TICK_MS

    assert ghost.invisible(battle.now_ms), "never went invisible"
    assert locked_ms < 4000, "was targetable for the whole test"


def test_an_electro_giant_shocks_everything_around_it_not_just_its_attacker():
    """Which is why piling melee onto one is a mistake."""
    spec = ALL["electro_giant"].unit
    assert spec.reflect_damage > 0 and spec.reflect_radius_mt > 0

    battle = Battle()
    giant = battle.add(make_unit(1, spec, -1, Point(9 * MT, 20 * MT)))
    attacker = battle.add(make_unit(2, ALL["knight"].unit, 1, Point(9 * MT, 21 * MT)))
    bystander = battle.add(make_unit(3, ALL["knight"].unit, 1, Point(9 * MT, 19 * MT)))
    for entity in (giant, attacker, bystander):
        entity.deploy_remaining_ms = 0
    before_a, before_b = attacker.hitpoints, bystander.hitpoints

    _run(battle, 3)
    assert before_a - attacker.hitpoints > 0, "the attacker was not shocked"
    assert before_b - bystander.hitpoints > 0, "only the attacker was shocked"


def test_a_healing_buff_puts_hitpoints_back_and_never_overfills():
    """Healing is the third thing a buff can do, beside speed and attack rate.

    Reading buffs as a pair of movement numbers meant a Battle Healer and every
    evolution heal did nothing at all.
    """
    from sim.gamedata import load_buffs

    buffs = load_buffs()
    healing = [name for name, values in buffs.items() if values[2] > 0]
    assert healing, "no healing buffs parsed at all"
    assert buffs["Freeze"] == (-100, -100, 0)

    battle = Battle()
    hurt = battle.add(make_unit(1, ALL["knight"].unit, 1, Point(9 * MT, 20 * MT)))
    hurt.deploy_remaining_ms = 0
    hurt.hitpoints = hurt.max_hitpoints // 2
    hurt.buff_until_ms = 10_000
    hurt.buff_heal_per_second = 100
    before = hurt.hitpoints

    _run(battle, 2)
    assert hurt.hitpoints > before, "the heal did nothing"

    hurt.hitpoints = hurt.max_hitpoints
    _run(battle, 2)
    assert hurt.hitpoints == hurt.max_hitpoints, "healed past full"


def test_buff_fields_are_read_from_their_own_line():
    """Searching for SpeedMultiplier also matches HitSpeedMultiplier.

    Unanchored, any buff that sets the two differently read one number twice.
    Archer Queen's client multiplier is 280% attack speed (+180% as an engine
    delta) and -25 movement; the old unanchored parser applied one to both.
    Freeze and the slows hid the bug completely by setting both to one value,
    which is why it survived being 'verified' against them.
    """
    from sim.gamedata import load_buffs

    buffs = load_buffs()
    assert buffs["ArcherQueenRapid"][:2] == (-25, 180), buffs["ArcherQueenRapid"]
    assert buffs["Poison"][:2] == (-15, 0), buffs["Poison"]
    assert buffs["Freeze"][:2] == (-100, -100)

    differing = [v for v in buffs.values() if v[0] != v[1] and (v[0] or v[1])]
    assert len(differing) >= 10, "the two fields are suspiciously always equal"


def test_elixir_income_is_not_truncated_away():
    """A tick is 50ms and single elixir is one per 2800ms.

    The integer division gave 17 milli-elixir a tick where the true figure is
    17.857, so nearly 5% of all income was dropped on the floor - about three
    elixir a match, a whole extra card each. Both players being poorer than
    they should be makes every simulated match run long.
    """
    from sim.match import (DOUBLE_MS, SINGLE_MS, TRIPLE_MS, Match)
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    assert (SINGLE_MS, DOUBLE_MS, TRIPLE_MS) == (2800, 1400, 933)

    cards = resolve_deck(load_gamedata(11), DECK_26)
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=1,
                  spells=load_spells(11))

    gained = 0
    for _ in range(int(60_000 / TICK_MS)):
        match.players[1].elixir = 0
        match._regen(TICK_MS)
        gained += match.players[1].elixir

    expected = 60_000 * 1000 // SINGLE_MS
    assert abs(gained - expected) < 100, (gained, expected)


def test_a_champion_ability_is_an_explicit_paid_action():
    """Policies choose the timing; the simulator must not press it for them."""
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["archer_queen"] = ALL["archer_queen"]
    spec = cards["archer_queen"].unit
    assert spec.ability_buff == "ArcherQueenRapid" and spec.ability_cost == 1

    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=3,
                  spells=load_spells(11))
    match.players[1].hand = ["archer_queen"] + list(DECK_26)[:3]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "archer_queen", grid_to_point(3, 18, 1))
    queen = [e for e in match.battle.entities.values()
             if e.name == "archer_queen"][0]

    before = match.players[1].elixir
    for _ in range(int(2_000 / TICK_MS)):
        match.step()
    assert not queen.ability_used, "the simulator pressed an RL action itself"
    assert match.can_activate_ability(1, queen.uid)
    assert match.activate_ability(1, queen.uid)
    assert queen.ability_used
    assert match.players[1].elixir < before, "the ability was free"
    assert queen.buff_hit_speed_pct == 180, queen.buff_hit_speed_pct
    assert queen.buff_speed_pct == -25, "she should be slower while firing fast"
    assert queen.invisible(match.battle.now_ms), "Archer Queen's ability buff is invisible"


def test_mirror_replays_the_last_card_dearer_and_a_level_up():
    """Mirror is a rule, not a card, which is why it has no data file.

    It replays whatever that player put down last, for one more elixir and at
    one level higher. Nothing about it needs stats of its own - the copy is the
    original card built a level up.
    """
    from sim.adapter import grid_to_point
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["mirror"] = ALL["mirror"]
    deck = list(DECK_26)
    match = Match(cards=cards, decks=(deck, deck), seed=3, spells=load_spells(11))
    match.players[1].hand = ["hog_rider", "mirror"] + deck[:2]
    match.players[1].elixir = 10_000

    assert not match.can_play(1, "mirror"), "mirrored nothing at all"

    assert match.play_card(1, "hog_rider", grid_to_point(3, 17, 1))
    spec, cost = match.mirrored(1)
    assert spec.name == "hog_rider"
    assert cost == cards["hog_rider"].cost + 1, cost

    before = match.players[1].elixir
    assert match.play_card(1, "mirror", grid_to_point(14, 17, 1))
    assert (before - match.players[1].elixir) // 1000 == cost

    hogs = [e for e in match.battle.entities.values() if e.name == "hog_rider"]
    assert len(hogs) == 2, len(hogs)
    assert hogs[1].max_hitpoints > hogs[0].max_hitpoints, "copy was not a level up"

    # a second Mirror must copy the Hog again, not copy the Mirror
    assert match.mirrored(1)[0].name == "hog_rider"


def test_goblin_curse_turns_what_dies_in_it():
    """The card is the conversion, not the chip damage.

    Goblin Curse's level-one data scales to 35 damage a second at level 11.
    What it actually
    does is written in its buff: DeathSpawn a goblin, DeathSpawnIsEnemy so it
    belongs to whoever cast it, DeathSpawnSameLocation so it appears where the
    victim fell - which can be at the enemy king tower.
    """
    from sim.spells import apply_spell, load_spells

    curse = load_spells(11)["goblin_curse"]
    assert curse.damage_per_second == 35, curse.damage_per_second
    assert not curse.initial_damage
    assert curse.convert_character, "no conversion read from the data"

    battle = _battle_with_spawns()
    victim = battle.add(make_unit(0, ALL["knight"].unit, -1, Point(9 * MT, 8 * MT)))
    victim.deploy_remaining_ms = 0

    apply_spell(battle, curse, Point(9 * MT, 8 * MT), side=1)
    battle.step()
    assert victim.cursed_by_side == 1, "the curse did not take"

    victim.hitpoints = 0
    battle.step()

    ours = [e for e in battle.entities.values() if e.side == 1 and e.alive]
    assert len(ours) == 1, [e.name for e in ours]
    # The client spawns the EXT GoblinCurseGoblin form, which inherits Goblin
    # combat data but retains a distinct identity for downstream effects.
    assert ours[0].name == "goblin_curse_goblin", ours[0].name
    # deep in the enemy half, where it died
    assert ours[0].pos.y < 12 * MT, ours[0].pos.y


def test_client_hero_form_is_not_collapsed_to_its_base_card():
    """Hero cards use the client's SPELL_HERO + EXT overlay, not a Knight."""
    hero = ALL["knight_hero"]
    assert hero.form == "HeroForm"
    assert hero.cost == 3
    assert hero.unit is not None
    assert hero.unit.name == "knight_hero"
    # The overlay's hero shield and ability are distinct from the normal
    # Knight, proving the loader did not silently substitute its base data.
    assert hero.unit.shield_hitpoints > ALL["knight"].unit.shield_hitpoints
    assert hero.unit.ability_cost == 2


def test_hero_knight_action_graph_starts_shieldless_then_rearms_shield():
    from sim.match import Match

    cards = {"knight_hero": ALL["knight_hero"]}
    match = Match(cards=cards,
                  decks=(["knight_hero"] * 8, ["knight_hero"] * 8), seed=1)
    player = match.players[1]
    player.hand = ["knight_hero"]
    player.elixir = 10_000
    assert match.play_card(1, "knight_hero", Point(9 * MT, 25 * MT))
    hero = next(e for e in match.battle.entities.values() if e.side == 1 and not e.is_tower)
    hero.deploy_remaining_ms = 0
    assert hero.shield_hitpoints == 0  # OnStartingAction -> ActionSetShield 0
    assert match.activate_ability(1, hero.uid)
    _run(match.battle, 0.15)
    assert hero.shield_hitpoints == hero.shield_max_hitpoints > 0


def test_evolution_catalogue_uses_client_declared_variant_edges():
    from sim.evolutions import catalogue
    variants = catalogue()
    assert variants["archer"] == ("archer_ev1",)
    assert "knight_ev1" in variants["knight"]


def test_public_evolutions_are_materialized_with_client_cycle_costs():
    evolved = {name: card for name, card in ALL.items()
               if card.form == "Evolution"}
    assert len(evolved) >= 40
    assert evolved["knight_ev1"].unit.name == "knight_ev1"
    assert evolved["knight_ev1"].evolution_cycles == 2
    assert evolved["pekka_ev1"].evolution_cycles == 1


def test_equipped_evolution_replaces_the_play_after_its_declared_cycles():
    from sim.match import Match

    cards = {"knight": ALL["knight"], "knight_ev1": ALL["knight_ev1"]}
    match = Match(cards=cards,
                  decks=(["knight"] * 8, ["knight"] * 8), seed=1,
                  evolution_slots={1: {"knight": "knight_ev1"}})
    player = match.players[1]
    player.elixir = 10_000
    for index in range(3):
        player.hand = ["knight"]
        assert match.play_card(1, "knight", Point((7 + index) * MT, 25 * MT))
        player.elixir = 10_000

    names = [e.name for e in match.battle.entities.values()
             if e.side == 1 and not e.is_tower]
    assert names == ["knight", "knight", "knight_ev1"]
    assert player.evolution_progress["knight"] == 0


def test_zap_evolution_uses_two_client_declared_pulses_and_radii():
    from sim.spells import apply_spell, load_spells

    spells = load_spells(11)
    evolved = spells["zap_ev1"]
    battle = _battle_with_spawns()
    inner = _spawn(battle, "giant", -1, 9, 20, 1)
    outer = _spawn(battle, "giant", -1, 12.5, 20, 2)
    for unit in (inner, outer):
        unit.speed_mt_per_sec = 0
    before = inner.hitpoints, outer.hitpoints

    apply_spell(battle, evolved, Point(9 * MT, 20 * MT), side=1)
    _run(battle, 1.6)
    assert inner.hitpoints == before[0] - 2 * spells["zap"].damage
    assert outer.hitpoints == before[1] - spells["zap"].damage


def test_little_prince_guardienne_ability_uses_source_delayed_guard_event():
    from sim.match import Match

    cards = {"little_prince": ALL["little_prince"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["little_prince"] * 8, ["knight"] * 8), seed=4)
    match.players[1].hand = ["little_prince"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "little_prince", Point(9 * MT, 24 * MT))
    prince = next(e for e in match.battle.entities.values()
                  if e.side == 1 and not e.is_tower)
    prince.deploy_remaining_ms = 0
    target = match.battle.add(make_unit(0, ALL["knight"].unit, -1,
                                         Point(9 * MT, 20 * MT)))
    target.deploy_remaining_ms = 0
    prince.target_uid = target.uid
    before = target.hitpoints
    assert match.activate_ability(1, prince.uid)
    assert not any(e.name == "champion_guard" for e in match.battle.entities.values())
    for _ in range(60):
        match.step()
    assert any(e.name == "champion_guard" and e.side == 1
               for e in match.battle.entities.values())
    assert target.hitpoints < before


def test_goblin_curse_uses_the_current_source_verified_slowdown():
    from sim.spells import apply_spell, load_spells

    curse = load_spells(11)["goblin_curse"]
    assert curse.area_speed_pct == -15
    battle = _battle_with_spawns()
    victim = _spawn(battle, "knight", -1, 9, 20, 1)
    apply_spell(battle, curse, Point(9 * MT, 20 * MT), side=1)
    battle.step()
    assert victim.buff_speed_pct == -15 and victim.buffed(battle.now_ms)


def test_spell_radii_are_read_from_the_right_field():
    """Third appearance of one bug: an unanchored key lookup.

    Searching a section for "Radius" also matches ProjectileStartRadius and
    DeflectRadius, so Fireball came out with a 0.7 tile blast instead of 2.5
    and Rocket 1.0 instead of 2.0. The Log states its width as ProjectileRadius
    rather than Radius, so it needs the fallback as well.
    """
    from sim.spells import load_spells

    spells = load_spells(11)
    assert spells["fireball"].radius_mt == 2500, spells["fireball"].radius_mt
    assert spells["rocket"].radius_mt == 2000, spells["rocket"].radius_mt
    assert spells["zap"].radius_mt == 2500
    assert spells["the_log"].radius_mt == 1950, spells["the_log"].radius_mt
    assert spells["the_log"].radius_y_mt == 600, "the Log is a shallow band"


def test_lightning_selects_only_the_three_highest_current_hp_targets():
    """Lightning is targeted, not an ordinary circle AOE.

    The AEO supplies its 3.5-tile selection circle while the linked projectile
    supplies damage and ZapFreeze. Losing either half made the spell look like
    a radius-less Fireball in the simulator.
    """
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    units = [_spawn(battle, "knight", -1, 6 + index * 2, 20, index + 1)
             for index in range(4)]
    for index, unit in enumerate(units):
        unit.hitpoints = 100 + index * 100
        unit.max_hitpoints = unit.hitpoints
        unit.speed_mt_per_sec = 0
    before = [unit.hitpoints for unit in units]

    lightning = load_spells(11)["lightning"]
    assert lightning.radius_mt == 3500
    assert lightning.target_limit == 3 and lightning.target_highest_hitpoints
    apply_spell(battle, lightning, Point(9 * MT, 20 * MT), side=1)
    _run(battle, 1.5)

    assert units[0].hitpoints == before[0], "lowest HP target was struck"
    assert all(unit.hitpoints < hp for unit, hp in zip(units[1:], before[1:]))


def test_vines_selects_three_targets_and_applies_its_snare_area():
    """Vines follows its action graph: 3 high-HP targets, 2 seconds of snare."""
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    units = [_spawn(battle, "knight", -1, 8 + index, 20, index + 1)
             for index in range(4)]
    for index, unit in enumerate(units):
        unit.hitpoints = 100 + index * 100
        unit.max_hitpoints = unit.hitpoints
        unit.speed_mt_per_sec = 0

    vines = load_spells(11)["vines"]
    assert vines.target_limit == 3 and vines.life_duration_ms == 2000
    assert vines.damage_per_second > 0
    apply_spell(battle, vines, Point(9 * MT, 20 * MT), side=1)
    _run(battle, 0.1)

    assert not units[0].buffed(battle.now_ms), "Vines hit a fourth target"
    assert all(unit.buffed(battle.now_ms) for unit in units[1:])
    assert all(unit.buff_speed_pct == -100 and unit.buff_hit_speed_pct == -100
               for unit in units[1:])


def test_vines_grounds_air_targets_for_ground_attackers():
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    knight = _spawn(battle, "knight", 1, 9, 20, 1)
    minions = _spawn(battle, "minions", -1, 9, 21, 2)
    knight.speed_mt_per_sec = minions.speed_mt_per_sec = 0
    assert not knight.is_valid_target(minions, battle.now_ms)
    apply_spell(battle, load_spells(11)["vines"], Point(9 * MT, 21 * MT), side=1)
    _run(battle, 0.1)
    assert minions.grounded_until_ms > battle.now_ms
    assert knight.is_valid_target(minions, battle.now_ms)


def test_clone_makes_one_hitpoint_friendly_troops_only_once():
    """Clone keeps a troop's mechanics but never creates clone recursion."""
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    knight = _spawn(battle, "knight", 1, 9, 20, 1)
    enemy = _spawn(battle, "knight", -1, 9, 20, 2)
    clone = load_spells(11)["clone"]
    assert clone.clone and clone.only_own_troops and clone.radius_mt == 3000

    apply_spell(battle, clone, Point(9 * MT, 20 * MT), side=1)
    copies = [entity for entity in battle.entities.values() if entity.side == 1]
    assert len(copies) == 2
    copied = next(entity for entity in copies if entity is not knight)
    assert copied.hitpoints == copied.shield_hitpoints == 1 and copied.is_clone
    assert enemy.hitpoints == enemy.max_hitpoints

    apply_spell(battle, clone, Point(9 * MT, 20 * MT), side=1)
    assert len([entity for entity in battle.entities.values() if entity.side == 1]) == 3


def test_void_recomputes_its_damage_tier_for_each_wave():
    """Void is source-backed: fewer targets means a stronger wave."""
    from sim.spells import apply_spell, load_spells

    battle = _battle_with_spawns()
    first = _spawn(battle, "knight", -1, 9, 20, 1)
    second = _spawn(battle, "knight", -1, 10, 20, 2)
    for unit in (first, second):
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
        unit.hitpoints = unit.max_hitpoints = 10_000

    void = load_spells(11)["dark_magic"]
    assert void.waves == 3 and void.damage_by_target_count == (696, 294, 153)
    apply_spell(battle, void, Point(9 * MT, 20 * MT), side=1)
    battle.step()
    assert first.hitpoints == second.hitpoints == 10_000 - 294

    second.hitpoints = 0
    battle.step(1200)
    assert first.hitpoints == 10_000 - 294 - 696


def test_electro_wizard_uses_client_multitarget_and_character_stun_fields():
    """Electro Wizard's two beams and stun are on CHARACTER, not projectile."""
    battle = Battle()
    wizard = _spawn(battle, "electro_wizard", 1, 9, 20, 1)
    first = _spawn(battle, "knight", -1, 9, 21, 2)
    second = _spawn(battle, "knight", -1, 10, 21, 3)
    third = _spawn(battle, "knight", -1, 8, 21, 4)
    for entity in (wizard, first, second, third):
        entity.speed_mt_per_sec = 0
    before = {entity.uid: entity.hitpoints for entity in (first, second, third)}

    spec = ALL["electro_wizard"].unit
    assert spec.multiple_targets == 2 and spec.all_targets_hit
    assert spec.target_buff == "ZapFreeze" and spec.buff_time_ms == 500
    battle._deal_damage(wizard, first)

    hit = [entity for entity in (first, second, third)
           if entity.hitpoints < before[entity.uid]]
    assert [entity.uid for entity in hit] == [first.uid, second.uid]
    assert all(entity.buff_hit_speed_pct == -100 for entity in hit)


def test_electro_wizard_deployment_aeo_uses_its_source_action_graph():
    battle = Battle()
    wizard = _spawn(battle, "electro_wizard", 1, 9, 20, 1, ready=False)
    target = _spawn(battle, "knight", -1, 9, 21, 2)
    target.speed_mt_per_sec = 0
    spec = ALL["electro_wizard"].unit
    assert (spec.spawn_area_radius_mt, spec.spawn_area_buff,
            spec.spawn_area_buff_ms) == (3000, "ZapFreeze", 500)
    before = target.hitpoints

    _run(battle, (spec.deploy_time_ms + TICK_MS) / 1000)
    assert target.hitpoints == before - spec.spawn_area_damage
    assert target.buff_hit_speed_pct == -100
    assert wizard.spawn_area_done


def test_electro_dragon_chains_using_client_count_radius_and_stun():
    battle = Battle()
    dragon = _spawn(battle, "electro_dragon", 1, 9, 20, 1)
    first = _spawn(battle, "knight", -1, 9, 21, 2)
    second = _spawn(battle, "knight", -1, 10, 21, 3)
    third = _spawn(battle, "knight", -1, 11, 21, 4)
    fourth = _spawn(battle, "knight", -1, 16, 21, 5)
    for entity in (dragon, first, second, third, fourth):
        entity.speed_mt_per_sec = 0
    spec = ALL["electro_dragon"].unit
    assert (spec.chained_hit_count, spec.chained_hit_radius_mt,
            spec.target_buff, spec.buff_time_ms) == (3, 4000, "ZapFreeze", 500)
    before = {entity.uid: entity.hitpoints for entity in (first, second, third, fourth)}

    # The projectile must fly before the first and subsequent chain hits land.
    battle._deal_damage(dragon, first)
    assert all(entity.hitpoints == before[entity.uid]
               for entity in (first, second, third, fourth))
    _run(battle, 1.0)

    assert all(entity.hitpoints < before[entity.uid] for entity in (first, second, third))
    assert fourth.hitpoints == before[fourth.uid]
    assert all(entity.buff_hit_speed_pct == -100 for entity in (first, second, third))


def test_fisherman_hook_uses_special_range_projectile_and_drag_fields():
    battle = Battle()
    fisher = _spawn(battle, "fisherman", 1, 9, 20, 1)
    target = _spawn(battle, "giant", -1, 9, 14, 2)
    fisher.speed_mt_per_sec = target.speed_mt_per_sec = 0
    spec = ALL["fisherman"].unit
    assert (spec.special_min_range_mt, spec.special_range_mt,
            spec.special_load_time_ms, spec.pull_margin_mt) == (3500, 7000, 1300, 200)
    assert (spec.pull_speed_pct, spec.pull_buff_ms) == (-30, 1500)
    assert spec.pull_projectile_speed_mt_per_sec > 0
    assert spec.pull_target_speed_mt_per_sec > 0
    before = distance(fisher.pos, target.pos)

    fisher.windup_remaining_ms = 0
    fisher.target_uid = target.uid
    assert battle._attack(fisher, TICK_MS)
    assert battle.pull_flight, "the hook did not launch"
    _run(battle, 1.5)

    assert distance(fisher.pos, target.pos) < before
    assert not battle.pull_flight and not battle.active_pulls
    assert target.buff_speed_pct == target.buff_hit_speed_pct == -30


def test_magic_archer_non_homing_pierce_lands_and_is_recorded_for_calibration():
    """A non-homing shot both connects and keeps its launch record.

    This used to assert the opposite - that the engine holds a non-homing
    launch back from resolution "until a measured collision rule is
    available". That was not the conservative choice it looked like. In Clash
    Royale a shot that has left the attacker connects with what it was fired
    at; there is no spatial miss to model. Holding them back meant twenty-five
    shooters - Magic Archer, Princess, Bomber, Mortar, Firecracker, Hunter,
    Bowler among them - dealt no damage at all, which is a far larger error
    than placing an impact a few hundred millitiles from its true point.

    The launch record is still kept, because the swept-path geometry genuinely
    is unmeasured and the gated action graphs still need it. It is now a record
    of a resolved shot rather than a discarded one.
    """
    battle = Battle()
    archer = _spawn(battle, "elite_archer", 1, 9, 20, 1)
    first = _spawn(battle, "knight", -1, 9, 24, 2)
    behind = _spawn(battle, "knight", -1, 9, 27, 3)
    off_ray = _spawn(battle, "knight", -1, 12, 27, 4)
    for entity in (archer, first, behind, off_ray):
        entity.speed_mt_per_sec = 0
    spec = ALL["elite_archer"].unit
    assert spec.pierces and (spec.projectile_radius_mt, spec.projectile_range_mt) == (250, 11000)
    battle._deal_damage(archer, first)

    assert not spec.projectile_homing
    # Both pierced targets are in flight, and the one off the ray is not.
    assert {shot[2] for shot in battle.in_flight} == {first.uid, behind.uid}
    assert len(battle.unmodelled_projectiles) == 2
    assert {shot["target_uid"] for shot in battle.unmodelled_projectiles} == {
        first.uid, behind.uid}

    # And the damage actually arrives.
    hitpoints_before = {entity.uid: entity.hitpoints
                        for entity in (first, behind, off_ray)}
    _run(battle, 2)
    assert first.hitpoints < hitpoints_before[first.uid]
    assert behind.hitpoints < hitpoints_before[behind.uid]
    assert off_ray.hitpoints == hitpoints_before[off_ray.uid]


def test_ram_rider_is_an_attached_ram_and_independent_troop_targeting_bola():
    from sim.gamedata import load_characters, to_snake_case

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(to_snake_case(name)))
    ram = battle.add(make_unit(0, ALL["ram_rider"].unit, 1, Point(9 * MT, 20 * MT)))
    rider = next(entity for entity in battle.entities.values()
                 if entity.name == "ram_rider")
    enemy = _spawn(battle, "knight", -1, 9, 16, 3)
    enemy.speed_mt_per_sec = 0
    ram.deploy_remaining_ms = rider.deploy_remaining_ms = 0
    rider.windup_remaining_ms = 0
    assert rider.attached_to_uid == ram.uid
    assert rider.target_only_troops
    assert rider.is_valid_target(enemy, battle.now_ms)
    assert not rider.is_valid_target(_spawn(battle, "cannon", -1, 9, 16, 4), battle.now_ms)

    before = enemy.hitpoints
    rider.target_uid = enemy.uid
    assert battle._attack(rider, TICK_MS)
    _run(battle, 1.0)
    assert enemy.hitpoints < before and enemy.buff_speed_pct == -70

    ram.pos = Point(9 * MT, 19 * MT)
    battle.step()
    assert rider.pos == ram.pos


def test_mother_witch_buff_on_damage_converts_a_dead_target_to_voodoo_hog():
    from sim.gamedata import load_characters, to_snake_case

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(to_snake_case(name)))
    witch = _spawn(battle, "witch_mother", 1, 9, 20, 1)
    victim = _spawn(battle, "knight", -1, 9, 21, 2)
    witch.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    spec = ALL["witch_mother"].unit
    assert (spec.target_buff, spec.buff_time_ms) == ("VoodooCurse", 5000)
    victim.hitpoints = 1

    battle._deal_damage(witch, victim)
    _run(battle, 1.0)
    assert not victim.alive
    battle.step()
    hogs = [entity for entity in battle.entities.values()
            if entity.name == "voodoo_hog" and entity.side == 1]
    assert len(hogs) == 1


def test_golden_knight_ability_is_a_source_declared_explicit_dash_chain():
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["golden_knight"] = ALL["golden_knight"]
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)),
                  spells=load_spells(11))
    knight = match.battle.add(make_unit(0, ALL["golden_knight"].unit,
                                         1, Point(9 * MT, 20 * MT)))
    first = match.battle.add(make_unit(0, ALL["knight"].unit, -1,
                                       Point(9 * MT, 17 * MT)))
    second = match.battle.add(make_unit(0, ALL["knight"].unit, -1,
                                        Point(11 * MT, 17 * MT)))
    knight.deploy_remaining_ms = first.deploy_remaining_ms = second.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000
    spec = ALL["golden_knight"].unit
    assert (spec.ability_dash_range_mt, spec.ability_dash_count,
            spec.ability_dash_landing_ms) == (5500, 10, 200)
    assert match.can_activate_ability(1, knight.uid)
    assert match.activate_ability(1, knight.uid)
    _run(match.battle, 1.0)

    hits = [row for row in match.battle.damage_log if row[1] == knight.uid]
    assert [row[2] for row in hits[:2]] == [first.uid, second.uid]
    assert knight.ability_used and not knight.ability_dashing


def test_monk_explicit_ability_applies_its_client_damage_reduction_buff():
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["monk"] = ALL["monk"]
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)),
                  spells=load_spells(11))
    monk = match.battle.add(make_unit(0, ALL["monk"].unit, 1, Point(9 * MT, 20 * MT)))
    monk.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000
    spec = ALL["monk"].unit
    assert (spec.ability_buff, spec.ability_buff_ms, spec.ability_cost) == ("ShieldBoostMonk", 4000, 1)
    # Ability's Buff is ShieldBoostMonk, not the ability's own name: the
    # generic loader must follow that relation to apply the 65% reduction.
    assert match.activate_ability(1, monk.uid)
    assert monk.damage_reduction_pct == 0
    _run(match.battle, 0.90)
    assert monk.damage_reduction_pct == 0
    _run(match.battle, 0.05)
    assert monk.damage_reduction_pct == 65
    before = monk.hitpoints
    monk.take_damage(100)
    assert monk.hitpoints == before - 35


def test_monk_reflects_homing_projectiles_from_allies_in_aura():
    from sim.match import Match

    cards = {"monk": ALL["monk"], "musketeer": ALL["musketeer"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["monk"] * 8, ["musketeer"] * 8), seed=44)
    monk = match.battle.add(make_unit(
        0, ALL["monk"].unit, 1, Point(9 * MT, 20 * MT)))
    ally = match.battle.add(make_unit(
        0, ALL["knight"].unit, 1, Point(10 * MT, 20 * MT)))
    shooter = match.battle.add(make_unit(
        0, ALL["musketeer"].unit, -1, Point(9 * MT, 15 * MT)))
    for entity in (monk, ally, shooter):
        entity.deploy_remaining_ms = 0
        entity.speed_mt_per_sec = 0
        entity.attack_cooldown_ms = 99999
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    match.players[1].elixir = 10_000
    assert match.activate_ability(1, monk.uid)
    _run(match.battle, 0.95)
    before_ally, before_shooter = ally.hitpoints, shooter.hitpoints
    match.battle.in_flight.append([
        match.battle.now_ms + 50, shooter, ally.uid, shooter.damage])
    _run(match.battle, 0.05)
    assert ally.hitpoints == before_ally
    assert len(match.battle.in_flight) == 1
    return_arrival = match.battle.in_flight[0][0]
    while match.battle.now_ms < return_arrival:
        match.battle.step()
    assert shooter.hitpoints == before_shooter - shooter.damage


def test_cannon_cart_transforms_at_client_health_threshold_into_broken_cannon():
    from sim.gamedata import load_characters, to_snake_case

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(to_snake_case(name)))
    cart = battle.add(make_unit(0, ALL["moving_cannon"].unit, 1, Point(9 * MT, 20 * MT)))
    spec = ALL["moving_cannon"].unit
    assert (spec.transform_at_hp_pct, spec.transform_character) == (50, "BrokenCannon")
    cart.deploy_remaining_ms = 0
    cart.hitpoints = cart.max_hitpoints // 2

    battle.step()
    transformed = battle.get(cart.uid)
    assert transformed.name == "broken_cannon"
    assert transformed.is_building and transformed.speed_mt_per_sec == 0
    assert transformed.hitpoints == cart.hitpoints


def test_inferno_damage_stages_are_data_driven_and_stun_resets_the_beam():
    battle = Battle()
    inferno = _spawn(battle, "inferno_tower", 1, 9, 20, 1)
    target = _spawn(battle, "giant", -1, 9, 21, 2)
    inferno.deploy_remaining_ms = target.deploy_remaining_ms = 0
    spec = ALL["inferno_tower"].unit
    # The raw row is level-1 (62/331); the simulator uses the requested
    # tournament level, so stages must be scaled through the same path as
    # ordinary damage rather than copied as stale base values.
    assert (int(spec.raw["VariableDamage2"]), int(spec.raw["VariableDamage3"]),
            spec.variable_damage_time1_ms, spec.variable_damage_time2_ms) == (62, 331, 2000, 2000)
    assert spec.variable_damage2 > spec.damage and spec.variable_damage3 > spec.variable_damage2

    battle._deal_damage(inferno, target)
    assert target.hitpoints == target.max_hitpoints - spec.damage
    battle.now_ms = 2000
    battle._deal_damage(inferno, target)
    assert target.hitpoints == target.max_hitpoints - spec.damage - spec.variable_damage2
    battle._apply_buff(_spawn(battle, "electro_wizard", 1, 8, 20, 3), inferno)
    assert inferno.ramp_target_uid is None
    battle.now_ms = 2500
    battle._deal_damage(inferno, target)
    assert target.hitpoints == target.max_hitpoints - spec.damage - spec.variable_damage2 - spec.damage


def test_evolved_knight_fortification_uses_client_damage_reduction_and_range():
    battle = Battle()
    knight = _spawn(battle, "knight_ev1", 1, 9, 20, 1)
    assert ALL["knight_ev1"].unit.idle_damage_reduction_pct == 60

    battle.step()
    assert knight.damage_reduction_pct == 60
    before = knight.hitpoints
    knight.take_damage(100)
    assert knight.hitpoints == before - 40

    enemy = _spawn(battle, "knight", -1, 9, 19, 2)
    enemy.damage = 0
    _run(battle, 0.5)
    assert knight.damage_reduction_pct == 0


def test_evolved_barbarian_rages_itself_after_a_landed_hit():
    battle = Battle()
    barbarian = battle.add(make_unit(
        1, ALL["barbarians_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    target = _spawn(battle, "giant", -1, 9, 21, 2)
    barbarian.deploy_remaining_ms = 0
    spec = ALL["barbarians_ev1"].unit
    assert (spec.buff_after_hits_count, spec.buff_after_hits_time_ms,
            spec.buff_after_hits_speed_pct,
            spec.buff_after_hits_hit_speed_pct) == (1, 5000, 30, 30)

    battle._land(barbarian, target, barbarian.damage)
    assert barbarian.buff_until_ms == 5000
    assert (barbarian.buff_speed_pct, barbarian.buff_hit_speed_pct) == (30, 30)


def test_evolved_bat_on_hit_heal_scales_and_can_overheal_to_200_percent():
    battle = Battle()
    bat = battle.add(make_unit(
        1, ALL["bats_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    target = _spawn(battle, "giant", -1, 9, 21, 2)
    bat.deploy_remaining_ms = 0
    spec = ALL["bats_ev1"].unit
    assert (spec.buff_after_hits_count, spec.buff_after_hits_time_ms,
            spec.buff_after_hits_heal_per_second,
            spec.buff_after_hits_overheal_pct) == (1, 1000, 77, 200)

    battle._land(bat, target, bat.damage)
    assert bat.buff_max_hitpoints_pct == 200
    _run(battle, 1.0)
    assert bat.hitpoints > bat.max_hitpoints
    assert bat.hitpoints <= bat.max_hitpoints * 2


def test_evolved_skeleton_duplicates_on_hit_but_respects_group_cap():
    from sim.gamedata import load_characters, to_snake_case

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(to_snake_case(name)))
    skeleton = battle.add(make_unit(
        1, ALL["skeletons_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    target = _spawn(battle, "giant", -1, 9, 21, 2)
    skeleton.deploy_remaining_ms = 0
    spec = ALL["skeletons_ev1"].unit
    assert (spec.buff_after_hits_spawn_character,
            spec.buff_after_hits_spawn_count,
            spec.buff_after_hits_spawn_interval_ms,
            spec.group_max_size) == ("Skeleton_EV1", 1, 50, 8)

    for _ in range(10):
        battle._land(skeleton, target, skeleton.damage)
        battle.step()
    group = [entity for entity in battle.entities.values()
             if entity.alive and entity.spawn_group_uid == skeleton.spawn_group_uid]
    assert len(group) == 8


def test_evolved_goblin_barrel_spawns_real_and_current_decoy_goblins_opposite():
    from sim.gamedata import load_characters
    from sim.spells import apply_spell, load_spells

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    spell = load_spells(11)["goblin_barrel_ev1"]
    landing = Point(3 * MT, 10 * MT)
    apply_spell(battle, spell, landing, side=1)

    spawned = list(battle.entities.values())
    real = [entity for entity in spawned if entity.damage == 125]
    decoys = [entity for entity in spawned if entity.damage == 66]
    assert len(real) == len(decoys) == 3
    assert all(entity.pos.x < 9 * MT for entity in real)
    assert all(entity.pos.x > 9 * MT for entity in decoys)
    assert all(entity.deploy_remaining_ms == 1100 for entity in spawned)
    assert all(entity.max_hitpoints == 82 for entity in decoys)


def test_evolved_snowball_captures_rolls_damages_and_releases_with_slow():
    from sim.spells import apply_spell, load_spells

    battle = Battle()
    victim = _spawn(battle, "giant", -1, 9, 19, 1)
    victim.speed_mt_per_sec = victim.damage = 0
    spell = load_spells(11)["snowball_ev1"]
    assert (spell.rolling_range_mt, spell.rolling_speed_mt_per_sec,
            spell.radius_mt, spell.rolling_release_slow_pct,
            spell.rolling_release_slow_ms) == (4000, 5000, 2500, -35, 3000)

    before = victim.hitpoints
    apply_spell(battle, spell, Point(9 * MT, 20 * MT), side=1)
    battle.step()
    assert victim.spell_captured
    assert victim.hitpoints == before - 179
    _run(battle, 0.75)

    assert not victim.spell_captured
    assert victim.pos == Point(9 * MT, 16 * MT)
    assert victim.buff_speed_pct == victim.buff_hit_speed_pct == -35
    assert victim.buff_until_ms >= battle.now_ms + 2950


@pytest.mark.parametrize("victim_name, expected", [
    ("skeletons", 430), ("knight", 819), ("giant", 1551),
])
def test_evolved_pekka_heals_by_defeated_troop_max_hp_tier(victim_name, expected):
    battle = Battle()
    pekka = _spawn(battle, "pekka_ev1", 1, 9, 20, 1)
    victim = _spawn(battle, victim_name, -1, 9, 21, 2)
    spec = ALL["pekka_ev1"].unit
    assert (spec.kill_heal_thresholds, spec.kill_heal_amounts,
            spec.kill_heal_overheal_pct) == ((990, 1990), (430, 819, 1551), 150)
    pekka.hitpoints = pekka.max_hitpoints
    victim.hitpoints = 1

    battle._land(pekka, victim, pekka.damage)
    assert pekka.hitpoints == pekka.max_hitpoints + expected
    assert pekka.hitpoints <= pekka.max_hitpoints * 3 // 2


def test_current_evolved_witch_only_initial_four_skeletons_heal_on_death():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    witch = battle.add(make_unit(
        0, ALL["witch_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    witch.deploy_remaining_ms = 0
    assert witch.max_hitpoints == 1451
    assert (witch.owned_spawn_death_heal,
            witch.owned_spawn_death_heal_remaining,
            witch.owned_spawn_death_heal_overheal_pct) == (153, 4, 173)

    _run(battle, 1.1)
    first_wave = [entity for entity in battle.entities.values()
                  if entity.spawn_owner_uid == witch.uid]
    assert len(first_wave) == 4
    assert all(entity.owner_heal_on_death == 153 for entity in first_wave)
    assert witch.spawn_character == "Witch_EV1_Skeleton_Interval"
    assert witch.spawn_pause_ms == 7000

    witch.hitpoints = witch.max_hitpoints
    for skeleton in first_wave:
        skeleton.hitpoints = 0
    battle.step()
    assert witch.hitpoints == witch.max_hitpoints + 4 * 153

    _run(battle, 7.0)
    later = [entity for entity in battle.entities.values()
             if entity.spawn_owner_uid == witch.uid]
    assert len(later) == 4
    assert all(entity.owner_heal_on_death == 0 for entity in later)


def test_evolved_princess_death_creates_client_damage_and_slow_area():
    battle = Battle()
    princess = _spawn(battle, "princess_ev1", 1, 9, 20, 1)
    victim = _spawn(battle, "giant", -1, 9, 20, 2)
    victim.speed_mt_per_sec = victim.damage = 0
    spec = ALL["princess_ev1"].unit
    assert (spec.death_area_damage, spec.death_area_radius_mt,
            spec.death_area_duration_ms, spec.death_area_hit_frequency_ms,
            spec.death_area_speed_pct, spec.death_area_hit_speed_pct,
            spec.death_area_buff_linger_ms) == (169, 3000, 3500, 300, -30, -30, 1000)

    before = victim.hitpoints
    princess.hitpoints = 0
    battle.step()
    assert victim.hitpoints == before - 169
    assert len(battle.areas) == 1
    battle.step()
    assert victim.buff_speed_pct == victim.buff_hit_speed_pct == -30
    _run(battle, 3.5)
    assert not battle.areas


def test_evolved_royal_giant_attack_emits_source_centred_damage_push():
    battle = Battle()
    royal_giant = _spawn(battle, "royal_giant_ev1", 1, 9, 20, 1)
    building = _spawn(battle, "cannon", -1, 9, 15, 2)
    nearby = _spawn(battle, "knight", -1, 9, 19, 3)
    for entity in (royal_giant, building, nearby):
        entity.speed_mt_per_sec = 0
    spec = ALL["royal_giant_ev1"].unit
    assert (spec.attack_area_damage, spec.attack_area_radius_mt,
            spec.attack_area_pushback_mt) == (82, 3000, 1000)
    royal_giant.target_uid = building.uid
    royal_giant.windup_remaining_ms = 0
    before = nearby.hitpoints

    assert battle._attack(royal_giant, TICK_MS)
    assert nearby.hitpoints == before - 82
    assert nearby.pos == Point(9 * MT, 18 * MT)


def test_evolved_recruit_unlocks_client_charge_when_shield_breaks():
    battle = Battle()
    recruit = _spawn(battle, "royal_recruits_ev1", 1, 9, 20, 1)
    target = _spawn(battle, "cannon", -1, 9, 10, 2)
    spec = ALL["royal_recruits_ev1"].unit
    assert (spec.shield_lost_charge_range_mt, spec.charge_range_mt,
            spec.charge_speed_multiplier, spec.damage_special) == (2500, 0, 200, 266)

    recruit.take_damage(recruit.shield_hitpoints)
    assert recruit.shield_hitpoints == 0
    assert recruit.charge_range_mt == 2500
    recruit.target_uid = target.uid
    recruit.charge_distance_mt = 2490
    battle._move(recruit, TICK_MS)
    assert recruit.charging


def test_evolved_wall_breaker_death_explodes_and_spawns_contact_mini():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    wallbreaker = battle.add(make_unit(
        0, ALL["wallbreakers_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    victim = _spawn(battle, "knight", -1, 9, 21, 2)
    wallbreaker.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    spec = ALL["wallbreakers_ev1"].unit
    assert (spec.death_spawn_character, spec.death_spawn_count,
            spec.death_damage, spec.death_damage_radius_mt) == (
                "Wallbreaker_mini", 1, 192, 2000)

    before = victim.hitpoints
    wallbreaker.hitpoints = 0
    battle.step()
    assert victim.hitpoints == before - 192
    mini = next(entity for entity in battle.entities.values()
                if entity.name == "wallbreaker_mini")
    assert (mini.damage, mini.projectile_range_mt, mini.kamikaze) == (184, 1, True)

    mini.deploy_remaining_ms = 0
    mini.pos = victim.pos
    mini.target_uid = victim.uid
    mini.windup_remaining_ms = 0
    before = victim.hitpoints
    assert battle._attack(mini, TICK_MS)
    assert victim.hitpoints == before - 184
    assert not mini.alive


def test_evolved_wizard_shield_break_explodes_with_current_damage_and_push():
    battle = Battle()
    wizard = _spawn(battle, "wizard_ev1", 1, 9, 20, 1)
    victim = _spawn(battle, "knight", -1, 9, 19, 2)
    wizard.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    spec = ALL["wizard_ev1"].unit
    assert (spec.shield_hitpoints, spec.shield_lost_area_damage,
            spec.shield_lost_area_radius_mt,
            spec.shield_lost_area_pushback_mt) == (192, 281, 3000, 3000)

    before = victim.hitpoints
    wizard.take_damage(wizard.shield_hitpoints)
    assert wizard.shield_lost_effect_pending
    battle.step()
    assert victim.hitpoints == before - 281
    assert victim.pos.y == 16 * MT
    assert not wizard.shield_lost_effect_pending


def test_evolved_minion_horde_first_damage_triggers_three_second_ghost_state():
    battle = Battle()
    minion = _spawn(battle, "minion_horde_ev1", 1, 9, 20, 1)
    spec = ALL["minion_horde_ev1"].unit
    assert (spec.on_damage_invulnerable_ms, spec.on_damage_speed_pct,
            spec.on_damage_hit_speed_pct,
            spec.on_damage_invisible) == (3000, -33, -33, True)

    before = minion.hitpoints
    assert minion.take_damage(10) == 10
    battle.step()
    assert minion.hitpoints == before - 10
    assert minion.invisible(battle.now_ms)
    assert minion.buff_speed_pct == minion.buff_hit_speed_pct == -33
    protected = minion.hitpoints
    assert minion.take_damage(100) == 0
    assert minion.hitpoints == protected

    _run(battle, 3.0)
    assert not minion.invisible(battle.now_ms)
    assert minion.take_damage(10) == 10


def test_evolved_royal_ghost_starts_with_two_guardians_and_delayed_spawn_damage():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    ghost = battle.add(make_unit(
        0, ALL["ghost_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    spec = ALL["ghost_ev1"].unit
    assert (spec.starting_side_summons,
            spec.starting_side_summon_distance_mt,
            spec.starting_side_summon_damage,
            spec.starting_side_summon_radius_mt,
            spec.starting_side_summon_damage_delay_ms) == (
                ("Ghost_EV1_Summon_Left", "Ghost_EV1_Summon_Right"),
                2000, 82, 1000, 200)
    guardians = [entity for entity in battle.entities.values()
                 if entity.uid != ghost.uid]
    assert {entity.pos for entity in guardians} == {
        Point(7 * MT, 20 * MT), Point(11 * MT, 20 * MT)}
    assert all((entity.max_hitpoints, entity.damage,
                entity.deploy_remaining_ms) == (82, 82, 800)
               for entity in guardians)

    victim = _spawn(battle, "knight", -1, 7, 20, 10)
    victim.speed_mt_per_sec = victim.damage = 0
    before = victim.hitpoints
    _run(battle, 0.2)
    assert victim.hitpoints == before - 82


def test_evolved_archer_uses_current_power_shot_damage_beyond_four_point_five_tiles():
    spec = ALL["archer_ev1"].unit
    assert spec is not None
    assert (spec.damage, spec.far_attack_min_range_mt,
            spec.far_attack_damage, spec.range_mt,
            spec.projectile_homing) == (113, 4500, 140, 6000, True)

    near_battle = Battle()
    near_archer = _spawn(near_battle, "archer_ev1", 1, 9, 20, 1)
    near_target = _spawn(near_battle, "knight", -1, 9, 24, 2)
    before = near_target.hitpoints
    near_battle._deal_damage(near_archer, near_target)
    _run(near_battle, 0.5)
    assert near_target.hitpoints == before - 113

    far_battle = Battle()
    far_archer = _spawn(far_battle, "archer_ev1", 1, 9, 20, 1)
    far_target = _spawn(far_battle, "knight", -1, 9, 25, 2)
    before = far_target.hitpoints
    far_battle._deal_damage(far_archer, far_target)
    _run(far_battle, 0.6)
    assert far_target.hitpoints == before - 140


def test_evolved_ice_spirit_repeats_target_bound_area_freeze_after_three_seconds():
    battle = Battle()
    spirit = _spawn(battle, "ice_spirits_ev1", 1, 9, 20, 1)
    carrier = _spawn(battle, "knight", -1, 9, 21, 2)
    nearby = _spawn(battle, "knight", -1, 10, 21, 3)
    spirit.deploy_remaining_ms = carrier.deploy_remaining_ms = 0
    nearby.deploy_remaining_ms = 0
    spirit.speed_mt_per_sec = carrier.speed_mt_per_sec = nearby.speed_mt_per_sec = 0
    spec = ALL["ice_spirits_ev1"].unit
    assert spec is not None
    assert (spec.damage, spec.splash_radius_mt, spec.buff_time_ms,
            spec.projectile_area_damage, spec.projectile_area_radius_mt,
            spec.projectile_area_delay_ms, spec.projectile_area_buff,
            spec.projectile_area_buff_ms) == (
                110, 2000, 1100, 110, 2000, 3000, "Freeze", 1100)

    carrier_before, nearby_before = carrier.hitpoints, nearby.hitpoints
    battle._deal_damage(spirit, carrier)
    # _deal_damage is the projectile-level test hook; the normal _attack path
    # performs this kamikaze transition immediately after launching it.
    spirit.hitpoints = 0
    _run(battle, 0.2)
    assert carrier.hitpoints == carrier_before - 110
    assert nearby.hitpoints == nearby_before - 110
    assert carrier.buff_until_ms == battle.now_ms + 1050
    assert len(battle.projectile_area_events) == 1

    # The carrier moves before the delayed blast; the area follows it.
    carrier.pos = Point(12 * MT, 21 * MT)
    nearby.pos = Point(13 * MT, 21 * MT)
    carrier_before, nearby_before = carrier.hitpoints, nearby.hitpoints
    _run(battle, 3.0)
    assert carrier.hitpoints == carrier_before - 110
    assert nearby.hitpoints == nearby_before - 110
    assert carrier.buff_until_ms == battle.now_ms + 1050
    assert not battle.projectile_area_events


def test_evolved_goblin_giant_starts_permanent_goblin_stream_at_half_health():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    giant = battle.add(make_unit(
        0, ALL["goblin_giant_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    giant.deploy_remaining_ms = 0
    giant.speed_mt_per_sec = 0
    assert (giant.threshold_spawn_hp_pct,
            giant.threshold_spawn_character,
            giant.threshold_spawn_interval_ms,
            giant.threshold_spawn_behind_mt) == (50, "Goblin", 2200, 2500)

    giant.hitpoints = giant.max_hitpoints // 2 + 1
    battle.step()
    assert not giant.threshold_spawn_active
    giant.hitpoints -= 1
    battle.step()
    assert giant.threshold_spawn_active

    # Healing back above the threshold does not cancel an action graph that
    # has already started; the first interval still completes after 2.2s.
    giant.hitpoints = giant.max_hitpoints
    _run(battle, 2.15)
    assert not [unit for unit in battle.entities.values()
                if unit.name == "goblin"]
    battle.step()
    spawned = [unit for unit in battle.entities.values()
               if unit.name == "goblin"]
    assert len(spawned) == 1
    assert spawned[0].pos == Point(9 * MT, 22500)


def test_evolved_royal_hog_descends_then_deals_current_ground_only_landing_damage():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    hog = battle.add(make_unit(
        0, ALL["royal_hogs_ev1"].unit, 1, Point(9 * MT, 20 * MT)))
    ground_target = _spawn(battle, "knight", -1, 9, 21, 10)
    air_target = _spawn(battle, "minions", -1, 10, 21, 11)
    hog.deploy_remaining_ms = ground_target.deploy_remaining_ms = 0
    air_target.deploy_remaining_ms = 0
    hog.speed_mt_per_sec = ground_target.speed_mt_per_sec = 0
    air_target.speed_mt_per_sec = 0
    assert (hog.flying, hog.ground_on_damage_hp_pct, hog.ground_on_attack,
            hog.ground_transition_ms, hog.ground_character,
            hog.ground_landing_damage, hog.ground_landing_radius_mt) == (
                True, 99, True, 500, "RoyalHog_EV1_Grounded", 84, 2000)

    ground_before, air_before = ground_target.hitpoints, air_target.hitpoints
    hog.hitpoints = hog.max_hitpoints * 98 // 100
    battle.step()
    assert hog.grounding_due_ms == battle.now_ms + 500
    _run(battle, 0.45)
    assert battle.get(hog.uid).flying
    battle.step()
    grounded = battle.get(hog.uid)
    assert grounded is not None and grounded.name == "royal_hog_ev1__grounded"
    assert not grounded.flying
    assert ground_target.hitpoints == ground_before - 84
    assert air_target.hitpoints == air_before


def test_evolved_hunter_net_uses_current_cooldown_flight_snare_and_air_grounding():
    battle = Battle()
    hunter = _spawn(battle, "hunter_ev1", 1, 9, 20, 1)
    victim = _spawn(battle, "minions", -1, 9, 23, 2)
    ground_attacker = _spawn(battle, "knight", 1, 10, 23, 3)
    hunter.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    ground_attacker.deploy_remaining_ms = 0
    hunter.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    ground_attacker.speed_mt_per_sec = 0
    assert (hunter.damage, hunter.control_range_mt,
            hunter.control_initial_cooldown_ms, hunter.control_cooldown_ms,
            hunter.control_cast_ms, hunter.control_projectile_speed_mt_per_sec,
            hunter.control_duration_ms, hunter.control_grounds_air) == (
                84, 4000, 1000, 5000, 200, 10000, 3000, True)

    _run(battle, 0.95)
    assert not battle.control_in_flight
    battle.step()
    assert len(battle.control_in_flight) == 1
    assert hunter.control_next_ms == battle.now_ms + 5000
    assert hunter.control_cast_until_ms == battle.now_ms + 200

    # Three tiles of flight at 10 tiles/sec plus the 0.2-second cast.
    _run(battle, 0.45)
    assert victim.buff_until_ms == 0
    battle.step()
    assert victim.buff_speed_pct == victim.buff_hit_speed_pct == -100
    assert victim.buff_until_ms == battle.now_ms + 3000
    assert victim.grounded_until_ms == battle.now_ms + 3000
    assert ground_attacker.can_attack(victim, battle.now_ms)
    _run(battle, 3.0)
    assert not ground_attacker.can_attack(victim, battle.now_ms)


def test_evolved_baby_dragon_attack_refreshes_following_movement_only_wind():
    battle = Battle()
    dragon = _spawn(battle, "baby_dragon_ev1", 1, 9, 20, 1)
    ally = _spawn(battle, "knight", 1, 9, 18, 2)
    enemy = _spawn(battle, "knight", -1, 10, 22, 3)
    outside = _spawn(battle, "knight", -1, 9, 24, 4)
    other_evo = _spawn(battle, "baby_dragon_ev1", 1, 8, 18, 5)
    for unit in battle.entities.values():
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
        unit.damage = 0
    assert (dragon.wind_width_mt, dragon.wind_height_mt,
            dragon.wind_forward_offset_mt, dragon.wind_duration_ms,
            dragon.wind_after_death_ms, dragon.wind_ally_speed_pct,
            dragon.wind_enemy_speed_pct, dragon.wind_buff_linger_ms) == (
                8000, 9000, 1500, 6000, 2000, 30, -30, 100)

    battle._deal_damage(dragon, enemy)
    battle.step()
    assert ally.buff_speed_pct == 30
    assert enemy.buff_speed_pct == -30
    assert outside.buff_until_ms == 0
    assert dragon.buff_until_ms == 0
    assert other_evo.buff_until_ms == 0
    assert ally.buff_hit_speed_pct == enemy.buff_hit_speed_pct == 0

    # The rectangle follows its source and is capped to two seconds when the
    # source dies, even though six seconds remain since the attack.
    dragon.pos = Point(12 * MT, 20 * MT)
    ally.pos = Point(12 * MT, 18 * MT)
    battle.step()
    assert ally.buff_speed_pct == 30
    dragon.hitpoints = 0
    battle.step()
    assert battle.wind_areas[dragon.uid][1] == battle.now_ms + 2000
    _run(battle, 2.0)
    assert dragon.uid not in battle.wind_areas


def test_evolved_mega_knight_every_second_hit_uppercuts_over_declared_flight_time():
    battle = Battle()
    mega = _spawn(battle, "mega_knight_ev1", 1, 9, 16, 1)
    victim = _spawn(battle, "knight", -1, 9, 18, 2)
    tower = battle.add(make_tower(
        0, 1, Point(9 * MT, 24 * MT), 3000, 100, 1000, 7500))
    tower.damage = 0
    mega.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    assert (mega.uppercut_every_hits, mega.uppercut_push_mt,
            mega.uppercut_flight_ms, mega.uppercut_root_ms) == (
                2, 4000, 900, 400)

    battle._land(mega, victim, 1)
    assert not battle.forced_moves
    battle._land(mega, victim, 1)
    assert len(battle.forced_moves) == 1
    assert victim.forced_move_until_ms == 1300
    mega.deploy_remaining_ms = 999999

    _run(battle, 0.45)
    assert victim.pos == Point(9 * MT, 20 * MT)
    _run(battle, 0.45)
    assert victim.pos == Point(9 * MT, 22 * MT)
    assert not battle.forced_moves
    assert battle.now_ms < victim.forced_move_until_ms
    _run(battle, 0.4)
    assert battle.now_ms == victim.forced_move_until_ms


def test_evolved_electro_dragon_infinitely_repeats_with_reduced_fourth_bolt():
    battle = Battle()
    dragon = _spawn(battle, "electro_dragon_ev1", 1, 9, 20, 1)
    first = _spawn(battle, "knight", -1, 9, 21, 2)
    second = _spawn(battle, "knight", -1, 10, 21, 3)
    third = _spawn(battle, "knight", -1, 11, 21, 4)
    for unit in battle.entities.values():
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
    for unit in (first, second, third):
        unit.damage = 0
    assert (dragon.damage, dragon.chain_unlimited,
            dragon.chain_full_damage_hits, dragon.chain_reduced_damage,
            dragon.chain_reduced_speed_mt_per_sec,
            dragon.chain_repeat_memory) == (
                192, True, 3, 64, 6666, 2)
    before = {unit.uid: unit.hitpoints for unit in (first, second, third)}

    battle._deal_damage(dragon, first)
    dragon.deploy_remaining_ms = 999999
    _run(battle, 0.4)
    assert first.hitpoints == before[first.uid] - 192
    assert second.hitpoints == before[second.uid] - 192
    assert third.hitpoints == before[third.uid] - 192
    battle.step()  # fourth bolt revisits the first target at t=450ms
    assert first.hitpoints == before[first.uid] - 192 - 64
    assert first.buff_until_ms == 550  # fourth bolt did not refresh the stun
    assert battle.chain_projectiles  # a fifth bolt is still travelling


def test_evolved_inferno_dragon_retains_four_stage_heat_then_decays_or_resets():
    battle = Battle()
    dragon = _spawn(battle, "inferno_dragon_ev1", 1, 9, 20, 1)
    first = _spawn(battle, "knight", -1, 9, 18, 2)
    second = _spawn(battle, "knight", -1, 10, 18, 3)
    assert (dragon.persistent_ramp_damages,
            dragon.persistent_ramp_thresholds,
            dragon.persistent_ramp_decay_ms) == (
                (36, 120, 422, 845), (4, 9, 49), 7000)

    before = first.hitpoints
    for _ in range(3):
        battle._deal_damage(dragon, first)
    assert first.hitpoints == before - 3 * 36
    before = second.hitpoints
    battle._deal_damage(dragon, second)
    assert second.hitpoints == before - 120  # target change retained heat

    dragon.persistent_ramp_attack_count = 8
    before = second.hitpoints
    battle._deal_damage(dragon, second)
    assert second.hitpoints == before - 422
    dragon.persistent_ramp_attack_count = 48
    before = second.hitpoints
    battle._deal_damage(dragon, second)
    assert second.hitpoints == before - 845

    battle.now_ms += 7000
    before = first.hitpoints
    battle._deal_damage(dragon, first)
    assert first.hitpoints == before - 36
    dragon.persistent_ramp_attack_count = 10
    zapper = _spawn(battle, "electro_wizard", -1, 9, 19, 4)
    battle._apply_buff(zapper, dragon)
    assert dragon.persistent_ramp_attack_count == 0


def test_hero_ice_golem_paid_single_use_blizzard_has_three_current_slow_blasts():
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["ice_golemite_hero"] = ALL["ice_golemite_hero"]
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=7,
                  spells=load_spells(11))
    hero = match.battle.add(make_unit(
        0, ALL["ice_golemite_hero"].unit, 1, Point(9 * MT, 14 * MT)))
    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(10 * MT, 14 * MT)))
    hero.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    hero.damage = victim.damage = 0
    hero.damage = victim.damage = 0
    assert (hero.ability_cost, hero.ability_area_damage,
            hero.ability_area_radius_mt, hero.ability_area_pulse_times_ms,
            hero.ability_area_slow_pct, hero.ability_area_duration_ms,
            hero.ability_area_slow_linger_ms) == (
                2, 69, 4000, (50, 1550, 3050), -30, 3050, 2000)

    match.players[1].elixir = 10_000
    before_elixir = match.players[1].elixir
    before_hp = victim.hitpoints
    assert match.can_activate_ability(1, hero.uid)
    assert match.activate_ability(1, hero.uid)
    assert match.players[1].elixir == before_elixir - 2000
    assert not match.can_activate_ability(1, hero.uid)

    match.battle.step()
    assert victim.hitpoints == before_hp - 69
    assert victim.buff_speed_pct == victim.buff_hit_speed_pct == -30
    _run(match.battle, 1.5)
    assert victim.hitpoints == before_hp - 2 * 69
    _run(match.battle, 1.5)
    assert victim.hitpoints == before_hp - 3 * 69
    assert victim.buff_until_ms == match.battle.now_ms + 2000


def test_hero_musketeer_paid_ability_deploys_current_trusty_turret():
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["musketeer_hero"] = ALL["musketeer_hero"]
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=9,
                  spells=load_spells(11))
    hero = match.battle.add(make_unit(
        0, ALL["musketeer_hero"].unit, 1, Point(9 * MT, 14 * MT)))
    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 11 * MT)))
    hero.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    hero.damage = victim.damage = 0
    match.players[1].elixir = 10_000

    assert (hero.ability_cost, hero.ability_deploy_character,
            hero.ability_deploy_forward_mt, hero.ability_deploy_delay_ms,
            hero.ability_deploy_damage, hero.ability_deploy_radius_mt) == (
                3, "MusketeerTurret", 3000, 1000, 204, 2000)
    before = victim.hitpoints
    assert match.activate_ability(1, hero.uid)
    _run(match.battle, 0.95)
    assert not any(e.name == "musketeer_turret"
                   for e in match.battle.entities.values())
    _run(match.battle, 0.05)
    turrets = [e for e in match.battle.entities.values()
               if e.name == "musketeer_turret"]
    assert len(turrets) == 1
    turret = turrets[0]
    assert (turret.pos.x, turret.pos.y) == (9 * MT, 11 * MT)
    assert (turret.hitpoints, turret.damage, turret.hit_speed_ms,
            turret.range_mt, turret.lifetime_ms) == (1536, 148, 500, 4000, 10000)
    assert victim.hitpoints == before - 204


def test_mighty_miner_current_stages_and_explosive_escape_lane_mirror():
    from sim.match import Match
    from sim.runner import DECK_26, resolve_deck
    from sim.spells import load_spells

    cards = dict(resolve_deck(load_gamedata(11), DECK_26))
    cards["mighty_miner"] = ALL["mighty_miner"]
    match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)), seed=11,
                  spells=load_spells(11))
    miner = match.battle.add(make_unit(
        0, ALL["mighty_miner"].unit, 1, Point(3500, 20 * MT)))
    victim = match.battle.add(make_unit(
        0, ALL["baby_dragon"].unit, -1, Point(4500, 20 * MT)))
    miner.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    miner.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    miner.damage = victim.damage = 0
    match.players[1].elixir = 10_000

    assert (miner.hitpoints, miner.damage, miner.variable_damage2,
            miner.variable_damage3) == (2250, 0, 204, 409)
    # The base value is zeroed above solely to prevent an unrelated combat hit.
    assert ALL["mighty_miner"].unit.damage == 43
    before = victim.hitpoints
    assert match.activate_ability(1, miner.uid)
    assert miner.ability_digging
    _run(match.battle, 0.95)
    assert miner.pos == Point(3500, 20 * MT)
    assert victim.hitpoints == before
    _run(match.battle, 0.05)
    assert not miner.ability_digging
    assert miner.pos == Point(14500, 20 * MT)
    assert victim.hitpoints == before - 332
    assert not match.can_activate_ability(1, miner.uid)


def test_goblinstein_group_deploy_and_current_link_survives_monster_death():
    from sim.match import Match

    cards = {"goblinstein": ALL["goblinstein"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["goblinstein"] * 8, ["knight"] * 8), seed=13)
    match.players[1].hand = ["goblinstein"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "goblinstein", Point(3500, 20 * MT))
    monster = next(e for e in match.battle.entities.values()
                   if e.name == "goblinstein")
    doctor = next(e for e in match.battle.entities.values()
                  if e.name == "goblinstein_doctor")
    assert monster.spawn_group_uid == doctor.spawn_group_uid
    assert monster.pos == Point(3500, 20 * MT)
    assert doctor.pos == Point(4500, 20 * MT)  # one tile toward centre
    assert (monster.hitpoints, doctor.hitpoints, doctor.damage,
            doctor.ability_cost) == (2393, 721, 135, 2)

    monster.deploy_remaining_ms = doctor.deploy_remaining_ms = 0
    monster.speed_mt_per_sec = doctor.speed_mt_per_sec = 0
    monster.damage = doctor.damage = 0
    receiver = monster.pos
    monster.hitpoints = 0
    match.battle.step()
    assert monster.uid not in match.battle.entities
    assert match.battle.link_receivers[doctor.spawn_group_uid] == receiver

    victim = match.battle.add(make_unit(
        0, ALL["baby_dragon"].unit, -1, Point(4000, 20 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = victim.damage = 0
    for towers in match.towers.values():
        for tower in towers.values():
            tower.damage = 0
    before = victim.hitpoints
    assert match.activate_ability(1, doctor.uid)
    _run(match.battle, 0.45)
    assert victim.hitpoints == before
    _run(match.battle, 0.05)
    assert victim.hitpoints == before - 94
    _run(match.battle, 3.5)
    assert victim.hitpoints == before - 8 * 94


def test_hero_berserker_savage_survival_cast_and_current_bear_buff():
    from sim.match import Match

    cards = {"berserker_hero": ALL["berserker_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["berserker_hero"] * 8, ["knight"] * 8), seed=15)
    hero = match.battle.add(make_unit(
        0, ALL["berserker_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 19 * MT)))
    hero.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = victim.speed_mt_per_sec = 0
    victim.damage = 0
    match.players[1].elixir = 10_000
    for towers in match.towers.values():
        for tower in towers.values():
            tower.damage = 0

    assert (hero.damage, hero.ability_cost, hero.ability_cast_ms,
            hero.ability_buff_ms, hero.ability_damage_pct,
            hero.ability_tower_damage_pct) == (102, 3, 1450, 4000, 64, 25)
    assert match.activate_ability(1, hero.uid)
    assert hero.control_cast_until_ms == 1450
    assert hero.buff_until_ms == hero.unkillable_until_ms == 4000
    assert (hero.buff_speed_pct, hero.buff_hit_speed_pct) == (50, 200)

    before = victim.hitpoints
    match.battle._deal_damage(hero, victim)
    assert victim.hitpoints == before - 167
    tower = match.towers[-1]["left"]
    before_tower = tower.hitpoints
    match.battle._deal_damage(hero, tower)
    assert tower.hitpoints == before_tower - 41
    hero.take_damage(100_000)
    assert hero.hitpoints == 1
    _run(match.battle, 4.0)
    assert hero.unkillable_until_ms == 0
    hero.take_damage(1)
    assert not hero.alive


def test_current_spirits_cannot_acquire_towers_but_triggered_splash_reaches_one():
    for card in ("fire_spirits", "ice_spirits", "electro_spirit", "heal"):
        assert ALL[card].unit.hitpoints == 215
        assert ALL[card].unit.cannot_target_towers
    assert ALL["ice_spirits_ev1"].unit.hitpoints == 215
    assert ALL["ice_spirits_ev1"].unit.cannot_target_towers

    battle = Battle()
    spirit = _spawn(battle, "fire_spirits", 1, 9, 20, 1)
    troop = _spawn(battle, "knight", -1, 9, 19, 2)
    tower = battle.add(make_tower(
        3, -1, Point(9 * MT, 19 * MT), 3346, 119, 800, 7500))
    assert not spirit.is_valid_target(tower)
    before = tower.hitpoints
    battle._land(spirit, troop, spirit.damage)
    assert tower.hitpoints < before


def test_evolved_dart_goblin_target_poison_stacks_and_uses_tower_rule():
    """Pin the published 1/4/7 poison controller, not just the base dart."""
    battle = Battle()
    dart = _spawn(battle, "blowdart_goblin_ev1", 1, 9, 20, 1)
    carrier = _spawn(battle, "giant", -1, 9, 18, 2)
    support = _spawn(battle, "baby_dragon", -1, 10, 18, 3)
    for entity in (dart, carrier, support):
        entity.speed_mt_per_sec = entity.damage = 0

    spec = ALL["blowdart_goblin_ev1"].unit
    assert (spec.target_poison_damage_tiers,
            spec.target_poison_stack_thresholds,
            spec.target_poison_radius_mt,
            spec.target_poison_first_tick_ms) == (
                (64, 128, 307), (1, 4, 7), 1500, 1250)

    # Four darts are active only after their source-backed 1.25 s delay.
    for _ in range(4):
        battle._land(dart, carrier, 1)
    before_carrier, before_support = carrier.hitpoints, support.hitpoints
    _run(battle, 1.20)
    assert (carrier.hitpoints, support.hitpoints) == (
        before_carrier, before_support)
    _run(battle, 0.05)
    assert carrier.hitpoints == before_carrier - 128
    assert support.hitpoints == before_support - 128

    # A Crown Tower never advances beyond tier one and receives 25% (floor).
    tower_battle = Battle()
    tower_dart = _spawn(tower_battle, "blowdart_goblin_ev1", 1, 9, 20, 1)
    tower = tower_battle.add(make_tower(
        2, -1, Point(9 * MT, 18 * MT), 3346, 119, 800, 7500))
    tower_dart.speed_mt_per_sec = tower_dart.damage = tower.damage = 0
    for _ in range(7):
        tower_battle._land(tower_dart, tower, 1)
    before = tower.hitpoints
    _run(tower_battle, 1.25)
    assert tower.hitpoints == before - 16


def test_goblin_demolisher_transforms_at_half_health_and_explodes():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    demolisher = _spawn(battle, "goblin_demolisher", 1, 9, 20, 1)
    demolisher.speed_mt_per_sec = demolisher.damage = 0
    assert (demolisher.hitpoints, demolisher.transform_at_hp_pct,
            demolisher.transform_character) == (
                1300, 50, "GoblinDemolisher_kamikaze_form")

    demolisher.hitpoints = 650
    battle._tick_transformations()
    transformed = battle.get(demolisher.uid)
    assert transformed is not None
    assert transformed.name == "goblin_demolisher_kamikaze_form"
    assert transformed.hitpoints == 650
    assert (transformed.speed_mt_per_sec, transformed.target_only_buildings,
            transformed.kamikaze, transformed.lifetime_ms) == (
                speed_to_mt_per_sec(120), True, True, 10000)
    assert (transformed.death_damage, transformed.death_damage_radius_mt,
            transformed.death_damage_pushback_mt) == (404, 2500, 2000)

    victim = _spawn(battle, "knight", -1, 10, 20, 2)
    victim.speed_mt_per_sec = victim.damage = 0
    before = victim.hitpoints
    transformed.hitpoints = 0
    battle._reap()
    assert victim.hitpoints == before - 404
    assert victim.pos == Point(12 * MT, 20 * MT)


def test_evolved_musketeer_uses_three_forward_long_shots_not_crown_towers():
    battle = Battle()
    musketeer = _spawn(battle, "musketeer_ev1", 1, 9, 20, 1)
    first = _spawn(battle, "firecracker", -1, 9, 10, 2)
    second = _spawn(battle, "knight", -1, 10, 9, 3)
    outside_strip = _spawn(battle, "knight", -1, 13, 9, 4)
    for entity in (musketeer, first, second, outside_strip):
        entity.speed_mt_per_sec = entity.damage = 0

    assert (musketeer.sniper_ammo, musketeer.sniper_min_range_mt,
            musketeer.sniper_max_range_mt, musketeer.sniper_side_clip_mt,
            musketeer.sniper_damage) == (3, 6000, 30000, 1250, 392)
    battle._acquire_target(musketeer)
    assert musketeer.target_uid == first.uid
    battle._deal_damage(musketeer, first)
    assert musketeer.sniper_ammo == 2
    assert battle.in_flight[-1][3] == 392

    # IgnorePendingDamageTargets avoids wasting another sniper round on a
    # target already covered by lethal homing damage.
    musketeer.target_uid = None
    battle._acquire_target(musketeer)
    assert musketeer.target_uid == second.uid
    assert musketeer.target_uid != outside_strip.uid

    tower_battle = Battle()
    tower_musketeer = _spawn(
        tower_battle, "musketeer_ev1", 1, 9, 20, 1)
    tower = tower_battle.add(make_tower(
        2, -1, Point(9 * MT, 10 * MT), 3346, 119, 800, 7500))
    tower_musketeer.speed_mt_per_sec = tower_musketeer.damage = tower.damage = 0
    tower_battle._acquire_target(tower_musketeer)
    # The tower remains the ordinary across-arena movement fallback, not a
    # legal Long Shot target, so no ammo can be spent at this distance.
    assert tower_musketeer.target_uid == tower.uid
    assert not tower_battle._attack(tower_musketeer, TICK_MS)
    assert tower_musketeer.sniper_ammo == 3


def test_evolved_skeleton_army_general_preserves_then_reaps_spectrals():
    from sim.match import Match

    cards = {"skeleton_army_ev1": ALL["skeleton_army_ev1"]}
    match = Match(cards=cards,
                  decks=(["skeleton_army_ev1"] * 8,
                         ["skeleton_army_ev1"] * 8), seed=21)
    match.players[1].hand = ["skeleton_army_ev1"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "skeleton_army_ev1", Point(9 * MT, 20 * MT))

    soldiers = [entity for entity in match.battle.entities.values()
                if entity.name == "skeleton_army_ev1__soldier"]
    generals = [entity for entity in match.battle.entities.values()
                if entity.name == "skeleton_army_ev1__general"]
    assert len(soldiers) == 15
    assert len(generals) == 1
    general = generals[0]
    assert general.pos == Point(9 * MT, 21 * MT)
    assert (general.hitpoints, general.shield_hitpoints) == (82, 82)
    assert all(soldier.spawn_group_uid == general.spawn_group_uid
               for soldier in soldiers)

    soldier = soldiers[0]
    death_pos = soldier.pos
    soldier.hitpoints = 0
    match.battle._reap()
    spectral = next(entity for entity in match.battle.entities.values()
                    if entity.name == "skeleton_army_ev1__spectral")
    assert spectral.pos == death_pos
    assert spectral.spawn_group_uid == general.spawn_group_uid
    assert spectral.always_invisible and spectral.permanent_invulnerable
    before = spectral.hitpoints
    assert spectral.take_damage(100_000) == 0
    assert spectral.hitpoints == before

    general.hitpoints = 0
    match.battle._reap()
    assert not any(entity.name == "skeleton_army_ev1__spectral"
                   for entity in match.battle.entities.values())


def test_evolved_elite_barbarians_throw_rage_spears_then_melee():
    from sim.match import Match

    cards = {"angry_barbarians_ev1": ALL["angry_barbarians_ev1"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["angry_barbarians_ev1"] * 8,
                         ["knight"] * 8), seed=22)
    match.players[1].hand = ["angry_barbarians_ev1"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "angry_barbarians_ev1", Point(9 * MT, 20 * MT))
    ebarbs = sorted(
        [entity for entity in match.battle.entities.values()
         if entity.name.startswith("angry_barbarian_ev1")],
        key=lambda entity: entity.pos.x)
    assert len(ebarbs) == 2
    assert [entity.pos.x for entity in ebarbs] == [8300, 9700]
    assert [entity.load_time_ms for entity in ebarbs] == [850, 900]

    source = ebarbs[0]
    target = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(8300, 16 * MT)))
    ally = match.battle.add(make_unit(
        0, ALL["knight"].unit, 1, Point(8300, 18 * MT)))
    for entity in (source, target, ally):
        entity.deploy_remaining_ms = 0
        entity.speed_mt_per_sec = entity.damage = 0
    source.damage = 384
    source.target_uid = target.uid
    source.windup_remaining_ms = source.attack_cooldown_ms = 0
    before = target.hitpoints
    assert match.battle._attack(source, TICK_MS)
    assert source.periodic_ranged_next_ms == 5000
    _run(match.battle, 0.4)
    assert target.hitpoints == before - 284
    assert ally.buff_speed_pct == ally.buff_hit_speed_pct == 30
    assert ally.buff_until_ms > match.battle.now_ms

    # Inside the 3.5-tile spear minimum, attack-sequence index zero is a real
    # 384-damage melee strike and does not consume another spear.
    target.pos = Point(8300, 19 * MT)
    source.target_uid = target.uid
    source.windup_remaining_ms = source.attack_cooldown_ms = 0
    before = target.hitpoints
    assert match.battle._attack(source, TICK_MS)
    assert target.hitpoints == before - 384
    assert len(match.battle.rage_spears) == 0


def test_evolved_skeleton_barrel_drops_two_current_damage_containers():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    barrel = _spawn(battle, "skeleton_balloon_ev1", 1, 9, 20, 1)
    barrel.speed_mt_per_sec = 0
    first_centre = Point(8650, 20450)
    first_victim = _spawn(battle, "knight", -1, 8.65, 20.45, 2)
    first_victim.speed_mt_per_sec = first_victim.damage = 0
    assert (barrel.hitpoints, barrel.container_drop_hp_pct,
            barrel.container_drop_damage, barrel.container_drop_delay_ms,
            barrel.container_drop_spawn_count) == (666, 75, 192, 600, 7)

    barrel.hitpoints = 499
    battle._tick_container_thresholds()
    assert len(battle.container_drop_events) == 1
    assert battle.container_drop_events[0][2] == first_centre
    before = first_victim.hitpoints
    _run(battle, 0.6)
    assert first_victim.hitpoints == before - 192
    assert sum(entity.name == "skeleton"
               for entity in battle.entities.values()) == 7
    spawned = [entity for entity in battle.entities.values()
               if entity.name == "skeleton"]
    assert all(entity.deploy_remaining_ms == 500 for entity in spawned)

    second_victim = _spawn(battle, "knight", -1, 9.35, 20, 3)
    second_victim.speed_mt_per_sec = second_victim.damage = 0
    before = second_victim.hitpoints
    barrel.hitpoints = 0
    battle._reap()
    assert len(battle.container_drop_events) == 1
    assert battle.container_drop_events[0][2] == Point(9350, 20 * MT)
    _run(battle, 0.6)
    assert second_victim.hitpoints == before - 192
    assert sum(entity.name == "skeleton"
               for entity in battle.entities.values()) == 14


def test_evolved_cannon_fires_source_timed_four_plus_five_barrage():
    battle = Battle()
    cannon = _spawn(battle, "cannon_ev1", 1, 9, 20, 1)
    cannon.damage = 0
    fast_victim = _spawn(battle, "knight", -1, 7, 18.5, 2)
    slow_victim = _spawn(battle, "knight", -1, 1.5, 18.5, 3)
    for victim in (fast_victim, slow_victim):
        victim.speed_mt_per_sec = victim.damage = 0
    tower = battle.add(make_tower(
        4, -1, Point(9 * MT, 11500), 3346, 119, 800, 7500))
    tower.damage = 0

    assert len(battle.deploy_barrage_events) == 9
    assert (cannon.deploy_barrage_damage, cannon.deploy_barrage_tower_damage,
            cannon.deploy_barrage_radius_mt,
            cannon.deploy_barrage_pushback_mt) == (281, 21, 2000, 1000)
    before_fast = fast_victim.hitpoints
    before_slow = slow_victim.hitpoints
    before_tower = tower.hitpoints
    _run(battle, 1.05)
    assert fast_victim.hitpoints == before_fast
    _run(battle, 0.05)
    assert fast_victim.hitpoints == before_fast - 281
    assert fast_victim.pos.x == 8 * MT
    assert slow_victim.hitpoints == before_slow
    # The central far-row JULIO shell lands at 1.2 seconds and keeps the
    # explicit post-balance Crown Tower value instead of 25% rounding.
    _run(battle, 0.1)
    assert tower.hitpoints == before_tower - 21
    _run(battle, 0.1)
    assert slow_victim.hitpoints == before_slow - 281


def test_lumberjack_evolution_drops_current_rage_and_fixed_life_ghost():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    lumberjack = _spawn(battle, "rage_barbarian_ev1", 1, 9, 20, 1)
    victim = _spawn(battle, "knight", -1, 9, 20, 2)
    ally = _spawn(battle, "knight", 1, 9, 20, 3)
    tower = battle.add(make_tower(
        4, -1, Point(9 * MT, 20 * MT), 3346, 119, 800, 7500))
    for entity in (lumberjack, victim, ally, tower):
        entity.speed_mt_per_sec = entity.damage = 0

    before_victim = victim.hitpoints
    before_tower = tower.hitpoints
    lumberjack.hitpoints = 0
    battle._reap()

    assert victim.hitpoints == before_victim - 179
    assert tower.hitpoints == before_tower - 45
    assert len(battle.areas) == 1
    ghost = next(entity for entity in battle.entities.values()
                 if entity.name == "rage_barbarian_evo_ghost")
    assert ghost.pos == Point(9 * MT, 20 * MT)
    assert (ghost.hitpoints, ghost.damage, ghost.tower_damage_pct,
            ghost.lifetime_ms, ghost.permanent_invulnerable,
            ghost.always_invisible) == (1, 256, 50, 5500, True, True)
    assert ghost.take_damage(9999) == 0

    _run(battle, 0.05)
    assert ally.buff_speed_pct == ally.buff_hit_speed_pct == 30
    before_tower = tower.hitpoints
    battle._deal_damage(ghost, tower)
    assert tower.hitpoints == before_tower - 128

    # The life controller is fixed: another Rage area cannot add time.
    fixed_life = ghost.lifetime_ms
    assert fixed_life == 5450
    _run(battle, fixed_life / 1000)
    assert ghost.uid not in battle.entities


def test_reworked_and_evolved_furnace_use_source_spawn_controllers():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    lookup = lambda name: characters.get(name)

    normal_battle = Battle(unit_lookup=lookup)
    furnace = _spawn(normal_battle, "firespirit_hut", 1, 9, 20, 1,
                     ready=False)
    furnace.speed_mt_per_sec = furnace.damage = 0
    assert (furnace.range_mt, furnace.hit_speed_ms,
            furnace.spawn_character, furnace.spawn_start_ms,
            furnace.spawn_pause_ms, furnace.spawn_forward_mt,
            furnace.spawn_deploy_ms) == (
                5500, 1700, "FireSpirits", 1950, 5000, 3000, 500)
    _run(normal_battle, 2.90)
    assert not any(entity.name == "fire_spirits"
                   for entity in normal_battle.entities.values())
    _run(normal_battle, 0.05)
    spirit = next(entity for entity in normal_battle.entities.values()
                  if entity.name == "fire_spirits")
    assert spirit.pos == Point(9 * MT, 17 * MT)
    assert spirit.deploy_remaining_ms == 500

    evo_battle = Battle(unit_lookup=lookup)
    evolved = _spawn(evo_battle, "firespirit_hut_ev1", 1, 9, 20, 1)
    target = _spawn(evo_battle, "giant", -1, 9, 15, 2)
    evolved.speed_mt_per_sec = target.speed_mt_per_sec = 0
    evolved.damage = target.damage = 0
    assert (evolved.hot_spawn_interval_ms,
            evolved.hot_spawn_first_delay_ms,
            evolved.hot_spawn_stop_moving_ms,
            evolved.hot_spawn_normal_resume_ms) == (2400, 600, 1000, 400)
    _run(evo_battle, 0.65)
    hot = [entity for entity in evo_battle.entities.values()
           if entity.name == "fire_spirits"]
    assert len(hot) == 1
    assert hot[0].pos == Point(7500, 21 * MT)
    assert hot[0].deploy_remaining_ms == 1000
    _run(evo_battle, 2.40)
    hot = [entity for entity in evo_battle.entities.values()
           if entity.name == "fire_spirits"]
    assert len(hot) == 2
    assert hot[-1].pos == Point(10500, 21 * MT)


def test_evolved_goblin_cage_captures_damages_and_releases_one_ground_troop():
    from sim.gamedata import load_characters

    characters = load_characters(11)
    battle = Battle(unit_lookup=lambda name: characters.get(name))
    cage = _spawn(battle, "goblin_cage_ev1", 1, 9, 20, 1)
    near = _spawn(battle, "giant", -1, 9, 18, 2)
    farther = _spawn(battle, "knight", -1, 9, 17.5, 3)
    flying = _spawn(battle, "baby_dragon", -1, 9, 19, 4)
    for entity in (near, farther, flying):
        entity.speed_mt_per_sec = entity.damage = 0
    assert (cage.capture_radius_mt, cage.capture_damage,
            cage.capture_hit_frequency_ms, cage.capture_drag_delay_ms,
            cage.capture_drag_time_ms, cage.capture_cooldown_ms) == (
                3000, 366, 1000, 100, 300, 300)

    _run(battle, 0.05)
    assert cage.captured_uid == near.uid
    assert not near.spell_captured
    _run(battle, 0.10)
    assert near.spell_captured
    assert not farther.spell_captured and not flying.spell_captured
    _run(battle, 0.30)
    assert near.pos == cage.pos
    before = near.hitpoints
    _run(battle, 1.0)
    assert near.hitpoints == before - 366

    cage.hitpoints = 0
    battle._reap()
    assert not near.spell_captured
    assert near.pos == cage.pos
    assert any(entity.name == "goblin_cage_ev1__goblin_brawler"
               for entity in battle.entities.values())


def test_hero_mini_pekka_cooks_from_time_and_hits_then_levels_once():
    from sim.match import Match

    cards = {"mini_pekka_hero": ALL["mini_pekka_hero"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["mini_pekka_hero"] * 8, ["knight"] * 8), seed=31)
    hero = match.battle.add(make_unit(
        0, ALL["mini_pekka_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    hero.deploy_remaining_ms = 0
    target = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 19 * MT)))
    target.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = target.speed_mt_per_sec = 0
    hero.damage = target.damage = 0

    assert (hero.quest_interval_ms, hero.quest_hit_advance_ms,
            hero.quest_start_delay_ms, hero.quest_max_stacks,
            hero.ability_level_adjustments) == (
                22000, 8000, 1000, 3, (1, 2, 3, 5))
    _run(match.battle, 1.0)
    assert hero.quest_progress_ms == 0
    match.battle._land(hero, target, 1)
    assert hero.quest_progress_ms == 8000
    _run(match.battle, 14.0)
    assert hero.quest_stacks == 1

    # Three completed cooking bars select the published maximum +5 levels.
    hero.quest_stacks = 3
    hero.hitpoints = 500
    hero.damage = 755
    match.players[1].elixir = 10_000
    assert match.can_activate_ability(1, hero.uid)
    assert match.activate_ability(1, hero.uid)
    assert match.players[1].elixir == 9_000
    assert (hero.max_hitpoints, hero.damage) == (1390, 755)
    _run(match.battle, 0.20)
    assert (hero.applied_level_adjustment, hero.max_hitpoints,
            hero.damage) == (5, 2221, 1207)
    assert hero.hitpoints == 500 + (2221 - 500) * 30 // 100
    assert hero.control_cast_until_ms > match.battle.now_ms
    assert not match.can_activate_ability(1, hero.uid)


def test_hero_knight_taunt_restores_current_shield_and_forces_targets():
    from sim.match import Match

    cards = {"knight_hero": ALL["knight_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["knight_hero"] * 8, ["knight"] * 8), seed=32)
    hero = match.battle.add(make_unit(
        0, ALL["knight_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    enemy = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 18 * MT)))
    air = match.battle.add(make_unit(
        0, ALL["baby_dragon"].unit, -1, Point(10 * MT, 18 * MT)))
    for entity in (hero, enemy, air):
        entity.deploy_remaining_ms = 0
        entity.speed_mt_per_sec = entity.damage = 0
    assert hero.shield_hitpoints == 0
    assert (hero.shield_max_hitpoints, hero.ability_taunt_radius_mt,
            hero.ability_taunt_area_ms,
            hero.ability_taunt_duration_ms) == (512, 6500, 1100, 4000)
    match.players[1].elixir = 10_000
    assert match.activate_ability(1, hero.uid)
    _run(match.battle, 0.10)
    assert hero.shield_hitpoints == 0
    _run(match.battle, 0.05)
    assert hero.shield_hitpoints == 512
    assert enemy.taunted_by_uid == air.taunted_by_uid == hero.uid
    assert enemy.target_uid == air.target_uid == hero.uid
    assert enemy.taunt_until_ms == match.battle.now_ms + 4000


def test_hero_giant_waits_then_hurls_highest_hp_troop_to_opposite_lane():
    from sim.match import Match

    cards = {"giant_hero": ALL["giant_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["giant_hero"] * 8, ["knight"] * 8), seed=33)
    hero = match.battle.add(make_unit(
        0, ALL["giant_hero"].unit, 1, Point(3 * MT, 20 * MT)))
    hero.deploy_remaining_ms = 0
    hero.speed_mt_per_sec = hero.damage = 0
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    match.players[1].elixir = 10_000

    # WaitForTarget spends the button charge and remains armed.
    assert match.activate_ability(1, hero.uid)
    assert match.players[1].elixir == 8_000
    _run(match.battle, 0.5)
    assert match.battle.hurl_pending == [hero]

    low = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(3 * MT, 18 * MT)))
    high = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(4 * MT, 19 * MT)))
    high.shield_hitpoints = high.shield_max_hitpoints = 3000
    air = match.battle.add(make_unit(
        0, ALL["baby_dragon"].unit, -1, Point(13 * MT, 19 * MT)))
    splash = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(13 * MT, 19 * MT)))
    for entity in (low, high, air, splash):
        entity.deploy_remaining_ms = 0
        entity.speed_mt_per_sec = entity.damage = 0
    before_high, before_splash, before_air = (
        high.hitpoints, splash.hitpoints, air.hitpoints)

    _run(match.battle, 0.05)  # selector includes shields in current HP
    assert not match.battle.hurl_pending
    assert high.control_cast_until_ms == 0
    _run(match.battle, 0.35)
    assert not high.spell_captured
    _run(match.battle, 0.10)
    assert high.spell_captured
    assert high.forced_move_until_ms == 2950
    _run(match.battle, 1.50)
    assert high.pos == Point(13 * MT, 19 * MT)
    assert not high.spell_captured
    assert high.hitpoints == before_high
    assert high.shield_hitpoints == 3000 - 135
    assert splash.hitpoints == before_splash - 135
    assert air.hitpoints == before_air
    assert high.forced_move_until_ms > match.battle.now_ms


def test_hero_bowler_stone_swish_uses_fixed_position_ground_impacts():
    from sim.match import Match

    cards = {"bowler_hero": ALL["bowler_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["bowler_hero"] * 8, ["knight"] * 8), seed=34)
    hero = match.battle.add(make_unit(
        0, ALL["bowler_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    hero.deploy_remaining_ms = 0
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    target = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 12 * MT)))
    splash = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(10 * MT, 12 * MT)))
    air = match.battle.add(make_unit(
        0, ALL["baby_dragon"].unit, -1, Point(10 * MT, 12 * MT)))
    for entity in (target, splash, air):
        entity.deploy_remaining_ms = 0
        entity.speed_mt_per_sec = entity.damage = 0
    match.players[1].elixir = 10_000

    assert (hero.ability_siege_range_mt, hero.ability_siege_duration_ms,
            hero.ability_siege_lock_ms, hero.ability_siege_damage,
            hero.ability_siege_tower_damage,
            hero.ability_siege_radius_mt) == (
                11500, 7300, 2300, 384, 192, 2000)
    assert match.activate_ability(1, hero.uid)
    assert hero.control_cast_until_ms == 2300
    _run(match.battle, 2.3)
    hero.target_uid = target.uid
    hero.windup_remaining_ms = hero.attack_cooldown_ms = 0
    assert match.battle._attack(hero, TICK_MS)
    assert hero.attack_cooldown_ms == 1900
    assert len(match.battle.siege_impacts) == 1
    arrival = match.battle.siege_impacts[0][0]
    assert arrival == match.battle.now_ms + 8000 * 1000 // 6666

    before_target, before_splash, before_air = (
        target.hitpoints, splash.hitpoints, air.hitpoints)
    while match.battle.now_ms < arrival:
        match.battle.step()
    assert target.hitpoints == before_target - 384
    assert splash.hitpoints == before_splash - 384
    assert air.hitpoints == before_air

    # A second positional shot can miss a troop that leaves the marked area.
    hero.target_uid = target.uid
    hero.attack_cooldown_ms = hero.windup_remaining_ms = 0
    assert match.battle._attack(hero, TICK_MS)
    before_target = target.hitpoints
    target.pos = Point(15 * MT, 12 * MT)
    while match.battle.siege_impacts:
        match.battle.step()
    assert target.hitpoints == before_target


def test_hero_dark_prince_dismount_preserves_damage_and_spawns_current_rhino():
    from sim.match import Match

    cards = {"dark_prince_hero": ALL["dark_prince_hero"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["dark_prince_hero"] * 8, ["knight"] * 8), seed=35)
    hero = match.battle.add(make_unit(
        0, ALL["dark_prince_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 18 * MT)))
    hero.deploy_remaining_ms = victim.deploy_remaining_ms = 0
    hero.hitpoints -= 200
    hero.shield_hitpoints -= 40
    victim.speed_mt_per_sec = victim.damage = 0
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    before_hp, before_shield, before_victim = (
        hero.hitpoints, hero.shield_hitpoints, victim.hitpoints)
    hero.target_uid = victim.uid
    match.players[1].elixir = 10_000

    assert match.activate_ability(1, hero.uid)
    assert match.players[1].elixir == 7_000
    _run(match.battle, 0.05)
    walking = match.battle.get(hero.uid)
    assert walking is not hero
    assert walking.name == "dark_prince_hero__walking"
    assert (walking.hitpoints, walking.shield_hitpoints) == (
        before_hp, before_shield)
    assert walking.charge_range_mt == 0 and walking.ability_used
    walking.speed_mt_per_sec = walking.damage = 0
    mount = next(entity for entity in match.battle.entities.values()
                 if entity.name == "dark_prince_hero__mount")
    assert (mount.hitpoints, mount.damage, mount.damage_special,
            mount.deploy_remaining_ms, mount.charge_range_mt) == (
                1357, 179, 358, 950, 2500)
    _run(match.battle, 0.50)
    assert walking.pos == Point(9 * MT, 22 * MT)
    assert victim.hitpoints == before_victim - 307
    assert victim.pos.y == 16500


def test_hero_barbarian_barrel_reroll_heals_and_sweeps_once():
    from sim.gamedata import load_characters
    from sim.match import Match

    characters = load_characters(11)
    cards = {"knight": ALL["knight"]}
    match = Match(cards=cards, decks=(["knight"] * 8, ["knight"] * 8), seed=36)
    hero = match.battle.add(make_unit(
        0, characters["BarbLogBarbarianHero"], 1, Point(9 * MT, 20 * MT)))
    hero.deploy_remaining_ms = 0
    hero.hitpoints = 117
    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 18 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = victim.damage = 0
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    before = victim.hitpoints
    match.players[1].elixir = 10_000

    assert (hero.ability_reroll_range_mt, hero.ability_reroll_duration_ms,
            hero.ability_reroll_damage, hero.ability_reroll_tower_damage,
            hero.ability_reroll_heal_missing_pct) == (3000, 1000, 232, 116, 50)
    assert match.activate_ability(1, hero.uid)
    _run(match.battle, 0.35)
    assert hero.hitpoints == 117 and not hero.spell_captured
    _run(match.battle, 0.05)
    assert hero.hitpoints == 117 + (hero.max_hitpoints - 117) * 50 // 100
    assert hero.spell_captured and hero.untargetable
    _run(match.battle, 1.0)
    assert hero.pos == Point(9 * MT, 17 * MT)
    assert not hero.spell_captured
    assert victim.hitpoints == before - 232


def test_hero_barbarian_barrel_card_rolls_before_spawning_hero():
    from sim.match import Match
    from sim.spells import load_spells

    cards = {"barb_log_hero": ALL["barb_log_hero"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["barb_log_hero"] * 8, ["knight"] * 8), seed=37,
                  spells=load_spells(11))
    match.players[1].hand = ["barb_log_hero"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "barb_log_hero", Point(9 * MT, 20 * MT))
    assert not any(entity.name == "barb_log_barbarian_hero"
                   for entity in match.battle.entities.values())
    _run(match.battle, 1.45)
    hero = next(entity for entity in match.battle.entities.values()
                if entity.name == "barb_log_barbarian_hero")
    assert hero.pos == Point(9 * MT, 15500)
    assert hero.deploy_remaining_ms > 0
    assert hero.ability_reroll_range_mt == 3000


def test_hero_valkyrie_waits_then_delivers_fourteen_uninterruptible_pulses():
    from sim.match import Match

    cards = {"valkyrie_hero": ALL["valkyrie_hero"],
             "giant": ALL["giant"]}
    match = Match(cards=cards,
                  decks=(["valkyrie_hero"] * 8, ["giant"] * 8), seed=38)
    hero = match.battle.add(make_unit(
        0, ALL["valkyrie_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    hero.deploy_remaining_ms = 0
    hero.damage = 0
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0
    match.players[1].elixir = 10_000
    assert match.activate_ability(1, hero.uid)
    _run(match.battle, 0.5)
    assert match.battle.spin_pending == [hero]
    assert not match.battle.spin_events  # seek time does not consume duration

    victim = match.battle.add(make_unit(
        0, ALL["giant"].unit, -1, Point(9 * MT, 24 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = victim.damage = 0
    before = victim.hitpoints
    _run(match.battle, 0.05)
    assert not match.battle.spin_pending
    assert hero.damage_reduction_pct == 15
    # A full Freeze-style action lock does not stop the independent pulses.
    victim.pos = hero.pos
    hero.buff_speed_pct = hero.buff_hit_speed_pct = -100
    _run(match.battle, 3.5)
    assert victim.hitpoints == before - 14 * 97
    assert not match.battle.spin_events
    assert hero.damage_reduction_pct == 0
    assert hero.control_cast_until_ms == match.battle.now_ms + 400


def test_hero_goblins_last_death_banner_and_current_two_unit_brigade():
    from sim.match import Match

    cards = {"goblins_hero": ALL["goblins_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["goblins_hero"] * 8, ["knight"] * 8), seed=39)
    match.players[1].hand = ["goblins_hero"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "goblins_hero", Point(6 * MT, 20 * MT))
    heroes = [entity for entity in match.battle.entities.values()
              if entity.name == "goblin_hero"]
    assert len(heroes) == 4
    assert len({entity.spawn_group_uid for entity in heroes}) == 1
    for tower in match.battle.entities.values():
        if tower.is_tower:
            tower.damage = 0

    # Three deaths do nothing; the fourth leaves exactly one source banner at
    # that final death position even when all deaths resolve in the same reap.
    for hero in heroes[:3]:
        hero.hitpoints = 0
    match.battle.step()
    assert not any(entity.ability_reinforcement_character
                   for entity in match.battle.entities.values())
    final_pos = heroes[3].pos
    heroes[3].hitpoints = 0
    match.battle.step()
    banners = [entity for entity in match.battle.entities.values()
               if entity.ability_reinforcement_character]
    assert len(banners) == 1
    banner = banners[0]
    assert banner.pos == final_pos
    assert banner.untargetable and banner.permanent_invulnerable
    assert (banner.ability_cost, banner.ability_window_ms,
            banner.ability_reinforcement_damage) == (1, 5000, 125)

    assert match.activate_ability(1, banner.uid)
    assert match.players[1].elixir == 7_000  # 2 for card, 1 for ability
    _run(match.battle, 0.95)
    assert not banner.alive
    brigade = [entity for entity in match.battle.entities.values()
               if entity.name == "goblin_dummy"]
    assert len(brigade) == 2
    assert all(entity.damage == 125 and entity.deploy_remaining_ms > 0
               for entity in brigade)
    assert {entity.pos for entity in brigade} == {
        Point(final_pos.x - MT, final_pos.y + 500),
        Point(final_pos.x + MT, final_pos.y + 500),
    }


def test_hero_goblins_banner_ability_expires_before_visual_cleanup():
    from sim.gamedata import load_characters
    from sim.match import Match

    match = Match(cards={"knight": ALL["knight"]},
                  decks=(["knight"] * 8, ["knight"] * 8), seed=40)
    banner_spec = load_characters(11)["GoblinHero_Flag_Building"]
    banner = match.battle.add(make_unit(
        0, banner_spec, 1, Point(9 * MT, 20 * MT), match.battle.now_ms))
    banner.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000
    _run(match.battle, 5.05)
    assert banner.alive  # the client's 1.5-second disappear phase remains
    assert not match.can_activate_ability(1, banner.uid)
    _run(match.battle, 1.45)
    assert not banner.alive


def test_hero_tombstone_regal_revival_raises_current_queen_and_death_wave():
    from sim.match import Match

    cards = {"tombstone_hero": ALL["tombstone_hero"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["tombstone_hero"] * 8, ["knight"] * 8), seed=41)
    match.players[1].hand = ["tombstone_hero"]
    match.players[1].elixir = 10_000
    at = Point(9 * MT, 20 * MT)
    assert match.play_card(1, "tombstone_hero", at)
    tomb = next(entity for entity in match.battle.entities.values()
                if entity.name == "tombstone_hero")
    carrier = next(entity for entity in match.battle.entities.values()
                   if entity.ability_transform_character)
    assert tomb.spawn_group_uid == carrier.spawn_group_uid
    assert (tomb.spawn_character, tomb.spawn_count, tomb.spawn_pause_ms,
            tomb.death_spawn_count) == (
                "TombstoneHeroSkeleton", 2, 3500, 4)
    tomb.deploy_remaining_ms = carrier.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000

    assert match.activate_ability(1, carrier.uid)
    assert match.players[1].elixir == 5_000
    queen = match.battle.get(carrier.uid)
    assert queen.name == "tombstone_hero__monster__active"
    assert (queen.hitpoints, queen.damage, queen.hit_speed_ms,
            queen.sight_range_mt, queen.target_only_buildings) == (
                4224, 422, 2100, 7000, True)
    assert queen.control_cast_until_ms == match.battle.now_ms + 2000
    assert not tomb.alive
    match.battle.step()
    death_wave = [entity for entity in match.battle.entities.values()
                  if entity.name == "tombstone_hero_skeleton"]
    assert len(death_wave) == 4

    queen.hitpoints = 0
    queen_pos = queen.pos
    match.battle.step()
    all_skeletons = [entity for entity in match.battle.entities.values()
                     if entity.name == "tombstone_hero_skeleton"]
    assert len(all_skeletons) == 8
    queen_wave = all_skeletons[-4:]
    assert all(entity.deploy_remaining_ms == 500 for entity in queen_wave)
    assert {entity.pos for entity in queen_wave} == {
        Point(queen_pos.x + MT, queen_pos.y),
        Point(queen_pos.x - MT, queen_pos.y),
        Point(queen_pos.x - MT, queen_pos.y - 2 * MT),
        Point(queen_pos.x + MT, queen_pos.y - 2 * MT),
    }


def test_hero_tombstone_ability_survives_source_death_for_1500ms_only():
    from sim.match import Match

    cards = {"tombstone_hero": ALL["tombstone_hero"],
             "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["tombstone_hero"] * 8, ["knight"] * 8), seed=42)
    match.players[1].hand = ["tombstone_hero"]
    match.players[1].elixir = 10_000
    assert match.play_card(1, "tombstone_hero", Point(9 * MT, 20 * MT))
    tomb = next(entity for entity in match.battle.entities.values()
                if entity.name == "tombstone_hero")
    carrier = next(entity for entity in match.battle.entities.values()
                   if entity.ability_transform_character)
    tomb.deploy_remaining_ms = carrier.deploy_remaining_ms = 0
    tomb.hitpoints = 0
    match.battle.step()
    assert match.can_activate_ability(1, carrier.uid)
    _run(match.battle, 1.55)
    assert not carrier.alive
    assert not match.can_activate_ability(1, carrier.uid)


def test_ronin_parry_blocks_one_melee_hit_and_reflects_exact_damage_later():
    battle = Battle()
    ronin = battle.add(make_unit(
        0, ALL["ronin"].unit, 1, Point(9 * MT, 20 * MT)))
    knight = battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 19 * MT)))
    ronin.deploy_remaining_ms = knight.deploy_remaining_ms = 0
    before_ronin, before_knight = ronin.hitpoints, knight.hitpoints
    assert (ronin.parry_cooldown_ms, ronin.parry_damage_pct,
            ronin.parry_stun_ms) == (3500, 200, 500)

    battle._land(knight, ronin, knight.damage)
    assert ronin.hitpoints == before_ronin
    assert knight.hitpoints == before_knight
    assert ronin.parry_ready_at_ms == 3500
    _run(battle, 0.05)
    assert (knight.buff_speed_pct, knight.buff_hit_speed_pct) == (-100, -95)
    _run(battle, 0.25)
    assert knight.hitpoints == before_knight - 2 * knight.damage

    # A second melee hit during recharge lands normally.
    battle._land(knight, ronin, knight.damage)
    assert ronin.hitpoints == before_ronin - knight.damage


def test_ronin_parry_excludes_projectiles_and_is_disabled_while_frozen():
    battle = Battle()
    ronin = battle.add(make_unit(
        0, ALL["ronin"].unit, 1, Point(9 * MT, 20 * MT)))
    musketeer = battle.add(make_unit(
        0, ALL["musketeer"].unit, -1, Point(9 * MT, 19 * MT)))
    knight = battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 19 * MT)))
    for entity in (ronin, musketeer, knight):
        entity.deploy_remaining_ms = 0
    before = ronin.hitpoints
    battle._land(musketeer, ronin, musketeer.damage)
    assert ronin.hitpoints == before - musketeer.damage
    assert ronin.parry_ready_at_ms == 0

    ronin.buff_until_ms = 1000
    ronin.buff_speed_pct = ronin.buff_hit_speed_pct = -100
    before = ronin.hitpoints
    battle._land(knight, ronin, knight.damage)
    assert ronin.hitpoints == before - knight.damage
    assert ronin.parry_ready_at_ms == 0


def test_boss_bandit_getaway_has_two_timed_backward_warps():
    from sim.match import Match

    cards = {"boss_bandit": ALL["boss_bandit"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["boss_bandit"] * 8, ["knight"] * 8), seed=43)
    boss = match.battle.add(make_unit(
        0, ALL["boss_bandit"].unit, 1, Point(9 * MT, 20 * MT)))
    boss.deploy_remaining_ms = 0
    match.players[1].elixir = 10_000
    assert (boss.hitpoints, boss.damage, boss.dash_damage,
            boss.ability_max_charges, boss.ability_cooldown_ms) == (
                2624, 245, 491, 2, 3000)

    assert match.activate_ability(1, boss.uid)
    assert not boss.ability_used and boss.ability_charges_used == 1
    assert boss.invisible(match.battle.now_ms)
    assert boss.control_cast_until_ms == 750
    assert not match.can_activate_ability(1, boss.uid)
    _run(match.battle, 0.70)
    assert boss.pos == Point(9 * MT, 26 * MT)
    assert boss.target_uid is None
    _run(match.battle, 2.30)
    assert match.can_activate_ability(1, boss.uid)

    # The source explicitly allows Getaway while movement/attack speed is zero.
    boss.buff_until_ms = match.battle.now_ms + 1000
    boss.buff_speed_pct = boss.buff_hit_speed_pct = -100
    second_origin = boss.pos
    assert match.activate_ability(1, boss.uid)
    assert match.battle.ability_warp_events[-1][2].y == min(
        32 * MT - 1, second_origin.y + 6 * MT)
    assert boss.ability_used and boss.ability_charges_used == 2
    assert not match.can_activate_ability(1, boss.uid)
    _run(match.battle, 0.70)
    assert boss.pos.y > second_origin.y


def test_firecracker_applies_client_one_tile_self_recoil_on_launch():
    battle = Battle()
    firecracker = battle.add(make_unit(
        0, ALL["firecracker"].unit, 1, Point(9 * MT, 20 * MT)))
    target = battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(9 * MT, 15 * MT)))
    firecracker.deploy_remaining_ms = target.deploy_remaining_ms = 0
    firecracker.target_uid = target.uid
    firecracker.windup_remaining_ms = 0
    firecracker.attack_cooldown_ms = 0
    assert firecracker.attack_self_pushback_mt == 1000
    assert battle._attack(firecracker, TICK_MS)
    assert firecracker.pos == Point(9 * MT, 21 * MT)
    assert len(battle.unmodelled_projectiles) == 1


def test_current_skeletrooper_stats_and_landing_damage_are_materialized():
    from sim.gamedata import load_characters

    spec = load_characters(11)["SkeletonTrooper"]
    assert (spec.hitpoints, spec.damage, spec.hit_speed_ms,
            spec.tower_damage_pct, spec.spawn_area_damage,
            spec.spawn_area_tower_damage, spec.spawn_area_radius_mt) == (
                474, 204, 1100, 10, 263, 26, 2000)
    battle = Battle()
    trooper = battle.add(make_unit(
        0, spec, 1, Point(9 * MT, 20 * MT)))
    victim = battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(10 * MT, 20 * MT)))
    trooper.deploy_remaining_ms = 0
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = victim.damage = 0
    before = victim.hitpoints
    battle.step()
    assert victim.hitpoints == before - 263


def test_hero_wizard_fiery_flight_changes_form_and_adds_enhanced_hit_area():
    from sim.match import Match

    cards = {"wizard_hero": ALL["wizard_hero"], "knight": ALL["knight"]}
    match = Match(cards=cards,
                  decks=(["wizard_hero"] * 8, ["knight"] * 8), seed=44)
    wizard = match.battle.add(make_unit(
        0, ALL["wizard_hero"].unit, 1, Point(9 * MT, 20 * MT)))
    wizard.deploy_remaining_ms = 0
    wizard.hitpoints -= 100
    original_hp = wizard.hitpoints
    match.players[1].elixir = 10_000

    assert match.activate_ability(1, wizard.uid)
    assert match.players[1].elixir == 9_000
    _run(match.battle, 0.35)
    assert match.battle.get(wizard.uid).name == "wizard_hero"
    _run(match.battle, 0.05)
    airborne = match.battle.get(wizard.uid)
    assert airborne.name == "wizard_hero_air" and airborne.flying
    assert airborne.hitpoints == original_hp
    assert (airborne.damage, airborne.buff_speed_pct,
            airborne.projectile_area_damage,
            airborne.projectile_area_radius_mt) == (238, 50, 43, 4000)

    victim = match.battle.add(make_unit(
        0, ALL["knight"].unit, -1, Point(10 * MT, 20 * MT)))
    victim.deploy_remaining_ms = 0
    victim.speed_mt_per_sec = victim.damage = 0
    before = victim.hitpoints
    match.battle._land(airborne, victim, airborne.damage)
    match.battle.step()
    assert victim.hitpoints == before - 238 - 43

    _run(match.battle, 4.75)
    assert match.battle.get(wizard.uid).name == "wizard_hero"
    assert match.battle.get(wizard.uid).hitpoints == original_hp


def test_coverage_has_no_unresolved_public_spell_and_counts_evo_summons_as_units():
    from sim.coverage import report

    coverage = report()
    # 176 rather than 174 since building evolutions started loading. The
    # overlay loader read characters_evo.toml only, so Mortar Evolution and
    # Tesla Evolution - which live in buildings_evo.toml with exactly the same
    # `Base=` shape - had no character data and their card rows were dropped
    # entirely. The client ships 42 evolutions and the simulator reported 40.
    assert coverage["units"] == 176
    assert coverage["spells_unresolved"] == []
    assert coverage["spell_rows_intentionally_excluded"] == [
        "goblin_party_rocket", "mirror", "tri_wizards", "warm_spell"]
