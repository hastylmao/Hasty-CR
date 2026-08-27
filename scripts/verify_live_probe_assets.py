"""Verify that recordings named by the live-probe manifest are unchanged.

This does not accept a probe or infer any game behaviour. It only checks the
chain of custody before a reviewer relies on a source-frame observation.

    python scripts/verify_live_probe_assets.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "validation" / "live_probes.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_captures(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """Return capture-id keyed errors; an empty result proves byte integrity."""
    errors: dict[str, list[str]] = {}
    for capture in manifest.get("captures", []):
        if not isinstance(capture, dict):
            continue
        capture_id = str(capture.get("id", "<unnamed>"))
        item_errors: list[str] = []
        source = capture.get("source_path")
        expected = capture.get("sha256")
        if not isinstance(source, str) or not source:
            item_errors.append("missing source_path")
        elif not Path(source).is_file():
            item_errors.append("source video is missing")
        if not isinstance(expected, str) or len(expected) != 64:
            item_errors.append("missing or malformed SHA-256")
        elif isinstance(source, str) and Path(source).is_file():
            actual = sha256(Path(source))
            if actual != expected:
                item_errors.append(
                    f"SHA-256 mismatch (manifest {expected}, actual {actual})")
        if item_errors:
            errors[capture_id] = item_errors
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"cannot read manifest: {exc}")
    errors = verify_captures(manifest)
    if errors:
        for capture_id, item_errors in sorted(errors.items()):
            print(f"{capture_id}: " + "; ".join(item_errors))
        return 2
    print(f"verified {len(manifest.get('captures', []))} recording hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
