"""Are the externally verified balance values actually in effect?

`combat_rules.json` is the only place this project keeps numbers it could not
derive from the shipped files: balance changes read off Supercell's blog and
RoyaleAPI, each carrying a source URL and a verification date. They are the
most expensive data in the repository, because each one cost a human going and
checking.

The loader applies such an override only when the requested level exactly
matches the level the value was verified at. Every rule was verified at level
11 and the project runs at level 11, so all of them are in effect - and that is
worth asserting, because an override that quietly stops applying looks exactly
like a card that was never special.

The second test pins the hazard rather than the happy path: away from level 11
these values vanish with no warning, and `--level` is a real flag on the viewer
and the runner.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import load_gamedata                          # noqa: E402
from sim.level_audit import report                              # noqa: E402

PROJECT_LEVEL = 11


def test_every_verified_override_applies_at_the_level_we_run_at():
    data = report(PROJECT_LEVEL)
    assert data["rules_with_overrides"] > 0
    assert not data["carried"], [row["card"] for row in data["carried"]]
    assert not data["pinned"], [row["card"] for row in data["pinned"]]


def test_away_from_that_level_values_are_carried_not_dropped():
    """They used to vanish. Now they are extrapolated, and labelled as such.

    The distinction matters: an extrapolated value is sound enough to play
    against and must not be quoted as a measurement.
    """
    data = report(15)
    assert data["carried"], "verified values are being dropped again"
    assert data["values_carried"] >= len(data["carried"])


def test_the_witch_evolution_keeps_its_verified_buff_at_every_level():
    """One card, three levels, because this is where the defect showed.

    Evolved Witch is verified at 1451 hitpoints at level 11. She used to fall
    back to raw scaling anywhere else, which tracked the ordinary Witch exactly
    - so the evolution silently stopped being an evolution.
    """
    from sim.match import Match

    levels = [9, PROJECT_LEVEL, PROJECT_LEVEL + Match.MIRROR_LEVEL_BONUS]
    evolved, base = [], []
    for level in levels:
        cards = load_gamedata(level=level)
        evolved.append(cards["witch_ev1"].unit.hitpoints)
        base.append(cards["witch"].unit.hitpoints)

    # The verified value is used exactly at the level it was verified at.
    assert evolved[1] == 1451, evolved
    # And it is an evolution at every level, not only that one.
    for index, level in enumerate(levels):
        assert evolved[index] > base[index], (level, evolved[index], base[index])
    # Higher level, more hitpoints - the property the defect inverted.
    assert evolved == sorted(evolved), evolved


def test_verified_values_reach_the_level_mirror_resolves_at():
    """Mirror is not a hypothetical `--level`; it hits this every play.

    `Match.mirrored` loads the card table at `level + MIRROR_LEVEL_BONUS`, so
    if verified values stopped at their own level, every Mirror play in every
    match would silently use raw scaling instead.
    """
    from sim.match import Match

    higher = PROJECT_LEVEL + Match.MIRROR_LEVEL_BONUS
    data = report(higher)
    assert data["carried"], "Mirror's level gets no verified values again"


def test_a_mirrored_card_is_never_weaker_than_the_card_itself():
    """The defect, stated as the thing it cost.

    A card played one level higher must not come out worse. Evolved Witch used
    to drop from a verified 1451 hitpoints to 922 when mirrored.
    """
    from sim.match import Match

    at_level = load_gamedata(level=PROJECT_LEVEL)
    mirrored = load_gamedata(level=PROJECT_LEVEL + Match.MIRROR_LEVEL_BONUS)

    weaker = []
    for name, card in at_level.items():
        unit, other = card.unit, mirrored.get(name)
        if unit is None or other is None or other.unit is None:
            continue
        if other.unit.hitpoints < unit.hitpoints:
            weaker.append((name, unit.hitpoints, other.unit.hitpoints))
    assert not weaker, weaker


def test_carrying_returns_the_verified_value_untouched_at_its_own_level():
    """The property that makes the carry safe to have added.

    Level 11 is what the whole project runs at, so the fix had to be a no-op
    there or every existing result would have moved underneath it.
    """
    from sim.gamedata import carry_verified

    # An empty rarity table exercises the same branch: at the verified level
    # the override is returned before any scaling is consulted at all.
    for level in (1, 9, 11, 15):
        assert carry_verified(1451, 328, "Epic", level, {}, level) == 1451
    # And with no recorded level there is nothing to carry from.
    assert carry_verified(1451, 328, "Epic", 15, {}, None) == 1451
