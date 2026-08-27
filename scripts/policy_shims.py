"""Hand-written strategy guards and Hog 2.6 micro-defense tactics layered on top of the learned policy.

Key strategic corrections:
1. Offensive Cycle: Force Hog at bridge when affordable and safe; alternate lanes.
2. Anti-Leak Cycle: When elixir >= 9.5 with no active push, cycle cheap cards at the back.
3. Building Geometry: Enforce optimal 4-3 and 2-3 Cannon pull coordinates based on incoming threat lane.
4. Cross-Lane Kiting: Pull heavy melee threats across the center with Ice Golem.
5. Skeletons Surround / Distraction: Place 1-elixir Skeletons in center (9, 21) against single-target melee rushers.
6. Anti-Spell Spacing: Stagger Musketeer placements away from Cannon to prevent dual-spell value.
7. Spell Retargeting & Tower Finishing: Redirect spells to densest enemy clusters and snipe finishable towers (<= 0.18 HP).

Grid convention (from adapter): 18 wide x 32 tall, top-down y.
  y < 16   enemy half        y >= 16  our half
  bridge   y ~= 16           our princess towers (4,24) and (14,24)
"""

from __future__ import annotations

import time
from typing import List, Tuple, Optional

BRIDGE_Y = 16
SPELLS = {"fireball", "the_log"}
BUILDINGS = {"cannon"}

# Canonical 2.6 defensive pocket ranges
BUILDING_X_RANGE = (8, 10)
BUILDING_Y_RANGE = (19, 22)

# Specific Cannon pull coordinates
CANNON_SPOT = (9, 20)
# 4-3 Pull (standard single-lane pull):
CANNON_4_3_LEFT = (9, 20)
CANNON_4_3_RIGHT = (10, 20)
# 2-3 Pull (two princess towers engage high-speed bridge rushers):
CANNON_2_3_LEFT = (9, 19)
CANNON_2_3_RIGHT = (10, 19)

# Kiting spots for Ice Golem across lanes
KITE_SPOT_FOR_LEFT_THREAT = (10, 18)   # Placed in right lane to pull left threat
KITE_SPOT_FOR_RIGHT_THREAT = (8, 18)   # Placed in left lane to pull right threat

# Center distraction pocket for Skeletons surround
SKELETONS_DISTRACT_SPOT = (9, 21)

# Anti-spell spaced Musketeer positions (far from center cannon pocket)
MUSKETEER_SAFE_LEFT = (3, 22)
MUSKETEER_SAFE_RIGHT = (15, 22)

# Safe cycling positions behind princess towers
CYCLE_BACK_LEFT = (4, 28)
CYCLE_BACK_RIGHT = (14, 28)
CYCLE_SAFE_ELIXIR = 6.0

# Spell parameters
FIREBALL_MIN_ENEMIES = 2
FIREBALL_RADIUS = 3.0
LOG_MIN_ENEMIES = 1
LOG_RADIUS = 2.5

# Offensive Cycle Constants
HOG_MIN_ELIXIR = 5
HOG_LANE_Y = 17
COUNTERPUSH_WINDOW = 5.0
COUNTERPUSH_ELIXIR = 4

TANK_WINDOW = 6.0
TANK_MIN_ELIXIR = 6

ENEMY_TOWERS = {"left": (4, 7), "right": (14, 7)}
FINISH_HP = 0.18

SUPPORT_WINDOW = 5.0
SUPPORT_PRIORITY = ("ice_golem", "musketeer", "ice_spirit")
SUPPORT_Y = 19
SUPPORT_MIN_ELIXIR = 4

CHIP_CARDS = {"ice_spirit", "skeletons"}
PRESSURE_UNITS = 2
DEEP_Y = 20
DEFENDER_Y = 22


def enemy_cells(state) -> List[Tuple[float, float]]:
    """Enemy unit positions in grid space (BuildABot tile_y is bottom-up)."""
    cells = []
    for enemy in state.enemies:
        cells.append((float(enemy.position.tile_x), 31.0 - float(enemy.position.tile_y)))
    return cells


