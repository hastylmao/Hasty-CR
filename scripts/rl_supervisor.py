"""Run PPO overnight without a human, and stop it destroying its own policy.

Every failure this project has had with PPO looks the same from the outside:
the run keeps going, the numbers keep printing, and the policy at the end is
worse than the one it started from. Five runs did that before value warmup and
the KL guard were added, and one did it again tonight at an entropy
coefficient of 0.10 - eval win rate 72% -> 52%, hog share 15% -> 4%, plays per
match 48 -> 84, all inside 400k steps. A training run left alone for fourteen
hours will happily spend all fourteen of them getting worse.

So this watches the eval line rather than the loss, because the eval line is
the only thing in the log that measures the thing we care about, and it acts
on three questions:

* **Is the policy still playing the game?** Hog share and plays per match.
  A policy that stops sending its win condition, or starts spraying 80 cards
  a match, has stopped playing Clash Royale whatever its return says.
* **Is it still winning?** Win rate against a fixed opponent, compared with
  the very first eval - which is the behaviour clone, before PPO has touched
  it. Anything below that for long enough is a regression, not exploration.
* **Is it still running?** Log silence and free disk.

On a trip it kills the run, steps one rung down a ladder of tamer settings,
and restarts *from the best checkpoint seen so far* rather than from the
wreck. The ladder ends at settings so conservative they cannot move the
policy far; if even those trip, it stops and keeps the best checkpoint.

Nothing here promotes a checkpoint to live play. It selects on a 40-episode
eval against one opponent, which is a smoke test, not evidence; the final
held-out comparison is a separate step and is run at the end.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venvs" / "buildabot" / "Scripts" / "python.exe"
OUT = ROOT / "tmp" / "rl"
KEEP = ROOT / "checkpoints" / "night"

EVAL_LINE = re.compile(
    r"EVAL\s+W(\d+) L(\d+) D(\d+)\s+crowns (\d+)-(\d+)\s+hog (\d+)%\s+"
    r"plays/match (\d+)\s+score ([-+][\d.]+)")
STEP_LINE = re.compile(r"step\s+([\d,]+)")


def log(message: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    print(line, flush=True)
    KEEP.mkdir(parents=True, exist_ok=True)
    with (KEEP / "supervisor.log").open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")


def free_gb(path: Path = ROOT) -> float:
    return shutil.disk_usage(path).free / 2 ** 30


@dataclass
class Rung:
    """One set of settings, tamer than the one before it."""
    name: str
    entropy: float
    entropy_final: float
    entropy_hold: int
    entropy_anneal: int
    lr: float
    target_kl: float
    league: int
    scripted_share: float
    why: str


# Rung 0 is the plan; each one after it is what to try when the previous one
# damaged the policy. Every knob moves in the safe direction: less exploration
# pressure, smaller steps, a tighter trust region, and an opponent mix that
# leans back toward the fixed opponents the policy already handles.
#
# The first version of this table ran rung 0 at league 8 / scripted_share 0.30,
# on the strength of a published figure of ~75% self-play for league training.
# Measured result after 10.3M steps: 82.5% against meta decks and **16.7%**
# against the rule engine, where the policy it started from scores 41.7%. The
# league had taught it its own metagame, which is precisely what `--scripted
# -share`'s own help text warns about - "a league that only plays itself gets
# good at its own metagame and loses to an ordinary ladder deck". A general
# result about a different setup does not outrank this project's measurement of
# itself. Self-play is now the minority of episodes at every rung.
LADDER = [
    Rung("plan", 0.03, 0.015, 8_000_000, 20_000_000, 5e-5, 0.02, 4, 0.50,
         "the 43% baseline's league size, with self-play held to half the "
         "episodes so it cannot drift into its own metagame"),
    Rung("tame", 0.025, 0.015, 4_000_000, 12_000_000, 4e-5, 0.015, 3, 0.65,
         "less exploration, smaller steps, and a mostly scripted opponent mix"),
    Rung("tighter", 0.02, 0.01, 2_000_000, 6_000_000, 3e-5, 0.010, 2, 0.80,
         "trust region halved; the league is a fifth of episodes at most"),
    Rung("crawl", 0.015, 0.01, 1_000_000, 4_000_000, 2e-5, 0.008, 0, 1.00,
         "no self-play at all and a rate that cannot move the policy far - "
         "if this regresses, the problem is not the settings"),
]


@dataclass
class Evaluation:
    step: int
    wins: int
    losses: int
    hog: float
    plays: int
    score: float

    @property
    def win_rate(self) -> float:
        played = self.wins + self.losses
        return self.wins / played if played else 0.0


@dataclass
class Attempt:
    rung: Rung
    name: str
    process: subprocess.Popen
    log_path: Path
    started: float
    evals: list = field(default_factory=list)


class Supervisor:
    def __init__(self, args):
        self.args = args
        self.deadline = time.time() + args.hours * 3600
        self.best_score = -99.0
        self.best_from = ""
        self.baseline_win_rate = None
        self.baseline_hog = 0.15
        self.baseline_plays = 50
        self.rung_index = 0
        self.attempts = 0
        self.history: list = []
        self.final: dict = {}
        self.audits: list = []
        self.first_audit = None
        self.next_audit = args.audit_every

    # ------------------------------------------------------------- launching

    def command(self, rung: Rung, name: str, init: Path) -> list:
        return [
            str(PYTHON), "-m", "sim.train_ppo",
            "--name", name,
            "--envs", str(self.args.envs), "--rollout", str(self.args.rollout),
            "--steps", str(self.args.steps),
            "--lr", str(rung.lr),
            "--entropy", str(rung.entropy),
            "--entropy-final", str(rung.entropy_final),
            "--entropy-hold", str(rung.entropy_hold),
            "--entropy-anneal", str(rung.entropy_anneal),
            "--target-kl", str(rung.target_kl),
            "--value-warmup", str(self.args.value_warmup),
            "--league", str(rung.league),
            "--scripted-share", str(self.args.scripted_share
                                    if self.args.scripted_share is not None
                                    else rung.scripted_share),
            "--scripted-alt", self.args.scripted_alt,
            "--chip", "10", "--crown", "3", "--win", "10", "--elixir", "0",
            # Selection and every trigger below read this eval, so it has to be
            # the opponent we are actually trying to beat. Run against `meta`,
            # it reported a policy improving from 62% to 82% while that same
            # policy fell from 41.7% to 16.7% against the rule engine. An
            # eval against the wrong opponent is worse than no eval: it does
            # not merely fail to catch the regression, it selects for it.
            "--opponent", self.args.opponent,
            "--brain-share", str(self.args.brain_share),
            "--eval-opponent", self.args.eval_opponent,
            "--eval-every", str(self.args.eval_every),
            "--eval-episodes", str(self.args.eval_episodes),
            "--init", str(init),
        ]

    def start(self, rung: Rung, init: Path) -> Attempt:
        self.attempts += 1
        name = f"{self.args.name}{self.attempts}"
        self.prune(name)
        log_path = OUT / f"{name}.out"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("w", encoding="utf-8")
        process = subprocess.Popen(self.command(rung, name, init), cwd=ROOT,
                                   stdout=stream, stderr=subprocess.STDOUT)
        log(f"attempt {self.attempts} '{name}' on rung '{rung.name}': {rung.why}")
        log(f"  entropy {rung.entropy}->{rung.entropy_final}  lr {rung.lr}  "
            f"kl {rung.target_kl}  league {rung.league}  "
            f"scripted {self.args.scripted_share if self.args.scripted_share is not None else rung.scripted_share:.0%}  init {init.name}")
        return Attempt(rung, name, process, log_path, time.time())

    def prune(self, keeping: str) -> None:
        """Drop the previous attempt's bulk.

        Each attempt costs about 1.1 GB - a 242 MB `_last`, a 242 MB `_best`
        and up to eight 80 MB league snapshots - and this machine is short of
        disk, which is a real way to lose a night's work. A previous attempt's
        `_best` is only deleted once the same weights are safely under
        `checkpoints/night/`, so pruning can never be what loses the policy.
        """
        kept_copy = (KEEP / "best.pt").exists()
        patterns = ["*_last.pt"] + (["*_best.pt"] if kept_copy else [])
        for pattern in patterns:
            for path in OUT.glob(f"{self.args.name}{pattern}"):
                if not path.name.startswith(keeping):
                    path.unlink(missing_ok=True)
                    log(f"  pruned {path.name} ({free_gb():.1f} GB free)")
        for league in OUT.glob(f"{self.args.name}*_league"):
            if not league.name.startswith(keeping):
                shutil.rmtree(league, ignore_errors=True)

    # -------------------------------------------------------------- watching

    def read_evals(self, attempt: Attempt) -> list:
        text = attempt.log_path.read_text(encoding="utf-8", errors="replace")
        found = []
        step = 0
        for line in text.splitlines():
            marker = STEP_LINE.search(line)
            if marker:
                step = int(marker.group(1).replace(",", ""))
            hit = EVAL_LINE.search(line)
            if hit:
                found.append(Evaluation(
                    step=step, wins=int(hit.group(1)), losses=int(hit.group(2)),
                    hog=int(hit.group(6)) / 100.0, plays=int(hit.group(7)),
                    score=float(hit.group(8))))
        return found

    def verdict(self, evals: list) -> str:
        """'' if healthy, otherwise why this run should be stopped."""
        if not evals:
            return ""
        if self.baseline_win_rate is None:
            # The first eval of the first attempt is the behaviour clone: the
            # policy PPO was handed. Everything is judged against that, not
            # against a number chosen in advance.
            self.baseline_win_rate = evals[0].win_rate
            self.baseline_hog = evals[0].hog
            self.baseline_plays = evals[0].plays
            log(f"  baseline (the clone): {self.baseline_win_rate:.0%} win rate, "
                f"hog {evals[0].hog:.0%}, {evals[0].plays} plays/match")

        # One eval is 40 episodes and swings about fifteen points on noise, so
        # two in a row is the normal bar. A collapse this far past the clone is
        # not noise, and waiting another half million steps to confirm it only
        # buys more damage.
        latest = evals[-1]
        if latest.win_rate < self.baseline_win_rate - self.args.severe_drop:
            return (f"win rate {latest.win_rate:.0%} is {self.args.severe_drop:.0%} "
                    f"below the clone in a single eval")
        if latest.hog < self.args.severe_hog:
            return (f"hog share {latest.hog:.0%} - the win condition has "
                    "effectively left the policy")
        # Win rate is 40 coin flips and swings accordingly. Hog share is a
        # fraction of roughly two thousand plays, so it barely moves on noise
        # - a single eval losing most of it is a behaviour change, and waiting
        # for a second one only buys more of it.
        if latest.hog < self.baseline_hog * self.args.hog_collapse:
            return (f"hog share {latest.hog:.0%} against the clone's "
                    f"{self.baseline_hog:.0%} - it is dropping its win "
                    "condition")
        if latest.plays > self.baseline_plays * self.args.plays_blowout:
            return (f"{latest.plays} plays/match against the clone's "
                    f"{self.baseline_plays} - spraying cards")

        recent = evals[-2:]
        if len(recent) == 2:
            floor = self.baseline_win_rate - self.args.win_drop
            if all(item.win_rate < floor for item in recent):
                return (f"win rate {recent[-1].win_rate:.0%} below "
                        f"{floor:.0%} on two evals running")
            if all(item.hog < self.args.hog_floor for item in recent):
                return (f"hog share {recent[-1].hog:.0%} below "
                        f"{self.args.hog_floor:.0%} - it has stopped playing "
                        "its win condition")
            if all(item.plays > self.args.plays_ceiling for item in recent):
                return (f"{recent[-1].plays} plays/match above "
                        f"{self.args.plays_ceiling} - spraying cards")
        drift = evals[-self.args.patience:]
        if (len(drift) >= self.args.patience
                and all(item.score < self.best_score - self.args.score_drop
                        for item in drift)):
            return (f"score {drift[-1].score:+.2f} more than "
                    f"{self.args.score_drop} below the best {self.best_score:+.2f} "
                    f"for {self.args.patience} evals")
        return ""

    def audit(self, attempt: Attempt, step: int) -> str:
        """Re-measure the kept checkpoint under the *held-out* protocol.

        The in-training eval runs on seed 900,000 and is fixed for the whole
        run, so selecting the maximum over dozens of evals selects partly for
        luck on those particular forty matches. It is also, on its own, blind
        to the failure that cost this project ten million steps tonight: a
        policy can climb on the opponent it is scored against while collapsing
        against the one that matters.

        So every `--audit-every` steps the kept checkpoint plays the rule
        engine on seed 8000 - the project's designated comparison seed, and a
        different set of matches from the one training selects on. A drop
        against the *first* such audit is a regression no amount of movement
        on the training eval can explain away.

        Returns '' if healthy, otherwise the reason to stop.
        """
        candidate = KEEP / "best.pt"
        if not candidate.exists():
            return ""
        out = OUT / f"{attempt.name}_audit.json"
        opponents = list(self.args.audit_opponents)
        log(f"  audit at {step:,}: {self.args.audit_episodes} held-out games "
            f"vs {' and '.join(opponents)} on seed 8000")
        out.unlink(missing_ok=True)          # never read a stale result
        try:
            finished = subprocess.run(
                [str(PYTHON), "-m", "scripts.evaluate_pilot",
                 "--ckpt", str(candidate),
                 "--episodes", str(self.args.audit_episodes),
                 "--opponents", *opponents, "--seed", "8000",
                 "--out", str(out)],
                cwd=ROOT, timeout=self.args.audit_timeout, check=False,
                capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            log(f"  audit TIMED OUT after {self.args.audit_timeout / 60:.0f} "
                "minutes - the run is now unguarded, treating as inconclusive")
            return ""
        # An audit that fails must say so. This returned silently on a missing
        # file, so when one died - starved of memory, most likely, with the
        # studio and sixteen workers already running - the log showed the
        # audit starting and then simply nothing. The only guard on the run
        # had stopped working and there was no way to tell from the outside.
        if not out.exists():
            log(f"  audit FAILED (exit {finished.returncode}) - no result "
                "written. The run is unguarded until the next one.")
            for line in (finished.stderr or "").strip().splitlines()[-6:]:
                log(f"    | {line}")
            return ""
        try:
            blob = json.loads(out.read_text(encoding="utf-8"))
            rows = {r["opponent"]: r
                    for rows_ in blob["results"].values() for r in rows_}
        except (OSError, ValueError, KeyError):
            return ""
        if not rows:
            return ""

        rates = {name: float(row["win_rate"]) for name, row in rows.items()}
        self.audits.append((step, rates))
        if self.first_audit is None:
            # Seeded from the *starting* policy's known held-out scores where
            # they were supplied, not from wherever the run has got to by the
            # time of the first audit. Anchoring on a policy that has already
            # trained for three million steps means a regression before that
            # point becomes the baseline and can never trip anything.
            self.first_audit = dict(self.args.audit_anchor or rates)
            for name, row in rows.items():
                anchor = self.first_audit.get(name)
                log(f"  audit {name}: {rates[name]:.1%} "
                    f"[{row['wilson_lo']:.1%}-{row['wilson_hi']:.1%}], "
                    f"hog {row['hog_share']:.0%}"
                    + (f" (start {anchor:.1%})" if anchor is not None else ""))
        else:
            for name, row in rows.items():
                log(f"  audit {name}: {rates[name]:.1%} "
                    f"[{row['wilson_lo']:.1%}-{row['wilson_hi']:.1%}] against "
                    f"{self.first_audit.get(name, float('nan')):.1%} at the start")

        # Either axis regressing is a stop. A policy that gains against one
        # opponent by losing against the other has specialised, and both
        # directions of that have now cost this project a run.
        for name, rate in rates.items():
            anchor = self.first_audit.get(name)
            if anchor is None:
                continue
            if rate < anchor - self.args.audit_drop:
                return (f"held-out win rate vs {name} is {rate:.1%}, more than "
                        f"{self.args.audit_drop:.0%} below the {anchor:.1%} it "
                        "started from - it is trading one opponent for another")
        return ""

    @staticmethod
    def loadable(path: Path) -> bool:
        """Does this file deserialise into something with weights in it?

        A truncated `torch.save` usually raises, but not always - a copy cut
        at the wrong boundary can unpickle into a dict that is missing the
        state it is supposed to carry. Checking the key is what makes this a
        test of the contents rather than of the file's existence.
        """
        try:
            import torch
            blob = torch.load(path, map_location="cpu", weights_only=False)
            return isinstance(blob, dict) and bool(blob.get("state_dict"))
        except Exception as exc:                       # noqa: BLE001
            log(f"  checkpoint at {path.name} failed to load: "
                f"{type(exc).__name__}: {exc}")
            return False

    def keep_best(self, attempt: Attempt, evaluation: Evaluation) -> None:
        """Copy the run's own best checkpoint out, once it beats every attempt.

        The trainer keeps a per-run best; this keeps the best across all
        attempts, which is what a restart initialises from and what gets
        evaluated in the morning. The metadata is read from the trainer's
        `_best.json` rather than from the eval line that triggered this,
        because those two can describe different steps: an eval that is good
        but not the run's own best leaves `_best.pt` where it was, and writing
        this eval's numbers next to those weights would mislabel them.
        """
        source = OUT / f"{attempt.name}_best.pt"
        if evaluation.score <= self.best_score or not source.exists():
            return

        # The trainer logs its EVAL line and *then* writes 242MB of
        # checkpoint, which takes about a second. Polling caught that gap on
        # the first night: the supervisor read an eval at 04:31:02, copied at
        # 04:31:02, and the trainer finished writing at 04:31:03 - so the copy
        # was the previous checkpoint carrying the new score. The benign
        # outcome is being one eval stale. The bad one is a poll landing
        # mid-write and copying a truncated file, which would only be
        # discovered when the morning tried to load it.
        #
        # The trainer's manifest is written after the checkpoint, so a
        # manifest whose step matches this eval is proof the bytes are
        # settled. Anything else waits for the next poll.
        record = {}
        manifest = OUT / f"{attempt.name}_best.json"
        if manifest.exists():
            try:
                record = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = {}
        if record.get("step") != evaluation.step:
            log(f"  best checkpoint for step {evaluation.step:,} not settled "
                f"yet (manifest says {record.get('step')}); waiting a poll")
            return

        KEEP.mkdir(parents=True, exist_ok=True)
        staged = KEEP / "best.pt.part"
        shutil.copy2(source, staged)
        if not self.loadable(staged):
            staged.unlink(missing_ok=True)
            log("  copied checkpoint would not load; leaving the previous one "
                "in place and retrying next poll")
            return
        # Replace is atomic, so a reader never sees a half-written best.pt.
        staged.replace(KEEP / "best.pt")
        self.best_score = evaluation.score
        self.best_from = attempt.name
        (KEEP / "best.json").write_text(json.dumps({
            "attempt": attempt.name, "rung": attempt.rung.name,
            "sim_fix": "building pull gated by sight range (2026-08-26)",
            "trainer_best": record,
            "supervisor_score": evaluation.score,
            # Not "eval": a manifest's `eval` key is a results block, and a
            # description string under that name crashed the studio's
            # checkpoint labeller when it tried to index it.
            "eval_note": "40 episodes vs meta decks - a smoke test, not held out",
            "saved": datetime.now().isoformat(timespec="seconds"),
        }, indent=1), encoding="utf-8")
        step = record.get("step", evaluation.step)
        log(f"  kept best: {attempt.name} step {step:,} "
            f"score {evaluation.score:+.2f} "
            f"(W{evaluation.wins} L{evaluation.losses}, hog {evaluation.hog:.0%})")

    # ------------------------------------------------------------- main loop

    def run(self) -> int:
        init = Path(self.args.init)
        if not init.exists():
            log(f"no init checkpoint at {init}")
            return 1
        log(f"supervising for {self.args.hours:.1f}h, "
            f"deadline {datetime.now() + timedelta(hours=self.args.hours):%H:%M}")
        log(f"{free_gb():.1f} GB free at the start")

        attempt = self.start(LADDER[self.rung_index], init)
        seen = 0
        consecutive_crashes = 0
        while True:
            time.sleep(self.args.poll)
            now = time.time()

            if now > self.deadline:
                log("deadline reached")
                self.stop(attempt)
                break

            if free_gb() < self.args.min_free_gb:
                log(f"only {free_gb():.1f} GB free - stopping to avoid "
                    "filling the disk")
                self.stop(attempt)
                break

            finished = attempt.process.poll() is not None
            evals = self.read_evals(attempt)
            for evaluation in evals[seen:]:
                self.keep_best(attempt, evaluation)
            if len(evals) > seen:
                latest = evals[-1]
                log(f"  {attempt.name} step {latest.step:,}  "
                    f"W{latest.wins} L{latest.losses}  hog {latest.hog:.0%}  "
                    f"plays {latest.plays}  score {latest.score:+.2f}")
            seen = len(evals)

            age = now - attempt.log_path.stat().st_mtime
            if age > self.args.stall_minutes * 60:
                reason = f"no output for {age / 60:.0f} minutes"
            else:
                reason = self.verdict(evals)

            # The held-out audit runs on the kept checkpoint, so it only means
            # anything once an eval has produced one.
            if not reason and evals and evals[-1].step >= self.next_audit:
                self.next_audit = evals[-1].step + self.args.audit_every
                reason = self.audit(attempt, evals[-1].step)

            if not reason and not finished:
                continue

            # A process that exits without ever producing an eval did not
            # finish, it fell over - a bad flag, a CUDA error, a killed
            # worker. Restarting it unchanged would loop on the same fault
            # all night, so the tail of the log goes into the record and the
            # supervisor gives up rather than burning the window.
            crashed = finished and not evals
            if crashed:
                consecutive_crashes += 1
                tail = attempt.log_path.read_text(
                    encoding="utf-8", errors="replace").splitlines()[-15:]
                log(f"{attempt.name} exited after "
                    f"{(now - attempt.started) / 60:.1f} min with no eval "
                    f"(exit {attempt.process.returncode}). Last lines:")
                for line in tail:
                    log(f"    | {line}")
                reason = f"crashed with no eval (exit {attempt.process.returncode})"
                if consecutive_crashes >= 2:
                    log("two crashes in a row - stopping rather than looping")
                    self.history.append({"attempt": attempt.name,
                                         "rung": attempt.rung.name,
                                         "reason": reason, "evals": 0})
                    break
            elif finished and not reason:
                consecutive_crashes = 0
                log(f"{attempt.name} finished on its own at "
                    f"{evals[-1].step:,} steps")
                reason = "run ended; continuing from the best so far"
            else:
                consecutive_crashes = 0
                log(f"STOP {attempt.name}: {reason}")
                self.stop(attempt)
                self.rung_index = min(self.rung_index + 1, len(LADDER) - 1)

            self.history.append({"attempt": attempt.name,
                                 "rung": attempt.rung.name, "reason": reason,
                                 "evals": len(evals)})
            # Running out of ladder is not a reason to stop with hours left.
            # Restarting the tamest rung from the best checkpoint cannot lose
            # ground - `best.pt` only ever moves upward, and a fresh attempt
            # begins from it - so the worst case is that the remaining time
            # buys nothing, and the best case is that a different seed finds
            # something. What has to be bounded is churn, not persistence.
            if self.attempts >= self.args.max_attempts:
                log(f"{self.attempts} attempts is the cap; keeping the best "
                    "checkpoint and stopping")
                break
            if self.rung_index >= len(LADDER) - 1 and self.attempts > len(LADDER):
                log("the tamest settings regressed too; retrying them from "
                    "the best checkpoint rather than idling")
            resume_from = KEEP / "best.pt"
            attempt = self.start(LADDER[self.rung_index],
                                 resume_from if resume_from.exists() else init)
            seen = 0

        self.final_comparison()
        self.report()
        return 0

    # ------------------------------------------------------- final judgement

    def final_comparison(self) -> None:
        """Play the night's policy against the incumbent on held-out seeds.

        The 40-episode eval that selected `best.pt` is a smoke test against
        meta decks. What decides whether anything ships is the rule engine on
        seeds no training run has touched, which is the same protocol the 43%
        baseline was measured under - otherwise the two numbers are not
        comparable and the comparison is the entire point.
        """
        candidate = KEEP / "best.pt"
        if not candidate.exists():
            log("no candidate to compare; skipping the held-out eval")
            return
        baseline = (ROOT / "checkpoints" / "sprint4_baseline"
                    / "pilot_best_4392960.pt")
        episodes = self.args.final_episodes
        for label, path in (("night", candidate), ("baseline", baseline)):
            if not path.exists():
                continue
            out = ROOT / "reports" / f"night_final_{label}.json"
            log(f"held-out eval: {label} ({path.name}), {episodes} games "
                f"vs brain + meta at seed 9000")
            try:
                subprocess.run(
                    [str(PYTHON), "-m", "scripts.evaluate_pilot",
                     "--ckpt", str(path), "--episodes", str(episodes),
                     "--opponents", "brain", "meta", "--seed", "9000",
                     "--out", str(out)],
                    cwd=ROOT, timeout=self.args.final_timeout, check=False)
                self.summarise(label, out)
            except subprocess.TimeoutExpired:
                log(f"  {label} eval timed out after "
                    f"{self.args.final_timeout / 60:.0f} minutes")

    def summarise(self, label: str, out: Path) -> None:
        if not out.exists():
            log(f"  {label}: no result file")
            return
        try:
            blob = json.loads(out.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for rows in blob.get("results", {}).values():
            for row in rows:
                log(f"  {label} vs {row['opponent']}: "
                    f"{row['win_rate']:.1%} "
                    f"[{row['wilson_lo']:.1%}-{row['wilson_hi']:.1%}] "
                    f"W{row['wins']} L{row['losses']}  "
                    f"crown {row['crown_diff']:+.2f}  "
                    f"hog {row['hog_share']:.0%}")
            self.final[label] = rows

    def stop(self, attempt: Attempt) -> None:
        if attempt.process.poll() is None:
            attempt.process.kill()
            try:
                attempt.process.wait(timeout=120)
            except subprocess.TimeoutExpired:
                log("  training process would not exit")
        # The vectorised env spawns worker processes; a killed parent can
        # leave them holding cores that the next attempt needs.
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        "Where-Object { $_.CommandLine -like '*train_ppo*' } | "
                        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],
                       cwd=ROOT, capture_output=True)
        time.sleep(3)

    def recommended(self) -> str:
        """The checkpoint path the verdict actually points at.

        Printing the night's checkpoint next to a verdict that says to keep
        the incumbent is how the wrong policy ends up on ladder at 8am.
        """
        verdict = self.verdict_line()
        if "baseline is still better" in verdict:
            return "checkpoints\\sprint4_baseline\\pilot_best_4392960.pt"
        if "Tonight's policy is better" in verdict:
            return "checkpoints\\night\\best.pt"
        # Overlapping intervals: the incumbent has three hundred held-out
        # games behind it and tonight's has two hundred. Ties go to the one
        # with more evidence.
        return "checkpoints\\sprint4_baseline\\pilot_best_4392960.pt"

    def verdict_line(self) -> str:
        """Which checkpoint to play, stated plainly, or that neither is better.

        Overlapping confidence intervals mean the night did not beat the
        incumbent, and saying so is the useful answer. Reporting the higher
        of two overlapping numbers as an improvement is how a project talks
        itself into shipping noise.
        """
        def brain_row(label):
            for row in self.final.get(label, []):
                if row["opponent"] == "brain":
                    return row
            return None

        night, baseline = brain_row("night"), brain_row("baseline")
        if night is None:
            return ("No held-out result for tonight's policy - nothing to "
                    "compare, keep the existing baseline.")
        if baseline is None:
            return (f"Tonight's policy: {night['win_rate']:.1%} vs the rule "
                    f"engine. The baseline was not re-measured, so compare "
                    f"against its recorded 43.3% with that caveat.")
        if night["wilson_lo"] > baseline["wilson_hi"]:
            return (f"**Tonight's policy is better**: {night['win_rate']:.1%} "
                    f"[{night['wilson_lo']:.1%}-{night['wilson_hi']:.1%}] "
                    f"against the baseline's {baseline['win_rate']:.1%} "
                    f"[{baseline['wilson_lo']:.1%}-{baseline['wilson_hi']:.1%}]"
                    f" - the intervals do not overlap. Play "
                    "`checkpoints/night/best.pt`.")
        if baseline["wilson_lo"] > night["wilson_hi"]:
            return (f"**The baseline is still better**: "
                    f"{baseline['win_rate']:.1%} against tonight's "
                    f"{night['win_rate']:.1%}, intervals clear of each other. "
                    "Keep playing `checkpoints/sprint4_baseline/"
                    "pilot_best_4392960.pt`.")
        return (f"**Too close to call**: tonight {night['win_rate']:.1%} "
                f"[{night['wilson_lo']:.1%}-{night['wilson_hi']:.1%}] against "
                f"the baseline's {baseline['win_rate']:.1%} "
                f"[{baseline['wilson_lo']:.1%}-{baseline['wilson_hi']:.1%}]. "
                "The intervals overlap, so this is not an improvement that "
                "has been demonstrated - either is defensible to play, and "
                "the sim did not move tonight.")

    def report(self) -> None:
        lines = ["# Overnight RL supervision", "",
                 f"Finished {datetime.now():%Y-%m-%d %H:%M}.",
                 f"Best eval score {self.best_score:+.2f} from "
                 f"{self.best_from or 'nothing'}.", "",
                 "| attempt | rung | evals | why it stopped |",
                 "|---|---|---|---|"]
        for item in self.history:
            lines.append(f"| {item['attempt']} | {item['rung']} | "
                         f"{item['evals']} | {item['reason']} |")
        lines += ["", "## Held out, seed 9000 (never trained or selected on)",
                  "", "| policy | opponent | win rate | 95% CI | crown diff | hog |",
                  "|---|---|---|---|---|---|"]
        for label, rows in self.final.items():
            for row in rows:
                lines.append(
                    f"| {label} | {row['opponent']} | {row['win_rate']:.1%} | "
                    f"{row['wilson_lo']:.1%}-{row['wilson_hi']:.1%} | "
                    f"{row['crown_diff']:+.2f} | {row['hog_share']:.0%} |")

        lines += ["", "## Verdict", "", self.verdict_line()]
        lines += ["", "`checkpoints/night/best.pt` was selected during "
                  "training on a 40-episode eval against meta decks, which is "
                  "a smoke test. The table above is the number that counts: "
                  "the rule engine, on seeds no run touched, under the same "
                  "protocol the 43.3% baseline was measured with.",
                  "", f"To play the one above: `.\\run.ps1 -Brain rl "
                  f"-Checkpoint {self.recommended()} -Matches 5`"]
        KEEP.mkdir(parents=True, exist_ok=True)
        (KEEP / "SUPERVISION.md").write_text("\n".join(lines), encoding="utf-8")
        log(f"wrote {KEEP / 'SUPERVISION.md'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="night")
    parser.add_argument("--hours", type=float, default=12.0)
    parser.add_argument("--envs", type=int, default=16)
    parser.add_argument("--rollout", type=int, default=128)
    parser.add_argument("--steps", type=int, default=200_000_000,
                        help="high on purpose; the deadline ends the run")
    parser.add_argument("--value-warmup", type=int, default=300_000)
    parser.add_argument("--eval-every", type=int, default=500_000)
    parser.add_argument("--eval-episodes", type=int, default=40)
    parser.add_argument("--init", default=str(OUT / "clone_pilot.pt"))
    parser.add_argument("--opponent", default="brain",
                        choices=("brain", "meta", "simple", "mirror"),
                        help="the opponent the in-training eval scores "
                             "against, which is what selects the kept "
                             "checkpoint and drives every trigger")
    parser.add_argument("--poll", type=float, default=60.0)
    parser.add_argument("--win-drop", type=float, default=0.18,
                        help="how far below the clone's win rate is a failure")
    parser.add_argument("--hog-floor", type=float, default=0.06)
    parser.add_argument("--plays-ceiling", type=int, default=75)
    parser.add_argument("--severe-drop", type=float, default=0.30,
                        help="a single-eval collapse this far below the clone "
                             "is acted on without waiting for confirmation")
    parser.add_argument("--severe-hog", type=float, default=0.02)
    parser.add_argument("--hog-collapse", type=float, default=0.40,
                        help="fraction of the clone's hog share below which a "
                             "single eval is enough")
    parser.add_argument("--plays-blowout", type=float, default=1.6)
    parser.add_argument("--score-drop", type=float, default=1.0)
    parser.add_argument("--patience", type=int, default=4)
    parser.add_argument("--stall-minutes", type=float, default=20.0)
    parser.add_argument("--min-free-gb", type=float, default=10.0)
    parser.add_argument("--scripted-alt", default="meta",
                        choices=("meta", "mirror", "simple"),
                        help="the non-rule-engine half of the "
                             "scripted episodes")
    parser.add_argument("--scripted-share", type=float, default=None,
                        help="override every rung's scripted share; "
                             "a mirror run wants self-play to be the "
                             "majority because it is the only "
                             "opponent with headroom left")
    parser.add_argument("--brain-share", type=float, default=0.5,
                        help="fraction of non-self-play episodes vs the "
                             "rule engine; the rest are meta decks")
    parser.add_argument("--eval-opponent", default="brain",
                        help="who the in-training eval selects on")
    parser.add_argument("--audit-opponents", nargs="+",
                        default=["brain", "meta"],
                        help="every axis the held-out audit checks; a "
                             "regression on any of them stops the run")
    parser.add_argument("--audit-anchor", default="",
                        help="starting held-out scores as "
                             "name=rate,name=rate - so the first audit "
                             "tests against the policy the run began "
                             "from instead of anchoring on itself")
    parser.add_argument("--audit-every", type=int, default=3_000_000,
                        help="steps between held-out re-measurements of "
                             "the kept checkpoint on seed 8000")
    parser.add_argument("--audit-episodes", type=int, default=60)
    parser.add_argument("--audit-drop", type=float, default=0.12,
                        help="held-out regression against the first "
                             "audit that stops the attempt")
    parser.add_argument("--audit-timeout", type=float, default=900.0)
    parser.add_argument("--max-attempts", type=int, default=12,
                        help="hard cap on restarts, so a fault the ladder "
                             "cannot fix does not churn all night")
    parser.add_argument("--final-episodes", type=int, default=200,
                        help="held-out games per opponent at the end")
    parser.add_argument("--final-timeout", type=float, default=2400.0)
    args = parser.parse_args()
    if args.audit_anchor:
        args.audit_anchor = {
            part.split("=")[0].strip(): float(part.split("=")[1])
            for part in args.audit_anchor.split(",") if "=" in part}
    else:
        args.audit_anchor = {}
    return Supervisor(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
