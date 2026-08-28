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


def anchor_kl(logits, other, mask):
    """The penalty exactly as sim/train_ppo.py computes it."""
    floor = torch.finfo(logits.dtype).min / 4
    logp = torch.log_softmax(logits.masked_fill(~mask, floor), dim=-1)
    logq = torch.log_softmax(other.masked_fill(~mask, floor), dim=-1)
    return (logp.exp() * (logp - logq)).sum(-1).mean().detach()


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
    assert float(anchor_kl(logits, other, mask)) == pytest.approx(0.0, abs=1e-5)


def test_the_penalty_survives_an_infinite_mask():
    """The regression that took down a training run.

    `masked_distribution` fills illegal actions with -inf. Through
    torch's kl_divergence that is -inf - -inf = nan on every masked entry,
    and multiplying by a zero probability does not rescue it: 0 * nan is
    nan. The whole batch went NaN on the first update after the policy
    unfroze, at step 301,056.

    The original version of this test moved the forbidden logits by a
    finite +25 and so never touched the -inf path at all. It asserted the
    right property and proved nothing, which is worse than no test.
    """
    net = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    planes, scalars, mask = a_batch()
    logits, _ = net(planes, scalars)
    other, _ = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)(planes, scalars)

    # Exactly what the training loop feeds it: -inf outside the mask.
    logits = logits.masked_fill(~mask, float("-inf"))
    other = other.masked_fill(~mask, float("-inf"))

    value = float(anchor_kl(logits, other, mask))
    assert value == value, "anchor KL produced NaN on an -inf mask"
    assert value >= 0.0 and value < float("inf")


def test_torch_kl_is_infinite_when_the_supports_disagree():
    """Why the penalty is hand-rolled, measured rather than assumed.

    With both sides masked identically torch's kl_divergence is perfectly
    fine - about 1e-3 here. It returns +inf only where the policy has
    probability on an action the anchor has ruled out. The training loop
    builds both from the same mask so that cannot happen today; the floor
    exists so a future caller that passes two different masks gets a large
    number instead of an inf that would poison a run silently.

    An earlier version of this file claimed the naive form produced NaN and
    asserted it. It does not, and the assertion failed the moment it was
    written against the real -inf path instead of a finite stand-in.
    """
    net_a = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    net_b = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
    planes, scalars, mask = a_batch()
    la, _ = net_a(planes, scalars)
    lb, _ = net_b(planes, scalars)

    same = torch.distributions.kl_divergence(
        masked_distribution(la, mask), masked_distribution(lb, mask)).detach()
    assert torch.isfinite(same).all(), "matching masks must give a finite KL"

    other = mask.clone()
    other[1, 5:40] = False
    other[1, 100:140] = True
    mismatched = torch.distributions.kl_divergence(
        masked_distribution(la, mask), masked_distribution(lb, other)).detach()
    assert torch.isinf(mismatched[1]), "a disagreeing support should be inf"

    # The hand-rolled version stays finite in both cases.
    assert torch.isfinite(anchor_kl(la, lb, mask))


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


def test_the_loss_never_calls_torchs_kl_on_masked_distributions():
    """The hand-rolled form is the point; a tidy-up that reverts it would
    reintroduce an inf that no log line explains."""
    from sim import train_ppo
    source = inspect.getsource(train_ppo.main)
    # Strip comments first. The previous version of this assertion matched
    # the comment that explains why the call is absent, which is a test that
    # fails precisely when the code is correct.
    code = chr(10).join(line.split("#", 1)[0]
                        for line in source.splitlines())
    assert "kl_divergence(" not in code, (
        "the anchor penalty must not go through torch's kl_divergence")
