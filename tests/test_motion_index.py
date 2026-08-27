import sys
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from index_recording_motion import MotionSample, candidate_events, group_candidate_frames  # noqa: E402
from verify_live_probe_assets import sha256  # noqa: E402


def test_motion_candidates_merge_only_nearby_source_frames():
    assert group_candidate_frames([5, 8, 9, 30], max_gap_frames=3) == [
        (5, 9), (30, 30)]


def test_motion_candidates_are_unreviewed_and_frame_padded():
    samples = [
        MotionSample(5, 1.0), MotionSample(10, 1.0),
        MotionSample(20, 1.0), MotionSample(30, 50.0),
        MotionSample(40, 1.0),
    ]
    events = candidate_events(samples, fps=30.0, max_events=5, last_frame=45)
    assert len(events) == 1
    assert events[0]["classification"] == "unreviewed_motion_candidate"
    assert events[0]["peak_frame"] == 30
    assert events[0]["start_frame"] == 0
    assert events[0]["end_frame"] == 45


def test_motion_index_hash_helper_identifies_source_bytes(tmp_path):
    video = tmp_path / "recording.mp4"
    video.write_bytes(b"source bytes")
    assert sha256(video) == "4d4823794cbed3c4ee0bbc684c8f66e1dfd5afa6f078d494ce254ec5a4671753"
