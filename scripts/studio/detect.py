"""Run the trained unit detector alongside the recording, in its own thread.

Detection is decoupled from display on purpose.  The UI repaints at 60fps
because that is what makes gameplay look right on video; the detector runs at
~12fps because that is all a 640px YOLO pass costs on a card that is also busy
training.  Coupling them would drag the mirror down to the detector's rate,
which is the one thing this whole exercise was meant to avoid.

So the worker keeps a single "latest frame" slot that the UI overwrites without
waiting, and publishes a tuple of boxes the UI reads without locking.  Frames
are dropped rather than queued: showing the *current* frame with boxes 80ms old
looks live, whereas a backlog would show correct boxes over stale gameplay.

Boxes are published in normalised 0..1 coordinates so the renderer can place
them on a panel of any size without knowing the capture resolution.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "tmp" / "yolo" / "runs"


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    label: str
    confidence: float
    class_id: int


def resolve_weights(explicit: Optional[Path] = None) -> Optional[Path]:
    """Pick the newest usable checkpoint across every training run.

    `best.pt` is rewritten each time validation improves, so it is readable
    mid-training - which is how the detector can be demoed before the 150-epoch
    run finishes.  Globbing rather than naming one run means renaming or adding
    a run (`cr_detector_s`, `cr_detector_n`, ...) does not silently leave the
    studio pointed at a stale checkpoint.
    """
    if explicit:
        return explicit if explicit.exists() else None
    candidates = list(RUNS.glob("*/weights/best.pt")) + list(RUNS.glob("*/weights/last.pt"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


class DetectorWorker:
    def __init__(self, weights: Optional[Path] = None, rate: float = 12.0,
                 confidence: float = 0.35, imgsz: int = 640,
                 max_boxes: int = 40, device: str = "0"):
        self.weights = resolve_weights(weights)
        self.interval = 1.0 / max(rate, 0.5)
        self.confidence = confidence
        self.imgsz = imgsz
        self.max_boxes = max_boxes
        self.device = device

        self.boxes: Tuple[Box, ...] = ()
        self.status = "off"
        self.inference_ms = 0.0
        self.detections = 0
        self.model_name = self.weights.parent.parent.name if self.weights else "-"
        self.epoch_hint = ""

        self._frame: Optional[np.ndarray] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------- lifecycle

    def start(self) -> bool:
        if self.weights is None:
            self.status = "no weights yet"
            return False
        self.status = "loading"
        self._thread = threading.Thread(target=self._run, name="detector", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()

    def submit(self, frame: np.ndarray) -> None:
        """Offer a frame; overwrites any frame not yet consumed."""
        if self._thread is None:
            return
        with self._lock:
            self._frame = frame

    def _take(self) -> Optional[np.ndarray]:
        with self._lock:
            frame, self._frame = self._frame, None
        return frame

    # ---------------------------------------------------------------- worker

    def _run(self) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:                       # pragma: no cover
            self.status = f"ultralytics import failed: {type(exc).__name__}"
            return
        try:
            model = YOLO(str(self.weights))
            names = model.names
        except Exception as exc:
            self.status = f"load failed: {type(exc).__name__}"
            return

        self.status = "live"
        while not self._stop.is_set():
            started = time.perf_counter()
            frame = self._take()
            if frame is None:
                time.sleep(0.005)
                continue
            try:
                # BGRA from the Win32 DIB; drop alpha and hand over BGR, which
                # is what ultralytics expects from a raw array.
                result = model.predict(
                    frame[:, :, :3], imgsz=self.imgsz, conf=self.confidence,
                    device=self.device, verbose=False, max_det=self.max_boxes,
                )[0]
            except Exception as exc:
                self.status = f"predict failed: {type(exc).__name__}"
                time.sleep(0.5)
                continue

            height, width = frame.shape[:2]
            found: List[Box] = []
            data = result.boxes
            if data is not None and len(data):
                xyxy = data.xyxy.cpu().numpy()
                confidences = data.conf.cpu().numpy()
                classes = data.cls.cpu().numpy().astype(int)
                for (x1, y1, x2, y2), conf, cls in zip(xyxy, confidences, classes):
                    found.append(Box(
                        float(x1) / width, float(y1) / height,
                        float(x2) / width, float(y2) / height,
                        str(names.get(int(cls), f"class_{cls}")),
                        float(conf), int(cls),
                    ))
            self.boxes = tuple(found)
            self.detections = len(found)
            self.inference_ms = (time.perf_counter() - started) * 1000.0

            remaining = self.interval - (time.perf_counter() - started)
            if remaining > 0:
                time.sleep(remaining)
        self.status = "stopped"


def palette_for(class_id: int) -> Tuple[int, int, int]:
    """Stable per-class colour.

    A hash rather than a fixed table because the class list is 201 long and only
    a handful appear in a Hog 2.6 mirror; what matters on video is that the same
    unit keeps the same colour from frame to frame.
    """
    golden = 0.61803398875
    hue = (class_id * golden) % 1.0
    return _hsv(hue, 0.72, 1.0)


def _hsv(h: float, s: float, v: float) -> Tuple[int, int, int]:
    i = int(h * 6.0)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = [(v, t, p), (q, v, p), (p, v, t),
               (p, q, v), (t, p, v), (v, p, q)][i % 6]
    return int(r * 255), int(g * 255), int(b * 255)


def summarise(boxes: Sequence[Box], limit: int = 6) -> List[Tuple[str, int]]:
    """Most common labels on screen, for the rail's detection list."""
    counts: dict[str, int] = {}
    for box in boxes:
        counts[box.label] = counts.get(box.label, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
