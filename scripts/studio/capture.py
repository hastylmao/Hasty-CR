"""Grab the emulator's render surface at video frame rates.

ADB is not an option here.  A `screencap` at 540x960 costs ~117ms, so the bot's
own capture path tops out near 8fps - fine for deciding, useless for recording.

Two Win32 routes were measured against the live MuMu window:

    desktop-bitblt     4.21 ms/frame  ~237 fps  mean=0.0   (black)
    printwindow        4.23 ms/frame  ~236 fps  mean=87.2  (real pixels)

BitBlt from the desktop DC copies whatever is composited *on screen*, so it
returns black whenever the emulator is behind another window.  `PrintWindow`
with `PW_RENDERFULLCONTENT` asks the window to redraw into our bitmap instead,
which keeps working when the desktop copy would come back black.

It is not unconditional, and the difference matters when recording.  For a
*fully occluded* window DWM can return the last frame it presented and keep
returning it: measured live, 40 identical grabs over six seconds with zero
failures while the bot was still playing.  So the call never fails, it just
stops telling the truth.  `stale_seconds` measures that, and the studio shows
it rather than silently recording a frozen mirror.  Keep the emulator window
unobscured while recording.

The surface we want is not the emulator's top-level window - that includes the
title bar and MuMu's side toolbar.  MuMu renders Android into a child window of
class `nemuwin`, which on this machine is exactly 560x996: a clean 9:16 with no
letterboxing.  Targeting the child means no cropping guesswork.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import threading
import os
import time
from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
PW_RENDERFULLCONTENT = 2

# Child-window classes that hold the Android surface, by emulator.  MuMu is the
# one in use; the others are here because they cost nothing and save an hour if
# the emulator ever changes again.
SURFACE_CLASSES = ("nemuwin", "subWin", "BlueStacksApp", "AndroidSurface")

# Which MuMu instance this project drives. Pinned because more than one
# emulator runs on this machine and the other one is a Clash of Clans bot that
# must never be touched. Override with HASTYCR_INSTANCE, or --instance.
DEFAULT_INSTANCE = os.environ.get("HASTYCR_INSTANCE", "Android Device-1-2")

_ENUM_PROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long), ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _children(hwnd: int) -> list[int]:
    found: list[int] = []
    user32.EnumChildWindows(hwnd, _ENUM_PROC(lambda h, _: (found.append(h), True)[1]), 0)
    return found


def _top_level() -> list[int]:
    found: list[int] = []
    user32.EnumWindows(_ENUM_PROC(lambda h, _: (found.append(h), True)[1]), 0)
    return found


@dataclass(frozen=True)
class Surface:
    hwnd: int
    width: int
    height: int
    owner: str

    def __str__(self) -> str:
        return f"hwnd={self.hwnd} {self.width}x{self.height} ({self.owner})"


def find_surfaces() -> Iterator[Surface]:
    """Yield every plausible Android render surface, largest first."""
    candidates: list[Surface] = []
    for top in _top_level():
        if not user32.IsWindowVisible(top):
            continue
        owner = _window_text(top) or _class_name(top)
        for child in _children(top):
            if _class_name(child) not in SURFACE_CLASSES:
                continue
            if not user32.IsWindowVisible(child):
                continue
            _, _, width, height = _rect(child)
            # Below this the "surface" is a thumbnail in MuMu's instance
            # manager, not a running device.
            if width < 200 or height < 200:
                continue
            candidates.append(Surface(child, width, height, owner))
    yield from sorted(candidates, key=lambda s: s.width * s.height, reverse=True)


def find_surface(hwnd: Optional[int] = None,
                 instance: Optional[str] = None) -> Surface:
    """The window to mirror, chosen by identity rather than by size.

    `find_surfaces` sorts largest first, and taking the first one was wrong
    the moment a second emulator existed. With a Clash Royale instance at
    560x996 beside a Clash of Clans instance at 1770x996, "largest" is the
    Clash of Clans one every time - so the studio mirrored the wrong device,
    and the bot drove it, which is a good way to lose a village.

    Size is not identity. `instance` names the MuMu instance to attach to and
    is matched against the owning window's title, exactly first so that
    "Android Device" cannot swallow "Android Device-1-2", then as a prefix.
    """
    if hwnd:
        _, _, width, height = _rect(hwnd)
        if width <= 0 or height <= 0:
            raise RuntimeError(f"hwnd {hwnd} has no area; is the emulator running?")
        return Surface(hwnd, width, height, _window_text(hwnd) or "explicit")

    surfaces = list(find_surfaces())
    if not surfaces:
        raise RuntimeError(
            "no emulator surface found - looked for child windows of class "
            + "/".join(SURFACE_CLASSES) + ". Is MuMu running with a device started?"
        )

    wanted = instance if instance is not None else DEFAULT_INSTANCE
    if wanted:
        for surface in surfaces:
            if surface.owner.strip() == wanted:
                return surface
        for surface in surfaces:
            if surface.owner.strip().startswith(wanted):
                return surface
        raise RuntimeError(
            f"no emulator surface belongs to instance {wanted!r}. Running: "
            + ", ".join(repr(s.owner) for s in surfaces)
            + ". Start it, or pass --instance with one of those names "
              "(or --hwnd to target a window directly)."
        )
    return surfaces[0]


class SurfaceGrabber:
    """Repeatedly copy one window's pixels into a reusable DIB.

    The bitmap and its device context are allocated once and reused, because
    creating them per frame is most of the cost.  `grab()` returns a numpy view
    onto that one buffer - it is overwritten by the next call, so anything that
    needs to keep a frame must copy it.
    """

    def __init__(self, surface: Surface):
        self.surface = surface
        self._dc = None
        self._bitmap = None
        self._buffer: Optional[ctypes.Array] = None
        self._size = (0, 0)
        self.failures = 0
        self._checksum = None
        self._changed_at = time.monotonic()
        self._allocate(surface.width, surface.height)

    def _release(self) -> None:
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
        if self._dc:
            gdi32.DeleteDC(self._dc)
        self._dc = self._bitmap = self._buffer = None

    def _allocate(self, width: int, height: int) -> None:
        self._release()
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = width
        # Negative height gives top-down rows, matching how numpy and Qt both
        # want to read the buffer.  Positive would hand back a flipped image.
        info.bmiHeader.biHeight = -height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0

        bits = ctypes.c_void_p()
        self._dc = gdi32.CreateCompatibleDC(None)
        self._bitmap = gdi32.CreateDIBSection(
            self._dc, ctypes.byref(info), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
        if not self._bitmap or not bits.value:
            raise RuntimeError("CreateDIBSection failed")
        gdi32.SelectObject(self._dc, self._bitmap)
        self._buffer = (ctypes.c_ubyte * (width * height * 4)).from_address(bits.value)
        self._size = (width, height)

    @property
    def size(self) -> tuple[int, int]:
        return self._size

    def alive(self) -> bool:
        return bool(user32.IsWindow(self.surface.hwnd))

    def grab(self) -> Optional[np.ndarray]:
        """Return the surface as a BGRA array, or None if the copy failed."""
        if not self.alive():
            return None
        _, _, width, height = _rect(self.surface.hwnd)
        if width <= 0 or height <= 0:
            return None
        if (width, height) != self._size:
            # The user resized the emulator window mid-recording.
            self._allocate(width, height)
        if not user32.PrintWindow(self.surface.hwnd, self._dc, PW_RENDERFULLCONTENT):
            self.failures += 1
            return None
        frame = np.frombuffer(self._buffer, dtype=np.uint8).reshape(height, width, 4)

        # PrintWindow always succeeds, but for a fully occluded window DWM can
        # hand back the last frame it presented - forever. Observed live: 40
        # identical grabs over six seconds, zero failures, while the bot was
        # plainly still playing. A frozen mirror recorded silently is worse than
        # an error, so staleness is measured rather than assumed away.
        # Sampling every 997th byte is enough to notice a changed frame and
        # costs far less than hashing two megabytes at 60fps.
        checksum = int(frame.reshape(-1)[::997].sum())
        if checksum != self._checksum:
            self._checksum = checksum
            self._changed_at = time.monotonic()
        return frame

    @property
    def stale_seconds(self) -> float:
        """How long the surface has been handing back an unchanged frame."""
        return time.monotonic() - self._changed_at

    def close(self) -> None:
        self._release()


class AdbGrabber:
    """Fallback frame source that reads the framebuffer instead of the window.

    MuMu's renderer can stall while the emulator keeps running perfectly: the
    bot goes on playing, because it reads the framebuffer over ADB, but the
    window presents one frame forever.  Observed live at 180 back-to-back grabs
    returning a single distinct frame, with the window in the foreground.

    ADB is far slower - a `screencap` costs ~117ms, which is why the mirror does
    not use it by default - and it shares the channel the bot needs, so this is
    rate-limited and only used when the window has gone stale.  A 6fps mirror is
    poor video; it is still enormously better than a frozen one.
    """

    def __init__(self, adb: str, serial: str, rate: float = 6.0):
        self.interval = 1.0 / max(0.5, rate)
        self.frames = 0
        self.error = ""
        self._cached: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        try:
            import sys
            from pathlib import Path as _Path
            root = _Path(__file__).resolve().parents[2]
            if str(root / "scripts") not in sys.path:
                sys.path.insert(0, str(root / "scripts"))
            from screencap_fast import FastScreenCap
            self._cap = FastScreenCap(adb, serial)
        except Exception as exc:
            self._cap = None
            self.error = f"{type(exc).__name__}: {exc}"

    @property
    def ready(self) -> bool:
        return self._cap is not None

    def grab(self) -> Optional[np.ndarray]:
        """Return the newest ADB frame without ever blocking the caller.

        A `screencap` costs ~117ms, and calling it from the UI thread dragged the
        whole studio - recorder included - from 60fps to 13. The capture runs on
        its own thread and this hands back the latest frame it produced.
        """
        if self._cap is None:
            return None
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="adb-mirror",
                                            daemon=True)
            self._thread.start()
        with self._lock:
            return self._cached

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                image = self._cap.capture_frame()
            except Exception as exc:
                self.error = f"{type(exc).__name__}: {exc}"
                image = None
            if image is not None:
                rgb = np.asarray(image.convert("RGB"))
                alpha = np.full(rgb.shape[:2], 255, np.uint8)
                frame = np.dstack([rgb[:, :, ::-1], alpha]).copy()
                with self._lock:
                    self._cached = frame
                self.frames += 1
            remaining = self.interval - (time.monotonic() - started)
            if remaining > 0:
                self._stop.wait(remaining)

    def close(self) -> None:
        self._stop.set()