def ally_cells(state) -> List[Tuple[float, float]]:
    """Our own unit positions in grid space, same convention as enemies."""
    return [
        (float(a.position.tile_x), 31.0 - float(a.position.tile_y))
        for a in state.allies
    ]


def _near(cells, x: float, y: float, radius: float) -> int:
    return sum(1 for cx, cy in cells if ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5 <= radius)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def best_cluster(cells, radius: float, minimum: int):
    """Centre of the densest group of >= `minimum` enemies, or None."""
    best_count = minimum - 1
    best = None
    for cx, cy in cells:
        group = [c for c in cells if ((c[0] - cx) ** 2 + (c[1] - cy) ** 2) ** 0.5 <= radius]
        if len(group) > best_count:
            best_count = len(group)
            best = (
                int(round(sum(c[0] for c in group) / len(group))),
                int(round(sum(c[1] for c in group) / len(group))),
            )
    return best


_last_hog_lane = 14
_hog_sent_at = 0.0
_hog_sent_lane = 4
_tank_sent_at = 0.0
_tank_lane = 4
_had_pressure = False
_cleared_at = 0.0
_defend_at = 0.0
_defend_size = 0
_defend_centre = (9.0, 20.0)

# The shim runs every decision tick. Without a small commitment memory it can
# answer the same push with Skeletons, then Cannon, then Ice Golem, then
# Musketeer before the first card has even finished spawning.
DEFEND_COMMIT_SECONDS = 3.8
DEFEND_COVER_RADIUS = 6.0
DEFEND_GROWTH_MARGIN = 1

HOG_SPELL_SUPPORT_WINDOW = 4.5
HOG_SPELL_LANE_RADIUS = 4.0
HOG_LOG_MIN_ENEMIES = 2


def hog_lane(left_hp: float, right_hp: float) -> int:
    """Pick the attack lane, alternating when both towers are equal."""
    global _last_hog_lane
    if abs(left_hp - right_hp) >= 0.10:
        return 4 if left_hp < right_hp else 14
    _last_hog_lane = 4 if _last_hog_lane == 14 else 14
    return _last_hog_lane


def hand_slot(state, card_name: str) -> Optional[int]:
    """Ready slot index (0-3) holding card_name, or None."""
    for slot in state.ready:
        if 0 <= slot < 4 and state.cards[slot + 1].name == card_name:
            return slot
    return None


def _threat_centre(threat) -> Tuple[float, float]:
    return (
        sum(cell[0] for cell in threat) / len(threat),
        sum(cell[1] for cell in threat) / len(threat),
    )


def _covered_by_allies(state, centre: Tuple[float, float]) -> bool:
    return any(
        ((ax - centre[0]) ** 2 + (ay - centre[1]) ** 2) ** 0.5 <= DEFEND_COVER_RADIUS
        for ax, ay in ally_cells(state)
    )


def _already_answered(state, threat, now: float) -> bool:
    if not threat:
        return False
    centre = _threat_centre(threat)
    same_fight = (
        ((centre[0] - _defend_centre[0]) ** 2 + (centre[1] - _defend_centre[1]) ** 2) ** 0.5
        <= DEFEND_COVER_RADIUS
    )
    not_grown = len(threat) <= _defend_size + DEFEND_GROWTH_MARGIN
    recent = now - _defend_at <= DEFEND_COMMIT_SECONDS
    return same_fight and not_grown and (recent or _covered_by_allies(state, centre))


def _mark_defended(threat, now: float) -> None:
    global _defend_at, _defend_size, _defend_centre
    _defend_at = now
    _defend_size = len(threat)
    _defend_centre = _threat_centre(threat)


