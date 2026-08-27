"""Periodic low-resolution game capture with a hard disk budget.

Frames are downscaled and JPEG-encoded, then pruned oldest-first so the folder
can never exceed --budget-mb no matter how long the run lasts.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import time
from datetime import datetime
from pathlib import Path

from PIL import Image


def capture(adb: Path, serial: str) -> Image.Image | None:
    try:
        raw = subprocess.run(
            [str(adb), "-s", serial, "exec-out", "screencap", "-p"],
            capture_output=True,
            check=True,
            timeout=20,
        ).stdout
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def folder_mb(folder: Path) -> float:
    return sum(f.stat().st_size for f in folder.glob("*.jpg")) / (1024 * 1024)


def prune(folder: Path, budget_mb: float) -> int:
    frames = sorted(folder.glob("*.jpg"))
    removed = 0
    while frames and folder_mb(folder) > budget_mb:
        # Always keep the most recent window intact.
        if len(frames) <= 50:
            break
        frames.pop(0).unlink(missing_ok=True)
        removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Low-res periodic capture with disk cap")
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", default="127.0.0.1:7555")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=3.0)
    parser.add_argument("--width", type=int, default=360)
    parser.add_argument("--quality", type=int, default=55)
    parser.add_argument("--budget-mb", type=float, default=1500.0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    saved = failures = pruned = 0
    while True:
        started = time.monotonic()
        image = capture(args.adb, args.serial)
        if image is None:
            failures += 1
        else:
            height = round(image.height * args.width / image.width)
            small = image.resize((args.width, height))
            name = f"{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3] + ".jpg"
            small.save(args.out / name, "JPEG", quality=args.quality, optimize=True)
            saved += 1
            if saved % 20 == 0:
                pruned += prune(args.out, args.budget_mb)
        if saved and saved % 200 == 0:
            print(
                f"{datetime.now():%H:%M:%S} CAPTURE saved={saved} failures={failures} "
                f"pruned={pruned} folder_mb={folder_mb(args.out):.1f}",
                flush=True,
            )
        time.sleep(max(0.1, args.interval - (time.monotonic() - started)))


if __name__ == "__main__":
    raise SystemExit(main())
