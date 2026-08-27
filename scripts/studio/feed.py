"""Tail the bot's log and turn it into something worth putting on camera.

The studio deliberately reads the same `tmp/live/cr_bot.log` a human would,
rather than hooking into the bot process.  That keeps recording completely
read-only: starting, stopping, or crashing the studio cannot affect a run that
is mid-match, which matters when the supervisor is meant to survive unattended.

Raw log lines are too wide to read on a phone screen:

    2026-08-17 06:02:06 PLAY #26 hog_rider slot=0 grid=(14,17)
    tag=push_counterpush_win_condition_right score=55.6 elixir=4
    enemy_elixir=2.7 threat=1/1 spent=4 t=124

so each line is re-laid out into fixed columns and given a family
(defend/push/cycle/value) that the renderer colours.  Nothing is invented: every
column is a field the bot actually logged.

One thing is deliberately *not* surfaced.  Tower HP is read off the screen by a
detector that `scripts/results.py` documents as unreliable ("reports our right
tower at 0.00 while it is at full health"), and it is only logged at MATCH_END
anyway.  Putting a wrong crown count on a video is worse than omitting it, so
the rail shows only quantities parsed straight out of the log.
"""

from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, List, Optional

# How much of the existing log to load on startup, so the feed is already
# populated on the first frame instead of empty until the next decision.
PRIME_BYTES = 96_000

HEAD = re.compile(r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d) (\w+)\s*(.*)$")

FAMILIES = ("defend", "push", "cycle", "value", "chip")


def _family(tag: str) -> str:
    for name in FAMILIES:
        if tag.startswith(name):
            return name
    return "other"


def _fields(tail: str) -> Dict[str, str]:
    """Pull `key=value` tokens out of a line tail.

    Parsed generically rather than with one big regex per line type: the log
    format has gained columns twice already, and a generic parse degrades to
    "missing key" instead of "line silently ignored".
    """
    out: Dict[str, str] = {}
    for token in tail.split():
        if "=" in token:
            key, _, value = token.partition("=")
            out[key] = value
    return out


def _number(value: Optional[str], default: float = 0.0) -> float:
    try:
        return float(str(value).rstrip("s%"))
    except (TypeError, ValueError):
        return default


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "\u2026"


@dataclass
class Event:
    at: str
    kind: str
    family: str
    text: str


@dataclass
class LiveState:
    """Everything the rail draws, all of it parsed from the log."""

    screen: str = "?"
    elixir: float = 0.0
    enemy_elixir: float = 0.0
    hand: List[str] = field(default_factory=list)
    threat: str = "0/0"
    threat_value: float = 0.0
    clock: int = 0
    match_index: int = 0
    plays: int = 0
    play_counts: Counter = field(default_factory=Counter)
    last_card: str = "-"
    last_tag: str = "-"
    last_score: float = 0.0
    last_grid: str = "-"
    last_family: str = "other"
    matches_done: int = 0
    session_hog_share: List[float] = field(default_factory=list)
    session_plays: List[float] = field(default_factory=list)
    stale_seconds: float = 0.0

    @property
    def hog_share(self) -> float:
        if not self.plays:
            return 0.0
        return 100.0 * self.play_counts.get("hog_rider", 0) / self.plays

    @property
    def mean_hog_share(self) -> float:
        if not self.session_hog_share:
            return 0.0
        return sum(self.session_hog_share) / len(self.session_hog_share)

    @property
    def mean_plays(self) -> float:
        if not self.session_plays:
            return 0.0
        return sum(self.session_plays) / len(self.session_plays)


