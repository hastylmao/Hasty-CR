from __future__ import annotations

from typing import Any

from ..models import BoundingBox, Entity, GameState


class BuildABotPerception:
    """Maps a configured BuildABot Detector result into HastyCR's neutral state."""

    def __init__(self, detector: Any):
        self.detector = detector

    @staticmethod
    def _entity(item: Any, side: str) -> Entity:
        position = item.position
        box = BoundingBox(*map(float, position.bbox))
        return Entity(
            name=str(item.unit.name),
            side=side,
            confidence=float(position.conf),
            box=box,
            tile=(int(position.tile_x), int(position.tile_y)),
        )

    def observe(self, frame: Any) -> GameState:
        upstream = self.detector.run(frame)
        if upstream is None:
            return GameState(frame=frame)
        numbers = upstream.numbers
        tower_hp = {
            name: int(getattr(numbers, name).number)
            for name in (
                "left_ally_princess_hp",
                "right_ally_princess_hp",
                "ally_king_hp",
                "left_enemy_princess_hp",
                "right_enemy_princess_hp",
                "enemy_king_hp",
            )
            if hasattr(numbers, name)
        }
        return GameState(
            frame=frame,
            screen=str(getattr(upstream.screen, "name", upstream.screen)),
            elixir=float(numbers.elixir.number),
            hand=tuple(card.name for card in upstream.cards),
            ready_slots=tuple(upstream.ready),
            allies=tuple(self._entity(item, "ally") for item in upstream.allies),
            enemies=tuple(self._entity(item, "enemy") for item in upstream.enemies),
            tower_hp=tower_hp,
            metadata={"upstream": "ClashRoyaleBuildABot"},
        )
