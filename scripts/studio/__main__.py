"""Entry point:  python -m scripts.studio   (or  .\\studio.ps1)

    --list                 show every emulator surface found, then exit
    --no-detect            skip YOLO entirely (lowest overhead)
    --record clip.mp4      start recording immediately
    --layout game|feed     trade log lines for mirror size, or the reverse
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG = ROOT / "tmp" / "live" / "cr_bot.log"
DEFAULT_ADB = Path(r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="studio", description="Record the bot playing, with its own brain overlaid")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG,
                        help="bot log to tail (read-only)")
    parser.add_argument("--layout", default="balanced",
                        choices=("balanced", "game", "feed", "sim"))
    parser.add_argument("--fps", type=int, default=60, help="mirror refresh rate")
    parser.add_argument("--sim-speed", type=float, default=2.0,
                        help="how fast the simulator panel plays. Faster than "
                             "real time on purpose: it is there to show the "
                             "trainer working, and a three minute match at 1x "
                             "is longer than the clip it goes into")
    parser.add_argument("--scale", type=float, default=0.48,
                        help="window size as a fraction of the 1080x1920 canvas")
    parser.add_argument("--hwnd", type=int, help="target a specific window handle")
    parser.add_argument("--frame", type=Path,
                        help="use a still image instead of the live window")
    parser.add_argument("--adb", default=str(DEFAULT_ADB))
    parser.add_argument("--serial", default="127.0.0.1:7555")
    # MuMu's renderer can stall while the game keeps running; ADB reads the
    # framebuffer, so it cannot freeze. Slow, and it shares the bot's channel,
    # so it engages only once the window has gone stale.
    parser.add_argument("--adb-fallback", dest="adb_fallback", action="store_true",
                        default=True,
                        help="read frames over ADB when the window stops rendering")
    parser.add_argument("--no-adb-fallback", dest="adb_fallback", action="store_false")
    parser.add_argument("--adb-fps", type=float, default=6.0)
    parser.add_argument("--stale-seconds", type=float, default=2.0,
                        help="how long an unchanging window counts as frozen")
    parser.add_argument("--list", action="store_true",
                        help="list candidate emulator surfaces and exit")
    parser.add_argument("--probe", type=int, metavar="N",
                        help="composite N frames offscreen, save a still, exit")

    parser.add_argument("--detect", dest="detect", action="store_true", default=True)
    parser.add_argument("--no-detect", dest="detect", action="store_false")
    parser.add_argument("--weights", type=Path,
                        help="detector checkpoint (default: newest cr_detector run)")
    parser.add_argument("--detect-fps", type=float, default=12.0)
    parser.add_argument("--conf", type=float, default=0.35)

    parser.add_argument("--record", nargs="?", const=True, default=False,
                        help="start recording at launch; optionally give a path")
    parser.add_argument("--record-fps", type=int, default=60)
    parser.add_argument("--crf", type=int, default=20, help="lower is better quality")
    parser.add_argument("--preset", default="veryfast")
    args = parser.parse_args(argv)

    if args.list:
        from .capture import find_surfaces
        found = list(find_surfaces())
        if not found:
            print("no emulator surface found - is MuMu running with a device started?")
            return 1
        for surface in found:
            print(surface)
        return 0

    args.out = Path(args.record) if isinstance(args.record, str) else None
    args.record = bool(args.record)

    from .app import run
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
