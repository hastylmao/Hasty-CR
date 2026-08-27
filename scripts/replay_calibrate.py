"""Extract replay mechanics observations and compare event timelines.

Examples:
    python scripts/replay_calibrate.py extract input.jsonl --events events.json
    python scripts/replay_calibrate.py compare observed.json simulated.json

The input is normalized JSON/JSONL, so a future authorized replay or video
collector can be added without changing calibration code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.replay_calibration import (  # noqa: E402
    EventTolerance,
    compare_events,
    extract_events,
    read_frames,
)


def _read_events(path: Path) -> list:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.get("events", payload) if isinstance(payload, dict) else payload
    if not isinstance(values, list):
        raise ValueError(f"{path} must contain an event list")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("observations", type=Path)
    extract_parser.add_argument("--events", type=Path, required=True)
    extract_parser.add_argument("--movement-threshold", type=float, default=0.08)
    extract_parser.add_argument("--damage-threshold", type=float, default=0.01)

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("observed", type=Path)
    compare_parser.add_argument("simulated", type=Path)
    compare_parser.add_argument("--time-ms", type=int, default=250)
    compare_parser.add_argument("--position", type=float, default=0.75)
    compare_parser.add_argument("--value", type=float, default=0.15)

    args = parser.parse_args()
    if args.command == "extract":
        events = extract_events(
            read_frames(args.observations),
            movement_threshold=args.movement_threshold,
            damage_threshold=args.damage_threshold)
        args.events.parent.mkdir(parents=True, exist_ok=True)
        args.events.write_text(json.dumps({
            "schema_version": 1,
            "events": [event.to_dict() for event in events],
        }, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(events)} events to {args.events}")
        return 0

    from tools.replay_calibration import MechanicsEvent
    observed = [MechanicsEvent(**value) for value in _read_events(args.observed)]
    simulated = [MechanicsEvent(**value) for value in _read_events(args.simulated)]
    report = compare_events(
        observed, simulated,
        EventTolerance(args.time_ms, args.position, args.value))
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
