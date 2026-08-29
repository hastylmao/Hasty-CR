"""Fetch, segment, track, delete - one video at a time, resumably.

Written to survive being interrupted, because it will be. Forty-eight hours of
video takes many hours to process, the machine it runs on is also the machine
the emulator and the trainer use, and a night's work that cannot resume is a
night's work that gets thrown away the first time something else needs the CPU.

So: every video's tracks are written before the next one starts, a completed
video is recorded in a manifest and skipped on the next run, and the video file
itself is deleted the moment its tracks exist. Nothing accumulates except the
tracks, which are about a thousandth of the size.

The disk guard is not decoration. This machine has been at 99% full once
already today, and a download that fills the last gigabyte mid-write corrupts
the file it was writing and stops everything after it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.vod import fetch, segment, track          # noqa: E402

DATA = ROOT / "data" / "vod"
VIDEOS = DATA / "videos"
TRACKS = DATA / "tracks"
MANIFEST = DATA / "manifest.json"
CATALOGUE = DATA / "catalogue.json"
WEIGHTS = ROOT / "tmp" / "yolo" / "runs" / "cr_detector_s" / "weights" / "best.pt"

# Refuse to start a download with less than this free. A stream at 888x1920/60
# runs a few gigabytes; this leaves room for the largest plus working space.
MIN_FREE_GB = 12.0


def free_gb(path: Path = ROOT) -> float:
    return shutil.disk_usage(path).free / 1e9


def load_manifest() -> dict:
    if MANIFEST.exists():
        try:
            return json.loads(MANIFEST.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"done": {}, "failed": {}}


def save_manifest(state: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(state, indent=2), encoding="utf-8")


def log(message: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


def process(video: fetch.Video, model, args, state: dict) -> bool:
    """One video, end to end. Returns True if tracks were written."""
    if video.video_id in state["done"]:
        return False
    if free_gb() < MIN_FREE_GB:
        log(f"stopping: only {free_gb():.1f} GB free")
        return False

    log(f"fetching {video.video_id} ({video.duration_s / 60:.0f} min) {video.title[:50]}")
    path = fetch.download(video, VIDEOS)
    if path is None:
        state["failed"][video.video_id] = "download failed"
        save_manifest(state)
        log(f"  could not download {video.video_id}; moving on")
        return False

    try:
        import cv2
        capture = cv2.VideoCapture(str(path))
        height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920.0
        source_fps = capture.get(cv2.CAP_PROP_FPS) or 60.0
        capture.release()

        log(f"  segmenting at {args.segment_stride}s stride")
        spans = segment.find_spans(model, path, args.segment_stride)
        log(f"  {segment.describe(spans)}")

        written = 0
        for index, span in enumerate(spans):
            start = segment.refine_start(model, path, span)
            dets = track.detect_span(model, path, start, span.end_s, args.track_fps)
            matrix, error = track.to_tiles(dets, height)
            if matrix is None:
                log(f"    span {index}: no tower fix, skipped")
                continue
            if error > args.max_residual:
                log(f"    span {index}: tower fit off by {error:.2f} tiles, skipped")
                continue
            out = TRACKS / f"{video.video_id}_{index:03d}.jsonl"
            track.write_jsonl(out, video.video_id, index, dets, {
                "title": video.title, "kind": video.kind,
                "video_start_s": round(start, 3),
                "video_end_s": round(span.end_s, 3),
                "duration_s": round(span.end_s - start, 3),
                "track_fps": args.track_fps,
                "source_fps": source_fps,
                "frame_height": height,
                "tower_fit_residual_tiles": round(error, 4),
            })
            written += 1
        state["done"][video.video_id] = {
            "title": video.title, "kind": video.kind,
            "spans": written, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_manifest(state)
        log(f"  wrote {written} match files")
        return written > 0
    finally:
        if not args.keep_videos:
            _remove(path)


def _remove(path: Path, attempts: int = 8) -> bool:
    """Delete a processed video, tolerating Windows holding it briefly.

    Ultralytics opens the file itself for `predict(stream=True)` and does not
    always let go the instant the generator is exhausted. On Windows that is a
    hard PermissionError rather than the silent no-op it would be elsewhere,
    and it used to abort the video's own cleanup *after* its tracks were
    safely written - so nothing was lost, but every processed video stayed on
    a disk that hit 99% full yesterday.

    Retry briefly, then give up and say so. A file left behind is a disk
    problem; a raised exception here would be a pipeline problem.
    """
    import gc
    import time

    if not path.exists():
        return True
    for attempt in range(attempts):
        gc.collect()                       # drop any lingering capture object
        try:
            path.unlink()
            log(f"  deleted {path.name} ({free_gb():.1f} GB free)")
            return True
        except PermissionError:
            time.sleep(0.5 * (attempt + 1))
        except OSError as exc:
            log(f"  could not delete {path.name}: {type(exc).__name__}")
            return False
    log(f"  {path.name} still locked; sweeping it on the next pass")
    return False


def sweep_videos(keep: bool) -> None:
    """Delete leftovers from earlier passes that were locked at the time."""
    if keep or not VIDEOS.exists():
        return
    for stale in sorted(VIDEOS.glob("*.*")):
        if stale.suffix.lower() in (".mp4", ".webm", ".mkv"):
            _remove(stale, attempts=2)


def process_local(path: Path, model, args, state: dict) -> int:
    """Segment and track a video already on disk.

    The Twitch captures were downloaded by hand and compressed here; there is
    nothing to fetch and nothing to delete. Same segmentation and tracking as
    the YouTube path, so measurements from both are directly comparable.
    """
    import cv2

    key = f"local:{path.stem}"
    if key in state["done"]:
        return 0
    capture = cv2.VideoCapture(str(path))
    height = capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920.0
    source_fps = capture.get(cv2.CAP_PROP_FPS) or 60.0
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    capture.release()
    duration = frames / source_fps if source_fps else 0.0

    if duration < args.min_duration_s:
        log(f"{path.name}: {duration:.0f}s, too short to be a stream, skipping")
        return 0

    log(f"{path.name}  {duration / 3600:.2f}h  segmenting")
    spans = segment.find_spans(model, path, args.segment_stride)
    log(f"  {segment.describe(spans)}")

    written = 0
    for index, span in enumerate(spans):
        start = segment.refine_start(model, path, span)
        dets = track.detect_span(model, path, start, span.end_s, args.track_fps)
        matrix, error = track.to_tiles(dets, height)
        if matrix is None:
            continue
        if error > args.max_residual:
            log(f"    span {index}: tower fit off by {error:.2f} tiles, skipped")
            continue
        out = TRACKS / f"{path.stem}_{index:03d}.jsonl"
        track.write_jsonl(out, path.stem, index, dets, {
            "title": path.stem, "kind": "twitch_local",
            "video_start_s": round(start, 3),
            "video_end_s": round(span.end_s, 3),
            "duration_s": round(span.end_s - start, 3),
            "track_fps": args.track_fps, "source_fps": source_fps,
            "frame_height": height,
            "tower_fit_residual_tiles": round(error, 4),
        })
        written += 1
    state["done"][key] = {"title": path.stem, "kind": "twitch_local",
                          "spans": written,
                          "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_manifest(state)
    log(f"  wrote {written} match files")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--videos", type=int, default=30)
    ap.add_argument("--streams", type=int, default=15)
    ap.add_argument("--limit", type=int, default=0, help="stop after N videos")
    ap.add_argument("--segment-stride", type=float, default=1.0)
    ap.add_argument("--track-fps", type=float, default=10.0,
                    help="detector samples per second inside a match. 10 "
                         "resolves a 2 tiles/s Hog to a fifth of a tile")
    ap.add_argument("--max-residual", type=float, default=0.75,
                    help="reject a match whose tower fit misses by more than "
                         "this many tiles; every distance would inherit it")
    ap.add_argument("--local-dir", type=Path,
                    help="segment and track videos already on disk "
                         "instead of fetching a channel. Nothing is "
                         "downloaded or deleted.")
    ap.add_argument("--min-duration-s", type=float, default=600.0,
                    help="ignore local files shorter than this; a "
                         "stream folder collects unrelated clips")
    ap.add_argument("--keep-videos", action="store_true")
    ap.add_argument("--weights", type=Path, default=WEIGHTS)
    args = ap.parse_args()

    if not args.weights.exists():
        raise SystemExit(f"detector weights not found at {args.weights}")

    from ultralytics import YOLO
    model = YOLO(str(args.weights))

    if args.local_dir:
        state = load_manifest()
        files = sorted(p for p in args.local_dir.glob("*.mp4") if p.is_file())
        log(f"{len(files)} local videos in {args.local_dir}")
        total = 0
        for path in files:
            try:
                total += process_local(path, model, args, state)
            except KeyboardInterrupt:
                log("interrupted")
                break
            except Exception as exc:
                state["failed"][f"local:{path.stem}"] = f"{type(exc).__name__}: {exc}"
                save_manifest(state)
                log(f"  {path.name} failed: {type(exc).__name__}: {exc}")
        log(f"done: {total} match files written from local video")
        return 0

    corpus = fetch.catalogue(CATALOGUE, args.videos, args.streams)
    log(f"catalogue: {len(corpus)} items, "
        f"{sum(v.duration_s for v in corpus) / 3600:.1f} hours")

    state = load_manifest()
    processed = 0
    for video in fetch.by_size(corpus):
        if args.limit and processed >= args.limit:
            break
        if video.video_id in state["done"]:
            continue
        sweep_videos(args.keep_videos)
        if free_gb() < MIN_FREE_GB:
            log(f"stopping: {free_gb():.1f} GB free, below the {MIN_FREE_GB} GB floor")
            break
        try:
            process(video, model, args, state)
        except fetch.BlockedError as exc:
            # Stop, and leave the untried videos untried. Recording them as
            # failures would make the next run skip footage that was never
            # actually requested.
            log(f"HALTED: {exc}")
            log("  pass --cookies-from-browser to yt-dlp, or wait it out; "
                "the manifest is unchanged for anything not attempted")
            break
        except KeyboardInterrupt:
            log("interrupted")
            break
        except Exception as exc:                       # keep the run alive
            state["failed"][video.video_id] = f"{type(exc).__name__}: {exc}"
            save_manifest(state)
            log(f"  {video.video_id} failed: {type(exc).__name__}: {exc}")
        processed += 1

    files = sorted(TRACKS.glob("*.jsonl"))
    log(f"done: {len(state['done'])} videos, {len(files)} match files, "
        f"{free_gb():.1f} GB free")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
