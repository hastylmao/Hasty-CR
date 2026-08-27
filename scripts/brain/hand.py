"""Temporal smoothing for the card hand.

The card classifier is not stable frame to frame. Captured live, with no card
played and elixir unchanged between frames, slot 3 read:

    frame 0   ice_spirit      (correct - verified against the pixels)
    frame 1   hog_rider
    frame 2   blank

Animated card art appears to be the cause: the classifier sees a different
picture on each frame of the Ice Spirit's idle animation.

This matters more than any strategy setting. The runner taps a *slot*, chosen
because the policy believed a particular card was in it, so a misread slot means
playing the wrong card in a position chosen for a different one. It also
corrupts the only feedback the review loop has: block reports were showing Ice
Spirit at 26.5% of plays, which is arithmetically impossible in an eight-card
deck where four other cards must be played before any card returns.

The fix is the same idea the unit tracker already uses: believe a slot only once
it has agreed with itself across several frames.
"""

from __future__ import annotations

from collections import Counter, deque
from typing import Deque, Dict, List, Optional

WINDOW = 4
MIN_VOTES = 2


class HandTracker:
    def __init__(self, window: int = WINDOW, min_votes: int = MIN_VOTES):
        self.window = window
        self.min_votes = min_votes
        self.history: Dict[int, Deque[str]] = {slot: deque(maxlen=window) for slot in range(4)}
        self.flips = 0

    def reset(self) -> None:
        for history in self.history.values():
            history.clear()
        self.flips = 0

    def update(self, names: List[Optional[str]]) -> Dict[int, str]:
        """Feed one frame's four slot readings, get the stable ones back.

        Returns {slot: card_name} containing only slots whose reading has been
        confirmed by at least `min_votes` of the last `window` frames.
        """
        stable: Dict[int, str] = {}
        for slot in range(4):
            name = names[slot] if slot < len(names) else None
            history = self.history[slot]
            if name is None and history and history[-1] != "blank":
                name = history[-1]
            if history and name and history[-1] != name:
                self.flips += 1
            history.append(name or "blank")

            counts = Counter(n for n in history if n and n != "blank")
            if not counts:
                continue
            best, votes = counts.most_common(1)[0]
            if votes >= min(self.min_votes, len(history)):
                stable[slot] = best
        return stable

    def confirm_played(self, slot: int) -> None:
        """Forget a slot after playing it; the card there is about to change."""
        self.history[slot].clear()
