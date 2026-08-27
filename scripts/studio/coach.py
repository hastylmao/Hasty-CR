"""What to do next, worked out from what the bot is actually doing.

A 1v1 against a person has a setup that is easy to get subtly wrong and hard
to notice: the emulator has to be on the 2.6 list or the policy holds every
card, the bot has to be told not to queue or it drags itself into ladder
between friendlies, and the friendly invite has to be accepted on the emulator
by hand because a bot told not to touch the lobby will not touch the lobby.

None of that is worth remembering. This reads the same log the rail reads and
says which step is next, so the window is the instructions.

Kept free of Qt on purpose: it is a state machine over observed facts, and the
drawing is somebody else's problem.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The eight the policy encodes. Anything else is priced at 99 elixir by
# `mask_from_live` and can never be played, so a wrong deck does not fail
# loudly - the bot just stands there holding.
DECK_26 = ("cannon", "fireball", "hog_rider", "ice_golem",
           "ice_spirit", "musketeer", "skeletons", "the_log")

# Cards whose detected name is not the card name. A Skeletons card puts three
# `skeleton` on the board; the hand is logged by card, but a play can be
# logged either way depending on where it came from.
ALIASES = {"skeleton": "skeletons", "log": "the_log"}


@dataclass
class Step:
    text: str
    done: bool = False
    blocked: bool = False


@dataclass
class Advice:
    headline: str
    steps: List[Step] = field(default_factory=list)
    warning: str = ""

    @property
    def next_step(self) -> Optional[Step]:
        return next((s for s in self.steps if not s.done), None)


def normalise(card: str) -> str:
    return ALIASES.get(card, card)


def foreign_cards(observed: Sequence[str]) -> List[str]:
    """Anything seen that the policy cannot play."""
    seen = {normalise(c) for c in observed if c and c not in ("?", "-")}
    return sorted(seen - set(DECK_26))


def advise(*, running: bool, friendly: bool, mode: str, screen: str,
           observed: Sequence[str], matches_done: int,
           brain: str = "rl") -> Advice:
    """The next thing to do, given what the log currently shows."""
    wrong = foreign_cards(observed)
    warning = ""
    if wrong:
        warning = (f"deck mismatch: {', '.join(wrong[:3])} is not in the 2.6 "
                   "list - the policy cannot play it and will hold instead")

    if brain != "rl":
        return Advice(
            "Pick a simulator-trained mode to test",
            [Step("Choose 'Hog vs Hog' in the brain selector"),
             Step("Tick 1v1"),
             Step("Press Play")], warning)

    steps = [
        Step("Set the emulator deck to the 2.6 list", done=not wrong,
             blocked=bool(wrong)),
        Step(f"Mode: {mode}", done=True),
        Step("Tick 1v1 so the bot never presses Battle", done=friendly),
        Step("Press Play", done=running),
        Step("Invite this account to a friendly from your phone",
             done=running and screen == "in_game"),
        Step("Accept the invite ON THE EMULATOR - the bot will not",
             done=running and screen == "in_game"),
    ]

    if wrong:
        headline = "Fix the deck first"
    elif not friendly:
        headline = "Tick 1v1 before starting, or it will queue for ladder"
    elif not running:
        headline = "Press Play, then invite from your phone"
    elif screen == "in_game":
        headline = f"Playing - match {matches_done + 1}"
    else:
        headline = "Waiting for a match - invite, then accept on the emulator"
    return Advice(headline, steps, warning)


# What is worth writing down afterwards. The win rate over five games says
# very little; how it loses says a lot, and these are the questions the
# simulator cannot answer for itself.
WATCH_FOR = (
    "Does it send the Hog, and does it stop when behind?",
    "Cannon placement - does it actually pull your Hog?",
    "Can you bait out the Log or Fireball and punish it?",
    "Does it over-commit at double elixir?",
    "Anything a person would never do.",
)
