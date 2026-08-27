"""Tests for the RL environment.

The one that matters most is the action mask. A mask that claims an action is
legal when the engine will reject it teaches an agent that some fraction of its
choices randomly do nothing, which is a slow and confusing way to learn. It was
wrong on 23% of attempts before the spell-placement fix, so it is checked
exhaustively here rather than sampled.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.env import ACTIONS, DECK_26, ClashEnv, GRID_W, NUM_PLANES  # noqa: E402


@pytest.fixture(scope="module")
def env():
    return ClashEnv(seed=11)


def test_action_encoding_round_trips():
    for slot in range(4):
        for x in (0, 7, GRID_W - 1):
            for y in (0, 16, 31):
                assert ClashEnv.decode(ClashEnv.encode(slot, x, y)) == (slot, x, y)
    assert ClashEnv.decode(0) is None
    assert ClashEnv.decode(ClashEnv.encode_ability(3)) == ("ability", 3)


def test_a_legal_champion_button_is_exposed_as_an_rl_action(env):
    from sim.entities import make_unit
    from sim.gamedata import load_gamedata
    from sim.arena import Point

    env.reset(seed=4)
    queen = env.match.battle.add(make_unit(0, load_gamedata(11)["archer_queen"].unit,
                                           1, Point(9_000, 20_000)))
    queen.deploy_remaining_ms = 0
    env.match.players[1].elixir = 10_000
    action = ClashEnv.encode_ability(0)
    assert env.action_mask()[action]
    before = env.match.players[1].elixir
    env.step(action)
    assert queen.ability_used
    assert env.match.players[1].elixir < before


def test_reset_returns_the_advertised_shapes(env):
    obs, info = env.reset(seed=5)
    assert obs["planes"].shape == (NUM_PLANES, 32, GRID_W)
    assert obs["scalars"].shape == env.observation_shape["scalars"]
    assert info["action_mask"].shape == (ACTIONS,)
    assert info["action_mask"][0], "holding elixir must always be legal"


def test_troops_are_masked_out_of_the_enemy_half(env):
    env.reset(seed=6)
    mask = env.action_mask()
    hand = env.match.players[1].hand
    for slot, card in enumerate(hand[:4]):
        if card in ("fireball", "the_log"):
            continue
        for y in range(0, 16):
            assert not mask[ClashEnv.encode(slot, 5, y)], f"{card} at y={y}"


def test_spells_may_be_aimed_at_the_enemy_tower(env):
    env.reset(seed=7)
    player = env.match.players[1]
    player.hand = ["fireball", "hog_rider", "cannon", "skeletons"]
    player.elixir = 10_000
    mask = env.action_mask()
    # (4, 7) is the enemy left princess tower in the policy's grid convention.
    assert mask[ClashEnv.encode(0, 4, 7)]


def test_every_masked_action_is_actually_accepted(env):
    """The invariant the agent trains against: if the mask offers it, it works.

    A mask is only valid for the state it was computed from - playing a card
    changes both the elixir and the hand - so it is re-read on every step. That
    is also how a training loop must use it.
    """
    rng = np.random.default_rng(3)
    for seed in (12, 13, 14):
        _, info = env.reset(seed=seed)
        for _ in range(120):
            legal = np.flatnonzero(info["action_mask"])
            assert len(legal), "no legal action, not even holding"
            action = int(rng.choice(legal))
            snapshot = (env.match.players[1].elixir, list(env.match.players[1].hand))
            before = env.stats.illegal
            _, _, terminated, truncated, info = env.step(action)
            assert env.stats.illegal == before, (
                f"mask offered action {action} ({ClashEnv.decode(action)}) but the "
                f"engine refused it (elixir={snapshot[0]}, hand={snapshot[1]})")
            if terminated or truncated:
                break


def test_losing_tower_health_is_penalised(env):
    env.reset(seed=8)
    env.match.towers[1]["left"].hitpoints //= 2
    reward = env._shaping_reward()
    assert reward < 0

    env.reset(seed=8)
    env.match.towers[-1]["left"].hitpoints //= 2
    assert env._shaping_reward() > 0


def test_an_episode_terminates_and_reports_a_result(env):
    obs, info = env.reset(seed=9)
    for _ in range(2000):
        obs, reward, terminated, truncated, info = env.step(0)
        if terminated or truncated:
            break
    assert terminated or truncated
    assert info["result"] in (None, "bottom", "top", "draw")
    # Holding every turn against the hand-written brain should not win.
    assert info["crowns"][0] <= info["crowns"][1]


def test_the_opponents_elixir_is_not_observable(env):
    """The live bot has to infer it, so training must not hand it over."""
    obs, _ = env.reset(seed=10)
    env.match.players[-1].elixir = 10_000
    rich = env._observe()["scalars"].copy()
    env.match.players[-1].elixir = 0
    poor = env._observe()["scalars"]
    assert np.array_equal(rich, poor)
