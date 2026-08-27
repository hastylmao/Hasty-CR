from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class BoundingBox:
    left: float
    top: float
    right: float
    bottom: float


@dataclass(frozen=True)
class Entity:
    name: str
    side: str
    confidence: float = 1.0
    box: BoundingBox | None = None
    tile: tuple[int, int] | None = None


@dataclass(frozen=True)
class GameState:
    frame: Any = None
    screen: str = "unknown"
    elixir: float | None = None
    hand: Sequence[str] = field(default_factory=tuple)
    ready_slots: Sequence[int] = field(default_factory=tuple)
    allies: Sequence[Entity] = field(default_factory=tuple)
    enemies: Sequence[Entity] = field(default_factory=tuple)
    tower_hp: Mapping[str, int] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """A normalized action. Coordinates are fractions in the closed interval [0, 1]."""

    card_slot: int | None = None
    x: float | None = None
    y: float | None = None

    @classmethod
    def wait(cls) -> "Action":
        return cls()

    @property
    def is_wait(self) -> bool:
        return self.card_slot is None

    def validate(self) -> None:
        if self.is_wait:
            if self.x is not None or self.y is not None:
                raise ValueError("wait actions cannot contain coordinates")
            return
        if self.card_slot not in range(4):
            raise ValueError("card_slot must be between 0 and 3")
        if self.x is None or self.y is None:
            raise ValueError("card actions require x and y")
        if not (0.0 <= self.x <= 1.0 and 0.0 <= self.y <= 1.0):
            raise ValueError("action coordinates must be normalized to [0, 1]")

