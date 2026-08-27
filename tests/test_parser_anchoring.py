"""Are data-key lookups anchored to the start of a line?

The recurring fault in this codebase is a key searched for without anchoring,
so a longer key swallows a shorter one and returns a number that looks
plausible. It has landed three times: SpeedMultiplier matched inside
HitSpeedMultiplier and got 18 buffs wrong, and Radius matched inside
ProjectileStartRadius and modelled Fireball at about a quarter of its blast.

Every one survived because the case used to verify it was symmetric - Freeze
is -100/-100, so a parser reading one field twice looks correct. These tests
use a deliberately asymmetric case, and guard the source itself so the next
occurrence fails here rather than in a match.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GAMEDATA = ROOT / "tmp" / "gamedata" / "csv_logic"
BUFF = re.compile(r"\[BUFF\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)", re.S)

# The asymmetric case. Archer Queen's ability is +280 attack speed and -25
# movement; a lookup that is not anchored reports +280 for both.
ASYMMETRIC = ("archer_queen.toml", "ArcherQueenRapid", "SpeedMultiplier", -25, 280)


def _buff_body(filename: str, buff: str) -> str:
    for path in GAMEDATA.rglob(filename):
        for match in BUFF.finditer(path.read_text(errors="ignore")):
            if match.group(1) == buff:
                return match.group(2)
    raise AssertionError(f"{buff} not found in {filename}")


def test_anchored_lookup_reads_the_real_movement_penalty():
    filename, buff, key, truth, decoy = ASYMMETRIC
    body = _buff_body(filename, buff)
    found = re.search(rf"^\s*{key}\s*=\s*(-?\d+)", body, re.M)
    assert found is not None and int(found.group(1)) == truth


def test_unanchored_lookup_would_still_read_the_wrong_number():
    """The decoy is real, so the guard below is not theoretical."""
    filename, buff, key, truth, decoy = ASYMMETRIC
    body = _buff_body(filename, buff)
    found = re.search(rf"{key}\s*=\s*(-?\d+)", body)
    assert found is not None and int(found.group(1)) == decoy != truth


def test_no_unanchored_data_key_lookups_in_the_simulator():
    r"""A key lookup built from a field name must be anchored to a line start.

    Matches a regex literal or an f-string/concatenated key followed by an
    `=` and a number, without a leading `^`. Section headers such as
    `\[BUFF\.` are not key lookups and are excluded by requiring the pattern
    to reach for a value.
    """
    offenders = []
    # re.match anchors at the start of the string by construction, so only
    # the scanning forms can let a longer key swallow a shorter one.
    lookup = re.compile(r"""re\.(?:search|findall|finditer)\(\s*(?:rf?|f)?["'](.*?)["']""")
    for path in sorted((ROOT / "sim").glob("*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(source.splitlines(), 1):
            for pattern in lookup.findall(line):
                if r"\s*=\s*" not in pattern:
                    continue
                if pattern.startswith("^"):
                    continue
                offenders.append(f"{path.name}:{number}: {pattern}")
        # A key held in a variable is concatenated rather than inlined, so it
        # does not appear inside the string literal above.
        for number, line in enumerate(source.splitlines(), 1):
            if re.search(r"""re\.(?:search|match)\(\s*(?:r?["']\^)""", line):
                continue
            if re.search(r"""re\.(?:search|match)\(\s*key\s*\+""", line):
                offenders.append(f"{path.name}:{number}: unanchored variable key")
    assert not offenders, "unanchored data-key lookups:\n" + "\n".join(offenders)
