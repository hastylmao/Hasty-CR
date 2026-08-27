import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from extract_probe_frames import (frame_numbers, select_filter,
                                  validate_source_range)  # noqa: E402
from ingest_live_recordings import merge_manifest  # noqa: E402
from verify_live_probe_assets import verify_captures  # noqa: E402


def test_probe_frame_ranges_are_inclusive_and_stable():
    assert frame_numbers(30, 36, 2) == [30, 32, 34, 36]
    assert select_filter(30, 36, 2) == (
        "select='between(n\\,30\\,36)*not(mod(n-30\\,2))'")


def test_probe_frame_ranges_reject_invalid_provenance():
    import pytest

    with pytest.raises(ValueError):
        frame_numbers(-1, 3, 1)
    with pytest.raises(ValueError):
        frame_numbers(4, 3, 1)
    with pytest.raises(ValueError):
        frame_numbers(1, 2, 0)
    with pytest.raises(ValueError, match="outside source video"):
        validate_source_range(10, 1, 10)
    validate_source_range(None, 500, 600)


def test_catalog_refresh_preserves_review_only_for_identical_capture_bytes():
    discovered = {
        "captures": [{"id": "clip-a", "sha256": "new", "classification": "contextual_only"}],
        "completed": [], "probes": {}, "notes": [],
    }
    existing = {
        "captures": [{"id": "clip-a", "sha256": "new", "classification": "controlled",
                      "assessment": "reviewed"}],
        "completed": ["map_anchors"], "probes": {"map_anchors": {"status": "accepted"}},
        "notes": ["keep this"],
    }
    merged = merge_manifest(existing, discovered)
    assert merged["captures"][0]["classification"] == "controlled"
    assert merged["captures"][0]["assessment"] == "reviewed"
    assert merged["completed"] == ["map_anchors"]

    changed = merge_manifest(existing, {**discovered, "captures": [{
        "id": "clip-a", "sha256": "changed", "classification": "contextual_only",
    }]})
    assert changed["captures"][0]["classification"] == "contextual_only"


def test_capture_hash_verifier_rejects_replaced_source_video(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"original")
    manifest = {"captures": [{
        "id": "clip", "source_path": str(source),
        "sha256": "0682c5f2076f099c4d0ce0d02ed8c22a7cb6f1b221f6f4bc9a2e3079c1f4d51d",
    }]}
    # Deliberately use the independently computed content hash, not a label.
    from verify_live_probe_assets import sha256
    manifest["captures"][0]["sha256"] = sha256(source)
    assert verify_captures(manifest) == {}

    source.write_bytes(b"edited")
    assert "SHA-256 mismatch" in verify_captures(manifest)["clip"][0]
