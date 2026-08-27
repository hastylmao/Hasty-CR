"""The 1v1 checklist: what the studio tells you to do next.

The setup for a friendly against a person has three ways to go quietly wrong,
and none of them fail loudly:

* the emulator is not on the 2.6 list, so every card is priced at 99 elixir
  and masked out - the bot stands there holding and looks merely bad;
* 1v1 is not ticked, so the bot presses Battle and queues ladder in the gap
  between two friendlies;
* the invite is never accepted, because a bot told not to touch the lobby
  will not touch the lobby, and it waits forever looking busy.

So the checklist is the product, and these are its rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from studio import coach                                       # noqa: E402

GOOD_HAND = ["hog_rider", "cannon", "ice_spirit", "the_log"]


def advise(**overrides):
    base = dict(running=False, friendly=True, mode="mirror", screen="lobby",
                observed=GOOD_HAND, matches_done=0, brain="rl")
    base.update(overrides)
    return coach.advise(**base)


def test_the_deck_check_matches_the_policys_own_list():
    """Drifting from sim.runner.DECK_26 would make the check a lie."""
    from sim.runner import DECK_26 as REAL
    assert set(coach.DECK_26) == set(REAL), (
        "the coach's deck list has drifted from the one the policy encodes")


def test_a_clean_setup_walks_to_the_invite():
    advice = advise(running=True, screen="lobby")
    assert advice.warning == ""
    assert "invite" in advice.headline.lower()


def test_a_foreign_card_is_caught_and_blocks_the_first_step():
    advice = advise(observed=GOOD_HAND + ["mega_knight"])
    assert "mega_knight" in advice.warning
    assert "deck mismatch" in advice.warning
    assert advice.steps[0].blocked
    assert advice.headline == "Fix the deck first"


def test_the_detected_name_is_resolved_before_judging_it():
    """A Skeletons card puts three `skeleton` on the board."""
    assert coach.foreign_cards(["skeleton", "log"]) == []
    assert coach.normalise("skeleton") == "skeletons"


def test_placeholders_from_the_log_are_not_treated_as_cards():
    assert coach.foreign_cards(["?", "-", ""]) == []


def test_not_ticking_1v1_is_called_out_before_anything_starts():
    advice = advise(friendly=False)
    assert "ladder" in advice.headline
    assert not advice.steps[2].done


def test_the_checklist_completes_once_a_match_is_running():
    advice = advise(running=True, screen="in_game")
    assert advice.next_step is None, [s.text for s in advice.steps if not s.done]
    assert "Playing" in advice.headline


def test_a_match_in_progress_counts_from_one():
    assert "match 1" in advise(running=True, screen="in_game",
                               matches_done=0).headline
    assert "match 3" in advise(running=True, screen="in_game",
                               matches_done=2).headline


def test_the_rules_brain_is_steered_to_a_trained_mode():
    advice = advise(brain="rules")
    assert "simulator-trained" in advice.headline
    assert any("Hog vs Hog" in step.text for step in advice.steps)


def test_the_accept_step_says_where_to_tap():
    """The bot will not accept the invite, and that surprises people."""
    advice = advise(running=True)
    accept = [s for s in advice.steps if "Accept" in s.text]
    assert accept and "EMULATOR" in accept[0].text


def test_a_deck_warning_survives_a_match_already_being_underway():
    """Wrong deck mid-match is still wrong, and still worth saying."""
    advice = advise(running=True, screen="in_game",
                    observed=GOOD_HAND + ["golem"])
    assert "golem" in advice.warning


@pytest.mark.parametrize("card", coach.DECK_26)
def test_no_card_of_our_own_deck_is_ever_flagged(card):
    assert coach.foreign_cards([card]) == []
