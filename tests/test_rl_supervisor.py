"""The overnight supervisor's judgement, which runs while nobody is watching.

It decides when a training run has stopped being worth continuing. Getting
that wrong is expensive in both directions: too twitchy and it restarts a run
that was only having a noisy eval, too slow and it spends the night polishing
a policy that has already lost its win condition.

The sequences here are taken from real logs. `tmp/rl/s4ent.out` is the run
aborted at entropy 0.10 - 72% -> 70% -> 52% with hog share falling 15% -> 4% -
and `tmp/rl/pilot.log` is the run that worked, which wandered a long way
without ever being in trouble.
"""

from __future__ import annotations

import sys
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from rl_supervisor import LADDER, Evaluation, Supervisor       # noqa: E402


def settings(**overrides) -> Namespace:
    base = dict(name="test", hours=1.0, envs=16, rollout=128, steps=1,
                value_warmup=0, eval_every=1, eval_episodes=40, init="x",
                poll=1.0, win_drop=0.18, hog_floor=0.06, plays_ceiling=75,
                severe_drop=0.30, severe_hog=0.02, hog_collapse=0.40,
                plays_blowout=1.6, score_drop=1.0, patience=4,
                stall_minutes=20.0, min_free_gb=10.0, opponent="brain",
                audit_every=3_000_000, audit_episodes=60, audit_drop=0.12,
                audit_timeout=900.0, max_attempts=12, brain_share=0.5,
                eval_opponent='brain',
                audit_opponents=['brain', 'meta'], audit_anchor={},
                scripted_alt='meta', scripted_share=None)
    base.update(overrides)
    return Namespace(**base)


def evaluation(wins: int, hog: float = 0.15, plays: int = 50,
               score: float = 0.5, step: int = 0) -> Evaluation:
    return Evaluation(step=step, wins=wins, losses=40 - wins, hog=hog,
                      plays=plays, score=score)


def judge(evals: list, **overrides) -> str:
    supervisor = Supervisor(settings(**overrides))
    supervisor.best_score = max([item.score for item in evals], default=0.0)
    return supervisor.verdict(evals)


def test_a_healthy_run_is_left_alone():
    healthy = [evaluation(29), evaluation(27), evaluation(30), evaluation(28)]
    assert judge(healthy) == ""


def test_the_first_eval_sets_the_bar_rather_than_a_number_we_guessed():
    """The clone is whatever it is; everything is measured against it."""
    supervisor = Supervisor(settings())
    supervisor.verdict([evaluation(24)])
    assert supervisor.baseline_win_rate == 0.6
    # A run that starts weaker is not immediately declared broken.
    assert supervisor.verdict([evaluation(24), evaluation(23)]) == ""


def test_one_noisy_eval_does_not_restart_the_run():
    """40 episodes swings; a single dip is not evidence."""
    assert judge([evaluation(29), evaluation(21), evaluation(28)]) == ""


def test_two_evals_below_the_floor_stop_the_run():
    verdict = judge([evaluation(29), evaluation(20), evaluation(19)])
    assert "win rate" in verdict, verdict


def test_the_real_entropy_collapse_is_caught():
    """72% -> 70% -> 52% with hog 15% -> 4%, from tmp/rl/s4ent.out."""
    observed = [evaluation(29, hog=0.15, plays=52),
                evaluation(28, hog=0.15, plays=48),
                evaluation(21, hog=0.04, plays=84)]
    verdict = judge(observed)
    assert verdict, "the run that had to be aborted by hand was not caught"
    assert "hog" in verdict or "win rate" in verdict, verdict


def test_losing_the_win_condition_is_a_stop_on_its_own():
    """A policy can chip its way to a decent record and still be broken."""
    verdict = judge([evaluation(29), evaluation(28, hog=0.04),
                     evaluation(27, hog=0.03)])
    assert "hog" in verdict, verdict


