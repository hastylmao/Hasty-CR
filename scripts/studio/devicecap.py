"""Capture the emulator at the device's own resolution, not the screen's.

The window mirror is bounded by the monitor. MuMu renders Android at 1080x1920
but the desktop only has 1080 rows to show it in, so the visible surface is
560x996 and the studio then upscales that into a 1080x1920 canvas. Everything
downstream inherits the blur - it is a 1.3x upscale of a source that was
already half the target's height - and no encoder setting recovers detail that
was never captured.

`screenrecord` encodes on the device, before any of that. It hands back true
1080x1920 H.264, which PyAV decodes here into the same BGRA frames the window
grabber produces. Same interface, four times the pixels.

The costs, stated plainly:

* Latency. The device buffers before emitting, so the mirror runs roughly a
  second behind the game. Irrelevant for recording, wrong for anything making
  decisions - the bot keeps using its own capture path regardless.
* `screenrecord` stops itself at 180 seconds. The reader restarts it, which
  drops a frame or two at the seam.
* It shares the ADB channel with the bot.

So this is opt-in, for when the run is going into a video.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import Optional

import numpy as np

# screenrecord's own hard limit. Restart before it, not after, so the gap
# lands where we choose rather than mid-frame.
SEGMENT_SECONDS = 170


class DeviceStream:
    """Native-resolution frames, decoded from an on-device H.264 stream."""

    def __init__(self, adb: str, serial: str, bitrate: str = "24M",
                 size: Optional[str] = None):
        self.adb = str(adb)
        self.serial = serial
        self.bitrate = bitrate
        self.size = size
        self.error = ""
        self.frames = 0
        self.width = 0
        self.height = 0
        self._latest: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        try:
            import av                                # noqa: F401
            self._ok = True
        except Exception as exc:                     # pragma: no cover
            self._ok = False
            self.error = f"PyAV unavailable: {type(exc).__name__}: {exc}"

    @property
    def ready(self) -> bool:
        return self._ok

    @property
    def last_error(self) -> str:
        return self.error

    def start(self) -> bool:
        if not self._ok or self._thread is not None:
            return self._ok
        self._thread = threading.Thread(target=self._run, name="device-stream",
                                        daemon=True)
        self._thread.start()
        return True

    def grab(self) -> Optional[np.ndarray]:
        """The newest decoded frame as BGRA, or None before the first arrives."""
        if not self._ok:
            return None
        if self._thread is None:
            self.start()
        with self._lock:
            return self._latest

    def close(self) -> None:
        self._stop.set()
        self._kill()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    # ---------------------------------------------------------------- inside

    def _command(self) -> list[str]:
        cmd = [self.adb, "-s", self.serial, "exec-out", "screenrecord",
               "--output-format=h264", f"--bit-rate={self.bitrate}",
               f"--time-limit={SEGMENT_SECONDS}"]
        if self.size:
            cmd.append(f"--size={self.size}")
        cmd.append("-")
        return cmd

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass

    def _run(self) -> None:
        import av

        while not self._stop.is_set():
            try:
                self._proc = subprocess.Popen(
                    self._command(), stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0)
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                time.sleep(1.0)
                continue

            try:
                # PyAV reads the pipe directly; the stream is raw Annex-B, so
                # the demuxer needs to be told rather than guess from an
                # extension it does not have.
                container = av.open(self._proc.stdout, format="h264", mode="r")
                for frame in container.decode(video=0):
                    if self._stop.is_set():
                        break
                    array = frame.to_ndarray(format="bgra")
                    self.height, self.width = array.shape[:2]
                    with self._lock:
                        self._latest = array
                    self.frames += 1
            except Exception as exc:
                # A restart at the segment boundary lands here as a decode or
                # EOF error. That is expected once every SEGMENT_SECONDS and is
                # not worth reporting as a fault; anything else is.
                self.error = f"{type(exc).__name__}: {exc}"
            finally:
                self._kill()

            if not self._stop.is_set():
                time.sleep(0.2)          # brief gap, then a fresh segment
