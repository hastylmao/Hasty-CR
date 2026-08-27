from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sim import arena
from tools.calibration.command_replay import (
    Command,
    CommandRecorder,
    MatchReplay,
    ReplayError,
    create_initial_state,
    demo_replay,
    execute_replay,
    first_divergence,
    read_replay,
    state_digest,
    write_replay,
)


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
DECK = ("cannon", "fireball", "hog_rider", "ice_golem",
        "ice_spirit", "musketeer", "skeletons", "the_log")


def _initial(seed: int):
    return create_initial_state((DECK, DECK), seed)


def test_command_replay_json_contains_only_initial_state_and_commands(tmp_path):
    replay = demo_replay(seed=3, duration_ticks=60)
    path = tmp_path / "replay.json"
    write_replay(path, replay)
    value = json.loads(path.read_text(encoding="utf-8"))
    assert set(value) == {"schema_version", "schema", "simulator_revision",
                           "game_data_hash", "initial_state", "commands"}
    assert all(set(command) <= {"tick", "player", "type", "card", "x_mt",
                                "y_mt", "actor_uid"}
               for command in value["commands"])
    assert "entities" not in value["initial_state"]
    assert "positions" not in value["initial_state"]
    assert read_replay(path) == replay


def test_roundtrip_matches_every_checkpoint_and_final_state():
    replay = demo_replay(seed=11, duration_ticks=80)
    first = execute_replay(replay)
    second = execute_replay(replay)
    assert first_divergence(first, second) is None
    assert [checkpoint.digest for checkpoint in first.checkpoints] == [
        checkpoint.digest for checkpoint in second.checkpoints]
    assert first.final.state == second.final.state
    assert state_digest(first.match) == first.final.digest


def test_command_order_is_preserved_and_invalid_order_is_rejected():
    initial = _initial(5)
    commands = (
        Command(2, 1, "PLAY_CARD", card="cannon", x_mt=4500, y_mt=24500),
        Command(1, -1, "PLAY_CARD", card="cannon", x_mt=13500, y_mt=7500),
    )
    with pytest.raises(ReplayError, match="ordered"):
        MatchReplay(initial, commands).validate()


def test_seed_changes_initial_derived_deck_but_same_seed_replays():
    first = execute_replay(demo_replay(seed=17, duration_ticks=2))
    same = execute_replay(demo_replay(seed=17, duration_ticks=2))
    other = execute_replay(demo_replay(seed=18, duration_ticks=2))
    assert first.final.digest == same.final.digest
    assert first.match.players[1].queue != other.match.players[1].queue


def test_canonical_digest_ignores_irrelevant_mapping_and_set_order():
    replay = demo_replay(seed=19, duration_ticks=10)
    execution = execute_replay(replay)
    original = execution.match
    original_digest = state_digest(original)
    original.battle.entities = dict(reversed(list(original.battle.entities.items())))
    original.battle.resolved_last_group_spawns = set(reversed(tuple(original.battle.resolved_last_group_spawns)))
    assert state_digest(original) == original_digest


def test_first_divergence_reports_tick_entity_and_field():
    replay = demo_replay(seed=23, duration_ticks=10)
    original = execute_replay(replay)
    altered = execute_replay(replay)
    altered.match._regen_carry += 1
    altered.checkpoints[-1] = type(altered.checkpoints[-1])(
        altered.final.tick, altered.final.time_ms,
        hashlib.sha256(json.dumps(altered.match._regen_carry).encode()).hexdigest(),
        {**altered.final.state, "regen_carry": altered.match._regen_carry},
    )
    difference = first_divergence(original, altered)
    assert difference is not None
    assert difference["tick"] == altered.final.tick
    assert difference["field"] == "regen_carry"


@pytest.mark.parametrize("seed", list(range(50)))
def test_fifty_seeded_command_only_episodes(seed):
    replay = demo_replay(seed=seed, duration_ticks=20 + seed % 8)
    execution = execute_replay(replay)
    repeat = execute_replay(replay)
    assert first_divergence(execution, repeat) is None, seed
    assert execution.final.digest == repeat.final.digest


def test_cross_process_replay_digest_matches(tmp_path):
    replay_path = tmp_path / "process.json"
    write_replay(replay_path, demo_replay(seed=31, duration_ticks=70))
    code = (
        "import json,sys; "
        "from tools.calibration.command_replay import read_replay,verify_replay; "
        "print(json.dumps(verify_replay(read_replay(sys.argv[1])),sort_keys=True))"
    )
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "random"
    outputs = [subprocess.check_output([PYTHON, "-c", code, str(replay_path)],
                                       cwd=ROOT, env=env, text=True)
               for _ in range(3)]
    parsed = [json.loads(output) for output in outputs]
    assert all(item["first_divergence"] is None for item in parsed)
    assert len({item["final_digest"] for item in parsed}) == 1