def test_a_catastrophic_single_eval_is_not_given_the_benefit_of_the_doubt():
    verdict = judge([evaluation(29), evaluation(10)])
    assert "single eval" in verdict, verdict


def test_spraying_cards_is_caught():
    verdict = judge([evaluation(29), evaluation(27, plays=88),
                     evaluation(26, plays=91)])
    assert "plays/match" in verdict, verdict


def test_a_long_slide_below_the_best_is_caught_even_while_winning():
    """Score can rot without the win rate crossing any floor."""
    evals = [evaluation(29, score=3.0)] + [evaluation(24, score=1.0)] * 4
    verdict = judge(evals)
    assert "below the best" in verdict, verdict


def test_the_ladder_only_ever_gets_tamer():
    """Each rung must reduce exploration pressure and step size."""
    for earlier, later in zip(LADDER, LADDER[1:]):
        assert later.entropy <= earlier.entropy
        assert later.lr <= earlier.lr
        assert later.target_kl <= earlier.target_kl
        assert later.scripted_share >= earlier.scripted_share
        assert later.league <= earlier.league
    assert LADDER[-1].league == 0, "the last rung should remove self-play"
    assert LADDER[-1].scripted_share == 1.0


# ------------------------------------------- keeping the checkpoint safely

def keeper(tmp_path, monkeypatch, manifest_step, contents=b"weights"):
    """A supervisor pointed at a fake trainer output directory."""
    import json

    import rl_supervisor as sup

    monkeypatch.setattr(sup, "KEEP", tmp_path / "keep")
    monkeypatch.setattr(sup, "OUT", tmp_path / "out")
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "night1_best.pt").write_bytes(contents)
    if manifest_step is not None:
        (tmp_path / "out" / "night1_best.json").write_text(
            json.dumps({"step": manifest_step, "wins": 30, "losses": 10}),
            encoding="utf-8")
    return sup, sup.Supervisor(settings())


def test_a_checkpoint_whose_manifest_lags_the_eval_is_not_copied(
        tmp_path, monkeypatch):
    """The real race: eval logged at 04:31:02, checkpoint written at 04:31:03."""
    sup, supervisor = keeper(tmp_path, monkeypatch, manifest_step=954_368)
    monkeypatch.setattr(supervisor, "loadable", lambda _p: True)
    supervisor.keep_best(Namespace(name="night1", rung=Namespace(name="plan")),
                         evaluation(30, step=1_705_984, score=0.93))
    assert not (tmp_path / "keep" / "best.pt").exists(), (
        "copied a checkpoint the trainer had not finished writing")
    assert supervisor.best_score == -99.0, "recorded a best it did not keep"


def test_a_settled_checkpoint_is_copied(tmp_path, monkeypatch):
    sup, supervisor = keeper(tmp_path, monkeypatch, manifest_step=1_705_984)
    monkeypatch.setattr(supervisor, "loadable", lambda _p: True)
    supervisor.keep_best(Namespace(name="night1", rung=Namespace(name="plan")),
                         evaluation(30, step=1_705_984, score=0.93))
    assert (tmp_path / "keep" / "best.pt").read_bytes() == b"weights"
    assert supervisor.best_score == pytest.approx(0.93)


def test_a_truncated_copy_never_replaces_the_previous_best(
        tmp_path, monkeypatch):
    """A torn 242MB copy must not become the checkpoint the morning loads."""
    sup, supervisor = keeper(tmp_path, monkeypatch, manifest_step=1_705_984)
    (tmp_path / "keep").mkdir()
    (tmp_path / "keep" / "best.pt").write_bytes(b"the good one")
    monkeypatch.setattr(supervisor, "loadable", lambda _p: False)
    supervisor.keep_best(Namespace(name="night1", rung=Namespace(name="plan")),
                         evaluation(30, step=1_705_984, score=0.93))
    assert (tmp_path / "keep" / "best.pt").read_bytes() == b"the good one"
    assert not (tmp_path / "keep" / "best.pt.part").exists(), "left a stage file"
    assert supervisor.best_score == -99.0


