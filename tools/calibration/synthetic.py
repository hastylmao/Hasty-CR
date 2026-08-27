"""Deterministic, explicitly synthetic observation corruption helpers."""
from __future__ import annotations

from dataclasses import replace
import math
import random
from typing import Any, Mapping

from .core import (NormalizedFrame, NormalizedTrace, Provenance, TrackedEntity,
                   Uncertainty, compare_traces)


def _normal(rng: random.Random, sigma: float) -> float:
    return rng.gauss(0.0, sigma) if sigma else 0.0


def corrupt_trace(trace: NormalizedTrace, config: Mapping[str, Any]) -> tuple[NormalizedTrace, dict[str, Any]]:
    """Corrupt a simulator trace without claiming measured data provenance."""
    time_shift = int(config.get("time_shift_ms", 0))
    translation = tuple(float(x) for x in config.get("translation", [0.0, 0.0]))
    sigma = float(config.get("position_noise_sigma", 0.0))
    drop_probability = float(config.get("drop_probability", 0.0))
    gap_tracks = {str(x) for x in config.get("gap_tracks", [])}
    gap_start = int(config.get("gap_start_ms", -1))
    gap_end = int(config.get("gap_end_ms", -1))
    seed = int(config.get("seed", 0))
    rng = random.Random(seed)
    dropped: list[str] = []
    frames: list[NormalizedFrame] = []
    for frame in trace.frames:
        entities: list[TrackedEntity] = []
        for entity in frame.entities:
            in_gap = entity.track_id in gap_tracks and gap_start <= frame.time_ms <= gap_end
            if in_gap or (drop_probability and rng.random() < drop_probability):
                dropped.append(f"{frame.time_ms}:{entity.track_id}")
                continue
            dx = translation[0] + _normal(rng, sigma)
            dy = translation[1] + _normal(rng, sigma)
            uncertainty = replace(entity.uncertainty, sigma=max(entity.uncertainty.sigma or 0.0, sigma), reason="synthetic corruption")
            entities.append(replace(entity, x=entity.x + dx, y=entity.y + dy,
                                     confidence=min(entity.confidence, 1.0 - min(0.5, sigma)),
                                     provenance=Provenance("synthetic", ("SYNTH-CORRUPTION",), "corrupt_trace"),
                                     uncertainty=uncertainty))
        events = tuple(replace(event, time_ms=max(0, event.time_ms + time_shift),
                               provenance=Provenance("synthetic", ("SYNTH-CORRUPTION",), "corrupt_trace"))
                       for event in frame.events)
        frames.append(replace(frame, time_ms=max(0, frame.time_ms + time_shift),
                              entities=tuple(entities), events=events,
                              source=Provenance("synthetic", ("SYNTH-CORRUPTION",), "corrupt_trace"),
                              metadata={**frame.metadata, "synthetic_corruption": True}))
    corrupted = replace(trace, frames=tuple(frames), trace_id=f"{trace.trace_id}:synthetic",
                        source=Provenance("synthetic", ("SYNTH-CORRUPTION",), "corrupt_trace"),
                        metadata={**trace.metadata, "synthetic_corruption": dict(config), "real_data_claim": False})
    ground_truth = {"time_shift_ms": time_shift, "translation": list(translation), "seed": seed,
                    "dropped_observations": dropped, "real_data_claim": False}
    return corrupted, ground_truth


def evaluate_identity(trace: NormalizedTrace) -> dict[str, float]:
    result = compare_traces(trace, trace, position_tolerance=0.0, time_tolerance_ms=0.0)
    values = {metric.name: float(metric.value or 0.0) for metric in result}
    return {"position_error": values.get("position.mean_error", 0.0),
            "timing_error_ms": values.get("timing.event_error", 0.0)}


def estimate_translation(reference: NormalizedTrace, observed: NormalizedTrace) -> tuple[float, float]:
    pairs = []
    time_shift = estimate_time_shift(reference, observed)
    by_time = {frame.time_ms: frame for frame in reference.frames}
    for frame in observed.frames:
        source = by_time.get(round(frame.time_ms - time_shift))
        if source is None:
            continue
        entities = {entity.track_id: entity for entity in source.entities}
        for entity in frame.entities:
            other = entities.get(entity.track_id)
            if other:
                pairs.append((entity.x - other.x, entity.y - other.y))
    if not pairs:
        return 0.0, 0.0
    return (sum(x for x, _ in pairs) / len(pairs), sum(y for _, y in pairs) / len(pairs))


def estimate_time_shift(reference: NormalizedTrace, observed: NormalizedTrace) -> float:
    reference_events = [event.time_ms for frame in reference.frames for event in frame.events]
    observed_events = [event.time_ms for frame in observed.frames for event in frame.events]
    if not reference_events or not observed_events:
        return 0.0
    return float(sum(observed_events) / len(observed_events) - sum(reference_events) / len(reference_events))
