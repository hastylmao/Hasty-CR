"""Shrink the Twitch captures without costing the detector anything.

Sixty-five gigabytes of .ts on a disk with under thirty free. The captures are
720x1558 at 60fps and about 4.34 Mbit/s, which is not badly encoded - the size
is simply thirty-three hours of video.

Re-encoding is only acceptable if the detector cannot tell. That was measured
rather than assumed, on a two minute segment, against the original:

    crf 24    99.6% of the original's detections, mean conf 0.805 vs 0.805
    crf 28   100.0%                               0.804
    crf 30   100.0%                               0.805

Detections per frame and confidence are unchanged at every level. Class-set
agreement falls from 94% to 89% across that range, but even crf 24 only agrees
with the original 94% of the time, so most of that is the detector's own
frame-to-frame jitter rather than compression. crf 24 is used because it is the
most conservative setting that still removes about two thirds of the bytes, and
the whole point of this corpus is that the footage stays measurable.

NVENC would be faster and is unavailable: this ffmpeg wants driver API 13.1 and
the installed driver offers 13.0. libx265 runs at about 5x realtime here, which
is enough.

**An original is only deleted after its replacement has been verified** - it
must exist, be non-trivial, decode, and match the source duration. A corrupt
encode that passed silently would destroy footage that cannot be re-downloaded,
because YouTube has already started refusing anonymous access.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

CRF = 24
PRESET = "fast"
AUDIO_BITRATE = "96k"

# A re-encode whose duration differs from the source by more than this is not
# the same video, whatever its size says.
DURATION_TOLERANCE_S = 2.0

# And one this much smaller than expected is a truncated write, not a good
# encode. Two thirds off is the target; ninety-five percent off is a failure.
MIN_SIZE_RATIO = 0.02


def probe(path: Path) -> Optional[dict]:
    """Duration, size and stream shape, or None if it will not decode."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_name,width,height",
         "-show_entries", "format=duration,size",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        return None
    try:
        blob = json.loads(out.stdout)
        stream = (blob.get("streams") or [{}])[0]
        fmt = blob.get("format") or {}
        return {"duration": float(fmt.get("duration", 0.0)),
                "size": int(fmt.get("size", 0)),
                "width": stream.get("width"),
                "height": stream.get("height"),
                "codec": stream.get("codec_name")}
    except (ValueError, KeyError, TypeError):
        return None


def encode(source: Path, target: Path, crf: int = CRF) -> bool:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(source),
         "-c:v", "libx265", "-preset", PRESET, "-crf", str(crf),
         "-c:a", "aac", "-b:a", AUDIO_BITRATE,
         "-movflags", "+faststart", str(target)],
        capture_output=True, text=True)
    return out.returncode == 0 and target.exists()


def verify(source_info: dict, target: Path) -> tuple[bool, str]:
    """Is `target` a faithful replacement for a source with `source_info`?"""
    if not target.exists():
        return False, "no output file"
    info = probe(target)
    if info is None:
        return False, "output does not decode"
    if info["size"] < source_info["size"] * MIN_SIZE_RATIO:
        return False, f"output implausibly small ({info['size'] / 1e6:.1f} MB)"
    drift = abs(info["duration"] - source_info["duration"])
    if drift > DURATION_TOLERANCE_S:
        return False, (f"duration differs by {drift:.1f}s "
                       f"({info['duration']:.0f} vs {source_info['duration']:.0f})")
    if (info["width"], info["height"]) != (source_info["width"], source_info["height"]):
        return False, (f"resolution changed to {info['width']}x{info['height']}")
    return True, "ok"


def human(n: float) -> str:
    return f"{n / 1e9:.2f} GB"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", type=Path,
                    default=Path(r"C:\Users\aksha\Downloads\Video\twitch"))
    ap.add_argument("--crf", type=int, default=CRF)
    ap.add_argument("--keep", action="store_true",
                    help="do not delete originals even after verification")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    sources = sorted(p for p in args.dir.glob("*.ts") if p.is_file())
    if not sources:
        raise SystemExit(f"no .ts files in {args.dir}")

    total_before = sum(p.stat().st_size for p in sources)
    print(f"{len(sources)} files, {human(total_before)} to process, crf {args.crf}",
          flush=True)

    saved = 0
    done = 0
    for source in sources:
        if args.limit and done >= args.limit:
            break
        target = source.with_suffix(".mp4")
        if target.exists() and not source.exists():
            continue
        info = probe(source)
        if info is None:
            print(f"{source.name}: will not decode, skipping", flush=True)
            continue

        print(f"\n{source.name}  {human(info['size'])}  "
              f"{info['duration'] / 3600:.2f}h", flush=True)
        started = time.time()
        if not encode(source, target, args.crf):
            print("  encode FAILED, original untouched", flush=True)
            if target.exists():
                target.unlink()
            continue

        ok, why = verify(info, target)
        took = time.time() - started
        if not ok:
            print(f"  verification failed ({why}); original untouched", flush=True)
            target.unlink()
            continue

        after = target.stat().st_size
        ratio = after / info["size"] * 100.0
        print(f"  -> {human(after)} ({ratio:.0f}% of original) in "
              f"{took / 60:.0f} min, {info['duration'] / took:.1f}x realtime",
              flush=True)

        if args.keep:
            print("  keeping original (--keep)", flush=True)
        else:
            source.unlink()
            saved += info["size"] - after
            print(f"  deleted original, {human(saved)} recovered so far",
                  flush=True)
        done += 1

    print(f"\ndone: {done} files, {human(saved)} recovered", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
