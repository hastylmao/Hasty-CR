"""Values transcribed from an action graph by hand, checked against the graph.

Some mechanics are read from the client and some were read *by a person* and
written into the loader as constants. The second kind is fine - an action graph
with conditionals and staged sub-actions is not always worth a parser - but it
has a failure mode the first kind does not: the client updates and the constant
does not, and nothing notices, because a hardcoded number never stops working.

This is the check that notices. It re-derives each transcribed value from the
shipped data and compares.

Found by `scripts/unread_fields.py` flagging `SubActionsDelay` as a key the
simulator never mentions. That is true, and mostly harmless: almost every group
in the client is `[0, 0]` or a sub-tick 50ms. Twenty-five files do stage by a
real interval, and they are enumerated at the bottom so a new one is visible -
but most of that staging is animation and effect sequencing, and the cards this
project models were built from their declared values rather than by walking
their graphs.

The one transcription that had to be checked is Zap Evolution's, whose two
pulses were written into the loader as constants.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import GAMEDATA_ROOT, parse_toml_file          # noqa: E402
from sim.spells import load_spells                               # noqa: E402

SPELLS = load_spells(level=11)
DATA = Path(GAMEDATA_ROOT)


def _actions():
    return parse_toml_file(DATA / "actions.toml")


def _evo_areas():
    return parse_toml_file(DATA / "area_effect_objects_evo.toml")


def test_evolved_zaps_pulses_match_the_client_graph():
    """`pulse_events` on zap_ev1 is a transcription of this graph:

        [Zap_EV1]                     OnStartingAction = Zap_EV1_AfterStun_V2
        [Zap_EV1_AfterStun_V2]        SubActionsDelay = [50, 1450]
                                      SubActions = [visual, SpawnAOE_medium]
        [Zap_EV1_SpawnAOE_medium]     Base = "Zap", Radius = ["+", 500]

    so: the ordinary Zap at once, then a full-damage one 1450ms later at
    Zap's radius plus 500.
    """
    pulses = SPELLS["zap_ev1"].pulse_events
    assert len(pulses) == 2, pulses

    area = _evo_areas()["Zap_EV1"]
    assert area["OnStartingAction"] == "Zap_EV1_AfterStun_V2", (
        "Evolved Zap now starts a different action than the one transcribed")

    group = _actions()["Zap_EV1_AfterStun_V2"]
    delays = list(group["SubActionsDelay"])
    subs = list(group["SubActions"])
    # The second sub-action is the one that spawns damage; the first is visual.
    spawn_index = next(i for i, name in enumerate(subs) if "SpawnAOE" in name)
    declared_delay = delays[spawn_index]

    second = _evo_areas()[subs[spawn_index]]
    bonus = second["Radius"]
    assert bonus[0] == "+", f"radius is no longer an increment: {bonus}"

    base_radius = SPELLS["zap"].radius_mt
    assert pulses[0] == (0, base_radius, 100), pulses[0]
    assert pulses[1] == (declared_delay, base_radius + int(bonus[1]), 100), (
        f"transcribed {pulses[1]} against a client graph saying "
        f"({declared_delay}, {base_radius + int(bonus[1])}, 100)")


def test_the_unused_large_pulse_is_still_unused():
    """`Zap_EV1_SpawnAOE_large` exists and nothing in the live graph spawns it.

    It is the older, wider, half-damage version. If a balance change ever wires
    it back in, the transcription above goes stale silently - so this asserts
    that it is still orphaned rather than trusting that it is.
    """
    areas = _evo_areas()
    assert "Zap_EV1_SpawnAOE_large" in areas, (
        "the orphan is gone; re-check what Evolved Zap spawns now")
    spawned = set()
    for action in _actions().values():
        if isinstance(action, dict) and action.get("SpawnData"):
            spawned.add(str(action["SpawnData"]))
    reachable = set()
    group = _actions().get("Zap_EV1_AfterStun_V2", {})
    for name in group.get("SubActions", ()):
        action = _actions().get(str(name), {})
        if isinstance(action, dict) and action.get("SpawnData"):
            reachable.add(str(action["SpawnData"]))
    assert "Zap_EV1_SpawnAOE_large" not in reachable, (
        "Evolved Zap now spawns the large pulse; pulse_events needs updating")


# Files whose action groups stage sub-actions more than one engine tick apart.
# Being on this list does NOT mean the staging is modelled - most of these are
# animation and effect sequencing, and several belong to cards this project has
# implemented from their declared values rather than by walking their graph.
# The list exists so that a *new* one appearing is visible, because a new
# staged group is a mechanic nobody has looked at yet.
STAGED_FILES = {
    "202410_event_blackout.toml", "actions.toml", "area_effect_objects.toml",
    "berserker_hero.toml", "bowler_hero.toml", "dark_prince_hero.toml",
    "elite_archer_hero.toml", "event_goblin_rocket_silo.toml",
    "furnace_ev1.toml", "giant_hero.toml", "goblin_curse.toml",
    "goblin_machine.toml", "goblin_queen.toml", "goblins_hero.toml",
    "goblinstein.toml", "graveyard_rework.toml", "mega_knight_ev1.toml",
    "mega_minion_hero.toml", "musketeer_ev1.toml", "princess_ev1.toml",
    "ronin.toml", "suspicious_bush.toml", "tombstone_hero.toml",
    "vines.toml", "witch_ev1.toml",
}


def test_no_new_staged_action_group_has_appeared():
    """`SubActionsDelay` is unread, and mostly that costs nothing.

    Almost every group in the client is `[0, ...]` or a sub-tick 50ms. The ones
    that stage by a real interval are the ones where ignoring the field could
    matter, so they are enumerated rather than assumed away.
    """
    pattern = re.compile(r"SubActionsDelay\s*=\s*\[([^\]]*)\]")
    staged = set()
    for path in DATA.rglob("*.toml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            values = [v.strip() for v in match.group(1).split(",") if v.strip()]
            try:
                numbers = [int(v) for v in values]
            except ValueError:
                continue
            # More than one engine tick apart is staging; 50 or 100ms is not.
            if any(n > 200 for n in numbers):
                staged.add(path.name)
    new = staged - STAGED_FILES
    assert not new, (
        f"new staged action groups: {sorted(new)} - check whether the "
        f"simulator needs to model their timing")
    assert not STAGED_FILES - staged, (
        f"these no longer stage: {sorted(STAGED_FILES - staged)}")
