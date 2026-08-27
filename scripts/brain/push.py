"""Pushes as committed multi-card plans, not one card at a time.

The complaint that prompted this: "it just puts hog alone which doesn't get much
damage in and then puts some random troops near crown tower". Both halves were
literally true of the old engine. It scored every card independently each tick,
so the Hog went in by itself, and whatever the scorer liked next tick - often a
cycle card at the back - looked like an unrelated random placement.

A push is a *plan*: an ordered list of steps with timing, created once and then
executed. Three plans, all standard 2.6:

* `golem_hog`   - Ice Golem at the bridge, wait ~1s, Hog behind it. The Golem
                  soaks a Fireball and pulls defenders off the Hog. This is the
                  default push and the one the guides describe.
* `punish`      - Hog alone, immediately, in the lane opposite whatever they
                  just committed behind their towers. Only when their elixir is
                  too low to answer.
* `counterpush` - Hog on the back of a defence that is already holding, so their
                  elixir is in our half and the lane is open.

The rule that stops the Hog dying alone: a plan is only *started* when we can
afford the whole thing, and `hog_alone` is only allowed when the opponent is
measurably short on elixir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

COSTS = {
    "cannon": 3, "fireball": 4, "hog_rider": 4, "ice_golem": 2,
    "ice_spirit": 1, "musketeer": 4, "skeletons": 1, "the_log": 2,
}


# Ice Spirit is `Speed = 120` in the client data - exactly the same as Hog
# Rider. So a support delay is a *lateness*: at 1.2s the Spirit arrived well
# after the defence had already engaged the Hog and its freeze hit nothing that
# mattered. Sent a few tenths behind, it arrives while the defender is mid-swing
# and the freeze buys the Hog an extra hit or two. That is the actual 2.6 combo,
# and the bot was spending the card without getting it.
SUPPORT_DELAY = 0.4


@dataclass
class Step:
    card: str
    role: str           # "tank" | "win_condition" | "support"
    delay: float = 0.0  # seconds to wait after the previous step landed
    optional: bool = False   # skipped rather than stalling the push


@dataclass
class Plan:
    name: str
    lane: str
    steps: List[Step]
    created_at: float
    index: int = 0
    last_step_at: float = 0.0
    abandoned: bool = False

    @property
    def done(self) -> bool:
        return self.index >= len(self.steps)

    @property
    def current(self) -> Optional[Step]:
        return None if self.done else self.steps[self.index]

    @property
    def remaining_cost(self) -> int:
        return sum(COSTS.get(step.card, 4) for step in self.steps[self.index:])

    @property
    def total_cost(self) -> int:
        """What the push must cost to be worth starting.

        Optional steps are excluded: requiring the whole seven elixir of
        Golem plus Hog plus Spirit up front meant the push rarely started at
        all, when the first six are what matters and the Spirit is a bonus if
        it happens to be affordable when its turn comes.
        """
        return sum(COSTS.get(step.card, 4) for step in self.steps
                   if not step.optional)

    def skip(self, now: float) -> None:
        """Drop an optional step we cannot pay for, rather than stalling."""
        self.index += 1
        self.last_step_at = now

    def ready(self, now: float) -> bool:
        step = self.current
        if step is None:
            return False
        if self.index == 0:
            return True
        return now - self.last_step_at >= step.delay

    def advance(self, now: float) -> None:
        self.index += 1
        self.last_step_at = now


PLAN_EXPIRY_SECONDS = 9.0


def build_plan(name: str, lane: str, hand: dict, now: float) -> Optional[Plan]:
    """Create a plan only if every card it needs is actually in hand."""
    if name == "golem_hog":
        if "ice_golem" not in hand or "hog_rider" not in hand:
            return None
        steps = [
            Step("ice_golem", "tank"),
            # One second is the guide timing: long enough for the Golem to be
            # in front, short enough that they cannot answer them separately.
            Step("hog_rider", "win_condition", delay=1.0),
            Step("ice_spirit", "freeze", delay=SUPPORT_DELAY, optional=True),
        ]
    elif name == "punish":
        if "hog_rider" not in hand:
            return None
        steps = [Step("hog_rider", "win_condition")]
    elif name == "probe":
        # No Ice Golem in hand. A lone Hog is still correct 2.6 - the guides
        # call it testing their defence - but only with elixir to spare, so
        # that losing the trade does not also lose the tower.
        if "hog_rider" not in hand:
            return None
        steps = [Step("hog_rider", "win_condition")]
        if "ice_spirit" in hand:
            steps.append(Step("ice_spirit", "freeze", delay=SUPPORT_DELAY, optional=True))
    elif name == "counterpush":
        if "hog_rider" not in hand:
            return None
        steps = [Step("hog_rider", "win_condition")]
        for support in ("ice_spirit", "skeletons"):
            if support in hand:
                steps.append(Step(support, "support", delay=SUPPORT_DELAY, optional=True))
                break
    else:
        return None
    return Plan(name=name, lane=lane, steps=steps, created_at=now)


def expired(plan: Optional[Plan], now: float) -> bool:
    if plan is None:
        return True
    return plan.done or plan.abandoned or (now - plan.created_at) > PLAN_EXPIRY_SECONDS
