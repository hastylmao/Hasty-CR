"""Card behaviour checked against the game's own info screens.

Source: 170 screenshots of the in-game card info panels, captured 2026-08-20
under `MuMuSharedFolder/VideoRecords/data/hero evo champs`. These are the
screens a player reads - name, type, ability name and description, and the stat
grid - for every Hero, Champion and Evolution on the account.

They are used the way this project uses any secondary source: for the
**mechanics they spell out**, not for their numbers. The account is boosted, so
a displayed hitpoint total is at a level the simulator does not run at, and
taking those figures would repeat the mistake of adopting a stat table from a
document instead of the shipped files.

What the screens are uniquely good for is naming behaviour the raw data only
implies. "The first strike against each member of Minion Horde Evolution makes
it briefly invincible" plus an "Invincibility Duration 3sec" stat is a far
clearer statement of that card than `on_damage_invulnerable_ms` sitting in a
TOML, and it is checkable.

Evolution cycle counts are the exception: they are small integers shown
directly on the screen and independent of level, so they are asserted as
numbers.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import load_gamedata                          # noqa: E402

CARDS = load_gamedata(level=11)

# Read off the "Cycles" badge on each Evolution's info screen. Independent of
# card level, so these are numbers rather than mechanics.
EVOLUTION_CYCLES = {
    "angry_barbarians_ev1": 1,      # Elite Barbarians
    "skeletons_ev1": 2,
    "zap_ev1": 2,
    "archer_ev1": 2,                # Archers
    "blowdart_goblin_ev1": 2,       # Dart Goblin
    "ghost_ev1": 2,                 # Royal Ghost
    "goblin_cage_ev1": 2,
    "battle_ram_ev1": 2,
    "rage_barbarian_ev1": 2,        # Lumberjack
    "royal_hogs_ev1": 2,
    "axe_man_ev1": 1,               # Executioner
    "royal_recruits_ev1": 1,
    "mega_knight_ev1": 1,
}


@pytest.mark.parametrize("card,cycles", sorted(EVOLUTION_CYCLES.items()))
def test_evolution_cycle_count_matches_the_info_screen(card, cycles):
    spec = CARDS.get(card)
    assert spec is not None, card
    assert spec.evolution_cycles == cycles, (
        f"{card}: info screen shows Cycles {cycles}, simulator has "
        f"{spec.evolution_cycles}")


def test_minion_horde_evolution_goes_invincible_not_merely_invisible():
    """"The first strike against each member ... makes it briefly invincible."

    The screen lists Invincibility Duration 3sec, Speed Slowdown -33% and Hit
    Speed Slowdown -33%, with a count of 6. Invincible and invisible are not
    the same claim - one refuses damage, the other refuses targeting - so this
    checks the durable one.
    """
    unit = CARDS["minion_horde_ev1"].unit
    assert unit.on_damage_invulnerable_ms == 3000
    assert unit.on_damage_speed_pct == -33
    assert unit.on_damage_hit_speed_pct == -33
    assert CARDS["minion_horde_ev1"].summon_number == 6


def test_electro_dragon_evolution_chains_forever_and_repeats_targets():
    """"Will chain between targets infinitely and can hit the same target more
    than once. Additional Chained Attacks won't stun enemy targets, and they
    will not hit Crown Towers."

    Three separate claims, and the middle one is the surprising part: a chain
    that revisits a target is not how the base card behaves.
    """
    unit = CARDS["electro_dragon_ev1"].unit
    assert unit.chain_unlimited is True
    assert unit.chain_repeat_memory >= 2
    assert unit.hit_speed_ms == 2100          # screen: 2.1sec
    assert unit.range_mt == 3500              # screen: 3.5


def test_berserker_hero_ability_makes_her_unkillable_for_four_seconds():
    """"Goes berserk and becomes unbeatable for a few seconds."

    The screen puts numbers on "unbeatable": Duration 4sec and Minimum
    Hitpoints 1, alongside Hit Speed 0.2sec, Ultra Fast movement and -75% crown
    tower damage. Minimum-hitpoints-1 is the mechanic; it cannot be killed
    while the buff is up but it is not immune to being reduced to one.
    """
    unit = CARDS["berserker_hero"].unit
    assert unit.ability_buff_ms == 4000            # screen: Duration 4sec
    assert unit.ability_unkillable is True         # screen: Minimum Hitpoints 1
    assert unit.ability_cost == 3                  # the badge on the ability icon
    # The screen shows Crown Tower Damage -75%, which the client states as the
    # percentage that still lands.
    assert unit.ability_tower_damage_pct == 25
    # And the ability damage: the screen shows 135 base going to 221, which is
    # +64% - exactly what the client declares, so the two agree on a number
    # without the level ever entering into it.
    assert unit.ability_damage_pct == 64
    assert round(135 * (1 + unit.ability_damage_pct / 100)) == 221
