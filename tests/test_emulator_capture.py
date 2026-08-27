from __future__ import annotations

import json
from pathlib import Path
import threading
import time

from PIL import Image

from tools.emulator_capture import (
    CaptureConfig,
    EmulatorCaptureWorker,
    MultiEmulatorCapture,
)


class FakeCapture:
    def __init__(self, _adb, serial):
        self.serial = serial
        self.calls = 0

    def capture_frame(self):
        self.calls += 1
        color = 40 + (self.calls % 2) * 20
        return Image.new("RGB", (8, 12), (color, 10, 5))


def test_worker_writes_frames_index_and_stats(tmp_path: Path):
    stop = threading.Event()
    worker = EmulatorCaptureWorker(
        CaptureConfig(Path("adb"), "emu:1", tmp_path, interval_seconds=0.001),
        stop,
        capture_factory=FakeCapture,
    )
    worker.start()
    time.sleep(0.02)
    stop.set()
    worker.join()

    device = tmp_path / "emu_1"
    index_lines = (device / "frames.jsonl").read_text().splitlines()
    stats = json.loads((device / "stats.json").read_text())
    assert index_lines
    assert stats["frames"] == worker.stats.frames
    assert stats["frames"] > 0
    assert all((tmp_path / json.loads(line)["path"]).is_file()
               for line in index_lines if "path" in json.loads(line))


def test_worker_deduplicates_identical_frames(tmp_path: Path):
    class SameCapture:
        def __init__(self, _adb, _serial):
            pass

        def capture_frame(self):
            return Image.new("RGB", (4, 4), (1, 2, 3))

    stop = threading.Event()
    worker = EmulatorCaptureWorker(
        CaptureConfig(Path("adb"), "emu", tmp_path, interval_seconds=0.001),
        stop,
        capture_factory=SameCapture,
    )
    worker.start()
    # Wait for the second capture to happen rather than for the clock. A
    # fixed sleep assumes this thread is scheduled many times in 20ms at a
    # 1ms interval, which is true on an idle machine and false on a busy one
    # - under a training run it was scheduled once, captured a single frame,
    # and failed with "assert 0 > 0" on a worker that was behaving perfectly.
    deadline = time.monotonic() + 5.0
    while worker.stats.duplicate_frames == 0 and time.monotonic() < deadline:
        time.sleep(0.005)
    stop.set()
    worker.join()

    assert worker.stats.frames == 1, "an identical frame must not be stored twice"
    assert worker.stats.duplicate_frames > 0, (
        "the worker never captured a second frame within five seconds")


def test_multi_capture_writes_manifest_for_each_serial(tmp_path: Path):
    capture = MultiEmulatorCapture([
        CaptureConfig(Path("adb"), "one", tmp_path, interval_seconds=0.001),
        CaptureConfig(Path("adb"), "two", tmp_path, interval_seconds=0.001),
    ], duration_seconds=0.01)
    capture.workers = [EmulatorCaptureWorker(config, capture.stop, FakeCapture)
                       for config in capture.configs]
    stats = capture.run()

    manifest = json.loads((tmp_path / "session.json").read_text())
    assert manifest["status"] == "stopped"
    assert manifest["devices"] == ["one", "two"]
    assert {item.serial for item in stats} == {"one", "two"}
    assert all(item.frames > 0 for item in stats)
