"""Does the shot list still describe experiments this engine can answer?

The plan is only useful if every clip has a simulator counterpart that prints a
number, because the point of recording is to disagree with one. A probe whose
scenario has quietly broken - a renamed card, a changed trace key - would send
someone to film something nobody can compare against.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.probe_plan import PROBES, render                   # noqa: E402
from sim.readiness import REQUIRED_PROBE_CATEGORIES         # noqa: E402


def test_every_required_probe_category_has_clips():
    covered = {probe.category for probe in PROBES}
    assert covered == set(REQUIRED_PROBE_CATEGORIES), covered


def test_probe_identifiers_are_unique():
    idents = [probe.ident for probe in PROBES]
    assert len(idents) == len(set(idents)), idents


@pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.ident)
def test_each_probe_predicts_something_measurable(probe):
    """A scenario that raises would be recorded and then have nothing to meet."""
    prediction = probe.prediction()
    assert prediction
    assert not prediction.startswith("scenario failed"), prediction
    assert "not resolved by the spell loader" not in prediction, prediction


def test_the_king_tower_probe_still_finds_the_engagement_exemption():
    """TC-4 is the clip that decides the contact approximation.

    It is only worth filming while the engine actually exempts an engaged pair
    from separation. If that changes, the probe needs rewriting rather than
    silently becoming a test of nothing.
    """
    probe = next(p for p in PROBES if p.ident == "TC-4")
    assert "engaged_contact_exempt" in probe.prediction()


def test_render_produces_both_forms():
    full = render()
    checklist = render(checklist_only=True)
    assert "sim says" in full
    assert "sim says" not in checklist
    for probe in PROBES:
        assert probe.ident in full and probe.ident in checklist
