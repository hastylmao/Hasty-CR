"""Read princess-tower HP directly and robustly from 1080x1920 frames.

Fixes the shifting tower HP bar bug and phantom zero readings.
- Dynamic vertical band scanning to handle inter-match shifts (y 1155-1205).
- Contiguous run-length detection from the bar anchor (left edge) to prevent
  false positives from stray blue/red arena UI.
- Height-consistency filtering (validates 4-12px vertical bar thickness).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
from PIL import Image

# Geometry specifications for 1080x1920 captures
ENEMY_SEARCH_Y = (275, 325)
# The fill track, not the frame around it. 133 was measured off the bar's outer
# gold trim; this function scans from x=216, where the pink fill actually starts,
# so it needs the width of that fill track alone.
#
# Segmenting a live frame across x: 206-215 is the tower's gold frame, the fill
# runs 216-333, a two-pixel dark border closes it at 334-335, and 336 onward is
# flat arena background for fifty pixels with no further structure. The bar
# element is 216-335, so 119 - the same as the ally bar after all.
#
# The check that settles it needs no frame at all. Both towers are full at the
# start of every match, and the ally reader reports exactly 1.000 in 3986 of
# 13384 logged readings. The enemy reader managed 7. Instead it piles up at 0.91,
# 0.89 and 0.87 - because a full 118px fill divided by 133 is 0.887, which falls
# under the >= 0.95 snap below and so never rounds up to a full tower.
#
# Direction matters downstream: every enemy reading was ~12% low, so the tower
# damage the bot dealt was under-credited against ally damage taken, which the
# ally reader had right. experience.py builds its reward from that difference,
# so the learning loop has been quietly paying the bot less for attacking than
# for defending. Crown counts are unaffected - a destroyed tower measures a zero
# run, and zero divided by either width is still zero.
ENEMY_BAR_FULL_WIDTH = 119
ENEMY_BARS = {"left": 216, "right": 782}

ALLY_SEARCH_Y = (1145, 1215)
ALLY_BAR_FULL_WIDTH = 119
ALLY_BARS = {"left": 216, "right": 782}

BAR_X_TOLERANCE = 8
MIN_BAR_THICKNESS = 4


def _measure_side_hp(
    mask: np.ndarray,
    x_anchor: int,
    full_width: int,
    y_offset: int = 0,
) -> float:
    """Measure the HP fraction for a specific tower side from a binary color mask.
    
    A valid Clash Royale HP bar is a horizontal rectangle of height 4-12px.
    It drains from right to left, so the left edge remains fixed near x_anchor.
    """
    h, w = mask.shape
    x_min = max(0, x_anchor - BAR_X_TOLERANCE)
    x_max = min(w, x_anchor + full_width + BAR_X_TOLERANCE)
    
    # Check each row for a contiguous run of filled pixels starting near x_anchor
    row_runs = []
    for r in range(h):
        row_pixels = mask[r, x_min:x_max]
        if not np.any(row_pixels):
            row_runs.append(0)
            continue
        
        # Find active pixel indices relative to x_min
        indices = np.nonzero(row_pixels)[0]
        # The bar must start near the left anchor
        valid_start = False
        run_length = 0
        for idx in indices:
            # Check if this index is within tolerance of the left edge
            abs_x = x_min + idx
            if abs(abs_x - x_anchor) <= BAR_X_TOLERANCE:
                valid_start = True
            if valid_start:
                run_length += 1
                
        # Count contiguous run from first positive near anchor
        if valid_start:
            # Find the longest continuous run starting near x_anchor
            # Look at contiguous segment from the anchor
            sub = row_pixels
            # Find index closest to x_anchor
            anchor_rel = x_anchor - x_min
            start_search = max(0, anchor_rel - BAR_X_TOLERANCE)
            end_search = min(len(sub), anchor_rel + BAR_X_TOLERANCE + 1)
            
            first_hit = None
            for idx in range(start_search, end_search):
                if sub[idx]:
                    first_hit = idx
                    break
            
            if first_hit is not None:
                # Count contiguous ones with up to 1px gap tolerance
                length = 0
                gaps = 0
                for idx in range(first_hit, len(sub)):
                    if sub[idx]:
                        length += 1 + gaps
                        gaps = 0
                    else:
                        gaps += 1
                        if gaps > 2:  # allow 2px border or number notch
                            break
                row_runs.append(min(full_width, length))
            else:
                row_runs.append(0)
        else:
            row_runs.append(0)
            
    # Find the thickest contiguous cluster of rows that have a consistent length
    best_len = 0
    curr_len = 0
    cluster_runs = []
    
    for length in row_runs:
        if length >= 10:  # Minimum 10px to avoid speckle noise
            curr_len += 1
            cluster_runs.append(length)
        else:
            if curr_len >= MIN_BAR_THICKNESS:
                # Median run length across the vertical thickness of the bar
                med = float(np.median(cluster_runs))
                best_len = max(best_len, med)
            curr_len = 0
            cluster_runs = []
            
    if curr_len >= MIN_BAR_THICKNESS:
        med = float(np.median(cluster_runs))
        best_len = max(best_len, med)
        
    if best_len == 0:
        return 0.0
        
    fraction = best_len / float(full_width)
    if fraction >= 0.95:
        return 1.000
    return round(float(np.clip(fraction, 0.0, 1.0)), 3)


def enemy_tower_fractions(image: Image.Image) -> Dict[str, float]:
    """Calculate enemy princess tower HP fractions (0.0 - 1.0)."""
    pixels = np.asarray(image.convert("RGB"))
    if pixels.shape[0] < 1900 or pixels.shape[1] < 1000:
        return {"left": 0.0, "right": 0.0}
        
    y0, y1 = ENEMY_SEARCH_Y
    band = pixels[y0:y1, :, :]
    r = band[:, :, 0].astype(int)
    g = band[:, :, 1].astype(int)
    b = band[:, :, 2].astype(int)
    
    # The enemy bar renders in two different colours depending on the arena and
    # tower skin, and the original test only knew about one of them. In most
    # arenas the fill is a deep red that satisfies g < 130. In others it is a
    # bright pink measured off a live frame at a flat (255, 156, 212), which
    # fails both g < 130 and b < 210 - so this function returned 0.0 for a tower
    # sitting on 1980 hitpoints. Accepting either keeps the arenas that already
    # worked and fixes the ones that did not. Some skins are light pink.
    deep_red = (r > 165) & (g < 130) & (b < 210) & (r - g > 35)
    bright_pink = (r > 200) & (g > 100) & (r - g > 70)
    light_pink = (r > 240) & (g > 180) & (b > 180) & (r - g > 15)
    # There used to be a fourth term here, `dark_red`, admitting
    # (r > 85) & (g < 60) & (b < 90) & (r - g > 25). It matched the *drained*
    # part of the bar, not the fill. Sampled off tmp/live/matches at y=293 in
    # bars_degraded_042718.png: the fill is a flat (255, 205, 255) and the empty
    # track behind it is a flat (93, 50, 73) - which passes dark_red exactly.
    # The run-length walk therefore started at the anchor, crossed the fill,
    # bridged the 2px divider on the gap tolerance, and ran on through the empty
    # track to the end, so every living enemy tower measured the full 119px.
    #
    # The reader was consequently a two-state device: over the 31 in-battle
    # frames on disk it returned exactly 1.0 thirty times and exactly 0.0 thirty
    # times, with two intermediate values in 62 readings. Enemy HP only ever
    # moved when a tower was destroyed and its bar vanished. Dropping the term
    # yields a spread across all ten deciles on the same frames.
    #
    # Ground truth on that frame: the tower prints 1331 hitpoints and the mask
    # below measures 0.370, implying a full bar of 3597 - a level-12 princess
    # tower is 3600. The ally reader has no equivalent problem; its empty track
    # is the same maroon, which fails the blue test by a wide margin.
    #
    # This is not cosmetic. experience.py's reward is
    # `enemy elixir killed + tower damage dealt - elixir spent - tower damage
    # taken`, and with the third term pinned at zero while the fourth was read
    # correctly, every attacking play scored as pure cost. That is visible in
    # learned.json: hog_rider is -0.90 over 3372 samples in hog|none|contained
    # and fireball is -6.69 in finish|none|contained, while every high-volume
    # positive entry is defensive. The learner was told the deck's only win
    # condition does not work.
    mask = deep_red | bright_pink | light_pink

    return {
        side: _measure_side_hp(mask, x_anchor, ENEMY_BAR_FULL_WIDTH, y0)
        for side, x_anchor in ENEMY_BARS.items()
    }


def ally_tower_fractions(image: Image.Image) -> Dict[str, float]:
    """Calculate ally princess tower HP fractions (0.0 - 1.0)."""
    pixels = np.asarray(image.convert("RGB"))
    if pixels.shape[0] < 1900 or pixels.shape[1] < 1000:
        return {"left": 0.0, "right": 0.0}
        
    y0, y1 = ALLY_SEARCH_Y
    band = pixels[y0:y1, :, :]
    r = band[:, :, 0].astype(int)
    g = band[:, :, 1].astype(int)
    b = band[:, :, 2].astype(int)
    
    # Ally HP bar: Distinct blue/cyan fill with high blue dominance
    mask = (b > 145) & (b - r > 45) & (b - g > 20)
    
    return {
        side: _measure_side_hp(mask, x_anchor, ALLY_BAR_FULL_WIDTH, y0)
        for side, x_anchor in ALLY_BARS.items()
    }


class TowerHpFilter:
    """Temporal filter over the per-frame bar readings.

    Two facts about the source, both measured off `tmp/live/matches/*.json`:

    * A princess tower's HP never rises.  Across forty logged matches the raw
      reader produced 107 rises on a five-second sample - one every other
      sample pair - so any rise is definitionally a misread.
    * A bar hidden behind a troop, a spell or the King-activation overlay
      measures as a zero-length run, which is the same measurement a destroyed
      tower gives.  Fifty-two readings of "tower destroyed" were followed by
      the same tower reporting health again.

    So: never let a reading rise, and make a fall prove itself over consecutive
    frames before accepting it.  A fall to zero has to hold for longer, because
    that is the one the occlusion case imitates and the one that cannot be
    walked back - it ends the match in the record and removes the tower from
    the policy's target list.

    Taking the median of the confirming run rather than its last value keeps a
    single bad frame inside an otherwise real drop from setting the new floor.

    `zero_max_accepted` adds the third rule: a tower is only allowed to die from
    a reading that already knows it was hurt.  See the comment in `update`.
    """

    ZERO = 0.01

    def __init__(self, confirm_seconds: float = 0.6,
                 zero_confirm_seconds: float = 2.5,
                 tolerance: float = 0.02,
                 zero_max_accepted: float = 0.75) -> None:
        self.confirm_seconds = confirm_seconds
        self.zero_confirm_seconds = zero_confirm_seconds
        self.tolerance = tolerance
        self.zero_max_accepted = zero_max_accepted
        self.reset()

    def reset(self) -> None:
        """Both towers are full at the start of every match."""
        self._accepted: Dict[str, float] = {
            "ally_left": 1.0, "ally_right": 1.0,
            "enemy_left": 1.0, "enemy_right": 1.0,
        }
        self._pending: Dict[str, list] = {}
        self._zero_run: Dict[str, float] = {}

    def update(self, key: str, raw: float, now: float) -> float:
        """Feed one raw reading for `key`; get back the accepted one.

        The two failure modes need separate windows.  A reading of zero is the
        occlusion case - it carries no information about *how much* health is
        left, only a claim that the bar is gone - so it is confirmed on its own
        run and never mixed into the estimate of a partial drop.  Mixing them
        let three occluded frames plus one honest 0.94 reading confirm as a
        median of 0.0 and kill a tower at 94% health.
        """
        accepted = self._accepted.get(key)
        if accepted is None:
            self._accepted[key] = raw
            return raw
        if accepted <= self.ZERO:
            return 0.0  # a destroyed tower stays destroyed

        if raw <= self.ZERO:
            # A tower cannot go from healthy to destroyed without being read on
            # the way down.  Nothing in the game deals a princess tower's full
            # health in one blow - the Rocket is the hardest-hitting spell there
            # is and tops out around 2.2k against a tower on ~2.5-3.6k - and the
            # bars are sampled several times a second, so a real death always
            # walks `accepted` down through the partial-drop path below first.
            #
            # A jump straight from healthy to zero is therefore the reader
            # failing, not a tower dying, and it is not a rare failure: in three
            # of sixty logged matches *both* enemy princess bars read zero
            # within five seconds of the start and stayed there for the whole
            # match, because the enemy colour mask misses some arena skins
            # outright.  "A destroyed tower stays destroyed" then made that
            # permanent, and the damage is not cosmetic - it fabricates two
            # crowns in the block report (the run's headline metric), feeds
            # experience.py a huge phantom reward for whatever was played at the
            # time, and removes the tower from the policy's target list so the
            # finisher and lane choice aim at a tower that is really at full.
            #
            # Holding the last healthy reading instead only ever under-credits,
            # which is the safe direction for both the score and the learner.
            if self._accepted[key] > self.zero_max_accepted:
                self._zero_run.pop(key, None)
                return self._accepted[key]
            run = self._zero_run.setdefault(key, now)
            if now - run >= self.zero_confirm_seconds:
                self._accepted[key] = 0.0
            return self._accepted[key]
        self._zero_run.pop(key, None)

        if raw >= accepted - self.tolerance:
            self._pending.pop(key, None)  # equal, noise, or an impossible rise
            return accepted

        run = self._pending.setdefault(key, [])
        run.append((now, raw))
        if now - run[0][0] >= self.confirm_seconds and len(run) >= 2:
            values = sorted(v for _, v in run)
            settled = values[len(values) // 2]
            self._accepted[key] = min(accepted, settled)
            self._pending.pop(key, None)
        return self._accepted[key]

    def fractions(self, image: Image.Image, now: float) -> Dict[str, float]:
        """Filtered ally and enemy readings for one frame, as `ally, enemy`."""
        ally = ally_tower_fractions(image)
        enemy = enemy_tower_fractions(image)
        ally = {s: self.update(f"ally_{s}", v, now) for s, v in ally.items()}
        enemy = {s: self.update(f"enemy_{s}", v, now) for s, v in enemy.items()}
        return ally, enemy


def format_summary(ally: Dict[str, float], enemy: Dict[str, float]) -> str:
    """Format string: 'left_ally/right_ally-left_enemy/right_enemy'."""
    return (f"{ally.get('left', 0.0):.2f}/{ally.get('right', 0.0):.2f}"
            f"-{enemy.get('left', 0.0):.2f}/{enemy.get('right', 0.0):.2f}")


def tower_summary(image: Image.Image) -> str:
    """Format string: 'left_ally/right_ally-left_enemy/right_enemy'."""
    return format_summary(ally_tower_fractions(image), enemy_tower_fractions(image))


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python scripts/tower_hp.py <image1.png> [image2.png ...]")
        return 2
        
    for path_str in sys.argv[1:]:
        p = Path(path_str)
        if not p.exists():
            print(f"File not found: {p}")
            continue
        try:
            img = Image.open(p)
            ally = ally_tower_fractions(img)
            enemy = enemy_tower_fractions(img)
            print(f"[{p.name}] Ally: {ally} | Enemy: {enemy} | Formatted: {tower_summary(img)}")
        except Exception as e:
            print(f"[{p.name}] Error reading image: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
