"""Build an unlabelled candidate-event index for gameplay recordings.

This is triage only: frame-to-frame arena motion identifies portions worth
human review, but never identifies a card or asserts a game mechanic. It keeps
the calibration workflow honest while avoiding manual scrubbing of every clip.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from verify_live_probe_assets import sha256


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "validation" / "motion_candidates.json"


@dataclass(frozen=True)
class MotionSample:
    frame: int
    score: float


def group_candidate_frames(frames: list[int], *, max_gap_frames: int) -> list[tuple[int, int]]:
    """Merge nearby above-threshold samples into inclusive source-frame ranges."""
    if not frames:
        return []
    ordered = sorted(set(frames))
    groups = []
    start = previous = ordered[0]
    for frame in ordered[1:]:
        if frame - previous > max_gap_frames:
            groups.append((start, previous))
            start = frame
        previous = frame
    groups.append((start, previous))
    return groups


def arena_roi(frame: np.ndarray) -> np.ndarray:
    """Exclude top labels and bottom hand while retaining the 18x32 board."""
    height, width = frame.shape[:2]
    return frame[int(height * 0.075):int(height * 0.79),
                 int(width * 0.035):int(width * 0.965)]


def motion_samples(video: Path, sample_fps: float) -> tuple[float, int, list[MotionSample]]:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0:
        raise ValueError(f"invalid FPS: {video}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError("ffmpeg is required for efficient recording indexing")
    # FFmpeg performs the full-resolution decode and crop in native code. This
    # is substantially faster than handing tens of thousands of 1080p frames
    # to OpenCV/Python just to discard most of them.
    width, height = 90, 128
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video),
        "-vf", (
            f"crop=iw*0.93:ih*0.715:iw*0.035:ih*0.075,"
            f"fps={sample_fps},scale={width}:{height}:flags=area,format=gray"),
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdout is not None
    previous = None
    samples = []
    sample_no = 0
    bytes_per_frame = width * height
    while True:
        payload = process.stdout.read(bytes_per_frame)
        if not payload:
            break
        if len(payload) != bytes_per_frame:
            process.kill()
            raise ValueError(f"truncated FFmpeg frame stream: {video}")
        image = np.frombuffer(payload, dtype=np.uint8).reshape(height, width)
        if previous is not None:
            samples.append(MotionSample(
                round(sample_no * fps / sample_fps),
                float(cv2.absdiff(image, previous).mean())))
        previous = image
        sample_no += 1
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    if process.wait() != 0:
        raise ValueError(f"FFmpeg failed for {video}: {stderr.strip()}")
    capture.release()
    return fps, frames, samples


def candidate_events(samples: list[MotionSample], fps: float, max_events: int,
                     last_frame: int | None = None) -> list[dict]:
    if not samples:
        return []
    scores = np.asarray([sample.score for sample in samples])
    median = float(np.median(scores))
    mad = float(np.median(np.abs(scores - median)))
    # MAD is robust against a fight itself becoming the average frame.  A tiny
    # fallback retains sensible behavior on almost-static videos.
    threshold = median + max(1.0, 3.0 * mad)
    selected = [sample.frame for sample in samples if sample.score >= threshold]
    groups = group_candidate_frames(selected, max_gap_frames=max(1, round(fps)))
    by_frame = {sample.frame: sample.score for sample in samples}
    events = []
    padding = round(fps)
    for start, end in groups:
        members = [score for frame, score in by_frame.items() if start <= frame <= end]
        peak_frame = max((frame for frame in by_frame if start <= frame <= end),
                         key=by_frame.__getitem__)
        events.append({
            "start_frame": max(0, start - padding),
            "end_frame": min(end + padding, last_frame)
            if last_frame is not None else end + padding,
            "peak_frame": peak_frame,
            "peak_motion": round(by_frame[peak_frame], 4),
            "mean_motion": round(float(np.mean(members)), 4),
            "classification": "unreviewed_motion_candidate",
        })
    return sorted(events, key=lambda event: event["peak_motion"], reverse=True)[:max_events]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("--sample-fps", type=float, default=10.0)
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.recordings.is_dir():
        parser.error(f"recordings directory does not exist: {args.recordings}")
    if args.sample_fps <= 0 or args.max_events <= 0:
        parser.error("sample FPS and max events must be positive")

    clips = []
    for video in sorted(args.recordings.rglob("*.mp4"), key=lambda path: path.name.lower()):
        fps, frames, samples = motion_samples(video, args.sample_fps)
        clips.append({
            "capture_id": video.stem,
            "source_path": str(video),
            "source_sha256": sha256(video),
            "fps": fps,
            "frames": frames,
            "events": candidate_events(samples, fps, args.max_events,
                                        last_frame=max(0, frames - 1)),
        })
    payload = {
        "schema_version": 1,
        "purpose": "triage only; candidates are not accepted calibration evidence",
        "sample_fps": args.sample_fps,
        "clips": clips,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"indexed {len(clips)} recordings: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
