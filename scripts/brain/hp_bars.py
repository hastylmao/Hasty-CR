"""Read unit hit points off the bars the game draws above damaged units.

The simulator trained the policy on every unit's *current* hit points
(`sim.env.observe` adds `entity.hitpoints / 1000` to planes 2 and 3). Live
vision used to report full hit points for everything, so a Hog on 10% looked
exactly like a fresh one. This module closes that gap. It only reads pixels and
boxes, so it can be tested without a detector, an emulator or the game data.

What the game draws, checked against a real screenshot and ~840k recorded
`bar` detections in `data/vod/tracks`:

* A unit at full health shows only its level badge. A damaged unit shows the
  badge with a bar to its right. So "no bar" means full health.
* The badge is square: its width is ~0.96 of the bar box's height.
* The empty part of the track is dark (max channel ~60-105, red-brown for the
  enemy, navy for us). The filled part is bright whatever its colour: red,
  light blue, and white or pink for a frame or two after a hit. So the fill is
  measured by brightness, not hue.
* The track length depends on the troop. The client declares a size class per
  character (`health_bar` in `data/royaleapi/cards_stats_characters.json`),
  and the recorded bars fall into matching clusters. Lengths below are in
  badge heights, so they hold at any resolution.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CHARACTERS = ROOT / "data" / "royaleapi" / "cards_stats_characters.json"
BUILDINGS = ROOT / "data" / "royaleapi" / "cards_stats_building.json"

Box = Tuple[float, float, float, float]          # x1, y1, x2, y2 in pixels

BADGE_WIDTH = 0.96          # badge width / bar box height (recorded median 0.962)
DARK = 130                  # max channel below this is empty track or outline
OUTLINE = 0.06              # the bar's right outline, in box heights
MIN_BAR_CONF = 0.5

# Track length (badge to rounded end) in badge heights, per client class.
# From the recorded detector boxes, corrected for box padding with the
# pixel-exact lengths in a real screenshot (Small 35px, Medium 62px, Cannon
# 92px against a ~31px badge).
TRACK_LENGTH = {
    "small": 1.13,
    "medium": 2.0,
    "high": 2.8,
    "building": 3.0,
}

# client `health_bar` value -> our length class
_CLIENT_CLASS = {
    "Small": "small", "Shield_small": "small",
    "Medium": "medium", "Shield": "medium", "MediumShield": "medium",
    "High": "high",
}

# Live unit names (BuildABot's table plus `vision.EXTRA_UNITS`) whose client
# name is different. Everything else matches after dropping `_`.
_CLIENT_NAME = {
    "bandit": "Assassin",
    "cannon_cart": "MovingCannon",
    "dart_goblin": "BlowdartGoblin",
    "elite_barbarian": "AngryBarbarian",
    "elixir_golem": "ElixirGolem1",
    "elixir_golem_large": "ElixirGolem1",
    "elixir_golem_medium": "ElixirGolem2",
    "elixir_golem_small": "ElixirGolem4",
    "executioner": "AxeMan",
    "fire_spirit": "FireSpirits",
    "flying_machine": "DartBarrell",
    "guard": "SkeletonWarrior",
    "hog": "RoyalHog",
    "ice_golem": "IceGolemite",
    "ice_spirit": "IceSpirits",
    "lava_pup": "LavaPups",
    "lumberjack": "RageBarbarian",
    "magic_archer": "EliteArcher",
    "mother_witch": "WitchMother",
    "night_witch": "DarkWitch",
    "phoenix": "Phoenix",
    "phoenix_large": "Phoenix",
    "phoenix_small": "PhoenixNoRespawn",
    "royal_ghost": "Ghost",
    "royal_recruit": "Recruit",
    "skeleton_barrel": "SkeletonBalloon",
    "sparky": "ZapMachine",
    "zappy": "MiniZapMachine",
}
# Buildings the client lists with `health_bar = None` still show a bar in
# play (the Cannon in the screenshot), so they get the building length. A
# building the client does give a class keeps it: Goblin Cage says Medium, and
# its recorded bars measure Medium. The Furnace's card name differs.
_BUILDING_NAME = {"furnace": "FirespiritHut", "x_bow": "Xbow"}
# Decided by recorded bars rather than the table:
#   little_prince - missing from the published snapshot; measures Medium.
#   cannon_cart   - the table says MediumShield, but 72 recorded bars measure
#                   building length with a tight spread (it becomes a building
#                   when its shield breaks).
_MEASURED = {"little_prince": "medium", "cannon_cart": "building"}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


_CLASS_CACHE: Optional[Dict[str, str]] = None


def _client_tables() -> Tuple[Dict[str, str], Dict[str, str]]:
    characters, buildings = {}, {}
    try:
        for row in json.loads(CHARACTERS.read_text(encoding="utf-8")):
            if isinstance(row, dict) and row.get("name"):
                characters[_norm(row["name"])] = str(row.get("health_bar"))
        for row in json.loads(BUILDINGS.read_text(encoding="utf-8")):
            if isinstance(row, dict) and row.get("name"):
                buildings[_norm(row["name"])] = str(row.get("health_bar"))
    except (OSError, ValueError):
        pass
    return characters, buildings


def bar_class(unit: str) -> Optional[str]:
    """`small`, `medium`, `high`, `building`, or None if unknown."""
    global _CLASS_CACHE
    if _CLASS_CACHE is None:
        _CLASS_CACHE = {}
    if unit in _CLASS_CACHE:
        return _CLASS_CACHE[unit]
    characters, buildings = _client_tables()
    found: Optional[str] = None
    building = _norm(_BUILDING_NAME.get(unit, unit))
    if unit in _MEASURED:
        found = _MEASURED[unit]
    elif building in buildings:
        found = _CLIENT_CLASS.get(buildings[building], "building")
    else:
        client = characters.get(_norm(_CLIENT_NAME.get(unit, unit)))
        found = _CLIENT_CLASS.get(client) if client else None
    _CLASS_CACHE[unit] = found
    return found


def expected_track_px(unit: Optional[str], box_height: float) -> Optional[float]:
    cls = bar_class(unit) if unit else None
    return TRACK_LENGTH[cls] * box_height if cls else None


# ------------------------------------------------------------------ reading


def read_fraction(pixels: np.ndarray, box: Box,
                  expected_px: Optional[float] = None) -> Optional[float]:
    """Fraction of the bar that is filled, or None if it cannot be read.

    `pixels` is the whole frame as HxWx3 (RGB or BGR, brightness is the same).
    The track starts one badge-width right of the box's left edge. The fill is
    the bright run from there; the track ends where the dark empty run after
    it ends. If that end is hidden or merged into a neighbour, so the measured
    track disagrees with the troop's known length, the known length is used.
    """
    x1, y1, x2, y2 = (float(v) for v in box)
    h = y2 - y1
    if h < 4 or x2 - x1 < 1.5 * h:
        return None
    height, width = pixels.shape[:2]
    cy = (y1 + y2) / 2.0
    # The track is a thin strip near the box's middle, but detector boxes sit a
    # few pixels off, so every row of the middle 60% is tried and only rows
    # with the bar's signature - fill, then a dark run, then background - count.
    r0 = int(max(0, round(cy - 0.3 * h)))
    r1 = int(min(height, round(cy + 0.3 * h) + 1))
    left = int(max(0, round(x1 + 0.7 * h)))         # inside the badge
    stop = int(min(width, round(x2 + 0.6 * h)))     # boxes are sometimes short
    if r1 <= r0 or stop - left < 3:
        return None
    rows = pixels[r0:r1, left:stop, :3].astype(np.int32).max(axis=2) >= DARK
    seam_window = int(round(0.5 * h))               # badge edge is in here
    geometric = int(round(x1 + BADGE_WIDTH * h)) - left

    fills, ends = [], []
    for bright in rows:
        start = _track_start(bright, seam_window, geometric)
        if start is None:
            continue
        fill_end = start
        while fill_end < len(bright) and bright[fill_end]:
            fill_end += 1
        track_end = fill_end
        while track_end < len(bright) and not bright[track_end]:
            track_end += 1
        if track_end - fill_end < 2 or track_end >= len(bright):
            continue            # no dark run, or no background after it
        fills.append(fill_end - start)
        ends.append(track_end - start)
    if not ends:
        return None
    track = float(np.median(ends)) - OUTLINE * h
    # Rows through the track's outline read as empty; the interior rows carry
    # the fill, so the upper end of the fill readings is the honest one.
    fill = float(np.percentile(fills, 75))

    if expected_px:
        if track < 0.8 * expected_px or track > 1.25 * expected_px:
            track = expected_px
    if track <= 1:
        return None
    return float(min(1.0, max(0.0, fill / track)))


def _track_start(bright: np.ndarray, window: int, geometric: int) -> Optional[int]:
    """Column where the track begins, in one row.

    The badge's right outline is a dark seam between the badge and the fill.
    When there is fill, the track starts right after the last dark column that
    is followed by a bright one inside the window. With no fill the row is
    dark from the seam on, and the track starts at the first dark column.
    Without a seam in the window, fall back to where the badge should end.
    """
    window = min(window + 1, len(bright) - 1)
    last_seam = None
    first_dark = None
    for i in range(window):
        if not bright[i]:
            if first_dark is None:
                first_dark = i
            if bright[i + 1]:
                last_seam = i
    if last_seam is not None:
        return last_seam + 1
    if not 0 <= geometric < len(bright):
        geometric = None
    if first_dark is not None:
        # No seam: either no fill at all, or a sliver of fill running straight
        # out of an unoutlined badge. Where the badge should end decides.
        return first_dark if geometric is None else min(first_dark, geometric)
    return geometric


# -------------------------------------------------------------- association


def match_bars(units: Sequence[Box], bars: Sequence[Box]) -> Dict[int, int]:
    """Map unit index -> bar index, one bar per unit at most.

    A bar floats just above its unit's head: the unit's box top sits within
    1.5 bar-heights of the bar's bottom, and the two are horizontally aligned
    to within 0.6 of the bar's width. Pairs are taken best-first, so in a
    clump each bar goes to the unit it fits best. The same rule, run over the
    recorded detections, sorts troops into the client's bar classes cleanly.
    """
    pairs = []
    for ui, (ux1, uy1, ux2, uy2) in enumerate(units):
        ucx = (ux1 + ux2) / 2.0
        for bi, (bx1, by1, bx2, by2) in enumerate(bars):
            bh, bw = by2 - by1, bx2 - bx1
            dy = uy1 - by2
            dx = abs(ucx - (bx1 + bx2) / 2.0)
            if -1.5 * bh <= dy <= 1.5 * bh and dx <= 0.6 * bw:
                pairs.append((abs(dy) + dx, ui, bi))
    pairs.sort()
    taken_u, taken_b, out = set(), set(), {}
    for _score, ui, bi in pairs:
        if ui in taken_u or bi in taken_b:
            continue
        taken_u.add(ui)
        taken_b.add(bi)
        out[ui] = bi
    return out


@dataclass(frozen=True)
class UnitBox:
    name: str
    box: Box


# A visible bar means the unit is hurt, so readings are capped just below 1.0
# and exactly 1.0 always means "no bar this frame". The tracker relies on that
# to tell a full-health unit from a bar the detector missed for a frame.
FULL = 1.0
MAX_READING = 0.99


def unit_fractions(pixels: np.ndarray, units: Sequence[UnitBox],
                   bars: Sequence[Box]) -> List[Optional[float]]:
    """Health fraction per unit: a reading, FULL for no bar, None if unreadable.

    None is distinct from FULL on purpose: a bar that is there but cannot be
    read says the unit is hurt, and the tracker keeps its last good reading
    rather than snapping it back to full.
    """
    matched = match_bars([u.box for u in units], bars)
    out: List[Optional[float]] = []
    for index, unit in enumerate(units):
        bar = matched.get(index)
        if bar is None:
            out.append(FULL)
            continue
        box = bars[bar]
        value = read_fraction(pixels, box,
                              expected_track_px(unit.name, box[3] - box[1]))
        out.append(None if value is None else min(MAX_READING, value))
    return out