def apply(state, slot: int, x: int, y: int, delay: int):
    """Return (slot, x, y, delay, note) or None to veto the action.

    `slot` is 1-based to match the policy's output convention.
    """
    elixir = state.numbers.elixir.number
    cells = enemy_cells(state)
    pressure = [cell for cell in cells if cell[1] >= BRIDGE_Y]
    now = time.monotonic()

    # 0. Finisher: Fireball a nearly-dead enemy tower (<= 0.18 HP)
    if not pressure:
        fireball = hand_slot(state, "fireball")
        if fireball is not None and elixir >= state.cards[fireball + 1].cost:
            targets = {
                side: hp
                for side, hp in (
                    ("left", state.numbers.left_enemy_princess_hp.number),
                    ("right", state.numbers.right_enemy_princess_hp.number),
                )
                if hp > 0.0
            }
            if targets:
                side = min(targets, key=targets.get)
                if targets[side] <= FINISH_HP:
                    tx, ty = ENEMY_TOWERS[side]
                    return fireball + 1, tx, ty, 0, f"finish_{side}({targets[side]:.2f})"

    # 1. Defensive Micro Tactics & Defender Substitution
    card = state.cards[slot].name if 1 <= slot <= 4 else "blank"
    deep = [cell for cell in pressure if cell[1] >= DEEP_Y]
    under_heavy_attack = len(pressure) >= PRESSURE_UNITS or bool(deep)
    
    if under_heavy_attack and card not in {"cannon", "musketeer"}:
        threat = deep or pressure
        if _already_answered(state, threat, now):
            return None
        avg_threat_x = sum(cell[0] for cell in threat) / len(threat)
        is_left_threat = avg_threat_x < 9.0
        
        # 1a. Check for Cross-Lane Ice Golem Kite Opportunity
        golem_slot = hand_slot(state, "ice_golem")
        if golem_slot is not None and elixir >= 2:
            kite_x, kite_y = KITE_SPOT_FOR_LEFT_THREAT if is_left_threat else KITE_SPOT_FOR_RIGHT_THREAT
            _mark_defended(threat, now)
            return golem_slot + 1, kite_x, kite_y, 0, f"kite_ice_golem_threat_{'left' if is_left_threat else 'right'}"
            
        # 1b. Pull with Cannon at 4-3 / 2-3 optimal pocket
        cannon_slot = hand_slot(state, "cannon")
        if cannon_slot is not None and elixir >= 3:
            cx, cy = CANNON_4_3_LEFT if is_left_threat else CANNON_4_3_RIGHT
            _mark_defended(threat, now)
            return cannon_slot + 1, cx, cy, 0, f"defend_cannon_pull_{'left' if is_left_threat else 'right'}"

        # 1c. Skeletons Surround / Distraction in Center Pocket
        skel_slot = hand_slot(state, "skeletons")
        if skel_slot is not None and elixir >= 1 and len(threat) == 1:
            _mark_defended(threat, now)
            return skel_slot + 1, SKELETONS_DISTRACT_SPOT[0], SKELETONS_DISTRACT_SPOT[1], 0, "defend_skeletons_distract"

        # 1d. Anti-Spell Spaced Musketeer
        musk_slot = hand_slot(state, "musketeer")
        if musk_slot is not None and elixir >= 4:
            mx, my = MUSKETEER_SAFE_LEFT if is_left_threat else MUSKETEER_SAFE_RIGHT
            _mark_defended(threat, now)
            return musk_slot + 1, mx, my, 0, f"defend_musketeer_spaced_{'left' if is_left_threat else 'right'}"

    # 2. Win Condition: Forced Hog Rider Cycling (When not under heavy attack)
    hog = hand_slot(state, "hog_rider")
    if hog is not None and elixir >= 4 and not under_heavy_attack:
        global _hog_sent_at, _hog_sent_lane, _tank_sent_at, _tank_lane
        if now - _tank_sent_at <= TANK_WINDOW:
            lane_x = _tank_lane
        else:
            lane_x = hog_lane(
                state.numbers.left_enemy_princess_hp.number,
                state.numbers.right_enemy_princess_hp.number,
            )
            golem = hand_slot(state, "ice_golem")
            if golem is not None and elixir >= 6:
                _tank_sent_at, _tank_lane = now, lane_x
                return golem + 1, lane_x, HOG_LANE_Y, 0, f"tank_first_lane{lane_x}"
                
        _hog_sent_at, _hog_sent_lane = now, lane_x
        return hog + 1, lane_x, HOG_LANE_Y, 0, f"force_hog_lane{lane_x}"

    # 2b. Push Support: use a spell only on a real cluster contesting the Hog's
    # lane. This protects against the old random Fireball/Log problem while
    # still helping pushes convert through swarms.
    if time.monotonic() - _hog_sent_at <= HOG_SPELL_SUPPORT_WINDOW and not deep:
        lane_cells = [
            cell for cell in cells
            if cell[1] <= BRIDGE_Y + 2 and abs(cell[0] - _hog_sent_lane) <= HOG_SPELL_LANE_RADIUS
        ]
        fireball = hand_slot(state, "fireball")
        if fireball is not None and elixir >= state.cards[fireball + 1].cost:
            best = best_cluster(lane_cells, FIREBALL_RADIUS, FIREBALL_MIN_ENEMIES)
            if best is not None:
                return fireball + 1, best[0], best[1], 0, "support_fireball_hog_cluster"
        log = hand_slot(state, "the_log")
        if log is not None and elixir >= state.cards[log + 1].cost:
            best = best_cluster(lane_cells, LOG_RADIUS, HOG_LOG_MIN_ENEMIES)
            if best is not None and best[1] >= 10:
                return log + 1, best[0], best[1], 0, "support_log_hog_cluster"

    # 2c. Push Support: Follow Hog with Ice Golem / Musketeer / Spirit
    if not pressure and time.monotonic() - _hog_sent_at <= SUPPORT_WINDOW:
        for support in SUPPORT_PRIORITY:
            found = hand_slot(state, support)
            if found is not None and elixir >= state.cards[found + 1].cost:
                return found + 1, _hog_sent_lane, SUPPORT_Y, 0, f"support_{support}"

    # 2d. Anti-Leak Elixir Cycling: If sitting at 9.5+ elixir with no push, cycle cheap cards at the back
    if not pressure and elixir >= 9.5:
        for chip in ("ice_spirit", "skeletons"):
            found = hand_slot(state, chip)
            if found is not None:
                cycle_spot = CYCLE_BACK_LEFT if _last_hog_lane == 14 else CYCLE_BACK_RIGHT
                return found + 1, cycle_spot[0], cycle_spot[1], 0, f"anti_leak_cycle_{chip}"

    # 3. Buildings Clamp: Ensure any Cannon placement stays strictly in pocket
    if card in BUILDINGS:
        avg_threat_x = sum(cell[0] for cell in pressure) / max(1, len(pressure)) if pressure else 9.0
        optimal_x = 9 if avg_threat_x < 9.0 else 10
        cx = _clamp(x if 8 <= x <= 10 else optimal_x, *BUILDING_X_RANGE)
        cy = _clamp(y, *BUILDING_Y_RANGE)
        if pressure:
            _mark_defended(deep or pressure, now)
        if (cx, cy) != (x, y):
            return slot, cx, cy, delay, f"clamp_building({x},{y})->({cx},{cy})"
        return slot, x, y, delay, None

    # 4. Spells Retargeting onto Densest Clusters
    if card in SPELLS:
        radius = FIREBALL_RADIUS if card == "fireball" else LOG_RADIUS
        minimum = FIREBALL_MIN_ENEMIES if card == "fireball" else LOG_MIN_ENEMIES
        if _near(cells, x, y, radius) >= minimum:
            return slot, x, y, delay, None
        best = best_cluster(cells, radius, minimum)
        if best is None:
            if not pressure and elixir >= CYCLE_SAFE_ELIXIR:
                for chip in ("skeletons", "ice_spirit", "ice_golem"):
                    found = hand_slot(state, chip)
                    if found is not None and elixir >= state.cards[found + 1].cost:
                        cycle_spot = CYCLE_BACK_LEFT if _last_hog_lane == 14 else CYCLE_BACK_RIGHT
                        return found + 1, cycle_spot[0], cycle_spot[1], 0, f"veto_{card}_cycle_{chip}"
            return None
        bx, by = best
        if card == "the_log" and by < BRIDGE_Y:
            return None
        return slot, bx, by, 0, f"retarget_{card}({x},{y})"

    if not (0 <= slot - 1 < 4) or slot - 1 not in state.ready:
        return None

    return slot, x, y, delay, None
