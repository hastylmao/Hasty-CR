"""Freezing a hut stops it producing, and raging one speeds it up.

Neither happened. A Freeze on a Tombstone stopped it attacking and left it
spawning skeletons at exactly its normal rate, which is a large error on a
common interaction - Freeze on a defensive spawner is a standard play and it
was buying nothing but the attack pause.

The mechanic is `SpawnSpeedMultiplier`, declared on twelve buffs and read by
nothing. What makes the fix a single line rather than a new field is that in
*every* case the client sets it to exactly the same number as
`HitSpeedMultiplier`:

    Stun, ContinueFreeze, ElectroGiantZapFreeze,
    Event_Freeze, MysteryBuff_ZapFreeze          -100 / -100
    RageModeRage                                  130 / 130
    Neutral_Rage, SuperRage                       170 / 170
    IgnoreBarrel                                  100 / 100

So the field the simulator already carries on every buffed entity is the field
the client uses; `_tick_spawners` simply never looked at it.

A frozen hut holds its wave rather than losing it, so it resumes where it was
when the freeze ends instead of restarting the timer.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import Point, TICK_MS                            # noqa: E402
from sim.engine import Battle                                   # noqa: E402
from sim.entities import make_unit                              # noqa: E402
from sim.gamedata import load_buffs, load_characters, load_gamedata  # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
TABLE = load_characters(11)
SPELLS = load_spells(level=11)

# Derived rather than named: card names and the roster both move, and a
# hardcoded list quietly stops testing anything when one of them is renamed.
#
# Bounded by how long a spawner takes to produce, because a test has to see a
# wave arrive before it can say freezing stopped one. That leaves out
# `witch_ev1`, whose interval is five minutes, and `barbarian_hut` at fourteen
# seconds a wave - both go through the same code path as the rest.
OBSERVABLE_MS = 8000
ALL_SPAWNERS = sorted(
    name for name, card in CARDS.items()
    if card.unit is not None and card.unit.spawn_character
    and card.unit.spawn_pause_ms > 0)
SPAWNERS = [name for name in ALL_SPAWNERS
            if CARDS[name].unit.spawn_pause_ms <= OBSERVABLE_MS]
# Super Mini P.E.K.K.A and Santa Hog Rider are the suite's two pinned inert
# spawners - the object they name has no Hitpoints in any source - so they
# produce nothing whether frozen or not and prove nothing here.
INERT = {"super_mini_pekka", "super_hog_rider"}
SPAWNERS = [name for name in SPAWNERS if name not in INERT]


def test_freeze_is_a_full_stop_on_hit_speed():
    """Which is what makes it a full stop on spawning too."""
    assert load_buffs()["Freeze"][1] <= -100
    assert load_buffs()["ZapFreeze"][1] <= -100


def _spawned_in(card, seconds, hit_speed_pct=0):
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    hut = battle.add(make_unit(1, CARDS[card].unit, 1, Point(9000, 22000)))
    hut.deploy_remaining_ms = 0
    seen = set()
    for _ in range(int(seconds * 1000 / TICK_MS)):
        if hit_speed_pct:
            hut.buff_until_ms = battle.now_ms + 1000
            hut.buff_hit_speed_pct = hit_speed_pct
        battle.step()
        seen |= {e.uid for e in battle.entities.values() if e.uid != hut.uid}
    return len(seen), hut


def test_there_are_spawners_to_check():
    assert len(SPAWNERS) >= 5, SPAWNERS
    # The excluded ones are excluded for being slow or already-known inert,
    # not for failing.
    assert set(ALL_SPAWNERS) - set(SPAWNERS) - INERT == {
        "barbarian_hut", "witch_ev1"}, sorted(set(ALL_SPAWNERS) - set(SPAWNERS))


@pytest.mark.parametrize("card", SPAWNERS)
def test_a_frozen_hut_produces_nothing(card):
    window = CARDS[card].unit.spawn_pause_ms * 3 / 1000
    normal, _hut = _spawned_in(card, seconds=window)
    frozen, _hut = _spawned_in(card, seconds=window, hit_speed_pct=-100)
    assert normal > 0, f"{card} spawned nothing even unfrozen in {window:.0f}s"
    assert frozen == 0, (
        f"{card} produced {frozen} while frozen; Freeze on a spawner was "
        f"buying only the attack pause")


def test_a_raged_hut_produces_faster():
    normal, _hut = _spawned_in("tombstone", seconds=12)
    raged, _hut = _spawned_in("tombstone", seconds=12, hit_speed_pct=30)
    assert raged > normal, (
        f"raged produced {raged} against {normal} unraged")


def test_the_wave_is_held_rather_than_lost():
    """It resumes where it was, instead of restarting its timer on thaw."""
    battle = Battle()
    battle.unit_lookup = lambda name: TABLE.get(name)
    hut = battle.add(make_unit(1, CARDS["tombstone"].unit, 1, Point(9000, 22000)))
    hut.deploy_remaining_ms = 0

    # Run most of the way to the first spawn, then freeze for two seconds.
    almost = hut.spawn_pause_ms - 400
    for _ in range(int(almost / TICK_MS)):
        battle.step()
    for _ in range(int(2000 / TICK_MS)):
        hut.buff_until_ms = battle.now_ms + 1000
        hut.buff_hit_speed_pct = -100
        battle.step()
    assert not [e for e in battle.entities.values() if e.uid != hut.uid]

    hut.buff_until_ms = 0
    hut.buff_hit_speed_pct = 0
    for _ in range(int(900 / TICK_MS)):
        battle.step()
    assert [e for e in battle.entities.values() if e.uid != hut.uid], (
        "the hut restarted its whole cycle after thawing instead of resuming")


def test_freezing_a_tombstone_in_a_real_match_stops_the_skeletons():
    deck = ["tombstone", "freeze", "archers", "musketeer",
            "cannon", "skeletons", "giant", "hog_rider"]
    counts = {}
    for cast in (False, True):
        match = Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)
        for _ in range(40):
            match.step()
        player = match.players[1]
        player.hand[0] = "tombstone"
        player.elixir = 10_000
        assert match.play_card(1, "tombstone", grid_to_point(9, 22, 1))
        for _ in range(40):
            match.step()
        tomb = next(e for e in match.battle.entities.values()
                    if e.name == "tombstone")
        if cast:
            enemy = match.players[-1]
            enemy.hand[0] = "freeze"
            enemy.elixir = 10_000
            assert match.play_card(-1, "freeze", tomb.pos)
        born = set()
        for _ in range(int(4 * 1000 / TICK_MS)):
            match.step()
            born |= {e.uid for e in match.battle.entities.values()
                     if e.name == "skeleton" and e.side == 1}
        counts[cast] = len(born)
    assert counts[False] > 0
    assert counts[True] == 0, (
        f"a frozen Tombstone still produced {counts[True]} skeletons")
