"""A complete hand-written Hog 2.6 policy.

Twelve blocks of shimming the learned checkpoint produced 11 crowns for and 90
against across 60 matches, flat throughout: the shims corrected individual
behaviours but the model still made most decisions and those decisions lost.
This module decides on its own terms and lets the runner fall back to the model
only when it has no opinion.

Grid: 18 wide x 32 tall, top-down y. y < 16 enemy half, y >= 16 ours.
"""

from __future__ import annotations

import time

import policy_shims as shims

# Placement anchors
BRIDGE_Y = shims.HOG_LANE_Y          # just our side of the bridge
DEFEND_Y = shims.DEFENDER_Y
CANNON_SPOT = shims.CANNON_SPOT
CYCLE_SPOT = (9, 26)                 # behind the king tower

DEFEND_PRIORITY = ("cannon", "musketeer", "ice_golem", "skeletons", "ice_spirit")
CYCLE_PRIORITY = ("skeletons", "ice_spirit", "ice_golem")

PUSH_ELIXIR = 7
SUPPORT_ELIXIR = 4
CYCLE_ELIXIR = 9

_tank_at = 0.0
_tank_lane = 4
_hog_at = 0.0
_hog_lane = 4
_defend_at = 0.0
_defend_size = 0

# One push deserves one answer. Without this the policy re-decided every tick
# and kept stacking defenders into a push it had already handled: 208 defends
# against 11 pushes in a block, with elixir never reaching attack threshold.
DEFEND_COOLDOWN = 4.0
DEFENDERS_NEARBY_RADIUS = 6.0


def _afford(state, slot: int, elixir: float) -> bool:
    return elixir >= state.cards[slot + 1].cost


def _lane_of(cells) -> int:
    return 4 if sum(c[0] for c in cells) / len(cells) < 9 else 14


def decide(state):
    """Return (slot_1based, x, y, note) or None to defer to the model."""
    global _tank_at, _tank_lane, _hog_at, _hog_lane, _defend_at, _defend_size

    elixir = state.numbers.elixir.number
    cells = shims.enemy_cells(state)
    pressure = [c for c in cells if c[1] >= shims.BRIDGE_Y]
    deep = [c for c in pressure if c[1] >= shims.DEEP_Y]
    now = time.monotonic()

    # 1. Finish a tower that is one spell from falling.
    fireball = shims.hand_slot(state, "fireball")
    if fireball is not None and _afford(state, fireball, elixir):
        alive = {
            side: hp
            for side, hp in (
                ("left", state.numbers.left_enemy_princess_hp.number),
                ("right", state.numbers.right_enemy_princess_hp.number),
            )
            if hp > 0.0
        }
        if alive:
            side = min(alive, key=alive.get)
            if alive[side] <= shims.FINISH_HP:
                tx, ty = shims.ENEMY_TOWERS[side]
                return fireball + 1, tx, ty, f"finish_{side}"

    # 2. Defend, but only against a real threat. Gating on "any enemy past the
    #    bridge" made this a turtle: 194 defends against 9 pushes in a block,
    #    hog share down to 3%, elixir never reaching the 7 needed to attack.
    #    A lone shallow unit is not worth a card.
    threatened = len(pressure) >= shims.PRESSURE_UNITS or bool(deep)
    if threatened:
        threat = deep or pressure
        lane = _lane_of(threat)
        # Already answered this push? Only add more if it has grown, or if
        # nothing of ours is near it any more.
        allies = shims.ally_cells(state)
        centre = (
            sum(c[0] for c in threat) / len(threat),
            sum(c[1] for c in threat) / len(threat),
        )
        covering = sum(
            1
            for a in allies
            if ((a[0] - centre[0]) ** 2 + (a[1] - centre[1]) ** 2) ** 0.5
            <= DEFENDERS_NEARBY_RADIUS
        )
        answered = len(threat) <= _defend_size
        recent = now - _defend_at <= DEFEND_COOLDOWN
        # `recent` covers the second between placing a card and the unit
        # appearing; `covering` covers the rest of the fight.
        if answered and (recent or covering):
            return None
        # Spells first when the push is a cluster worth hitting.
        for spell, radius, minimum in (
            ("fireball", shims.FIREBALL_RADIUS, shims.FIREBALL_MIN_ENEMIES),
            ("the_log", shims.LOG_RADIUS, shims.LOG_MIN_ENEMIES),
        ):
            found = shims.hand_slot(state, spell)
            if found is None or not _afford(state, found, elixir):
                continue
            best = shims.best_cluster(pressure, radius, minimum)
            if best is not None and best[1] >= shims.BRIDGE_Y:
                _defend_at, _defend_size = now, len(threat)
                return found + 1, best[0], best[1], f"defend_{spell}"
        for name in DEFEND_PRIORITY:
            found = shims.hand_slot(state, name)
            if found is None or not _afford(state, found, elixir):
                continue
            _defend_at, _defend_size = now, len(threat)
            if name == "cannon":
                return found + 1, CANNON_SPOT[0], CANNON_SPOT[1], "defend_cannon"
            return found + 1, lane, DEFEND_Y, f"defend_{name}"
        return None

    # 3. Back up a Hog that is already running.
    if not threatened and now - _hog_at <= shims.SUPPORT_WINDOW and elixir >= SUPPORT_ELIXIR:
        for name in shims.SUPPORT_PRIORITY:
            found = shims.hand_slot(state, name)
            if found is not None and _afford(state, found, elixir):
                return found + 1, _hog_lane, shims.SUPPORT_Y, f"support_{name}"

    # 4. Build a push: tank first, Hog behind it in the same lane.
    hog = shims.hand_slot(state, "hog_rider")
    if hog is not None and not threatened and elixir >= PUSH_ELIXIR:
        if now - _tank_at <= shims.TANK_WINDOW:
            lane = _tank_lane
        else:
            lane = shims.hog_lane(
                state.numbers.left_enemy_princess_hp.number,
                state.numbers.right_enemy_princess_hp.number,
            )
            golem = shims.hand_slot(state, "ice_golem")
            if golem is not None and elixir >= shims.TANK_MIN_ELIXIR:
                _tank_at, _tank_lane = now, lane
                return golem + 1, lane, BRIDGE_Y, f"tank_lane{lane}"
        _hog_at, _hog_lane = now, lane
        return hog + 1, lane, BRIDGE_Y, f"hog_lane{lane}"

    # 5. Nearly capped with nothing to do: cycle a cheap card at the back.
    if elixir >= CYCLE_ELIXIR:
        for name in CYCLE_PRIORITY:
            found = shims.hand_slot(state, name)
            if found is not None and _afford(state, found, elixir):
                return found + 1, CYCLE_SPOT[0], CYCLE_SPOT[1], f"cycle_{name}"

    # Nothing worth spending on: bank elixir.
    return None
