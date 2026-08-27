"""The training diet has to contain every opponent we intend to beat.

Both failure directions were measured on this project on the same night, on
60 held-out games at seed 8000, starting from a policy scoring 41.7% against
the rule engine and 86.7% against meta decks:

* trained on meta decks + self-play -> 82.5% vs meta, **16.7%** vs the rule
  engine. Reported as a triumph for ten million steps because the eval that
  selected checkpoints was also against meta decks.
* trained 50% on the rule engine + self-play -> **93.3%** vs the rule engine,
  76.7% vs meta decks. Caught in three million because the eval was against
  the rule engine and an independent check against meta decks was run.

A single-opponent diet produces a policy that beats that opponent. So the
scripted half of the episodes now alternates, and the eval opponent is
separable from the training opponent - the number that selects a checkpoint
should not be one the policy has been trained to death against.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.vecenv import _LeagueSeat                              # noqa: E402


class FakeEnv:
    """Records what the seat asked for, without building a simulator."""

    def __init__(self, deck_pool=True):
        self.policy_opponent = "unset"
        self.kinds: list[str] = []
        self._deck_pool = [("a", "cycle", [])] if deck_pool else []
        self._opponent_kind = "brain"

    def set_policy_opponent(self, opponent):
        self.policy_opponent = opponent

    def set_opponent_kind(self, kind):
        self.kinds.append(kind)
        self._opponent_kind = kind


def test_without_a_brain_share_the_opponent_is_never_switched():
    """The previous behaviour has to survive untouched."""
    seat = _LeagueSeat(seed=1, scripted_share=1.0)
    env = FakeEnv()
    for _ in range(50):
        seat.choose(env)
    assert env.kinds == [], "switched opponents when no mix was asked for"
    assert env.policy_opponent is None


def test_a_brain_share_alternates_the_scripted_opponent():
    seat = _LeagueSeat(seed=1, scripted_share=1.0, brain_share=0.5)
    env = FakeEnv()
    for _ in range(400):
        seat.choose(env)
    brain = env.kinds.count("brain")
    assert len(env.kinds) == 400
    assert 0.4 < brain / 400 < 0.6, f"brain share was {brain / 400:.0%}"


@pytest.mark.parametrize("share,low,high", [(0.0, 0.0, 0.05),
                                            (0.25, 0.18, 0.32),
                                            (1.0, 0.95, 1.0)])
def test_the_share_is_honoured_across_the_range(share, low, high):
    seat = _LeagueSeat(seed=7, scripted_share=1.0, brain_share=share)
    env = FakeEnv()
    for _ in range(400):
        seat.choose(env)
    if share == 0.0:
        assert env.kinds == []            # no mixing requested at all
        return
    seen = env.kinds.count("brain") / len(env.kinds)
    assert low <= seen <= high, f"asked {share:.0%}, got {seen:.0%}"


def test_meta_is_refused_when_no_deck_pool_was_loaded():
    """A worker that raises mid-rollout takes the whole run down."""
    from sim.env import ClashEnv

    env = ClashEnv.__new__(ClashEnv)          # no simulator construction
    env._deck_pool = []
    env._opponent_kind = "brain"
    env.set_opponent_kind("meta")
    assert env._opponent_kind == "brain", "accepted meta without a deck pool"


def test_a_nonsense_kind_is_ignored_rather_than_stored():
    from sim.env import ClashEnv

    env = ClashEnv.__new__(ClashEnv)
    env._deck_pool = [("a", "cycle", [])]
    env._opponent_kind = "brain"
    env.set_opponent_kind("definitely_not_an_opponent")
    assert env._opponent_kind == "brain"
    env.set_opponent_kind("meta")
    assert env._opponent_kind == "meta"


def test_self_play_episodes_still_bypass_the_scripted_choice():
    """A league episode faces a past self, not a scripted opponent."""
    seat = _LeagueSeat(seed=3, scripted_share=0.0, brain_share=0.5)
    seat.add("nonexistent.pt", "self@1k")
    env = FakeEnv()
    seat.choose(env)
    # The snapshot cannot load, so it falls back - but it must not have been
    # counted as a scripted episode and given a kind.
    assert env.kinds == []


def test_the_trainer_exposes_both_knobs():
    source = (ROOT / "sim" / "train_ppo.py").read_text(encoding="utf-8")
    assert "--brain-share" in source
    assert "--eval-opponent" in source
    assert "brain_share=args.brain_share" in source
    assert "opponent=eval_opponent" in source, (
        "the eval must be able to score against someone other than the "
        "training opponent")


def test_the_diet_line_names_the_real_opponent():
    """It printed 'vs meta decks' for a run that was 50% rule engine."""
    source = (ROOT / "sim" / "train_ppo.py").read_text(encoding="utf-8")
    assert 'f"{args.scripted_share:.0%} of episodes still vs meta decks"' not in source
    assert "rule engine / " in source
