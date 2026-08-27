"""Measure the upstream card detector against the replacement, on live frames.

Captures a burst of frames and reports, for each classifier, how often a slot's
reading changed between consecutive frames. Cards do not change on their own, so
during a burst with no plays almost every change is a misread. This is the
evidence that decides whether the replacement is actually better - not a guess.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import mumu_overnight_bot as guarded  # noqa: E402
from brain.cards import CardClassifier  # noqa: E402
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402

DECK_CARDS = [
    Cards.CANNON, Cards.FIREBALL, Cards.HOG_RIDER, Cards.ICE_GOLEM,
    Cards.ICE_SPIRIT, Cards.MUSKETEER, Cards.SKELETONS, Cards.THE_LOG,
]
DECK_NAMES = [card.name for card in DECK_CARDS]


def flips(readings):
    """Slot changes between consecutive frames, ignoring unknown readings."""
    count = 0
    for slot in range(4):
        series = [frame[slot] for frame in readings]
        previous = None
        for value in series:
            if value is None:
                continue
            if previous is not None and value != previous:
                count += 1
            previous = value
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Old vs new card classifier")
    parser.add_argument("--adb", type=Path,
                        default=Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"))
    parser.add_argument("--serial", default="127.0.0.1:7555")
    parser.add_argument("--frames", type=int, default=20)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    detector = Detector(DECK_CARDS)
    classifier = CardClassifier(DECK_NAMES)
    if not classifier.ready:
        print("WARN: reference art missing for some cards")

    old_readings, new_readings = [], []
    old_counts, new_counts = Counter(), Counter()
    for _ in range(args.frames):
        full, state = guarded.detect(detector, args.adb, args.serial)
        if state is None or state.screen.name != "in_game":
            time.sleep(0.3)
            continue
        old = [state.cards[slot + 1].name for slot in range(4)]
        old = [None if name == "blank" else name for name in old]
        new = classifier.classify_hand(full)
        old_readings.append(old)
        new_readings.append(new)
        old_counts.update(n for n in old if n)
        new_counts.update(n for n in new if n)
        time.sleep(0.2)

    frames = len(old_readings)
    if frames < 3:
        print(f"only {frames} in-game frames captured; run during a battle")
        return 1

    print(f"frames={frames}")
    print(f"upstream  flips={flips(old_readings):3d}  "
          f"unknown={sum(v is None for f in old_readings for v in f):3d}")
    print(f"replacement flips={flips(new_readings):3d}  "
          f"unknown={sum(v is None for f in new_readings for v in f):3d}")
    print(f"upstream    last: {old_readings[-1]}")
    print(f"replacement last: {new_readings[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
