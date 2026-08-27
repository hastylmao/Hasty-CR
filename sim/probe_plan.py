"""The exact clips to record, each paired with what the simulator predicts.

The remaining work on this simulator is measurement, not code, and the reason
it is tractable is that none of the missing physics is per-card.  Collision is
one rule reading each unit's collision radius and mass, both already parsed
from the shipped files; projectile steering is a `Homing` field.  So the matrix
measures a rule a handful of times, not a card against every other card.

Much of what used to be on this list is not here any more, because it was
never unmeasured - it was unfetched. The published datasets carry every
projectile's speed and its `homing` and `check_collisions` flags, every spell's
radius and duration, and both towers' hitpoints and damage at every level. A
shot that has left an attacker connects with what it was fired at, and
`check_collisions` is false, so there is no spatial miss to film. Projectile
timing, spell timing and tower damage all came off this list that way.

What is left is contact: how close two bodies stand when they meet, and how
close a troop gets to a building it walks past. No dataset publishes that.

Each probe below names one hypothesis, the tiles to deploy on, and the number
this engine currently produces.  Recording it turns the clip into an immediate
agreement or disagreement rather than a judgement call, and a disagreement is
worth more than an agreement.

    python -m sim.probe_plan              the shot list, with predictions
    python -m sim.probe_plan --checklist   just what to record, for the session

Nothing here promotes evidence.  Follow docs/LIVE_PROBE_PROTOCOL.md and add
accepted observations to data/validation/live_probes.json by hand.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Callable, List, Optional

from .arena import (ALLY_KING, ALLY_PRINCESS, BRIDGE_X, MT, Point,
                    RIVER_BOTTOM, RIVER_TOP, TICK_MS, distance)
from .engine import Battle
from .entities import make_unit
from .gamedata import load_gamedata

LEVEL = 11
_CARDS = None


def _cards():
    global _CARDS
    if _CARDS is None:
        _CARDS = load_gamedata(level=LEVEL)
    return _CARDS


def _spawn(battle, name, side, x, y, uid, ready=True):
    entity = battle.add(make_unit(uid, _cards()[name].unit, side,
                                  Point(int(x * MT), int(y * MT))))
    if ready:
        entity.deploy_remaining_ms = 0
    return entity


def _run(battle, seconds):
    for _ in range(int(seconds * 1000 / TICK_MS)):
        battle.step()


@dataclass
class Probe:
    """One clip: one hypothesis, one observable outcome."""

    ident: str
    category: str
    cards: str
    deployment: str
    hypothesis: str
    watch: str
    predict: Optional[Callable[[], str]] = None
    repeats: int = 3

    def prediction(self) -> str:
        if self.predict is None:
            return "no simulator counterpart; the measured value is the input"
        try:
            return self.predict()
        except Exception as error:                        # pragma: no cover
            return f"scenario failed: {type(error).__name__}: {error}"


# --------------------------------------------------------------------------
# map_anchors - measured once, ever.  These are read out of the engine rather
# than simulated: the clip confirms the board, not a behaviour.
# --------------------------------------------------------------------------

def _anchor_readout() -> str:
    left, right = ALLY_PRINCESS["left"], ALLY_PRINCESS["right"]
    return (f"princess centres at tiles ({left.x / MT:g},{left.y / MT:g}) and "
            f"({right.x / MT:g},{right.y / MT:g}); king at "
            f"({ALLY_KING.x / MT:g},{ALLY_KING.y / MT:g})")


def _bridge_readout() -> str:
    return (f"bridge centres at x={BRIDGE_X[0] / MT:g} and "
            f"x={BRIDGE_X[1] / MT:g}, crossable strip one tile either side")


def _river_readout() -> str:
    return (f"river band y={RIVER_TOP / MT:g} to {RIVER_BOTTOM / MT:g}, "
            f"centred on the halfway line")


# --------------------------------------------------------------------------
# troop_contact - the separation rule against four size pairings.  If the rule
# is right, every other pairing follows from radii the sim already has.
# --------------------------------------------------------------------------

def _contact_gap(first_card: str, second_card: str) -> str:
    battle = Battle(trace_contacts=True)
    first = _spawn(battle, first_card, 1, 9.0, 20.0, uid=1)
    second = _spawn(battle, second_card, 1, 9.6, 20.0, uid=2)
    first.speed_mt_per_sec = second.speed_mt_per_sec = 0
    _run(battle, 3)
    gap = distance(first.pos, second.pos)
    required = [row["required_gap_mt"] for row in battle.contact_trace
                if row.get("required_gap_mt")]
    need = max(required) if required else None
    text = f"settles {gap / MT:.2f} tiles apart"
    if need:
        text += f"; rule requires {need / MT:.2f}"
    return text + f"; {len(battle.contact_trace)} trace rows"


def _king_tower_two_troops() -> str:
    """The experiment the protocol calls out by name.

    Two opposing units meeting at the King Tower is where the present
    approximation deliberately lets mutual engagement overlap, so the trace
    marks `engaged_contact_exempt`.  The clip decides whether the real game
    pushes them apart there.
    """
    battle = Battle(trace_contacts=True)
    ours = _spawn(battle, "knight", 1, 9.0, 26.0, uid=1)
    theirs = _spawn(battle, "knight", -1, 9.0, 26.5, uid=2)
    _run(battle, 6)
    exempt = [row for row in battle.contact_trace
              if row.get("kind") == "engaged_contact_exempt"]
    gap = distance(ours.pos, theirs.pos)
    text = (f"{len(exempt)} engaged_contact_exempt rows; "
            f"final separation {gap / MT:.2f} tiles")
    if exempt:
        text += " - the approximation is letting them touch"
    return text


def _building_route(building: str) -> str:
    """How close a troop's centre gets to a building it must walk past.

    The engine routes around a building through the flow field rather than by
    pushing a unit out of it, so `building_contact` rows are the exception and
    the closest approach is the number a video can actually show.  A friendly
    building is used so the troop walks past rather than stopping to attack.
    """
    from .entities import make_tower
    from .arena import ENEMY_PRINCESS

    battle = Battle(trace_contacts=True)
    battle.add(make_tower(90, -1, ENEMY_PRINCESS["left"], 3052, 109, 800, 7500))
    mover = _spawn(battle, "giant", 1, 3.5, 20.0, uid=1)
    blocker = _spawn(battle, building, 1, 4.0, 17.0, uid=2)
    closest = distance(mover.pos, blocker.pos)
    for _ in range(int(12 * 1000 / TICK_MS)):
        battle.step()
        closest = min(closest, distance(mover.pos, blocker.pos))
    rows = [row for row in battle.contact_trace
            if row.get("kind") == "building_contact"]
    passed = mover.pos.y < blocker.pos.y
    return (f"closest approach {closest / MT:.2f} tiles to centre; "
            + ("routed past it" if passed else "did not get past")
            + f"; {len(rows)} building_contact push-out rows")


# --------------------------------------------------------------------------
# projectile_timing - one homing and one non-homing shot, stationary and
# moving.  Non-homing geometry is why all nine action graphs are gated.
# --------------------------------------------------------------------------

def _projectile(shooter: str, moving: bool) -> str:
    battle = Battle(trace_contacts=True)
    source = _spawn(battle, shooter, 1, 9.0, 20.0, uid=1)
    target = _spawn(battle, "giant", -1, 9.0, 15.0, uid=2)
    source.speed_mt_per_sec = 0
    if not moving:
        target.speed_mt_per_sec = 0
    target.damage = 0
    _run(battle, 6)
    unmodelled = battle.unmodelled_projectiles
    if unmodelled:
        shot = unmodelled[0]
        flight = shot["arrival_ms"] - shot["launch_ms"]
        return (f"NON-HOMING and unresolved: {len(unmodelled)} launches held "
                f"for calibration; first flight {flight}ms at "
                f"{shot['speed_mt_per_sec']} mt/s, radius "
                f"{shot['radius_mt'] / MT:.2f} tiles")
    hits = [time for time, src, _, _ in battle.damage_log if src == 1]
    if not hits:
        return "no shots landed"
    gaps = [later - earlier for earlier, later in zip(hits, hits[1:])]
    return (f"homing: first hit at {hits[0]}ms, {len(hits)} hits in 6s, "
            f"gaps {gaps[:3]}")


# --------------------------------------------------------------------------
# spell_timing - cast to impact, and where the target actually was.
# --------------------------------------------------------------------------

def _spell(name: str) -> str:
    from .spells import load_spells
    spec = load_spells(level=LEVEL).get(name)
    if spec is None:
        return f"{name} not resolved by the spell loader"
    bits = []
    for attribute, label in (("radius_mt", "radius"),
                             ("speed_mt_per_sec", "speed"),
                             ("damage", "damage"),
                             ("duration_ms", "duration")):
        value = getattr(spec, attribute, None)
        if not value:
            continue
        if attribute == "radius_mt":
            bits.append(f"{label}={value / MT:.2f} tiles")
        else:
            bits.append(f"{label}={value}")
    return "; ".join(bits) or "no timing fields exposed"


def _tower_damage() -> str:
    from .match import (KING_DAMAGE, KING_HIT_MS, PRINCESS_DAMAGE,
                        PRINCESS_HIT_MS)
    return (f"king {KING_DAMAGE} per shot every {KING_HIT_MS}ms; "
            f"princess {PRINCESS_DAMAGE} every {PRINCESS_HIT_MS}ms "
            f"(king damage is the uncertain one)")


PROBES: List[Probe] = [
    # ---- map_anchors -----------------------------------------------------
    Probe("MAP-1", "map_anchors",
          "no cards; empty Training Camp board",
          "screenshot the full arena with no units placed",
          "Tower centres and the deploy boundary sit where the engine puts them.",
          "Tower centre tiles against the grid; the exact deploy-zone line.",
          _anchor_readout, repeats=1),
    Probe("MAP-2", "map_anchors",
          "no cards; empty board",
          "screenshot both bridges",
          "Bridge centres and crossable width match the engine.",
          "Bridge centre x, and how wide a strip a troop may cross on.",
          _bridge_readout, repeats=1),
    Probe("MAP-3", "map_anchors",
          "no cards; empty board",
          "screenshot the river",
          "The river band is centred on the halfway line, not offset to one side.",
          "River top and bottom edge. An offset band once cost one seat a whole "
          "tile per push and invalidated every A/B result run on that board.",
          _river_readout, repeats=1),

    # ---- troop_contact ---------------------------------------------------
    Probe("TC-1", "troop_contact",
          "two Skeletons (same-size swarm), level 11",
          "both on the same tile in the open lane, around (9, 20)",
          "Same-size bodies settle at exactly twice the collision radius.",
          "Steady-state spacing between two adjacent bodies once they stop.",
          lambda: _contact_gap("skeletons", "skeletons")),
    Probe("TC-2", "troop_contact",
          "Skeleton + Knight (small + medium), level 11",
          "adjacent tiles in the open lane, around (9, 20)",
          "Unequal radii settle at the sum of the two, and the lighter moves.",
          "Which unit gets displaced, and by how much. Mass decides this.",
          lambda: _contact_gap("skeletons", "knight")),
    Probe("TC-3", "troop_contact",
          "Knight + Giant (medium + large), level 11",
          "adjacent tiles in the open lane, around (9, 20)",
          "A large body displaces a medium one rather than sharing the push.",
          "How the displacement splits between the pair.",
          lambda: _contact_gap("knight", "giant")),
    Probe("TC-4", "troop_contact",
          "two Knights, one each side, level 11",
          "both at the King Tower, around (9, 26) and (9, 27)",
          "Two opposing units engaged at the King Tower are still pushed apart.",
          "Whether they overlap while fighting. This is the single most "
          "important contact clip: the engine currently exempts engaged pairs "
          "from separation, and the trace marks exactly that.",
          _king_tower_two_troops),

    # ---- building_contact ------------------------------------------------
    Probe("BC-1", "building_contact",
          "Giant + Cannon, level 11",
          "Giant at (3.5, 20), your own Cannon at (4, 17), left lane",
          "A troop stops at the building hitbox edge, not the building centre.",
          "Standoff distance from the Cannon footprint.",
          lambda: _building_route("cannon")),
    Probe("BC-2", "building_contact",
          "Giant + Tesla, level 11",
          "Giant at (3.5, 20), your own Tesla at (4, 17), left lane",
          "Tesla's retracted and raised states do not change the contact gap.",
          "Whether the standoff shifts when the Tesla pops up.",
          lambda: _building_route("tesla")),
    Probe("BC-3", "building_contact",
          "Giant + Goblin Cage, level 11",
          "Giant at (3.5, 20), your own Goblin Cage at (4, 17), left lane",
          "Routing around a building uses the same gap as stopping at one.",
          "The path taken around the cage, and the gap held while walking past.",
          lambda: _building_route("goblin_cage")),

]


def _by_category() -> dict:
    grouped: dict = {}
    for probe in PROBES:
        grouped.setdefault(probe.category, []).append(probe)
    return grouped


def render(checklist_only: bool = False) -> str:
    lines: List[str] = []
    total = sum(probe.repeats for probe in PROBES)
    lines.append("Controlled capture shot list")
    lines.append("=" * 74)
    lines.append(f"{len(PROBES)} distinct clips, {total} takes with repeats.")
    lines.append("")
    lines.append("Record at 60 fps. The catalogued 30 fps recordings are")
    lines.append("permanently ineligible: the gate requires 50+ fps.")
    lines.append("Training Camp, one hypothesis per clip, nothing else in the")
    lines.append("lane, two seconds before deployment through two seconds after")
    lines.append("the outcome. Name each file with its probe id.")

    for category, probes in _by_category().items():
        lines.append("")
        lines.append(f"[{category}]")
        lines.append("-" * 74)
        for probe in probes:
            lines.append(f"  {probe.ident}  ({probe.repeats}x)  {probe.cards}")
            lines.append(f"      place   : {probe.deployment}")
            lines.append(f"      claim   : {probe.hypothesis}")
            lines.append(f"      measure : {probe.watch}")
            if not checklist_only:
                lines.append(f"      sim says: {probe.prediction()}")
            lines.append("")

    lines.append("")
    lines.append("A disagreement is the valuable outcome. Do not edit a constant")
    lines.append("from these clips directly - follow docs/LIVE_PROBE_PROTOCOL.md,")
    lines.append("then add the observation to data/validation/live_probes.json")
    lines.append("together with the test that protects it.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Controlled capture shot list")
    parser.add_argument("--checklist", action="store_true",
                        help="omit simulator predictions; just what to record")
    args = parser.parse_args()
    print(render(checklist_only=args.checklist))


if __name__ == "__main__":
    main()
