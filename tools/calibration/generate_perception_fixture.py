"""Generate the small deterministic perception plumbing fixture."""
from __future__ import annotations

import json
from pathlib import Path

from .core import Detection, Provenance, Uncertainty, trace_digest
from .perception import IterableFrameSource, PerceptionTraceBuilder, CallableDetectorAdapter, perception_manifest


def generate(output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    rows = json.loads((output / "perception_detection_rows.json").read_text(encoding="utf-8"))

    def detect(index: int):
        return rows[index]

    source = IterableFrameSource(range(len(rows)), interval_ms=100, source="synthetic-fixture")
    detector = CallableDetectorAdapter(lambda frame: detect(int(frame)))
    trace = PerceptionTraceBuilder(detector).build(source, trace_id="synthetic-perception")
    payload = perception_manifest(trace)
    payload["detector_input_sha256"] = __import__("hashlib").sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    (output / "perception_trace.json").write_text(
        json.dumps(trace.to_dict(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (output / "perception_manifest.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    return payload


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("calibration/fixtures"))
    args = parser.parse_args()
    print(json.dumps(generate(args.output_dir), indent=2))