def test_a_missing_manifest_is_treated_as_unsettled(tmp_path, monkeypatch):
    sup, supervisor = keeper(tmp_path, monkeypatch, manifest_step=None)
    monkeypatch.setattr(supervisor, "loadable", lambda _p: True)
    supervisor.keep_best(Namespace(name="night1", rung=Namespace(name="plan")),
                         evaluation(30, step=1_705_984, score=0.93))
    assert not (tmp_path / "keep" / "best.pt").exists()


def test_loadable_rejects_a_file_without_weights(tmp_path):
    import torch

    from rl_supervisor import Supervisor
    good, bad, junk = (tmp_path / "g.pt"), (tmp_path / "b.pt"), (tmp_path / "j.pt")
    torch.save({"state_dict": {"w": torch.zeros(2)}, "step": 1}, good)
    torch.save({"step": 1}, bad)                  # unpickles, carries nothing
    junk.write_bytes(b"not a checkpoint at all")
    assert Supervisor.loadable(good)
    assert not Supervisor.loadable(bad)
    assert not Supervisor.loadable(junk)


# ------------------------------------------------------------- the audit

def audit_with(rates, tmp_path, monkeypatch, **overrides):
    """Drive Supervisor.audit over a sequence of held-out win rates."""
    import json

    import rl_supervisor as sup

    monkeypatch.setattr(sup, "KEEP", tmp_path)
    monkeypatch.setattr(sup, "OUT", tmp_path)
    (tmp_path / "best.pt").write_bytes(b"x")

    supervisor = sup.Supervisor(settings(**overrides))
    attempt = Namespace(name="night1")
    verdicts = []
    for index, rate in enumerate(rates):
        rows = [{"opponent": name, "win_rate": value,
                 "wilson_lo": max(0.0, value - 0.1),
                 "wilson_hi": min(1.0, value + 0.1), "hog_share": 0.18}
                for name, value in (rate if isinstance(rate, dict)
                                    else {"brain": rate}).items()]
        payload = {"results": {"c": rows}}

        def fake_run(*_a, **_k):
            (tmp_path / "night1_audit.json").write_text(
                json.dumps(payload), encoding="utf-8")
            return Namespace(returncode=0, stderr="")

        monkeypatch.setattr(sup.subprocess, "run", fake_run)
        verdicts.append(supervisor.audit(attempt, (index + 1) * 3_000_000))
    return supervisor, verdicts


def test_the_first_audit_only_records_the_bar(tmp_path, monkeypatch):
    supervisor, verdicts = audit_with([0.42], tmp_path, monkeypatch)
    assert verdicts == [""]
    assert supervisor.first_audit["brain"] == pytest.approx(0.42)


def test_the_audit_catches_the_run_that_fooled_the_training_eval(
        tmp_path, monkeypatch):
    _supervisor, verdicts = audit_with([0.417, 0.167], tmp_path, monkeypatch)
    assert verdicts[0] == ""
    assert "trading one opponent for another" in verdicts[1], verdicts[1]
    assert "vs brain" in verdicts[1], verdicts[1]


def test_held_out_noise_does_not_trip_the_audit(tmp_path, monkeypatch):
    """60 games swings; only a real drop counts."""
    _supervisor, verdicts = audit_with([0.42, 0.38, 0.45, 0.40],
                                       tmp_path, monkeypatch)
    assert all(v == "" for v in verdicts), verdicts


def test_an_audit_that_improves_is_never_a_trip(tmp_path, monkeypatch):
    _supervisor, verdicts = audit_with([0.42, 0.55], tmp_path, monkeypatch)
    assert verdicts[1] == ""


