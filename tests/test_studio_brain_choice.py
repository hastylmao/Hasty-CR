"""The studio can start either brain, and says which one is playing.

Two policies now exist for the live bot: the hand-written rules with the local
Qwen advisor biasing them, and a policy trained in the simulator that decides
every play itself. They are launched through the same `run.ps1`, so the choice
has to survive three hops - studio combo, `BotController`, PowerShell - and a
wrong turn anywhere means playing the other brain without being told.

The failure that matters is silent: launching "sim-trained" and getting the
rules, or the reverse. So these check the arguments actually built, and that
liveness reporting reads the brain off the running process rather than
remembering what was requested.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

pytest.importorskip("psutil")

from studio.botctl import BotController, BotState                  # noqa: E402


class Recorder(BotController):
    """A controller that records launches instead of spawning anything."""

    def __init__(self):
        self.launched: list[tuple[list[str], str]] = []
        self.last_action = ""
        self.state = BotState()
        self._launched_at = 0.0

    def _launch(self, arguments, description):
        self.launched.append((list(arguments), description))
        self.last_action = description

    def _guard_is_clear(self):
        return True


def test_rules_mode_passes_no_brain_flag():
    """The default has to stay exactly what it was before rl existed."""
    bot = Recorder()
    bot.start_matches(5, 2.0, "rules")
    arguments, description = bot.launched[-1]
    assert "-Brain" not in arguments, arguments
    assert "-Checkpoint" not in arguments
    assert arguments[:4] == ["-Matches", "5", "-Hours", "2"]
    assert "rules + advisor" in description


def test_rl_mode_passes_the_brain_and_the_checkpoint():
    bot = Recorder()
    bot.start_matches(3, 1.5, "rl", "tmp/rl/hog26v6_best.pt")
    arguments, description = bot.launched[-1]
    assert "-Brain" in arguments and arguments[arguments.index("-Brain") + 1] == "rl"
    assert arguments[arguments.index("-Checkpoint") + 1] == "tmp/rl/hog26v6_best.pt"
    assert "simulator-trained" in description


def test_the_loop_button_carries_the_choice_too():
    """The supervisor path is the one that runs unattended for hours."""
    bot = Recorder()
    bot.start_supervisor("rl", "tmp/rl/hog26v6_best.pt")
    arguments, _description = bot.launched[-1]
    assert arguments[0] == "-Forever"
    assert "-Brain" in arguments and "rl" in arguments

    bot.start_supervisor("rules")
    arguments, _description = bot.launched[-1]
    assert arguments == ["-Forever"], arguments


def test_rl_without_a_checkpoint_still_names_the_brain():
    """run.ps1 has a default checkpoint; omitting the path must not mean rules."""
    bot = Recorder()
    bot.start_matches(5, 2.0, "rl", "")
    arguments, _description = bot.launched[-1]
    assert "-Brain" in arguments and arguments[arguments.index("-Brain") + 1] == "rl"
    assert "-Checkpoint" not in arguments


def test_an_unknown_brain_name_is_treated_as_rules():
    """Anything but 'rl' is the safe, existing behaviour."""
    bot = Recorder()
    bot.start_matches(5, 2.0, "qwen")
    arguments, _description = bot.launched[-1]
    assert "-Brain" not in arguments


# --------------------------------------------------------------- run.ps1 side

def read_launcher() -> str:
    return (ROOT / "run.ps1").read_text(encoding="utf-8")


def test_the_launcher_accepts_the_brain_parameter():
    text = read_launcher()
    assert "[ValidateSet('rules', 'rl')][string]$Brain" in text, (
        "run.ps1 does not declare -Brain, so the studio's argument would be "
        "rejected at launch")
    assert "'--rl', $checkpointPath" in text


def test_the_launcher_refuses_a_missing_checkpoint_rather_than_falling_back():
    """Silently playing the rules when you asked for rl is the bad outcome."""
    text = read_launcher()
    assert "Test-Path $checkpointPath" in text
    assert "exit 1" in text


def test_the_advisor_is_off_in_rl_mode():
    """It can only bias a rule engine, and there is no rule engine in rl mode."""
    text = read_launcher()
    assert "$useAdvisor = (-not $NoAdvisor) -and ($Brain -eq 'rules')" in text


def test_the_supervisor_forwards_the_checkpoint():
    text = (ROOT / "scripts" / "supervisor.py").read_text(encoding="utf-8")
    assert '"--rl", str(rl)' in text
    assert 'cmd += ["--advisor"]' in text, (
        "the supervisor should pass --advisor only on the rules path")


# ------------------------------------------------------------ what is running

# ------------------------------------------------------- which one is offered

class Combo:
    """Enough QComboBox for `_load_brain_choices`, without a Qt app."""

    def __init__(self):
        self.items: list[tuple[str, tuple[str, str]]] = []
        self.tips: dict[int, str] = {}
        self.tip = ""

    def clear(self):
        self.items.clear()

    def addItem(self, label, data):                         # noqa: N802 - Qt
        self.items.append((label, data))

    def count(self):                                        # noqa: N802 - Qt
        return len(self.items)

    def insertSeparator(self, index):                       # noqa: N802 - Qt
        self.items.append(("---", None))

    def setItemData(self, index, value, role):              # noqa: N802 - Qt
        self.tips[index] = value

    def toolTip(self):                                      # noqa: N802 - Qt
        return self.tip

    def setToolTip(self, text):                             # noqa: N802 - Qt
        self.tip = text


class Picker:
    def __init__(self):
        from studio.app import Studio
        self.brain = Combo()
        self.SCRATCH_SHOWN = Studio.SCRATCH_SHOWN
        self.OTHERS_SHOWN = Studio.OTHERS_SHOWN

    def _add_mode(self, path, record):
        from studio.app import Studio
        Studio._add_mode(self, path, record)

    @staticmethod
    def _checkpoint_record(path):
        from studio.app import Studio
        return Studio._checkpoint_record(path)

    @staticmethod
    def _manifest(path):
        from studio.app import Studio
        return Studio._manifest(path)


def load_choices(vetted_root, scratch_root, monkeypatch):
    """Selectable rows only - separators are furniture, not choices."""
    from studio import app as studio_app
    monkeypatch.setattr(studio_app, "VETTED_CHECKPOINTS", vetted_root)
    monkeypatch.setattr(studio_app, "RL_CHECKPOINTS", scratch_root)
    picker = Picker()
    studio_app.Studio._load_brain_choices(picker)
    return [row for row in picker.brain.items if row[1] is not None]


@pytest.fixture
def two_roots(tmp_path):
    """A vetted checkpoint with a manifest, and a newer scratch one."""
    import json
    import os
    import time

    vetted = tmp_path / "checkpoints" / "sprint4_baseline"
    vetted.mkdir(parents=True)
    (vetted / "good.pt").write_bytes(b"x")
    (vetted / "manifest.json").write_text(json.dumps({
        "held_out": {"brain_300": {"wins": 130, "losses": 170, "draws": 0},
                     "brain_100": {"wins": 42, "losses": 58, "draws": 0}},
    }), encoding="utf-8")

    scratch = tmp_path / "tmp" / "rl"
    scratch.mkdir(parents=True)
    (scratch / "mid_run.pt").write_bytes(b"x")
    # Newer than the vetted one - which is the whole point of the ordering.
    later = time.time() + 60
    os.utime(scratch / "mid_run.pt", (later, later))
    return vetted.parent, scratch


def test_a_mode_manifest_is_shown_by_what_it_was_trained_against(
        tmp_path, monkeypatch):
    """"Hog vs Hog" is the thing that decides which one to play."""
    import json

    vetted = tmp_path / "checkpoints" / "mirror"
    vetted.mkdir(parents=True)
    (vetted / "mirror_best.pt").write_bytes(b"x")
    (vetted / "manifest.json").write_text(json.dumps({
        "mode": "Hog vs Hog", "order": 0,
        "measured": "88% rule engine on 2.6"}), encoding="utf-8")
    scratch = tmp_path / "tmp" / "rl"
    scratch.mkdir(parents=True)

    picker = Picker()
    from studio import app as studio_app
    monkeypatch.setattr(studio_app, "VETTED_CHECKPOINTS", vetted.parent)
    monkeypatch.setattr(studio_app, "RL_CHECKPOINTS", scratch)
    studio_app.Studio._load_brain_choices(picker)
    rows = [row for row in picker.brain.items if row[1] is not None]
    labels = [label for label, _data in rows]

    # The label is the name alone - short enough to survive the combo width.
    assert labels[1] == "Hog vs Hog", labels
    assert "mirror_best" not in labels[1], "the filename is not the useful part"
    # The numbers move to the hover, where they do not crowd out the name.
    tip = next(v for v in picker.brain.tips.values() if "Hog vs Hog" in v)
    assert "88% rule engine" in tip, tip


def test_modes_are_ordered_and_come_before_unlabelled_checkpoints(
        tmp_path, monkeypatch):
    import json

    root = tmp_path / "checkpoints"
    for name, order in (("ladder", 1), ("mirror", 0)):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / f"{name}.pt").write_bytes(b"x")
        (folder / "manifest.json").write_text(json.dumps(
            {"mode": f"mode-{order}", "order": order}), encoding="utf-8")
    plain = root / "other"
    plain.mkdir(parents=True)
    (plain / "nameless.pt").write_bytes(b"x")
    scratch = tmp_path / "tmp" / "rl"
    scratch.mkdir(parents=True)

    labels = [label for label, _d in load_choices(root, scratch, monkeypatch)]
    assert labels[1] == "mode-0" and labels[2] == "mode-1", labels
    assert labels[3].startswith("Sim: nameless"), labels


def test_the_scratch_list_is_capped_so_dead_runs_do_not_bury_the_modes(
        tmp_path, monkeypatch):
    """Thirty checkpoints accumulate and several are collapsed policies."""
    from studio.app import Studio

    vetted = tmp_path / "checkpoints"
    vetted.mkdir()
    scratch = tmp_path / "tmp" / "rl"
    scratch.mkdir(parents=True)
    for index in range(20):
        (scratch / f"run{index:02d}_best.pt").write_bytes(b"x")

    items = load_choices(vetted, scratch, monkeypatch)
    offered = [label for label, _d in items if label.startswith("scratch:")]
    assert len(offered) == Studio.SCRATCH_SHOWN, offered


def test_vetted_checkpoints_come_before_scratch_however_new_the_scratch_is(
        two_roots, monkeypatch):
    """A run writes into tmp/rl while it trains; that file is not a candidate."""
    vetted, scratch = two_roots
    items = load_choices(vetted, scratch, monkeypatch)
    labels = [label for label, _data in items]
    assert labels[0].startswith("Qwen")
    assert labels[1].startswith("Sim: good"), labels
    assert labels[2].startswith("scratch: mid_run"), labels


def test_the_label_quotes_the_largest_held_out_sample(two_roots, monkeypatch):
    """43% over 300 games, not 42% over 100 - and n is shown either way."""
    vetted, scratch = two_roots
    items = load_choices(vetted, scratch, monkeypatch)
    label = items[1][0]
    assert "43%" in label and "n300" in label, label


def test_a_self_eval_is_labelled_as_one(tmp_path, monkeypatch):
    """`live_candidate` reads 82% on its own eval and 24% held out."""
    import json
    from studio.app import Studio

    root = tmp_path / "checkpoints" / "old"
    root.mkdir(parents=True)
    (root / "c.pt").write_bytes(b"x")
    (root / "manifest.json").write_text(json.dumps({
        "eval": {"wins": 33, "losses": 7, "draws": 0, "hog_share": 0.17},
    }), encoding="utf-8")
    record = Studio._checkpoint_record(root / "c.pt")
    assert "self" in record, record
    assert "82%" in record and "n40" in record, record


def test_a_supervisor_manifest_is_read_and_marked_as_a_self_eval(tmp_path):
    """`scripts/rl_supervisor.py` nests its numbers under `trainer_best`."""
    import json
    from studio.app import Studio

    root = tmp_path / "checkpoints" / "night"
    root.mkdir(parents=True)
    (root / "best.pt").write_bytes(b"x")
    (root / "best.json").write_text(json.dumps({
        "attempt": "night1", "rung": "plan",
        "trainer_best": {"step": 2306048, "wins": 32, "losses": 8, "draws": 0,
                         "hog_share": 0.136},
        "supervisor_score": 1.12,
    }), encoding="utf-8")
    record = Studio._checkpoint_record(root / "best.pt")
    assert "80%" in record and "n40" in record, record
    assert "self" in record, "a 40-game smoke test must not read as held out"


def test_a_description_where_a_results_block_was_expected_does_not_raise(tmp_path):
    """Labels read foreign JSON; one bad shape must not empty the dropdown.

    The supervisor wrote `"eval": "<description>"` where manifests put a
    results dict, and indexing that string raised out of the combo builder -
    leaving the studio with no brains to choose from at all.
    """
    import json
    from studio.app import Studio

    root = tmp_path / "odd"
    root.mkdir()
    (root / "c.pt").write_bytes(b"x")
    (root / "manifest.json").write_text(json.dumps({
        "eval": "40 episodes vs meta decks - a smoke test, not held out",
    }), encoding="utf-8")
    assert Studio._checkpoint_record(root / "c.pt") == ""


def test_a_checkpoint_with_no_report_gets_no_invented_number(tmp_path):
    from studio.app import Studio
    (tmp_path / "bare.pt").write_bytes(b"x")
    assert Studio._checkpoint_record(tmp_path / "bare.pt") == ""


def test_the_friendly_toggle_reaches_the_launcher():
    """1v1 against a person: they press Battle, the bot must not."""
    bot = Recorder()
    bot.start_matches(3, 1.0, "rl", "checkpoints/mirror/mirror_best.pt",
                      friendly=True)
    arguments, description = bot.launched[-1]
    assert "-NoQueue" in arguments, arguments
    assert "friendly" in description


def test_friendly_is_off_by_default_so_ladder_still_queues():
    bot = Recorder()
    bot.start_matches(3, 1.0, "rl", "checkpoints/mirror/mirror_best.pt")
    arguments, _description = bot.launched[-1]
    assert "-NoQueue" not in arguments


def test_the_friendly_toggle_works_on_the_rules_brain_too():
    """Nothing about not-queueing is specific to the learned policy."""
    bot = Recorder()
    bot.start_matches(3, 1.0, "rules", friendly=True)
    arguments, _description = bot.launched[-1]
    assert "-NoQueue" in arguments
    assert "-Brain" not in arguments


def test_the_launcher_can_play_without_queueing_for_a_friendly():
    """A 1v1 against a human: they press Battle, the bot only plays."""
    text = read_launcher()
    assert "[switch]$NoQueue" in text
    assert "if ($NoQueue)    { $botArgs += '--no-queue' }" in text
    bot = (ROOT / "scripts" / "cr_bot.py").read_text(encoding="utf-8")
    assert '"--no-queue"' in bot, "the runner no longer accepts --no-queue"


def test_the_launcher_default_checkpoint_is_a_vetted_one():
    """It pointed at tmp\\rl\\hog26v6_best.pt, which won 1 of 59."""
    text = read_launcher()
    assert "checkpoints\\sprint4_baseline" in text, (
        "run.ps1's default -Checkpoint should be a frozen, evaluated policy, "
        "not a scratch file a training run can overwrite")
    assert "hog26v6_best.pt'" not in text


def test_liveness_reports_the_brain_from_the_command_line():
    """Read from the process, not from what we think we started."""
    from studio import botctl
    assert 'brain = "rl" if "--rl" in line.split() else "rules"' in (
        (ROOT / "scripts" / "studio" / "botctl.py").read_text(encoding="utf-8"))
    assert "brain" in BotState.__dataclass_fields__
    assert botctl.BotState().brain == ""
