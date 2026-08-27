"""Encode the canvas to H.264 in-process, so OBS is not part of the pipeline.

Recording the Qt window with an external capture tool would resample a
1080x1920 canvas through whatever size the window happens to be, which is how
text ends up soft in a Short.  PyAV is already a dependency, so the canvas can
go straight to libx264 at full resolution.

The encoder runs on its own thread and pulls from a single "latest frame" slot
at a fixed cadence, duplicating the previous frame when the UI has not produced
a new one.  That yields genuinely constant-frame-rate output - editors handle
CFR mp4 predictably, whereas a variable-rate file from dropped frames plays back
at the wrong speed in some of them.  If the encoder cannot keep up, wall clock
runs ahead of the stream; `behind_seconds` reports that instead of hiding it.
"""

from __future__ import annotations

import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Optional

import numpy as np


class Recorder:
    def __init__(self, path: Path, size: tuple[int, int], fps: int = 60,
                 crf: int = 20, preset: str = "veryfast"):
        import av                                   # imported late: ~0.4s

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.size = size

        self._container = av.open(str(self.path), mode="w")
        self._stream = self._container.add_stream("libx264", rate=fps)
        self._stream.width, self._stream.height = size
        self._stream.pix_fmt = "yuv420p"
        self._stream.codec_context.time_base = Fraction(1, fps)
        self._stream.options = {
            "crf": str(crf),
            "preset": preset,
            # Portrait web video: keep GOPs short so scrubbing in an editor and
            # thumbnailing on upload both behave.
            "g": str(fps * 2),
            "movflags": "+faststart",
        }

        self._av = av
        self._latest: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self.frames = 0
        self.started = time.perf_counter()
        self._thread = threading.Thread(target=self._run, name="recorder", daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ api

    def submit(self, frame: np.ndarray) -> None:
        """Hand over a BGRA canvas; the encoder copies what it needs."""
        with self._lock:
            self._latest = frame

    @property
    def elapsed(self) -> float:
        return time.perf_counter() - self.started

    @property
    def behind_seconds(self) -> float:
        return max(0.0, self.elapsed - self.frames / self.fps)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self._thread.join(timeout=20)
        try:
            for packet in self._stream.encode():
                self._container.mux(packet)
        finally:
            self._container.close()

    # --------------------------------------------------------------- worker

    def _run(self) -> None:
        interval = 1.0 / self.fps
        next_tick = time.perf_counter()
        previous: Optional[np.ndarray] = None
        while not self._stop.is_set():
            now = time.perf_counter()
            if now < next_tick:
                time.sleep(min(interval, next_tick - now))
                continue
            next_tick += interval
            with self._lock:
                frame = self._latest
            if frame is None:
                frame = previous
            if frame is None:
                continue
            previous = frame
            self._encode(frame)

    def _encode(self, array: np.ndarray) -> None:
        try:
            video = self._av.VideoFrame.from_ndarray(array, format="bgra")
            video.pts = self.frames
            video.time_base = Fraction(1, self.fps)
            for packet in self._stream.encode(video):
                self._container.mux(packet)
            self.frames += 1
        except Exception:
            # A recorder that raises must not take the mirror down with it.
            self._stop.set()
