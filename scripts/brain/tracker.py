"""Frame-to-frame enemy tracking so the policy can lead a moving push.

The old policy placed defenders on where a unit *was*.  At roughly 0.5 Hz that
is one to two tiles behind reality, which is why cannons kept being dropped
after the tank had already walked past them.  This module keeps a short-lived
identity for each enemy unit, estimates its velocity, and exposes a predicted
position a configurable number of seconds ahead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from .arena import Cell, distance

MATCH_RADIUS = 4.0      # tiles a unit can plausibly move between two frames
STALE_SECONDS = 2.5     # drop a track that has not been seen this long
MAX_SPEED = 3.0         # tiles/second; clamps velocity from noisy detections
# A damaged unit's bar can drop out for a frame (overlap, a missed detection).
# Hit points almost never go up, so a missing bar keeps the last reading until
# it has been absent this many frames in a row - long enough to ride out a
# flicker, short enough that a healed unit does come back to full.
NO_BAR_FRAMES = 3


@dataclass
class Track:
    name: str
    cell: Cell
    seen_at: float
    first_seen: float
    vx: float = 0.0
    vy: float = 0.0
    hits: int = 1
    hp: float = 1.0          # share of hit points left, from `hp_bars`
    no_bar: int = 0          # consecutive frames seen without a bar

    def predict(self, seconds: float) -> Cell:
        return Cell(self.cell.x + self.vx * seconds, self.cell.y + self.vy * seconds)

    @property
    def confident(self) -> bool:
        return self.hits >= 2


@dataclass
class Tracker:
    tracks: Dict[int, Track] = field(default_factory=dict)
    _next_id: int = 0

    def update(self, detections: Sequence[tuple], now: float | None = None) -> List[Track]:
        """Associate `(name, cell)` or `(name, cell, hp)` detections with tracks.

        `hp` is what `hp_bars.unit_fractions` read: a fraction below 1.0, 1.0
        for no bar, or None for a bar that could not be read.
        """
        now = time.monotonic() if now is None else now
        # Expire BEFORE association: otherwise an old unit can be resurrected
        # by a new copy appearing in the same location after a long frame gap.
        for track_id, track in list(self.tracks.items()):
            if now - track.seen_at > STALE_SECONDS:
                del self.tracks[track_id]
        unmatched = dict(self.tracks)
        result: List[Track] = []

        for detection in detections:
            name, cell = detection[0], detection[1]
            reading = detection[2] if len(detection) > 2 else 1.0
            best_id, best_d = None, MATCH_RADIUS
            for track_id, track in unmatched.items():
                if track.name != name:
                    continue
                gap = distance(cell, track.predict(max(0.0, now - track.seen_at)))
                if gap < best_d:
                    best_id, best_d = track_id, gap
            if best_id is None:
                self._next_id += 1
                track = Track(name=name, cell=cell, seen_at=now, first_seen=now,
                              hp=1.0 if reading is None else float(reading))
                self.tracks[self._next_id] = track
            else:
                track = unmatched.pop(best_id)
                dt = max(1e-3, now - track.seen_at)
                raw_vx = (cell.x - track.cell.x) / dt
                raw_vy = (cell.y - track.cell.y) / dt
                # Exponential smoothing keeps a single bad detection from
                # throwing the predicted intercept across the arena.
                track.vx = _clamp_speed(0.5 * track.vx + 0.5 * raw_vx)
                track.vy = _clamp_speed(0.5 * track.vy + 0.5 * raw_vy)
                track.cell = cell
                track.seen_at = now
                track.hits += 1
                _update_hp(track, reading)
            result.append(track)

        for track_id, track in list(self.tracks.items()):
            if now - track.seen_at > STALE_SECONDS:
                del self.tracks[track_id]
        return result

    def reset(self) -> None:
        self.tracks.clear()


def _update_hp(track: Track, reading) -> None:
    if reading is None:                  # a bar is there, just unreadable
        track.no_bar = 0
    elif reading < 1.0:
        track.hp = float(reading)
        track.no_bar = 0
    else:
        track.no_bar += 1
        if track.no_bar >= NO_BAR_FRAMES:
            track.hp = 1.0


def _clamp_speed(value: float) -> float:
    return max(-MAX_SPEED, min(MAX_SPEED, value))
