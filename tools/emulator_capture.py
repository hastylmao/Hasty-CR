"""Durable multi-emulator screenshot collection for mechanics analysis.

Each worker owns one ADB serial and writes an append-only JSONL index alongside
PNG frames. The collector is intentionally observation-only: it never taps,
queues, dismisses dialogs, or changes emulator state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import threading
import time
from typing import Any, Callable

from PIL import Image


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CaptureConfig:
    adb: Path
    serial: str
    output: Path
    interval_seconds: float = 0.5
    deduplicate: bool = True
    max_gib: float = 0.0
    jpeg_quality: int = 90


@dataclass
class CaptureStats:
    serial: str
    started_at_utc: str
    frames: int = 0
    bytes_written: int = 0
    capture_errors: int = 0
    duplicate_frames: int = 0
    last_error: str = ""
    stopped_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            **self.__dict__,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _write_jsonl(handle, value: dict[str, Any]) -> None:
    handle.write(json.dumps(value, separators=(",", ":")) + "\n")
    handle.flush()


class EmulatorCaptureWorker:
    """Capture one emulator until the shared stop event is set."""

    def __init__(self, config: CaptureConfig, stop: threading.Event,
                 capture_factory: Callable[[Path, str], Any] | None = None):
        if config.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if config.max_gib < 0:
            raise ValueError("max_gib cannot be negative")
        self.config = config
        self.stop = stop
        self.capture_factory = capture_factory
        self.stats = CaptureStats(config.serial, utc_now())
        self.thread = threading.Thread(target=self.run, name=f"capture-{config.serial}",
                                       daemon=True)

    def start(self) -> None:
        self.thread.start()

    def join(self) -> None:
        self.thread.join()

    def _capture(self):
        if self.capture_factory is not None:
            return self.capture_factory(self.config.adb, self.config.serial)
        from scripts.screencap_fast import FastScreenCap
        return FastScreenCap(self.config.adb, self.config.serial)

    def run(self) -> None:
        device_dir = self.config.output / self.config.serial.replace(":", "_")
        frames_dir = device_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        index_path = device_dir / "frames.jsonl"
        capturer = None
        previous_digest: str | None = None
        started_monotonic = time.monotonic()
        next_capture = started_monotonic
        try:
            capturer = self._capture()
            with index_path.open("a", encoding="utf-8") as index:
                while not self.stop.is_set():
                    now = time.monotonic()
                    if now < next_capture:
                        self.stop.wait(next_capture - now)
                        continue
                    next_capture = max(next_capture + self.config.interval_seconds,
                                       time.monotonic())
                    capture_started = time.monotonic()
                    try:
                        image = capturer.capture_frame()
                        if image is None:
                            raise RuntimeError("ADB capture returned no frame")
                        image = image.convert("RGB")
                        pixels = image.tobytes()
                        import hashlib
                        digest = hashlib.sha256(pixels).hexdigest()
                        if self.config.deduplicate and digest == previous_digest:
                            self.stats.duplicate_frames += 1
                            continue
                        previous_digest = digest
                        timestamp = utc_now()
                        frame_name = f"{self.stats.frames:09d}_{int(time.time() * 1000)}.png"
                        frame_path = frames_dir / frame_name
                        image.save(frame_path, format="PNG", optimize=False)
                        size = frame_path.stat().st_size
                        self.stats.frames += 1
                        self.stats.bytes_written += size
                        _write_jsonl(index, {
                            "schema_version": SCHEMA_VERSION,
                            "serial": self.config.serial,
                            "captured_at_utc": timestamp,
                            "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
                            "frame_index": self.stats.frames - 1,
                            "path": str(frame_path.relative_to(self.config.output)),
                            "width": image.width,
                            "height": image.height,
                            "sha256_pixels": digest,
                            "bytes": size,
                            "capture_ms": round((time.monotonic() - capture_started) * 1000, 3),
                            "source": "adb_screencap",
                        })
                        if self.config.max_gib and self.stats.bytes_written >= self.config.max_gib * (1024 ** 3):
                            self.stats.last_error = "disk budget reached"
                            self.stop.set()
                            break
                    except Exception as exc:
                        self.stats.capture_errors += 1
                        self.stats.last_error = f"{type(exc).__name__}: {exc}"
                        _write_jsonl(index, {
                            "schema_version": SCHEMA_VERSION,
                            "serial": self.config.serial,
                            "captured_at_utc": utc_now(),
                            "error": self.stats.last_error,
                        })
                        self.stop.wait(min(self.config.interval_seconds, 5.0))
        finally:
            self.stats.stopped_at_utc = utc_now()
            _atomic_json(device_dir / "stats.json", self.stats.to_dict())


class MultiEmulatorCapture:
    """Run independent capture workers for several emulator serials."""

    def __init__(self, configs: list[CaptureConfig], duration_seconds: float = 0):
        if not configs:
            raise ValueError("at least one emulator configuration is required")
        if duration_seconds < 0:
            raise ValueError("duration_seconds cannot be negative")
        self.configs = configs
        self.duration_seconds = duration_seconds
        self.stop = threading.Event()
        self.workers = [EmulatorCaptureWorker(config, self.stop)
                        for config in configs]
        self._old_handlers: dict[int, Any] = {}

    def _request_stop(self, *_args) -> None:
        self.stop.set()

    def run(self) -> list[CaptureStats]:
        output = self.configs[0].output
        output.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "started_at_utc": utc_now(),
            "duration_seconds": self.duration_seconds,
            "devices": [config.serial for config in self.configs],
            "interval_seconds": {config.serial: config.interval_seconds for config in self.configs},
            "deduplicate": {config.serial: config.deduplicate for config in self.configs},
            "status": "running",
        }
        _atomic_json(output / "session.json", manifest)
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                self._old_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, self._request_stop)
            except (OSError, ValueError):
                pass
        try:
            for worker in self.workers:
                worker.start()
            if self.duration_seconds:
                self.stop.wait(self.duration_seconds)
            else:
                while not self.stop.wait(1.0):
                    pass
        finally:
            self.stop.set()
            for worker in self.workers:
                worker.join()
            manifest.update({
                "stopped_at_utc": utc_now(),
                "status": "stopped",
                "stats": [worker.stats.to_dict() for worker in self.workers],
            })
            _atomic_json(output / "session.json", manifest)
            for signum, handler in self._old_handlers.items():
                try:
                    signal.signal(signum, handler)
                except (OSError, ValueError):
                    pass
        return [worker.stats for worker in self.workers]
