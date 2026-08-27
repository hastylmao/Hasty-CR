"""Tornado moves things, which is the entire reason anyone plays it.

The engine had no attraction of any kind. Tornado was modelled as a second of
weak damage - 60 a second, which is less than an Arrow - and never shifted a
unit by a millitile. Every use of the card is repositioning: pulling a Hog off
the tower, stacking a swarm for a Fireball, dragging troops onto the king to
activate it. All of that silently did nothing, and the damage numbers were
right, so nothing failed.

The number was in the file the whole time. `[BUFF.Tornado]` declares
`AttractPercentage = 360`, read as a pull speed in percent of one tile per
second. The Clash Royale wiki independently states the drag as "up to 3.5 tiles
per second", against a declared 3.6 - the shortfall being the resistance it
also documents, where a unit walking away from the centre keeps walking and its
own movement eats into the pull. That falls out of applying the drag as a
displacement alongside normal movement instead of overriding it.

Two other cards declare the same field and are not spells, so they are not
covered here: Evolved Valkyrie's spin (300) and Wizard Hero's mini tornado
(250), both of which reach the board through character-ability paths.
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
from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import cast_spell, load_spells                  # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)


def test_the_declared_pull_is_read_from_the_buff():
    """Not from the area beside it, which carries no such field."""
    assert SPELLS["tornado"].attract_percentage == 360


def test_a_stationary_unit_is_dragged_at_the_published_speed():
    """3.6 tiles per second declared, "up to 3.5" published.

    Measured with nothing for the unit to walk toward, so the drag is the only
    thing moving it and the resistance term is out of the picture.
    """
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS["giant"].unit, -1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    centre = Point(9000, 24000)
    start = distance(centre, unit.pos)
    cast_spell(battle, SPELLS["tornado"], centre, side=1)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    pulled = (start - distance(centre, unit.pos)) / MT
    duration = SPELLS["tornado"].life_duration_ms / 1000
    assert 3.2 <= pulled / duration <= 3.7, f"dragged {pulled/duration:.2f} tiles/sec"


@pytest.mark.parametrize("card", ["hog_rider", "giant", "minions", "skeletons"])
def test_the_pull_reaches_ground_and_air_alike(card):
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS[card].unit, -1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    centre = Point(9000, 23000)
    start = distance(centre, unit.pos)
    cast_spell(battle, SPELLS["tornado"], centre, side=1)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    if unit.alive:
        assert distance(centre, unit.pos) < start, f"{card} was not moved at all"


def test_a_unit_outside_the_radius_is_left_alone():
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS["giant"].unit, -1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    unit.speed_mt_per_sec = 0
    centre = Point(9000, 20000 + SPELLS["tornado"].radius_mt + 4000)
    before = unit.pos
    cast_spell(battle, SPELLS["tornado"], centre, side=1)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    assert unit.pos == before


def test_our_own_troops_are_not_dragged():
    """`OnlyEnemies` on the area, and it has to hold for the pull too."""
    battle = Battle()
    unit = battle.add(make_unit(1, CARDS["giant"].unit, 1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    unit.speed_mt_per_sec = 0
    before = unit.pos
    cast_spell(battle, SPELLS["tornado"], Point(9000, 23000), side=1)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        battle.step()
    assert unit.pos == before


def test_buildings_and_towers_do_not_move():
    """Towers only exist in a Match, so this one goes through the real board."""
    deck = ["tornado", "knight", "archers", "musketeer",
            "cannon", "skeletons", "giant", "hog_rider"]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=4, spells=SPELLS)
    for _ in range(40):
        match.step()
    battle = match.battle
    towers = {uid: e.pos for uid, e in battle.entities.items() if e.is_tower}
    assert towers, "the match has no towers to check"

    enemy = match.players[-1]
    enemy.hand[0] = "cannon"
    enemy.elixir = 10_000
    assert match.play_card(-1, "cannon", grid_to_point(9, 20, -1))
    for _ in range(40):
        match.step()
    building = next(e for e in battle.entities.values()
                    if e.name == "cannon" and e.side == -1)
    before = building.pos

    ours = match.players[1]
    ours.hand[0] = "tornado"
    ours.elixir = 10_000
    assert match.play_card(1, "tornado", Point(building.pos.x, building.pos.y - 3000))
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        match.step()

    assert building.pos == before, "a Cannon was dragged; buildings do not move"
    for uid, pos in towers.items():
        assert battle.entities[uid].pos == pos


def test_a_unit_running_away_resists_the_drag():
    """The wiki's resistance clause, which is why 360 reads as "up to 3.5".

    A Hog Rider charging a tower is the case that matters in play: it is
    dragged, but far less than a unit standing still, because it keeps running
    while the tornado pulls.
    """
    deck = ["tornado", "knight", "archers", "musketeer",
            "cannon", "skeletons", "giant", "hog_rider"]
    match = Match(cards=CARDS, decks=(deck, list(deck)), seed=3, spells=SPELLS)
    for _ in range(40):
        match.step()
    enemy = match.players[-1]
    enemy.hand[0] = "hog_rider"
    enemy.elixir = 10_000
    assert match.play_card(-1, "hog_rider", grid_to_point(9, 20, -1))
    for _ in range(100):
        match.step()
    hog = next(e for e in match.battle.entities.values() if e.name == "hog_rider")

    centre = Point(hog.pos.x, hog.pos.y - 3500)
    start = distance(centre, hog.pos)
    ours = match.players[1]
    ours.hand[0] = "tornado"
    ours.elixir = 10_000
    assert match.play_card(1, "tornado", centre)
    for _ in range(int(1.5 * 1000 / TICK_MS)):
        match.step()

    dragged = (start - distance(centre, hog.pos)) / MT
    assert dragged > 0, "the Hog was not dragged at all"
    assert dragged < 3.2, (
        f"the Hog was dragged {dragged:.2f} tiles, as though it had been "
        f"standing still - its own running should resist the pull")


def test_no_other_spell_gained_a_pull():
    """`AttractPercentage` is declared by exactly one spell."""
    pulling = {name for name, spec in SPELLS.items() if spec.attract_percentage}
    assert pulling == {"tornado"}, sorted(pulling)


# --------------------------------------------------------------------------
# Evolved Valkyrie, whose entire evolution is the same mechanic on a swing.
#
# "Evolved Valkyrie draws all enemies towards her with each swing" is the
# published description of the card, and the client backs it: every attack
# spawns `Valkyrie_MiniTornado_EV1`, a half-second area with `Base = "Tornado"`
# overriding `AttractPercentage` to 300. She swung and nothing moved, and no
# test could have caught it, because her damage was right.
# --------------------------------------------------------------------------


def test_only_the_evolution_declares_a_swing_pull():
    pulling = {name for name, card in CARDS.items()
               if card.unit is not None
               and getattr(card.unit, "attack_area_attract_percentage", 0)}
    assert pulling == {"valkyrie_ev1"}, sorted(pulling)


def test_the_swing_pull_matches_the_declared_area():
    unit = CARDS["valkyrie_ev1"].unit
    assert unit.attack_area_attract_percentage == 300
    assert unit.attack_area_radius_mt == 5000
    assert unit.attack_area_duration_ms == 500


def _valkyrie_swinging(variant):
    """Her, a target she can actually reach, and two she cannot."""
    battle = Battle()
    valk = battle.add(make_unit(1, CARDS[variant].unit, 1, Point(9000, 20000)))
    valk.deploy_remaining_ms = 0
    valk.speed_mt_per_sec = 0
    in_reach = battle.add(make_unit(2, CARDS["giant"].unit, -1, Point(9000, 21000)))
    far = battle.add(make_unit(3, CARDS["giant"].unit, -1, Point(9000, 23500)))
    air = battle.add(make_unit(4, CARDS["minions"].unit, -1, Point(11500, 22500)))
    for unit in (in_reach, far, air):
        unit.deploy_remaining_ms = 0
        unit.speed_mt_per_sec = 0
        unit.damage = 0
    return battle, valk, far, air


@pytest.mark.parametrize("target", ["ground", "air"])
def test_the_evolution_drags_and_the_base_card_does_not(target):
    """The one difference the evolution is supposed to make."""
    moved = {}
    for variant in ("valkyrie_ev1", "valkyrie"):
        battle, valk, far, air = _valkyrie_swinging(variant)
        subject = far if target == "ground" else air
        start = distance(valk.pos, subject.pos)
        for _ in range(int(5 * 1000 / TICK_MS)):
            battle.step()
        moved[variant] = (start - distance(valk.pos, subject.pos)) / MT

    assert moved["valkyrie_ev1"] > 0.4, (
        f"the evolution pulled {moved['valkyrie_ev1']:.2f} tiles of {target}")
    assert moved["valkyrie"] < 0.1, (
        f"the base card pulled {moved['valkyrie']:.2f} tiles of {target}, "
        f"and it has no tornado")


def test_the_pull_catches_air_even_though_her_axe_does_not():
    """Both halves matter and they disagree.

    Valkyrie's axe is ground-only; the tornado is declared `HitsAir` and the
    card is documented as catching air with it. The inline attack-area path
    skips flying units outright, which is why the pull is spawned as a real
    area instead of resolved there.
    """
    battle, valk, _far, air = _valkyrie_swinging("valkyrie_ev1")
    hp = air.hitpoints
    start = distance(valk.pos, air.pos)
    for _ in range(int(5 * 1000 / TICK_MS)):
        battle.step()
    assert distance(valk.pos, air.pos) < start, "the tornado did not catch air"
    assert air.hitpoints == hp, "her axe should not be reaching a flying unit"


# --------------------------------------------------------------------------
# Wizard Hero, the third and last card in the client that declares a pull.
#
# Its ability projectile spawns two areas from one action group: the 43-damage
# one, and `WizardHero_MiniTornadoAEO` at `AttractPercentage = 250`. The buff
# is declared inside wizard_hero.toml rather than in the shared buff tables,
# which is why it needed looking for in both places.
# --------------------------------------------------------------------------


def test_the_three_attractors_are_the_only_ones_in_the_client():
    """A fourth appearing means the client changed, not that this is wrong."""
    from sim.gamedata import load_characters
    table = load_characters(11)
    pulls = {name for name, unit in table.items()
             if getattr(unit, "attack_area_attract_percentage", 0)
             or getattr(unit, "projectile_area_attract_percentage", 0)}
    # Each unit appears under both its client identifier and its snake-case
    # alias, so compare on the underscore-free form.
    assert {name.lower().replace("_", "") for name in pulls} == {
        "valkyrieev1", "wizardheroair"}, sorted(pulls)
    assert {name for name, spec in SPELLS.items() if spec.attract_percentage} == {
        "tornado"}


def test_the_hero_form_declares_the_mini_tornado():
    from sim.gamedata import load_characters
    unit = load_characters(11)["WizardHero_air"]
    assert unit.projectile_area_attract_percentage == 250
    assert unit.projectile_area_attract_radius_mt == 4000
    assert unit.projectile_area_attract_duration_ms == 500


def test_the_hit_drags_bystanders_toward_the_struck_unit():
    """The tornado lands where the projectile did, so it pulls the neighbours.

    Checked against the ground form, which fires the same character's ordinary
    projectile and should move nothing.
    """
    from sim.gamedata import load_characters
    table = load_characters(11)
    moved = {}
    for form in ("WizardHero_air", "WizardHero"):
        battle = Battle()
        hero = battle.add(make_unit(1, table[form], 1, Point(9000, 20000)))
        hero.deploy_remaining_ms = 0
        hero.speed_mt_per_sec = 0
        struck = battle.add(make_unit(2, table["Giant"], -1, Point(9000, 23000)))
        bystander = battle.add(make_unit(3, table["Giant"], -1, Point(11800, 23000)))
        for unit in (struck, bystander):
            unit.deploy_remaining_ms = 0
            unit.speed_mt_per_sec = 0
            unit.damage = 0
        start = distance(struck.pos, bystander.pos)
        for _ in range(int(4 * 1000 / TICK_MS)):
            battle.step()
        moved[form] = (start - distance(struck.pos, bystander.pos)) / MT

    assert moved["WizardHero_air"] > 0.5, (
        f"the ability form pulled {moved['WizardHero_air']:.2f} tiles")
    assert moved["WizardHero"] < 0.1, (
        f"the ground form pulled {moved['WizardHero']:.2f} tiles and has no tornado")
