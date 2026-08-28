"""Where does the bot's reaction time actually go?

The decision loop runs at roughly 2 Hz while a human reacts in a few hundred
milliseconds, so every defensive placement lands up to half a second late. That
is a plausible reason the bot loses two thirds of its matches, but "plausible"
is not a measurement - this splits the loop into its parts so the fix goes
where the time is rather than where it feels like it is.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import mumu_overnight_bot as guarded  # noqa: E402
from brain.policy import Brain  # noqa: E402
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402

DECK = [
    Cards.CANNON, Cards.FIREBALL, Cards.HOG_RIDER, Cards.ICE_GOLEM,
    Cards.ICE_SPIRIT, Cards.MUSKETEER, Cards.SKELETONS, Cards.THE_LOG,
]
DEFAULT_ADB = Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe")


def report(name: str, samples: list[float]) -> float:
    if not samples:
        print(f"{name:22s}  no samples")
        return 0.0
    mean = statistics.mean(samples)
    print(f"{name:22s} mean {mean * 1000:6.1f}ms   "
          f"median {statistics.median(samples) * 1000:6.1f}ms   "
          f"max {max(samples) * 1000:6.1f}ms")
    return mean


def main() -> int:
    parser = argparse.ArgumentParser(description="Profile the decision loop")
    parser.add_argument("--adb", type=Path, default=DEFAULT_ADB)
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--frames", type=int, default=25)
    args = parser.parse_args()

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    detector = Detector(DECK)
    brain = Brain(use_advisor=False, learn=False)

    capture, detect, decide = [], [], []
    for _ in range(args.frames):
        started = time.monotonic()
        full, small = guarded.capture(args.adb, args.serial)
        after_capture = time.monotonic()
        state = detector.run(small)
        after_detect = time.monotonic()
        if state is not None and state.screen.name == "in_game":
            brain.decide(state, 30.0, time.monotonic(), frame=full)
        after_decide = time.monotonic()

        capture.append(after_capture - started)
        detect.append(after_detect - after_capture)
        decide.append(after_decide - after_detect)

    print(f"\n{args.frames} frames\n")
    a = report("adb screen capture", capture)
    b = report("perception (detector)", detect)
    c = report("policy decision", decide)
    total = a + b + c
    print(f"\n{'total':22s} mean {total * 1000:6.1f}ms  "
          f"-> {1 / total if total else 0:.1f} decisions/sec")
    for name, value in (("capture", a), ("perception", b), ("policy", c)):
        print(f"   {name:12s} {100 * value / total if total else 0:5.1f}% of the loop")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
