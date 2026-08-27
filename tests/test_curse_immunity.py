"""Goblin Curse cannot convert a Golem, and could.

Goblin Curse turns whatever dies inside it into a goblin for the caster. Some
units are declared exempt, and every one of them is a unit whose death already
leaves something of its own:

    Golem, Lava Hound, Battle Ram, Elixir Golem, Cannon Cart,
    Skeleton Balloon, Suspicious Bush

The exemption is `IgnoreBuff = ["VoodooCurse", "GoblinCurse"]` on the character,
and it was read by nothing. So a cursed Golem left two Golemites *and* a goblin
- free value for the curse - and the rule that makes the interaction sensible
was simply absent.

Found by `scripts/unread_fields.py`. Most `IgnoreBuff` entries are party-mode
event buffs and irrelevant; the curse pair is the one that matters on ladder.

Two things this deliberately does not claim:

  * Goblin Giant is *not* exempt. The `IgnoreBuff` in goblingiant.toml belongs
    to `[CHARACTER.SpearGoblinGiant]`, the goblins he leaves, not to him - so
    he converts and they do not, which is what the simulator already did.
  * A single immunity is written as a bare string rather than a list, and
    iterating that yields characters. Royal Delivery and Super Lava Hound came
    out immune to "E", "v", "e", "n"... until that was handled.
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.arena import Point, TICK_MS                            # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_characters, load_gamedata         # noqa: E402
from sim.spells import cast_spell, load_spells                  # noqa: E402

CARDS = load_gamedata(level=11)
TABLE = load_characters(11)
SPELLS = load_spells(level=11)
CURSE_GOBLIN = "goblin_curse_goblin"

IMMUNE = ["golem", "lava_hound", "battle_ram", "elixir_golem"]
CURSABLE = ["knight", "skeletons", "goblin_giant"]


def test_the_immunity_is_read():
    for card in IMMUNE:
        assert "GoblinCurse" in CARDS[card].unit.ignored_buffs, card


def test_a_bare_string_immunity_is_not_read_as_characters():
    """Royal Delivery declares one buff, unwrapped."""
    for card, expected in (("royal_delivery", "Event_Berserk_OnStartBuff"),
                           ("super_lava_hound", "VoodooCurse")):
        if card not in CARDS or CARDS[card].unit is None:
            continue
        assert CARDS[card].unit.ignored_buffs == (expected,), (
            CARDS[card].unit.ignored_buffs)


def test_the_matching_survives_the_naming_difference():
    """The client writes `GoblinCurse`; the spell loads as `goblin_curse`."""
    golem = CARDS["golem"].unit
    assert golem.ignored_buffs
    entity = make_unit(1, golem, 1, Point(9000, 20000))
    assert entity.immune_to("goblin_curse")
    assert entity.immune_to("GoblinCurse")
    assert not entity.immune_to("freeze")


def _cursed_death(card):
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    unit = battle.add(make_unit(1, CARDS[card].unit, -1, Point(9000, 20000)))
    unit.deploy_remaining_ms = 0
    unit.speed_mt_per_sec = 0
    cast_spell(battle, SPELLS["goblin_curse"], unit.pos, side=1)
    for _ in range(20):
        battle.step()
    unit.hitpoints = 0                      # `alive` is derived from hitpoints
    for _ in range(int(2 * 1000 / TICK_MS)):
        battle.step()
    return Counter(e.name for e in battle.entities.values() if e.alive)


@pytest.mark.parametrize("card", IMMUNE)
def test_an_exempt_unit_leaves_its_own_spawns_and_no_goblin(card):
    left = _cursed_death(card)
    assert left, f"{card} left nothing at all"
    assert CURSE_GOBLIN not in left, (
        f"cursed {card} left {dict(left)}; it is declared exempt and its "
        f"death spawn is its own")


@pytest.mark.parametrize("card", CURSABLE)
def test_a_unit_with_no_exemption_is_still_converted(card):
    left = _cursed_death(card)
    assert left.get(CURSE_GOBLIN, 0) > 0, (
        f"cursed {card} left {dict(left)} and is not exempt")


def test_the_giants_spear_goblins_are_exempt_but_he_is_not():
    """The `IgnoreBuff` in his file belongs to them, not to him."""
    assert not CARDS["goblin_giant"].unit.ignored_buffs
    assert "GoblinCurse" in TABLE["SpearGoblinGiant"].ignored_buffs


def test_the_exempt_set_is_the_one_the_client_declares():
    """A card gaining or losing the exemption is a balance change, not a bug."""
    exempt = {name for name, card in CARDS.items()
              if card.unit is not None
              and "GoblinCurse" in getattr(card.unit, "ignored_buffs", ())}
    assert exempt == {
        "battle_ram", "battle_ram_ev1", "elixir_golem", "golem", "lava_hound",
        "moving_cannon", "skeleton_balloon", "skeleton_balloon_ev1",
        "suspicious_bush",
    }, sorted(exempt)
