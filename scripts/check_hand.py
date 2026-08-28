"""Compare what the detector thinks is in hand against the actual screen.

The block reports showed Ice Spirit at 26.5% of all plays. In an eight-card
deck a card cannot exceed 20% of plays - four other cards must be played before
it returns - so a share above that is proof the hand is being misread, not
evidence about strategy. This script captures a live frame, prints the detected
hand, and writes the cropped hand strip so the two can be compared by eye.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import mumu_overnight_bot as guarded  # noqa: E402
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402

DECK = [
    Cards.CANNON, Cards.FIREBALL, Cards.HOG_RIDER, Cards.ICE_GOLEM,
    Cards.ICE_SPIRIT, Cards.MUSKETEER, Cards.SKELETONS, Cards.THE_LOG,
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump detected hand vs the screen")
    parser.add_argument("--adb", type=Path,
                        default=Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"))
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--samples", type=int, default=4)
    parser.add_argument("--out", type=Path, default=ROOT / "tmp" / "live" / "hand")
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    detector = Detector(DECK)
    args.out.mkdir(parents=True, exist_ok=True)

    for index in range(args.samples):
        full, state = guarded.detect(detector, args.adb, args.serial)
        if state is None:
            print(f"{index}: no state")
            continue
        hand = [card.name for card in state.cards[1:]]
        ready = sorted(getattr(state, "ready", ()))
        print(f"{index}: screen={state.screen.name} next={state.cards[0].name} "
              f"hand={hand} ready={ready} elixir={state.numbers.elixir.number}")
        # The hand strip on a 1080x1920 device, generous margins.
        full.crop((230, 1590, 1060, 1830)).save(args.out / f"hand_{index}.png")
    print(f"hand crops written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
