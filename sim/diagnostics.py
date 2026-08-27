"""Opt-in structured diagnostics for simulator calibration.

The engine holds ``None`` when diagnostics are disabled.  This module is only
imported by callers that opt in, keeping ordinary rollouts free of event
allocation and serialization work.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Optional


class DiagnosticSink:
    """Collect deterministic, normalized simulator events in memory."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.tick = 0
        self.time_ms = 0
        self.phase = "external"
        self.order = 0
        self._damage_cursor = 0

    def begin_tick(self, time_ms: int, dt_ms: int) -> None:
        self.tick += 1
        self.time_ms = time_ms
        self.phase = "tick"
        self.order = 0
        self.emit("tick_start", value=dt_ms, reason="fixed_step")

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self.emit("phase", reason=phase)

    def emit(
        self,
        event_type: str,
        *,
        source: Any = None,
        target: Any = None,
        source_uid: Optional[int] = None,
        target_uid: Optional[int] = None,
        position: Any = None,
        value: Optional[int | float] = None,
        reason: str = "",
        state: Any = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> dict[str, Any]:
        source_position = getattr(source, "pos", None)
        target_position = getattr(target, "pos", None)
        if position is not None:
            target_position = position
        event = {
            "event_type": event_type,
            "time_ms": self.time_ms,
            "tick": self.tick,
            "phase": self.phase,
            "order": self.order,
            "source_uid": source_uid if source_uid is not None else getattr(source, "uid", None),
            "target_uid": target_uid if target_uid is not None else getattr(target, "uid", None),
            "source_pos": self._point(source_position),
            "target_pos": self._point(target_position),
            "value": value,
            "reason": reason,
            "state": state,
        }
        if metadata:
            event["metadata"] = dict(metadata)
        self.events.append(event)
        self.order += 1
        return event

    def capture_damage(self, damage_log: list[tuple], entities: Mapping[int, Any]) -> None:
        for row in damage_log[self._damage_cursor:]:
            if len(row) < 4:
                continue
            time_ms, source_uid, target_uid, amount = row[:4]
            self.time_ms = int(time_ms)
            self.emit(
                "damage",
                source=entities.get(source_uid),
                target=entities.get(target_uid),
                source_uid=int(source_uid),
                target_uid=int(target_uid),
                value=amount,
                reason="damage_log",
                state=getattr(entities.get(target_uid), "state", None),
            )
        self._damage_cursor = len(damage_log)

    def digest(self) -> str:
        payload = json.dumps(
            self.events, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    def _point(point: Any) -> Optional[tuple[int, int]]:
        if point is None:
            return None
        return (int(point.x), int(point.y))
