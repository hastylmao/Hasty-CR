"""Read-only readiness probe for a Clash Royale emulator connection."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

from PIL import Image

CLASH_ROYALE_PACKAGE = "com.supercell.clashroyale"


def adb(adb_path: Path, serial: str, *args: str, binary: bool = False):
    command = [str(adb_path), "-s", serial, *args]
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=not binary,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument(
        "--save-frame",
        type=Path,
        default=None,
        help="optional path for the captured PNG",
    )
    args = parser.parse_args()

    packages = adb(args.adb, args.serial, "shell", "pm", "list", "packages")
    if packages.returncode != 0:
        print(json.dumps({"ready": False, "error": packages.stderr.strip()}))
        return 2

    installed = f"package:{CLASH_ROYALE_PACKAGE}" in packages.stdout.splitlines()
    focus = adb(
        args.adb,
        args.serial,
        "shell",
        "dumpsys",
        "window",
        "windows",
    )
    active = CLASH_ROYALE_PACKAGE in focus.stdout

    frame = adb(
        args.adb,
        args.serial,
        "exec-out",
        "screencap",
        "-p",
        binary=True,
    )
    if frame.returncode != 0 or not frame.stdout:
        print(
            json.dumps(
                {
                    "ready": False,
                    "installed": installed,
                    "active": active,
                    "error": "screen capture failed",
                }
            )
        )
        return 3

    image = Image.open(io.BytesIO(frame.stdout)).convert("RGB")
    width, height = image.size
    orientation = "portrait" if height > width else "landscape"
    if args.save_frame:
        args.save_frame.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.save_frame)

    ready = installed and active and orientation == "portrait"
    print(
        json.dumps(
            {
                "ready": ready,
                "installed": installed,
                "active": active,
                "serial": args.serial,
                "resolution": [width, height],
                "orientation": orientation,
                "frame_saved": str(args.save_frame) if args.save_frame else None,
            },
            indent=2,
        )
    )
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())

