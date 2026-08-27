from __future__ import annotations

from dataclasses import dataclass

from .models import Action, GameState
from .ports import ActionSink, FrameSource, PerceptionBackend, PolicyBackend


@dataclass(frozen=True)
class StepResult:
    state: GameState
    action: Action
    executed: bool


class ChimeraPipeline:
    """One perception-policy-action cycle with an explicit live-action gate."""

    def __init__(
        self,
        source: FrameSource,
        perception: PerceptionBackend,
        policy: PolicyBackend,
        sink: ActionSink,
        *,
        allow_live_actions: bool = False,
    ) -> None:
        self.source = source
        self.perception = perception
        self.policy = policy
        self.sink = sink
        self.allow_live_actions = allow_live_actions

    def step(self) -> StepResult:
        frame = self.source.capture()
        state = self.perception.observe(frame)
        action = self.policy.decide(state)
        action.validate()
        executed = self.allow_live_actions and not action.is_wait
        if executed:
            self.sink.execute(action)
        return StepResult(state=state, action=action, executed=executed)

