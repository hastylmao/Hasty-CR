"""List a channel and pull one video at a time.

Deliberately not a bulk downloader. The corpus is about forty-eight hours of
video and this machine has under a hundred gigabytes free, so `pipeline.py`
fetches, measures and deletes in a loop. Nothing here keeps a video around; the
tracks extracted from it are what survive.

Format choice matters more than it looks. These are phone-screen recordings, so
the offered ladder tops out at 888x1920/60 - a hair under native, portrait,
sixty frames a second. That last part is the one that counts: the simulator
advances on a 50ms tick, and 60fps samples at 16.7ms, so a frame boundary can
place an event inside the right tick rather than next to it. A 30fps source
would blur exactly the timings this exists to measure.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

CHANNEL = "https://www.youtube.com/@hunter_cr"

# Best portrait ladder available on this channel, newest first. yt-dlp picks
# the first that exists, so a video published at a lower ceiling still fetches.
FORMAT = "bv*[height<=1920][fps>=50]/bv*[height<=1920]/bv*[height<=1280]/bv*"


@dataclass(frozen=True)
class Video:
    video_id: str
    duration_s: int
    title: str
    kind: str                      # "video" or "stream"

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "yt_dlp", *args],
                          capture_output=True, text=True, timeout=timeout)


def listing(kind: str = "video", limit: int = 30) -> list[Video]:
    """The newest `limit` uploads of `kind`, without downloading anything."""
    tab = "videos" if kind == "video" else "streams"
    out = _run(["--flat-playlist", "--playlist-end", str(limit),
                "--print", "%(id)s|%(duration)s|%(title)s",
                f"{CHANNEL}/{tab}"])
    videos: list[Video] = []
    for line in out.stdout.splitlines():
        parts = line.strip().split("|", 2)
        if len(parts) != 3 or not parts[0]:
            continue
        try:
            duration = int(float(parts[1]))
        except (TypeError, ValueError):
            continue          # a premiere or an ongoing stream has no duration
        videos.append(Video(parts[0], duration, parts[2], kind))
    return videos


def download(video: Video, into: Path, timeout: int = 5400) -> Optional[Path]:
    """Fetch one video. Returns its path, or None if it could not be had.

    Failures are returned rather than raised: across forty-five videos some
    will be members-only, region-locked or withdrawn, and one of those must not
    stop a run that has hours of work behind it.
    """
    into.mkdir(parents=True, exist_ok=True)
    target = into / f"{video.video_id}.mp4"
    if target.exists() and target.stat().st_size > 0:
        return target
    out = _run(["-f", FORMAT, "--no-part", "--no-playlist",
                "--retries", "3", "--fragment-retries", "10",
                "-o", str(into / f"{video.video_id}.%(ext)s"), video.url],
               timeout=timeout)
    if out.returncode != 0:
        return None
    for candidate in sorted(into.glob(f"{video.video_id}.*")):
        if candidate.suffix.lower() in (".mp4", ".webm", ".mkv"):
            return candidate
    return None


def catalogue(path: Path, videos: int = 30, streams: int = 15) -> list[Video]:
    """Build (and cache) the full corpus listing.

    Cached because the listing is the one part of this that touches the network
    for no measurement, and a re-run after a crash should not pay for it twice.
    """
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
        return [Video(**item) for item in raw]
    found = listing("video", videos) + listing("stream", streams)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([v.__dict__ for v in found], indent=2),
                    encoding="utf-8")
    return found


def by_size(videos: list[Video]) -> Iterator[Video]:
    """Shortest first.

    Ordering matters for an unattended run: the thirty edited uploads average
    nine minutes and the streams average nearly three hours, so going shortest
    first means a night that dies early still leaves a usable dataset instead
    of one half-processed ten-hour stream.
    """
    yield from sorted(videos, key=lambda v: v.duration_s)


if __name__ == "__main__":
    corpus = catalogue(Path("data/vod/catalogue.json"))
    total = sum(v.duration_s for v in corpus)
    print(f"{len(corpus)} items, {total / 3600:.1f} hours")
    for v in by_size(corpus)[:5] if isinstance(corpus, list) else []:
        print(f"  {v.duration_s:>6}s  {v.kind:<6} {v.title[:60]}")
