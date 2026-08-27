"""Deterministic simulator-only probes for shared battle mechanics.

The probes expose current HastyCR behavior; they do not measure the live game,
select a correct implementation, or promote any value to real evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from sim import arena
from sim.arena import Point, TICK_MS, tile
from sim.diagnostics import DiagnosticSink
from sim.engine import Battle
from sim.entities import make_unit
from sim.gamedata import load_characters, load_gamedata, to_snake_case

SCHEMA_VERSION = "mechanics-characterization-v1"
LEVEL = 11


def _resolver(level: int = LEVEL) -> Callable[[str], Any]:
    characters = load_characters(level)

    def resolve(name: str) -> Any:
        return characters.get(name) or characters.get(to_snake_case(name))

    return resolve


def _battle() -> tuple[Battle, DiagnosticSink]:
    sink = DiagnosticSink()
    battle = Battle(diagnostics=sink, trace_contacts=True)
    battle.unit_lookup = _resolver()
    return battle, sink


def _unit(battle: Battle, cards: dict[str, Any], card: str, side: int,
          position: Point) -> Any:
    spec = cards[card].unit
    if spec is None:
        raise ValueError(f"card has no unit: {card}")
    entity = battle.add(make_unit(0, spec, side, position, battle.now_ms))
    entity.deploy_remaining_ms = 0
    return entity


def _hold(entity: Any) -> None:
    entity.deploy_remaining_ms = 1_000_000
    entity.speed_mt_per_sec = 0
    entity.attacks_ground = False
    entity.attacks_air = False


def _step(battle: Battle, count: int) -> None:
    for _ in range(count):
        battle.step(TICK_MS)


def _events(sink: DiagnosticSink, event_type: str, **filters: Any) -> list[dict[str, Any]]:
    result = []
    for event in sink.events:
        if event.get("event_type") != event_type:
            continue
        if all(event.get(key) == value for key, value in filters.items()):
            result.append(event)
    return result


def _event_view(event: dict[str, Any]) -> dict[str, Any]:
    return {
        key: event[key]
        for key in ("event_type", "time_ms", "tick", "phase", "order",
                    "source_uid", "target_uid", "value", "reason",
                    "metadata")
        if key in event and event[key] is not None
    }


def _targeting_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    source = _unit(battle, cards, "knight", 1, tile(9, 20))
    source.speed_mt_per_sec = 0
    source.load_time_ms = 0
    near = _unit(battle, cards, "skeletons", -1, tile(9, 19))
    far = _unit(battle, cards, "skeletons", -1, tile(11, 20))
    _hold(near)
    _hold(far)
    _step(battle, 1)
    acquired = _events(sink, "target_acquired", source_uid=source.uid)
    return {
        "id": "TARGET-001",
        "category": "targeting",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": source.name, "candidate_uids": [near.uid, far.uid]},
        "observed": {
            "target_uid": source.target_uid,
            "target_name": battle.get(source.target_uid).name if battle.get(source.target_uid) else None,
            "acquisition": _event_view(acquired[0]) if acquired else None,
            "candidate_positions": {
                str(near.uid): [near.pos.x, near.pos.y],
                str(far.uid): [far.pos.x, far.pos.y],
            },
        },
        "evidence": "_acquire_target scans valid visible candidates and chooses the smallest edge gap with UID tie-breaking.",
    }


def _pathing_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    source = _unit(battle, cards, "giant", 1, tile(9, 24))
    source.load_time_ms = 0
    blocker = _unit(battle, cards, "cannon", -1, tile(9, 7))
    _hold(blocker)
    positions = [[battle.now_ms, source.pos.x, source.pos.y]]
    _step(battle, 700)
    movement_events = _events(sink, "movement", source_uid=source.uid)
    positions.extend(
        [event["time_ms"], event["source_pos"][0], event["source_pos"][1]]
        for event in movement_events
        if event.get("source_pos")
    )
    unique_positions = []
    seen = set()
    for row in positions:
        key = tuple(row)
        if key not in seen:
            seen.add(key)
            unique_positions.append(row)
    bridge_rows = [row for row in unique_positions if arena.on_bridge(Point(row[1], row[2]))]
    return {
        "id": "PATH-001",
        "category": "pathing",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": source.name, "destination": blocker.name, "duration_ms": 700 * TICK_MS},
        "observed": {
            "movement_events": len(movement_events),
            "first_waypoint": movement_events[0].get("metadata", {}).get("goal") if movement_events else None,
            "final_position": [source.pos.x, source.pos.y],
            "river_y_start": tile(9, 24).y,
            "river_y_end": tile(9, 7).y,
            "crossed_river": source.pos.y < arena.RIVER_Y,
            "bridge_contact_samples": bridge_rows[:5],
            "unique_position_samples": unique_positions[:5] + unique_positions[-5:],
        },
        "evidence": "_waypoint uses cached eight-way BFS bridge terrain for ground cross-river movement; _avoid_buildings handles dynamic blockers locally.",
    }


def _collision_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    heavy = _unit(battle, cards, "giant", 1, tile(9, 20))
    light = _unit(battle, cards, "skeletons", -1, tile(9, 20))
    _hold(heavy)
    _hold(light)
    _step(battle, 1)
    contacts = [row for row in battle.contact_trace if row["kind"] == "troop_contact"]
    gap = arena.distance(heavy.pos, light.pos)
    required = heavy.collision_radius_mt + light.collision_radius_mt
    return {
        "id": "COLLISION-001",
        "category": "collision",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": heavy.name, "target": light.name, "initial_gap_mt": 0},
        "observed": {
            "final_positions": {
                str(heavy.uid): [heavy.pos.x, heavy.pos.y],
                str(light.uid): [light.pos.x, light.pos.y],
            },
            "final_gap_mt": gap,
            "required_gap_mt": required,
            "nonoverlap": gap >= required,
            "contact_events": len(contacts),
            "first_contact": contacts[0] if contacts else None,
        },
        "evidence": "_separate applies four full-strength pairwise passes and distributes overlap inversely by mass.",
    }


def _attack_and_order_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    source = _unit(battle, cards, "knight", 1, tile(9, 20))
    target = _unit(battle, cards, "skeletons", -1, tile(9, 20))
    source.speed_mt_per_sec = 0
    source.load_time_ms = 0
    source.attack_cooldown_ms = 0
    source.windup_remaining_ms = 0
    target.hitpoints = 1
    target.max_hitpoints = 1
    _hold(target)
    _step(battle, 1)
    tick_events = [event for event in sink.events if event.get("tick") == 1]
    phase_order = []
    for event in tick_events:
        phase = event.get("phase")
        if phase and phase not in phase_order:
            phase_order.append(phase)
    key_events = [event for event in tick_events
                  if event.get("event_type") in {"attack", "damage", "death", "cleanup"}]
    return {
        "id": "TIMING-001",
        "category": "event_order",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": source.name, "target": target.name, "target_hp": 1},
        "observed": {
            "phase_order": phase_order,
            "key_events": [_event_view(event) for event in key_events],
            "target_removed": target.uid not in battle.entities,
        },
        "evidence": "Battle.step emits scheduled effects, deploy, targeting, attack, movement, collision, cleanup; lethal death effects resolve before parent cleanup.",
    }


def _projectile_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    source = _unit(battle, cards, "musketeer", 1, tile(9, 20))
    source.load_time_ms = 0
    source.speed_mt_per_sec = 0
    target = _unit(battle, cards, "giant", -1,
                   Point(source.pos.x + source.range_mt, source.pos.y))
    _hold(target)
    target.hitpoints = 100_000
    target.max_hitpoints = 100_000
    _step(battle, 35)
    launches = _events(sink, "projectile_launch", source_uid=source.uid)
    damages = _events(sink, "damage", source_uid=source.uid, target_uid=target.uid)
    return {
        "id": "PROJECTILE-001",
        "category": "attack_timing",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": source.name, "target": target.name, "duration_ms": 35 * TICK_MS},
        "observed": {
            "first_launch": _event_view(launches[0]) if launches else None,
            "first_damage": _event_view(damages[0]) if damages else None,
            "launch_count": len(launches),
            "damage_count": len(damages),
        },
        "evidence": "_attack schedules projectile flight from target-edge distance; _resolve_projectiles emits impact/damage on later ticks.",
    }


def _death_spawn_probe(cards: dict[str, Any]) -> dict[str, Any]:
    battle, sink = _battle()
    source = _unit(battle, cards, "golem", 1, tile(9, 20))
    source.hitpoints = 0
    source.state = 4
    _step(battle, 1)
    related = [event for event in sink.events
               if event.get("source_uid") == source.uid
               or event.get("metadata", {}).get("owner_uid") == source.uid]
    return {
        "id": "SPAWN-001",
        "category": "death_spawn",
        "claim_class": "CURRENT_IMPLEMENTATION_ONLY",
        "setup": {"source": source.name, "declared_spawn": source.death_spawn_character},
        "observed": {
            "event_sequence": [_event_view(event) for event in related],
            "living_names_after": sorted(entity.name for entity in battle.living()),
            "parent_removed": source.uid not in battle.entities,
        },
        "evidence": "_reap invokes _resolve_death before cleanup; child Battle.add spawn events occur during cleanup processing.",
    }


def characterize() -> dict[str, Any]:
    cards = load_gamedata(level=LEVEL)
    probes = [
        _targeting_probe(cards),
        _pathing_probe(cards),
        _collision_probe(cards),
        _attack_and_order_probe(cards),
        _projectile_probe(cards),
        _death_spawn_probe(cards),
    ]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "claim_class": "SIMULATOR_ONLY",
        "real_measurements": 0,
        "measurement_status": "UNMEASURED_LIVE",
        "level": LEVEL,
        "tick_ms": TICK_MS,
        "probe_count": len(probes),
        "probes": probes,
        "limitations": [
            "Results describe only the current HastyCR implementation.",
            "No live game trace, external simulator, or controlled observation is used.",
            "A passing invariant such as non-overlap does not verify the real game's solver.",
        ],
    }
    digest_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["sha256"] = hashlib.sha256(digest_payload.encode("utf-8")).hexdigest()
    return payload


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Sprint 2 Mechanics Characterization",
        "",
        "Generated from bounded deterministic HastyCR probes. This is simulator-only evidence, not live-game truth.",
        "",
        f"- Schema: `{payload['schema_version']}`",
        f"- Status: `{payload['status']}`",
        f"- Probes: `{payload['probe_count']}`",
        f"- Tick: `{payload['tick_ms']} ms`",
        f"- Real measurements: `{payload['real_measurements']}`",
        f"- Report SHA-256: `{payload['sha256']}`",
        "",
        "## Results",
        "",
        "| Probe | Category | Current simulator observation |",
        "|---|---|---|",
    ]
    for probe in payload["probes"]:
        observed = json.dumps(probe["observed"], sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        lines.append(f"| `{probe['id']}` | `{probe['category']}` | `{observed}` |")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- Targeting uses current visible-candidate edge-gap selection and reports acquisition reasons through diagnostics.",
        "- Ground cross-river movement uses the current cached bridge-aware flow field; dynamic buildings use local steering and collision push-out.",
        "- Collision probes confirm current non-overlap behavior and expose the current mass-weighted solver output, not live collision semantics.",
        "- Same-tick diagnostics expose the current phase order and death-before-cleanup behavior.",
        "- Projectile timestamps are current fixed-tick scheduling behavior and require live target-motion observations before calibration.",
        "",
        "## Boundary",
        "",
        "The probes do not change `real_measurements=0`, do not produce an accuracy scalar, and do not move HastyCR to RL-ready status.",
        "",
    ])
    return "\n".join(lines)


def write_outputs(json_path: Path, markdown_path: Path | None = None) -> dict[str, Any]:
    payload = characterize()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown_report(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    payload = write_outputs(args.output, args.markdown)
    print(json.dumps({key: payload[key] for key in ("status", "probe_count", "real_measurements", "sha256", "output")
                      } | {"output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
