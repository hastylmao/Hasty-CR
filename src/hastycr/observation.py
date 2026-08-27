"""Non-breaking deployable observation projection and explicit noise injection."""
from __future__ import annotations

from dataclasses import dataclass, replace
import random
from typing import Any, Mapping, Sequence

from .models import BoundingBox, Entity, GameState


@dataclass(frozen=True)
class ObservationNoise:
    seed: int = 0
    position_sigma: float = 0.0
    confidence_sigma: float = 0.0
    drop_probability: float = 0.0
    elixir_sigma: float = 0.0

    def validate(self) -> None:
        if self.position_sigma < 0 or self.confidence_sigma < 0 or self.elixir_sigma < 0:
            raise ValueError("observation noise sigmas must be nonnegative")
        if not 0.0 <= self.drop_probability <= 1.0:
            raise ValueError("drop_probability must be between 0 and 1")


class DeployableObservationAdapter:
    """Wrap a perception backend while preserving the GameState contract."""

    def __init__(self, backend: Any, *, noise: ObservationNoise | None = None) -> None:
        self.backend = backend
        self.noise = noise or ObservationNoise()
        self.noise.validate()
        self._observation_index = 0

    def observe(self, frame: Any) -> GameState:
        state = self.backend.observe(frame)
        if not isinstance(state, GameState):
            raise TypeError("perception backend must return GameState")
        observation_index = self._observation_index
        self._observation_index += 1
        return inject_observation_noise(state, self.noise, observation_index=observation_index)


def inject_observation_noise(
    state: GameState,
    noise: ObservationNoise,
    *,
    observation_index: int = 0,
) -> GameState:
    noise.validate()
    rng = random.Random(f"{noise.seed}:{observation_index}")
    allies = _corrupt_entities(state.allies, rng, noise)
    enemies = _corrupt_entities(state.enemies, rng, noise)
    elixir = state.elixir
    if elixir is not None and noise.elixir_sigma:
        elixir = min(10.0, max(0.0, elixir + rng.gauss(0.0, noise.elixir_sigma)))
    metadata = {
        **state.metadata,
        "observation_adapter": "DeployableObservationAdapter",
        "observation_noise": {
            "seed": noise.seed,
            "observation_index": observation_index,
            "position_sigma": noise.position_sigma,
            "confidence_sigma": noise.confidence_sigma,
            "drop_probability": noise.drop_probability,
            "elixir_sigma": noise.elixir_sigma,
        },
    }
    return replace(state, elixir=elixir, allies=allies, enemies=enemies, metadata=metadata)


def game_state_observation(state: GameState) -> dict[str, Any]:
    """Create a stable serializable view without changing GameState or KataCR tensors."""
    return {
        "schema_version": 1,
        "screen": state.screen,
        "elixir": state.elixir,
        "hand": list(state.hand),
        "ready_slots": list(state.ready_slots),
        "allies": [_entity_payload(entity) for entity in state.allies],
        "enemies": [_entity_payload(entity) for entity in state.enemies],
        "tower_hp": dict(state.tower_hp),
        "metadata": dict(state.metadata),
    }


def _corrupt_entities(
    entities: Sequence[Entity], rng: random.Random, noise: ObservationNoise,
) -> tuple[Entity, ...]:
    result = []
    for entity in entities:
        if noise.drop_probability and rng.random() < noise.drop_probability:
            continue
        box = entity.box
        if box is not None and noise.position_sigma:
            dx = rng.gauss(0.0, noise.position_sigma)
            dy = rng.gauss(0.0, noise.position_sigma)
            box = BoundingBox(box.left + dx, box.top + dy, box.right + dx, box.bottom + dy)
        confidence = entity.confidence
        if noise.confidence_sigma:
            confidence = min(1.0, max(0.0, confidence + rng.gauss(0.0, noise.confidence_sigma)))
        result.append(replace(entity, confidence=confidence, box=box))
    return tuple(result)


def _entity_payload(entity: Entity) -> dict[str, Any]:
    box = None if entity.box is None else {
        "left": entity.box.left, "top": entity.box.top,
        "right": entity.box.right, "bottom": entity.box.bottom,
    }
    return {
        "name": entity.name, "side": entity.side, "confidence": entity.confidence,
        "box": box, "tile": None if entity.tile is None else list(entity.tile),
    }
