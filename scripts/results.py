"""Win/loss from end-of-game screenshots. **Currently unreliable - see below.**

MEASURED BROKEN 2026-08-18. Run against 36 live end-of-game frames it returned
"loss" for every single one, including two matches that were unambiguous wins on
crowns. The blue mask counts every blue row in the frame - our own half of the
arena, the card bar, the UI - so blue's mean row is always lower on screen than
red's and the comparison always resolves the same way.

Note what that does to the original validation recorded below: it was checked
against two confirmed *losses*, and a function that always answers "loss" passes
that test. Two samples of one class cannot validate a binary classifier.

It also has no way to express a draw, and 53% of this bot's matches end 1-1.

Until both are fixed, count crowns from the tower fractions instead (see
scripts/record.py). The one case crowns get wrong is an opponent who quits:
the match ends at once with every tower standing, which reads as a draw when it
was a win.


Crown counting depends on tower HP, which the detector gets wrong (it reports
our right tower at 0.00 while it is at full health), so every crown statistic
in this run is unreliable. The result screen is independent of that: the
winner's banner sits above the loser's, so comparing the vertical position of
the opponent's red banner against our blue one gives the real outcome.

Validated against two visually-confirmed losses before use.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

ROW_PIXELS = 400  # a banner spans most of the screen width


def outcome_of(image: Image.Image) -> str:
    """Winner from an end-of-game frame, by banner position.

    Split out from `outcome` so the bot can adjudicate a match while it still
    has the frame in memory, instead of counting crowns afterwards. Crown
    counting is wrong in one specific and common case: if the opponent quits,
    Clash Royale ends the match immediately and you win, with every tower still
    standing. Six of fifty-one matches one night ended under 110 seconds, two of
    them with all four towers alive - all scored as draws or losses by a crown
    count, all of them almost certainly wins.
    """
    px = np.asarray(image.convert("RGB"))
    if px.shape[0] < 1900:
        return "unknown"
    r = px[:, :, 0].astype(int)
    g = px[:, :, 1].astype(int)
    b = px[:, :, 2].astype(int)
    red = (r > 150) & (r - g > 60) & (r - b > 40)
    blue = (b > 140) & (b - r > 40) & (b - g > 20)
    rows_red = np.where(red.sum(axis=1) > ROW_PIXELS)[0]
    rows_blue = np.where(blue.sum(axis=1) > ROW_PIXELS)[0]
    if not len(rows_red) or not len(rows_blue):
        return "unknown"
    return "win" if rows_blue.mean() < rows_red.mean() else "loss"


def outcome(path: Path) -> str:
    return outcome_of(Image.open(path))


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "tmp/live/katacr_results")
    shots = sorted(root.glob("*end_of_game.png"))
    tally = Counter(outcome(s) for s in shots)
    total = tally["win"] + tally["loss"]
    print(f"result screens: {len(shots)}")
    for key in ("win", "loss", "unknown"):
        if tally[key]:
            print(f"  {key:<8}{tally[key]}")
    if total:
        print(f"win rate: {100 * tally['win'] / total:.1f}%  ({tally['win']}/{total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
