"""Can every externally sourced number say where it came from?

`combat_rules.json` is the one sanctioned place to put a value the shipped
client files do not give, and the project's standing rule is that such a value
carries an official source. That rule is what separates this file from a list
of numbers somebody remembered - and a rule nothing checks is a rule that holds
until the first hurried evening.

The check is deliberately about provenance rather than plausibility. Whether
1451 is the right hitpoint total for Evolved Witch cannot be settled here; that
the entry names a Supercell blog post, a date, and the level it was read at can
be, and that is what makes the number auditable later.
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RULES = json.loads((ROOT / "data" / "royaleapi" / "combat_rules.json")
                   .read_text(encoding="utf-8"))["rules"]
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SOURCED = sorted(name for name, rule in RULES.items()
                 if isinstance(rule, dict)
                 and any(key.endswith("_override") for key in rule))


def _source_of(rule: dict):
    return rule.get("source") or (rule.get("sources") or [None])[0]


def test_there_are_sourced_rules_to_check():
    assert len(SOURCED) > 20, len(SOURCED)


@pytest.mark.parametrize("name", SOURCED)
def test_a_sourced_value_names_where_it_came_from(name):
    rule = RULES[name]
    source = _source_of(rule)
    assert source, f"{name} overrides a stat with no source"
    assert str(source).startswith("http"), (name, source)


@pytest.mark.parametrize("name", SOURCED)
def test_a_sourced_value_records_when_it_was_checked(name):
    """A balance number without a date cannot be known to be stale."""
    verified = RULES[name].get("verified_at")
    assert verified, f"{name} has no verified_at"
    assert ISO_DATE.match(str(verified)), (name, verified)


@pytest.mark.parametrize("name", SOURCED)
def test_a_sourced_value_records_the_level_it_was_read_at(name):
    """Stats scale with level, so a bare number means nothing without one.

    It is also load-bearing: `gamedata.carry_verified` uses this to place the
    value on the client's scaling curve, and treats a missing level as "applies
    everywhere", which for a level-specific stat would be wrong.
    """
    level = RULES[name].get("level")
    assert level is not None, f"{name} has no recorded level"
    assert 1 <= int(level) <= 15, (name, level)
