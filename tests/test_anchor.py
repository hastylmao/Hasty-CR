"""PPO can be held near a policy that is known to transfer.

The agent that beats the rule engine 94% of the time in simulation played
worse than that rule engine against a person: measured live on 2026-08-28,
hog 3% at 2.3 average elixir against the rule engine's 15% at 4.5. PPO had
not learned to play Clash Royale, it had learned to exploit a simulator whose
body-block cost and pocket size are both unmeasured guesses - and dumping
cheap bodies is what that rewards.

The behaviour clone at the start of training does not have that problem: it
imitates the rule engine, which a person wrote for the real game. So the
anchor lets PPO improve on the clone while paying for how far it moves, which
bounds the drift into simulator-specific behaviour.

These tests pin the mechanics, not the benefit. Whether an anchored run beats
an unanchored one live is a measurement nobody has made yet.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

torch = pytest.importorskip("torch")

from sim.env import ACTIONS, NUM_PLANES, NUM_SCALARS       # noqa: E402
from sim.train_ppo import build_network, masked_distribution  # noqa: E402


def a_batch(n=4):
    planes = torch.randn(n, NUM_PLANES, 32, 18)
    scalars = torch.randn(n, NUM_SCALARS)
    mask = torch.zeros(n, ACTIONS, dtype=torch.bool)
    mask[:, 0] = True
    mask[:, 5:40] = True
    return planes, scalars, mask


def test_a_policy_has_zero_divergence_from_itself():
    """The floor. If this is not zero the penalty punishes standing still."""
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    planes, scalars, mask = a_batch()
    logits, _ = net(planes, scalars)
    d1 = masked_distribution(logits, mask)
    d2 = masked_distribution(logits.clone(), mask)
    kl = torch.distributions.kl_divergence(d1, d2).mean().detach()
    assert float(kl) == pytest.approx(0.0, abs=1e-6)


def test_divergence_from_a_different_policy_is_positive():
    net_a = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    net_b = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    planes, scalars, mask = a_batch()
    la, _ = net_a(planes, scalars)
    lb, _ = net_b(planes, scalars)
    kl = torch.distributions.kl_divergence(
        masked_distribution(la, mask), masked_distribution(lb, mask)).mean().detach()
    assert float(kl) > 0.0


def test_masked_actions_cannot_contribute_to_the_penalty():
    """Two policies that differ only on illegal actions are the same policy.

    Otherwise the anchor would spend gradient pulling the network towards
    agreement about moves neither is allowed to make.
    """
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    planes, scalars, mask = a_batch()
    logits, _ = net(planes, scalars)
    other = logits.clone()
    other[:, ~mask[0]] += 25.0          # only the forbidden ones move
    kl = torch.distributions.kl_divergence(
        masked_distribution(logits, mask),
        masked_distribution(other, mask)).mean().detach()
    assert float(kl) == pytest.approx(0.0, abs=1e-5)


def test_the_penalty_is_off_unless_both_flags_are_given():
    """A path this quiet must not switch itself on, and must not be a no-op
    when it is asked for."""
    from sim import train_ppo
    source = inspect.getsource(train_ppo.main)
    assert "args.anchor and args.anchor_coef > 0" in source, (
        "the anchor must require both a checkpoint and a non-zero weight")
    assert "anchor_net is not None" in source, (
        "the loss must be gated on the anchor actually being loaded")


def test_a_missing_anchor_file_is_refused_not_ignored():
    from sim import train_ppo
    source = inspect.getsource(train_ppo.main)
    assert "does not exist" in source, (
        "a typo'd --anchor path must stop the run, not silently train "
        "unanchored for six hours")
