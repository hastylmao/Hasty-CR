"""Does the simulator find its data on a machine that is not this one?

`load_gamedata` defaulted to an absolute path inside one developer's home
directory, while the ten other loaders in the same module already resolved
through the file-relative `GAMEDATA_ROOT`. So the repository ran on exactly one
machine, and the failure would not have been obvious anywhere else: missing
data did not raise. With no `rarities.csv`, `scale_stat` falls through to
compounding the default 110% step and returns stats about 1.3% off the shipped
table - wrong, plausible, and silent, which is the shape of every expensive bug
this project has had.
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import GAMEDATA_ROOT, load_gamedata, scale_stat  # noqa: E402

# Anything that pins a path to one person's machine. The account name is
# captured so a documentation example using a placeholder is not flagged: the
# point is to catch a real home directory, not to ban writing down what a path
# looks like.
USER_PATH = re.compile(
    r"(?:[A-Za-z]:[\\/]+Users|/home|/Users)[\\/]+([A-Za-z0-9_.-]+)",
    re.IGNORECASE)
PLACEHOLDERS = {"you", "user", "username", "youruser", "yourname", "me",
                "someone", "example", "name"}


def test_the_data_root_lives_under_the_repository():
    assert GAMEDATA_ROOT.is_dir(), GAMEDATA_ROOT
    assert ROOT in GAMEDATA_ROOT.parents, GAMEDATA_ROOT


def test_missing_data_raises_instead_of_scaling_by_a_fallback_curve():
    with pytest.raises(FileNotFoundError):
        load_gamedata(level=11, root=ROOT / "does" / "not" / "exist")


def test_the_fallback_curve_really_would_have_been_wrong():
    """Guards the premise, so the test above is not protecting nothing.

    If an empty rarity table ever started agreeing with the shipped one, the
    silent-failure argument would no longer hold and this should be revisited.
    """
    shipped = load_gamedata(level=11)["knight"].unit.hitpoints
    fallback = scale_stat(1400, "Common", 11, {})
    assert fallback != shipped
    assert scale_stat(1400, "Common", 11, {}) == 3630


def test_no_module_hardcodes_a_path_into_somebodys_home_directory():
    offenders = []
    for path in sorted(list((ROOT / "sim").glob("*.py"))
                       + list((ROOT / "scripts").glob("*.py"))):
        for number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            found = USER_PATH.search(line)
            if found and found.group(1).lower() not in PLACEHOLDERS:
                offenders.append(f"{path.name}:{number}: {line.strip()[:90]}")
    assert not offenders, "\n".join(offenders)


def test_every_shipped_toml_parses_with_the_real_parser():
    """`parse_toml_file` falls back to a hand-written parser on any exception.

    That fallback is a simplified reimplementation, and it is silent: a data
    drop containing one file tomllib rejects would quietly start being read by
    different rules than the other 250. Today none of them take that path, and
    this is what says so.
    """
    tomllib = pytest.importorskip("tomllib")
    rejected = []
    for path in sorted(GAMEDATA_ROOT.rglob("*.toml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        try:
            tomllib.loads(text)
        except Exception as error:                       # noqa: BLE001
            rejected.append(f"{path.name}: {type(error).__name__}: {error}")
    assert not rejected, rejected[:10]
