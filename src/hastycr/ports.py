from __future__ import annotations

from typing import Any, Protocol

from .models import Action, GameState


class FrameSource(Protocol):
    def capture(self) -> Any: ...


class PerceptionBackend(Protocol):
    def observe(self, frame: Any) -> GameState: ...


class PolicyBackend(Protocol):
    def decide(self, state: GameState) -> Action: ...


class ActionSink(Protocol):
    def execute(self, action: Action) -> None: ...