class LogFeed:
    """Incremental tail of the bot log, plus the state it implies."""

    def __init__(self, path: Path, history: int = 200):
        self.path = Path(path)
        self.events: Deque[Event] = deque(maxlen=history)
        self.state = LiveState()
        self._offset = 0
        self._partial = ""
        self._prime()

    # ---------------------------------------------------------------- tailing

    def _prime(self) -> None:
        if not self.path.exists():
            return
        size = self.path.stat().st_size
        start = max(0, size - PRIME_BYTES)
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(start)
            if start:
                stream.readline()          # discard a half line
            for line in stream:
                self._consume(line.rstrip("\n"))
        self._offset = size

    def poll(self) -> None:
        """Read whatever has been appended since the last call."""
        if not self.path.exists():
            return
        size = self.path.stat().st_size
        if size < self._offset:
            # The supervisor truncates this log once it passes 25MB.
            self._offset = 0
            self._partial = ""
        if size == self._offset:
            return
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            stream.seek(self._offset)
            chunk = stream.read()
            self._offset = size
        chunk = self._partial + chunk
        # A line may be half-written when we read it; keep the remainder for the
        # next poll rather than parsing a truncated decision.
        if not chunk.endswith("\n"):
            chunk, _, self._partial = chunk.rpartition("\n")
        else:
            self._partial = ""
        for line in chunk.splitlines():
            self._consume(line)

    # --------------------------------------------------------------- parsing

    def _consume(self, line: str) -> None:
        match = HEAD.match(line.strip())
        if not match:
            return
        _, at, kind, tail = match.groups()
        handler = getattr(self, f"_on_{kind.lower()}", None)
        if handler is None:
            self._push(at, kind, "other", _short(tail, 78))
            return
        handler(at, kind, tail)

    def _push(self, at: str, kind: str, family: str, text: str) -> None:
        self.events.append(Event(at, kind, family, text))

    def _on_play(self, at: str, kind: str, tail: str) -> None:
        parts = tail.split()
        card = parts[1] if len(parts) > 1 else "?"
        values = _fields(tail)
        tag = values.get("tag", "-")
        state = self.state
        state.elixir = _number(values.get("elixir"))
        state.enemy_elixir = _number(values.get("enemy_elixir"))
        state.threat = values.get("threat", "0/0")
        state.threat_value = _number(state.threat.split("/")[0])
        state.clock = int(_number(values.get("t")))
        state.last_card = card
        state.last_tag = tag
        state.last_score = _number(values.get("score"))
        state.last_grid = values.get("grid", "-")
        state.last_family = _family(tag)
        state.plays += 1
        state.play_counts[card] += 1
        self._push(at, "PLAY", state.last_family,
                   f"{card:<13} {values.get('grid', ''):<9} "
                   f"{_short(tag, 33):<33} {state.last_score:>6.1f}")

    def _on_idle(self, at: str, kind: str, tail: str) -> None:
        values = _fields(tail)
        hand = re.findall(r"'([^']+)'", tail)
        state = self.state
        state.hand = hand
        state.elixir = _number(values.get("elixir"))
        state.threat = values.get("threat", state.threat)
        state.threat_value = _number(state.threat.split("/")[0])
        state.clock = int(_number(values.get("t"), state.clock))
        waited = tail.split()[0] if tail.split() else "?"
        self._push(at, "IDLE", "idle",
                   f"held {waited:<6} elixir {state.elixir:.0f}  "
                   f"threat {state.threat:<6} hand {_short(','.join(hand) or '-', 34)}")

    def _on_screen(self, at: str, kind: str, tail: str) -> None:
        self.state.screen = tail.split("->")[-1].strip() or "?"
        self._push(at, "SCREEN", "system", f"screen {tail}")

    def _on_match_start(self, at: str, kind: str, tail: str) -> None:
        state = self.state
        state.match_index = state.matches_done + 1
        state.plays = 0
        state.play_counts = Counter()
        state.clock = 0
        self._push(at, "START", "system", f"match {state.match_index} begins")

    def _on_match_end(self, at: str, kind: str, tail: str) -> None:
        values = _fields(tail)
        state = self.state
        # The bot numbers its own matches, so take its count rather than
        # counting MATCH_START lines - the feed is primed from the tail of an
        # existing log, and counting would report the size of that window.
        parts = tail.split()
        if parts and parts[0].startswith("#") and parts[0][1:].isdigit():
            state.matches_done = int(parts[0][1:])
            state.match_index = state.matches_done
        else:
            state.matches_done += 1
        state.session_hog_share.append(_number(values.get("hog_share")))
        state.session_plays.append(_number(values.get("plays"), state.plays))
        # Averages over the last 20 matches, not all history: a mean that
        # includes matches played under an older policy hides current form.
        del state.session_hog_share[:-20]
        del state.session_plays[:-20]
        self._push(at, "END", "system",
                   f"match over  {values.get('dur', '?')}  "
                   f"{state.plays} plays  hog {values.get('hog_share', '?')}")

    def _on_learn(self, at: str, kind: str, tail: str) -> None:
        values = _fields(tail)
        self._push(at, "LEARN", "system",
                   f"episodes {values.get('episodes', '?')}  "
                   f"situations {values.get('situations', '?')}  "
                   f"matchups {values.get('matchups', '?')}")

    def _on_ready(self, at: str, kind: str, tail: str) -> None:
        self._push(at, "READY", "system", _short(tail, 74))

    def _on_queue(self, at: str, kind: str, tail: str) -> None:
        self._push(at, "QUEUE", "system", f"searching for a match {tail}")

    def _on_error(self, at: str, kind: str, tail: str) -> None:
        self._push(at, "ERROR", "error", _short(tail, 74))

    def _on_sprites(self, at: str, kind: str, tail: str) -> None:
        return   # disk bookkeeping, not gameplay
