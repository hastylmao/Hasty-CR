"""Capture gameplay frames from one or more Android emulators.

This command is observation-only. It does not automate play or interact with
Clash Royale. Stop with Ctrl+C; the session manifest and per-device stats are
updated before exit.

Single emulator:
    python scripts/capture_emulators.py --adb C:\\path\\adb.exe \\
        --serial 127.0.0.1:7555 --hours 8 --interval 0.5

Multiple emulators:
    python scripts/capture_emulators.py --adb C:\\path\\adb.exe \\
        --serial 127.0.0.1:7555 --serial 127.0.0.1:7557 --hours 12
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.emulator_capture import CaptureConfig, MultiEmulatorCapture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", action="append", required=True,
                        help="ADB serial; repeat for multiple emulators")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "tmp" / "mechanics-captures")
    parser.add_argument("--hours", type=float, default=0.0,
                        help="capture duration; zero means until Ctrl+C")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="seconds between captures per emulator")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="save identical consecutive frames too")
    parser.add_argument("--max-gib", type=float, default=0.0,
                        help="stop all workers after this total per-device budget; zero means unlimited")
    args = parser.parse_args()
    if args.hours < 0:
        parser.error("--hours cannot be negative")
    if not args.adb.is_file():
        parser.error(f"ADB executable does not exist: {args.adb}")
    if len(set(args.serial)) != len(args.serial):
        parser.error("--serial values must be unique")
    configs = [CaptureConfig(
        adb=args.adb,
        serial=serial,
        output=args.output,
        interval_seconds=args.interval,
        deduplicate=not args.keep_duplicates,
        max_gib=args.max_gib,
    ) for serial in args.serial]
    capture = MultiEmulatorCapture(configs, args.hours * 3600)
    print(f"capturing {len(configs)} emulator(s) into {args.output}", flush=True)
    print("observation-only mode; press Ctrl+C to stop safely", flush=True)
    stats = capture.run()
    for item in stats:
        print(f"{item.serial}: frames={item.frames} duplicates={item.duplicate_frames} "
              f"errors={item.capture_errors} bytes={item.bytes_written}", flush=True)
    return 0 if all(item.frames or item.capture_errors == 0 for item in stats) else 1


if __name__ == "__main__":
    raise SystemExit(main())
