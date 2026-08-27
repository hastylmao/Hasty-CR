"""Extract a frame-accurate segment from a recorded Clash Royale match.

The output contains numbered PNG frames and a small provenance file.  It does
not mark a probe as accepted; that remains a human review plus simulator-test
decision in ``data/validation/live_probes.json``.

    python scripts/extract_probe_frames.py recording.mp4 900 990
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from verify_live_probe_assets import sha256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "tmp" / "live" / "probe_frames"


def frame_numbers(start_frame: int, end_frame: int, stride: int) -> list[int]:
    if start_frame < 0:
        raise ValueError("start frame must be non-negative")
    if end_frame < start_frame:
        raise ValueError("end frame must not precede start frame")
    if stride < 1:
        raise ValueError("stride must be at least one")
    return list(range(start_frame, end_frame + 1, stride))


def select_filter(start_frame: int, end_frame: int, stride: int) -> str:
    """Return an ffmpeg filter preserving exactly the declared source frames."""
    frame_numbers(start_frame, end_frame, stride)
    return (
        f"select='between(n\\,{start_frame}\\,{end_frame})*"
        f"not(mod(n-{start_frame}\\,{stride}))'"
    )


def validate_source_range(frame_count: int | None, start_frame: int,
                          end_frame: int) -> None:
    """Reject a claimed source range that cannot exist in the video."""
    frame_numbers(start_frame, end_frame, 1)
    if frame_count is not None and end_frame >= frame_count:
        raise ValueError(
            f"end frame {end_frame} is outside source video (last frame {frame_count - 1})")


def probe_frame_count(video: Path, ffprobe: str) -> int | None:
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=nb_frames", "-of", "default=nokey=1:noprint_wrappers=1",
        str(video),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    value = result.stdout.strip()
    return int(value) if value.isdigit() else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("start_frame", type=int)
    parser.add_argument("end_frame", type=int)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe"))
    args = parser.parse_args()
    source_frames = frame_numbers(args.start_frame, args.end_frame, args.stride)
    if not args.video.is_file():
        parser.error(f"video does not exist: {args.video}")
    if not args.ffmpeg:
        parser.error("ffmpeg is required; install FFmpeg or pass --ffmpeg PATH")
    if not args.ffprobe:
        parser.error("ffprobe is required; install FFmpeg or pass --ffprobe PATH")
    try:
        validate_source_range(probe_frame_count(args.video, args.ffprobe),
                              args.start_frame, args.end_frame)
    except (ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))

    destination = args.output_root / (
        f"{args.video.stem}_f{args.start_frame:06d}-{args.end_frame:06d}_s{args.stride}")
    destination.mkdir(parents=True, exist_ok=True)
    # This directory is created solely by this command for this exact range;
    # remove only old generated PNGs so a partial prior FFmpeg run cannot look
    # complete when its output is counted below.
    for old_frame in destination.glob("frame_*.png"):
        old_frame.unlink()
    command = [
        args.ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(args.video),
        "-vf", select_filter(args.start_frame, args.end_frame, args.stride),
        "-vsync", "0", str(destination / "frame_%06d.png"),
    ]
    subprocess.run(command, check=True)
    generated = sorted(destination.glob("frame_*.png"))
    if len(generated) != len(source_frames):
        raise RuntimeError(
            f"FFmpeg exported {len(generated)} frames; expected {len(source_frames)}")
    metadata = {
        "source_video": str(args.video),
        "source_sha256": sha256(args.video),
        "source_start_frame": args.start_frame,
        "source_end_frame": args.end_frame,
        "stride": args.stride,
        "source_frames": source_frames,
        "source_frame_count": probe_frame_count(args.video, args.ffprobe),
        "frame_pattern": "frame_%06d.png",
        "acceptance": "unreviewed; add only reviewed observations to live_probes.json",
    }
    (destination / "provenance.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"extracted {len(source_frames)} frames: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