def test_a_missing_result_file_is_inconclusive_not_a_trip(tmp_path, monkeypatch):
    import rl_supervisor as sup
    monkeypatch.setattr(sup, "KEEP", tmp_path)
    monkeypatch.setattr(sup, "OUT", tmp_path)
    (tmp_path / "best.pt").write_bytes(b"x")
    monkeypatch.setattr(sup.subprocess, "run",
                        lambda *a, **k: Namespace(returncode=1, stderr="boom"))
    supervisor = sup.Supervisor(settings())
    assert supervisor.audit(Namespace(name="night1"), 3_000_000) == ""


# ------------------------------------------------------- the morning verdict

def row(win_rate: float, lo: float, hi: float, opponent: str = "brain") -> dict:
    return {"opponent": opponent, "win_rate": win_rate, "wilson_lo": lo,
            "wilson_hi": hi, "crown_diff": 0.0, "hog_share": 0.15,
            "wins": 0, "losses": 0}


def verdict_for(night: dict, baseline: dict | None) -> str:
    supervisor = Supervisor(settings())
    supervisor.final = {"night": [night]}
    if baseline is not None:
        supervisor.final["baseline"] = [baseline]
    return supervisor.verdict_line()


def test_a_clear_win_says_play_the_new_one():
    verdict = verdict_for(row(0.55, 0.50, 0.60), row(0.43, 0.38, 0.49))
    assert "better" in verdict and "night/best.pt" in verdict, verdict


def test_a_clear_loss_says_keep_the_baseline():
    verdict = verdict_for(row(0.30, 0.25, 0.36), row(0.43, 0.38, 0.49))
    assert "baseline is still better" in verdict, verdict


def test_overlapping_intervals_are_not_reported_as_an_improvement():
    """A higher number inside the other's interval is not a result."""
    verdict = verdict_for(row(0.47, 0.41, 0.53), row(0.43, 0.38, 0.49))
    assert "Too close to call" in verdict, verdict
    assert "better" not in verdict.split("Too close")[0], verdict


def test_a_missing_baseline_is_flagged_rather_than_assumed():
    verdict = verdict_for(row(0.50, 0.44, 0.56), None)
    assert "not re-measured" in verdict, verdict


def test_no_result_at_all_keeps_the_incumbent():
    supervisor = Supervisor(settings())
    supervisor.final = {}
    assert "keep the existing baseline" in supervisor.verdict_line()


def test_every_rung_has_a_stated_reason():
    """The log has to say why it changed the settings, not just that it did."""
    for rung in LADDER:
        assert rung.why and len(rung.why) > 20, rung.name


def test_a_gain_on_one_opponent_bought_by_a_loss_on_the_other_is_a_trip(
        tmp_path, monkeypatch):
    """The specialisation that a single-axis audit cannot see.

    Measured on this project at 3.2M steps: 41.7% -> 93.3% against the rule
    engine while meta decks went 86.7% -> 76.7%. A brain-only audit calls that
    a triumph.
    """
    _s, verdicts = audit_with([{"brain": 0.417, "meta": 0.867},
                               {"brain": 0.933, "meta": 0.60}],
                              tmp_path, monkeypatch)
    assert verdicts[0] == ""
    assert "vs meta" in verdicts[1], verdicts[1]


def test_both_axes_holding_is_not_a_trip(tmp_path, monkeypatch):
    _s, verdicts = audit_with([{"brain": 0.417, "meta": 0.867},
                               {"brain": 0.933, "meta": 0.80}],
                              tmp_path, monkeypatch)
    assert all(v == "" for v in verdicts), verdicts


def test_the_anchor_can_be_supplied_so_the_first_audit_is_not_self_referential(
        tmp_path, monkeypatch):
    """Anchoring on the 3M policy hides any regression before 3M."""
    supervisor, verdicts = audit_with(
        [{"brain": 0.20, "meta": 0.50}], tmp_path, monkeypatch,
        audit_anchor={"brain": 0.417, "meta": 0.867})
    assert supervisor.first_audit["brain"] == pytest.approx(0.417)
    assert "vs brain" in verdicts[0], (
        "a first audit far below the supplied start must trip immediately")
