from __future__ import annotations

from typing import Any

from ..models import Action


class PyClashBotFrameSource:
    def __init__(self, controller: Any):
        self.controller = controller

    def capture(self):
        return self.controller.screenshot()


class PyClashBotActionSink:
    """Delegates normalized actions to an existing py-clash-bot controller."""

    def __init__(
        self,
        controller: Any,
        *,
        frame_width: int,
        frame_height: int,
        card_centres: tuple[tuple[int, int], ...],
    ) -> None:
        if len(card_centres) != 4:
            raise ValueError("exactly four card centres are required")
        self.controller = controller
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.card_centres = card_centres

    def execute(self, action: Action) -> None:
        action.validate()
        if action.is_wait:
            return
        card_x, card_y = self.card_centres[action.card_slot]
        target_x = round(action.x * (self.frame_width - 1))
        target_y = round(action.y * (self.frame_height - 1))
        self.controller.click(card_x, card_y, clicks=1, interval=0.0)
        self.controller.click(target_x, target_y, clicks=1, interval=0.0)

