"""Does an independent source still agree with the numbers the sim runs on?

`card_catalog_audit` proves every public card maps to a local row. That is an
identity check: it would pass just as happily if every cost on those rows were
wrong. This checks the values, for the two fields where being wrong is silent.

Rarity is the dangerous one. Card stats are scaled from level-1 bases by
rarity, so a card filed under the wrong rarity has the wrong hitpoints and
damage at every level while parsing perfectly - which is this codebase's
signature failure, and the reason the movement-speed bug survived a full green
suite.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.public_stat_audit import KNOWN_DIVERGENCES, report    # noqa: E402

DATA = report()


def test_every_public_card_maps_and_is_checked():
    assert DATA["mapped"] == DATA["public_cards"]
    assert DATA["values_checked"] >= DATA["mapped"], DATA["values_checked"]
    assert not DATA["unchecked"], DATA["unchecked"]


def test_no_unexplained_divergence_from_the_public_snapshot():
    """A new divergence means one of the two sources moved.

    Do not silence this by adding the card to KNOWN_DIVERGENCES. Read the
    client row first; the entry has to quote what the shipped file says,
    because the whole point is that the game's own files win on evidence
    rather than by assumption.
    """
    rows = DATA["unexplained_divergences"]
    assert not rows, "\n".join(
        f"{r['local_name']}.{r['field']}: snapshot={r['snapshot']} sim={r['sim']}"
        for r in rows)


def test_known_divergences_are_all_still_real():
    """A recorded divergence that has resolved should be deleted, not kept.

    A stale entry is an exemption nobody is checking any more, and it would
    hide a genuine regression on that exact field.
    """
    still_diverging = {row["public_key"] for row in DATA["explained_divergences"]}
    stale = set(KNOWN_DIVERGENCES) - still_diverging
    assert not stale, f"no longer diverging, remove them: {sorted(stale)}"


def test_each_known_divergence_cites_the_shipped_row():
    for key, (field, snapshot, local, why) in KNOWN_DIVERGENCES.items():
        assert field in ("elixir", "rarity"), key
        assert snapshot != local, key
        # The justification has to point at a file, not merely assert.
        assert ".csv" in why or ".toml" in why, key
