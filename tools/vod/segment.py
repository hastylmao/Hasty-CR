"""Find the parts of a recording that are actually a match.

A ten-hour stream contains maybe three hours of Clash Royale and seven of deck
edits, shop screens, chat and talking. Tracking all of it would cost eight
times the detector time for the same measurements, and every menu frame that
leaks into a track is noise a calibration step has to survive.

The signal is the arena itself. In a match the detector sees a king tower and
princess towers and the match clock, at 0.9 confidence on real footage; on a
menu it sees none of them. That is a far steadier cue than the "FIGHT!" banner,
which is two seconds long, easily missed at a one-frame-per-second sweep, and
absent entirely from a rejoin.

The banner still matters for a different job. Tower presence gives a span; it
does not give a t=0 precise enough to reason about elixir, because elixir is
counted from the start of the match and a second of error is most of a card.
So `find_start` refines the leading edge afterwards, over a handful of seconds,
rather than scanning a whole video for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# Detector classes that only exist inside a match. `clock` is the match timer;
# `tower-bar` is the hit-point bar above a crown tower.
ARENA_CLASSES = frozenset({"king-tower", "queen-tower", "tower-bar",
                           "dagger-duchess-tower", "cannoneer-tower",
                           "king-tower-bar"})

# Confidence a class needs before it counts as seen. Deliberately not high: a
# false positive on one sampled second is smoothed away by the run-length rule
# below, and a false negative costs a real match.
MIN_CONF = 0.45

# How many of ARENA_CLASSES must appear for a frame to be in a match. Two
# stops a lone misfire opening a span; requiring three lost matches where the
# camera sat on a corner of the arena.
MIN_CLASSES = 2

# Spans shorter than this are not matches. The shortest possible Clash Royale
# game is a three-minute regulation plus overtime, but a rejoin or a heavily
# cut highlight can be far less, so this only excludes obvious noise.
MIN_SPAN_S = 45.0

# A gap this long inside a span ends it. Sampling at 1fps, a couple of missed
# seconds is a detector blink; ten seconds is a menu.
MAX_GAP_S = 8.0


@dataclass(frozen=True)
class Span:
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _arena_hits(result) -> int:
    names = result.names
    seen = set()
    for box in result.boxes:
        if float(box.conf) < MIN_CONF:
            continue
        name = names[int(box.cls)]
        if name in ARENA_CLASSES:
            seen.add(name)
    return len(seen)


def in_match_seconds(model, video: Path, stride_s: float = 1.0,
                     fps: Optional[float] = None) -> list[float]:
    """Timestamps, one per sampled frame, where the frame looks like a match."""
    import cv2

    capture = cv2.VideoCapture(str(video))
    source_fps = fps or capture.get(cv2.CAP_PROP_FPS) or 30.0
    capture.release()

    stride = max(1, int(round(source_fps * stride_s)))
    hits: list[float] = []
    index = 0
    for result in model.predict(str(video), stream=True, vid_stride=stride,
                                conf=MIN_CONF, verbose=False):
        if _arena_hits(result) >= MIN_CLASSES:
            hits.append(index * stride / source_fps)
        index += 1
    return hits


def to_spans(seconds: list[float], stride_s: float = 1.0) -> list[Span]:
    """Group sampled in-match timestamps into contiguous spans."""
    if not seconds:
        return []
    spans: list[Span] = []
    start = previous = seconds[0]
    for value in seconds[1:]:
        if value - previous > MAX_GAP_S:
            spans.append(Span(start, previous + stride_s))
            start = value
        previous = value
    spans.append(Span(start, previous + stride_s))
    return [s for s in spans if s.duration_s >= MIN_SPAN_S]


def find_spans(model, video: Path, stride_s: float = 1.0) -> list[Span]:
    return to_spans(in_match_seconds(model, video, stride_s), stride_s)


def refine_start(model, video: Path, span: Span, window_s: float = 12.0,
                 step_s: float = 0.2) -> float:
    """Walk backwards from a span's leading edge to the first in-match frame.

    The 1fps sweep can only place a match start within a second, and a second
    is 0.36 elixir at the opening rate - enough to make a two-card opening look
    like a three-card one. This re-samples the edge finely.

    It answers "when did the arena appear", not "when did FIGHT! flash". Those
    differ by the banner's own duration, which is why anything reasoning about
    elixir should treat this as a lower bound and say so.
    """
    import cv2

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        return span.start_s
    earliest = span.start_s
    probe = span.start_s
    limit = max(0.0, span.start_s - window_s)
    while probe > limit:
        probe -= step_s
        capture.set(cv2.CAP_PROP_POS_MSEC, probe * 1000.0)
        ok, frame = capture.read()
        if not ok:
            break
        result = model.predict(frame, conf=MIN_CONF, verbose=False)[0]
        if _arena_hits(result) >= MIN_CLASSES:
            earliest = probe
        else:
            break          # the first miss walking back is the edge
    capture.release()
    return earliest


def describe(spans: list[Span]) -> str:
    if not spans:
        return "no matches found"
    total = sum(s.duration_s for s in spans)
    return (f"{len(spans)} matches, {total / 60:.1f} min of play "
            f"(longest {max(s.duration_s for s in spans) / 60:.1f} min)")
