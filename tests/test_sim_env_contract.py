"""The parts of the RL contract that break training quietly rather than loudly.

`test_sim_env.py` already pins the direction of the action mask that an agent
notices: if the mask offers an action, the engine takes it. These cover the
failures that produce a policy which trains to a plateau and never says why.

A mask that hides a legal action costs the agent that move forever, and nothing
errors. A non-deterministic reset makes the environment non-stationary, so the
value function is chasing a moving target. A single non-finite number in an
observation propagates to NaN weights on the first backward pass, and by then
the cause is many steps upstream.
"""

import copy
import random
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.env import ClashEnv                                    # noqa: E402


@pytest.fixture
def env():
    return ClashEnv(seed=0)


def test_the_mask_does_not_hide_a_legal_action(env):
    """The direction the agent cannot notice.

    A false 'legal' shows up as a refused action. A false 'illegal' shows up as
    nothing at all: the move is simply never available, and the policy learns a
    game slightly smaller than the one it will be deployed into.
    """
    _, info = env.reset(seed=4)
    rng = random.Random(11)
    accepted_but_masked = []
    probed = 0
    for _ in range(8):
        hidden = np.flatnonzero(~info["action_mask"])
        for action in rng.sample(list(hidden), min(30, len(hidden))):
            probe = copy.deepcopy(env)
            before = probe.stats.illegal
            probe.step(int(action))
            probed += 1
            if probe.stats.illegal == before:
                accepted_but_masked.append((int(action),
                                            ClashEnv.decode(int(action))))
        _, _, terminated, truncated, info = env.step(0)
        if terminated or truncated:
            break
    assert probed, "nothing was probed"
    assert not accepted_but_masked, accepted_but_masked[:10]


def _rollout(seed: int, steps: int = 50):
    env = ClashEnv(seed=seed)
    _, info = env.reset(seed=seed)
    trace, rewards, observations = [], [], []
    for index in range(steps):
        legal = np.flatnonzero(info["action_mask"])
        # A fixed rule rather than a random one, so the two runs being compared
        # differ only in the environment and not in the actions chosen.
        action = int(legal[(index * 7 + 3) % len(legal)])
        observation, reward, terminated, truncated, info = env.step(action)
        trace.append((action, info["crowns"]))
        rewards.append(reward)
        observations.append(observation)
        if terminated or truncated:
            break
    return trace, rewards, observations


def test_a_seed_and_an_action_sequence_replay_identically():
    assert _rollout(0)[0] == _rollout(0)[0]


def test_the_seed_actually_changes_the_episode():
    """Determinism must not have been bought by ignoring the seed."""
    assert _rollout(0)[0] != _rollout(5)[0]


def test_observations_stay_finite_and_keep_their_shape():
    _, _, observations = _rollout(2)
    assert observations
    first = observations[0]
    for observation in observations:
        assert set(observation) == set(first)
        for key, value in observation.items():
            array = np.asarray(value)
            assert array.shape == np.asarray(first[key]).shape, key
            assert array.dtype == np.float32, key
            assert np.isfinite(array).all(), key
            assert (array >= 0).all(), key


def test_rewards_are_finite_and_bounded():
    """A single unbounded reward dominates every gradient it appears in."""
    _, rewards, _ = _rollout(3)
    assert rewards
    assert all(np.isfinite(rewards))
    assert max(abs(reward) for reward in rewards) < 10.0, max(rewards)
