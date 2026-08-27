"""Inventory gameplay recordings without treating them as calibration proof.

The simulator needs controlled, frame-linked experiments.  Ordinary gameplay
captures are still useful context, but they commonly contain overlapping cards
and unknown deployment positions.  This tool records their immutable metadata
and deliberately imports them as ``contextual_only`` rather than silently
turning them into accepted collision evidence.

    python scripts/ingest_live_recordings.py \
        "C:\\Users\\you\\Documents\\MuMuSharedFolder\\VideoRecords\\recordings"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "validation" / "live_probes.json"
REQUIRED_CATEGORIES = (
    "map_anchors", "troop_contact", "building_contact",
    "projectile_timing", "spell_timing",
)

PENDING_PROBES = {
    "map_anchors": {
        "criteria": "same-frame tower/bridge/river anchors with a known arena crop",
    },
    "troop_contact": {
        "criteria": "isolated two-unit King-Tower and open-lane contact at 60 fps",
    },
    "building_contact": {
        "criteria": "isolated troop-to-building route/contact at 60 fps",
    },
    "projectile_timing": {
        "criteria": "known launch frame, target path, hit/miss frame and card levels",
    },
    "spell_timing": {
        "criteria": "known cast frame, aim point, impact frames and affected units",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fraction(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    return float(Fraction(value))


def _probe_video(path: Path, ffprobe: str) -> dict[str, Any]:
    command = [
        ffprobe, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,avg_frame_rate,nb_frames,duration",
        "-of", "json", str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise ValueError(f"no video stream: {path}")
    stream = streams[0]
    return {
        "duration_seconds": round(float(stream.get("duration") or 0), 6),
        "fps": _fraction(stream.get("avg_frame_rate")),
        "frames": int(stream["nb_frames"]) if str(stream.get("nb_frames", "")).isdigit() else None,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


def build_manifest(recordings: Path, ffprobe: str) -> dict[str, Any]:
    files = sorted(recordings.rglob("*.mp4"), key=lambda path: path.name.lower())
    captures = []
    for path in files:
        metadata = _probe_video(path, ffprobe)
        captures.append({
            "id": path.stem,
            "source_path": str(path),
            "sha256": _sha256(path),
            "classification": "contextual_only",
            "assessment": (
                "ordinary gameplay; not accepted for calibration until a "
                "reviewer adds frame ranges, card levels, deployment points "
                "and an isolated observation"),
            **metadata,
        })
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed": [],
        "captures": captures,
        "probes": {
            category: {
                "status": "pending",
                "accepted_evidence": [],
                **details,
            }
            for category, details in PENDING_PROBES.items()
        },
        "notes": [
            "A capture being catalogued is not an accepted live measurement.",
            "Only a controlled clip with recorded frame ranges may be promoted to accepted_evidence.",
        ],
    }


def merge_manifest(existing: dict[str, Any], discovered: dict[str, Any]) -> dict[str, Any]:
    """Refresh capture metadata without discarding reviewed probe evidence.

    A controlled capture's classification is a human review decision.  It may
    be retained only when the bytes are identical; if a recording was replaced
    or edited, the new hash deliberately returns it to ``contextual_only`` and
    any accepted evidence pointing at it will fail the readiness gate until it
    is reviewed again.
    """
    old_captures = {
        item.get("id"): item for item in existing.get("captures", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    captures = []
    discovered_ids = set()
    for capture in discovered["captures"]:
        capture_id = capture["id"]
        discovered_ids.add(capture_id)
        old = old_captures.get(capture_id)
        if old and old.get("sha256") == capture["sha256"]:
            for field in ("classification", "assessment"):
                if field in old:
                    capture[field] = old[field]
        captures.append(capture)

    # Retain a historical record that has disappeared from the input folder:
    # accepted evidence must remain auditable rather than silently losing its
    # capture reference. It cannot become fresh evidence without re-recording.
    captures.extend(old_captures[capture_id] for capture_id in sorted(
        set(old_captures) - discovered_ids))
    merged = dict(discovered)
    merged["captures"] = captures
    for field in ("completed", "probes", "notes"):
        if field in existing:
            merged[field] = existing[field]
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recordings", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe"))
    args = parser.parse_args()
    if not args.recordings.is_dir():
        parser.error(f"recordings directory does not exist: {args.recordings}")
    if not args.ffprobe:
        parser.error("ffprobe is required; install FFmpeg or pass --ffprobe PATH")

    discovered = build_manifest(args.recordings, args.ffprobe)
    if args.output.exists():
        try:
            existing = json.loads(args.output.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"existing manifest is unreadable: {exc}")
        manifest = merge_manifest(existing, discovered)
    else:
        manifest = discovered
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"catalogued {len(discovered['captures'])} recordings; preserved probe review: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
