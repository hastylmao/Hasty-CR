"""Canonical command-only deterministic replay for HastyCR.

The replay file contains initial match configuration and external player
commands only. Positions, entities, targets, effects, and outcomes remain
simulator-derived. The state digest is an audit/debug view, never replay
input.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from sim import arena
from sim.entities import Entity
from sim.gamedata import GAMEDATA_ROOT, load_gamedata
from sim.match import (DOUBLE_AT_MS, DOUBLE_MS, MAX_ELIXIR, OVERTIME_END_MS,
                       REGULAR_END_MS, SINGLE_MS, START_ELIXIR, TRIPLE_AT_MS,
                       TRIPLE_MS, Match)
from sim.runner import resolve_deck
from sim.spells import VERIFIED_RULES, load_spells


SCHEMA_VERSION = 1
SCHEMA_NAME = "hastycr-command-replay-v1"
RULESET_ID = "fixed-tick-match-v1"
_SOURCE_FILES = (
    Path("sim/arena.py"), Path("sim/entities.py"), Path("sim/engine.py"),
    Path("sim/match.py"), Path("sim/gamedata.py"), Path("sim/spells.py"),
    Path("tools/calibration/command_replay.py"),
)


class ReplayError(ValueError):
    """The replay is invalid or cannot be executed with this checkout."""


def _sha256_files(paths: Sequence[Path], root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted((Path(path) for path in paths), key=lambda item: item.as_posix()):
        absolute = path if path.is_absolute() else root / path
        if not absolute.is_file():
            continue
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(absolute.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def game_data_hash() -> str:
    """Hash every loaded game-data file and the verified combat rule table."""
    root = Path(GAMEDATA_ROOT).resolve()
    paths = [path for path in root.rglob("*") if path.is_file()]
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    rules = Path(VERIFIED_RULES).resolve()
    if rules.is_file():
        digest.update(b"verified_rules.json\0")
        digest.update(rules.read_bytes())
    return digest.hexdigest()


def simulator_revision() -> str:
    """Return a source-content revision that works on dirty checkouts."""
    root = Path(__file__).resolve().parents[2]
    return "source-sha256:" + _sha256_files(_SOURCE_FILES, root)


def _canonical(value: Any) -> Any:
    if isinstance(value, Entity):
        return {"uid": int(value.uid)}
    if isinstance(value, arena.Point):
        return [int(value.x), int(value.y)]
    if isinstance(value, Mapping):
        pairs = [(str(key), _canonical(item)) for key, item in value.items()]
        return {key: item for key, item in sorted(pairs, key=lambda pair: pair[0])}
    if isinstance(value, (set, frozenset)):
        items = [_canonical(item) for item in value]
        return sorted(items, key=canonical_json)
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name))
                for field in fields(value)}
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayError("non-finite value cannot enter a deterministic digest")
        normalized = float(format(value, ".15g"))
        return int(normalized) if normalized.is_integer() else normalized
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ReplayError(f"unsupported value in deterministic state: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _entity_state(entity: Entity) -> dict[str, Any]:
    return {field.name: _canonical(getattr(entity, field.name))
            for field in fields(entity)}


def _derived_battle_state(match: Match) -> dict[str, Any]:
    excluded_battle = {
        "entities", "diagnostics", "trace_contacts", "contact_trace",
        "unit_lookup", "_buildings_cache", "_buildings_stamp",
    }
    battle_payload: dict[str, Any] = {}
    for field in fields(match.battle):
        if field.name in excluded_battle:
            continue
        battle_payload[field.name] = _canonical(getattr(match.battle, field.name))
    return {
        "time_ms": int(match.elapsed_ms),
        "finished": bool(match.finished),
        "result": match.result,
        "level": int(match.level),
        "seed": int(match.seed),
        "regen_carry": int(match._regen_carry),
        "spell_damage": _canonical(match.spell_damage),
        "players": _canonical(match.players),
        "towers": _canonical(match.towers),
        "entities": {
            str(uid): _entity_state(entity)
            for uid, entity in sorted(match.battle.entities.items())
        },
        "battle": battle_payload,
    }


@lru_cache(maxsize=16)
def _state_schema() -> tuple[str, ...]:
    return tuple(field.name for field in fields(Entity))


def state_payload(match: Match) -> dict[str, Any]:
    """Return all mutable simulation state needed by the audit digest."""
    return _derived_battle_state(match)


def state_digest(match: Match) -> str:
    return hashlib.sha256(canonical_json(state_payload(match)).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InitialState:
    game_data_hash: str
    simulator_revision: str
    level: int
    seed: int
    decks: tuple[tuple[str, ...], tuple[str, ...]]
    duration_ticks: int = OVERTIME_END_MS // arena.TICK_MS
    tick_ms: int = arena.TICK_MS
    initial_elixir: int = START_ELIXIR
    max_elixir: int = MAX_ELIXIR
    auto_abilities: bool = False
    evolution_slots: tuple[tuple[int, tuple[tuple[str, str], ...]], ...] = ()
    ruleset: str = RULESET_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_data_hash": self.game_data_hash,
            "simulator_revision": self.simulator_revision,
            "level": self.level,
            "seed": self.seed,
            "duration_ticks": self.duration_ticks,
            "decks": {"1": list(self.decks[0]), "-1": list(self.decks[1])},
            "tick_ms": self.tick_ms,
            "initial_elixir": self.initial_elixir,
            "max_elixir": self.max_elixir,
            "auto_abilities": self.auto_abilities,
            "evolution_slots": {
                str(side): {card: evolved for card, evolved in mapping}
                for side, mapping in self.evolution_slots
            },
            "ruleset": self.ruleset,
            "arena": {
                "width_mt": arena.WIDTH, "height_mt": arena.HEIGHT,
                "river_y_mt": arena.RIVER_Y,
                "bridge_x_mt": list(arena.BRIDGE_X),
            },
            "rules": {
                "single_regen_ms": SINGLE_MS, "double_regen_ms": DOUBLE_MS,
                "triple_regen_ms": TRIPLE_MS, "double_at_ms": DOUBLE_AT_MS,
                "triple_at_ms": TRIPLE_AT_MS, "regular_end_ms": REGULAR_END_MS,
                "overtime_end_ms": OVERTIME_END_MS,
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "InitialState":
        decks = value.get("decks", {})
        if not isinstance(decks, Mapping):
            raise ReplayError("initial_state.decks must be an object")
        deck_bottom = tuple(str(item) for item in decks.get("1", ()))
        deck_top = tuple(str(item) for item in decks.get("-1", ()))
        if not deck_bottom or not deck_top:
            raise ReplayError("both initial decks are required")
        slots = value.get("evolution_slots", {})
        evolution_slots = tuple(
            (int(side), tuple(sorted((str(card), str(evolved))
                                     for card, evolved in mapping.items())))
            for side, mapping in sorted(slots.items(), key=lambda pair: str(pair[0]))
            if isinstance(mapping, Mapping)
        )
        return cls(
            str(value["game_data_hash"]), str(value["simulator_revision"]),
            int(value["level"]), int(value["seed"]), (deck_bottom, deck_top),
            int(value.get("duration_ticks", OVERTIME_END_MS // arena.TICK_MS)),
            int(value.get("tick_ms", arena.TICK_MS)),
            int(value.get("initial_elixir", START_ELIXIR)),
            int(value.get("max_elixir", MAX_ELIXIR)),
            bool(value.get("auto_abilities", False)), evolution_slots,
            str(value.get("ruleset", RULESET_ID)),
        )


@dataclass(frozen=True)
class Command:
    tick: int
    player: int
    command_type: str
    card: str | None = None
    x_mt: int | None = None
    y_mt: int | None = None
    actor_uid: int | None = None

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ReplayError("command tick must be nonnegative")
        if self.player not in (-1, 1):
            raise ReplayError("command player must be -1 or 1")
        if self.command_type not in {"PLAY_CARD", "ACTIVATE_ABILITY"}:
            raise ReplayError(f"unsupported command type: {self.command_type}")
        if self.command_type == "PLAY_CARD":
            if not self.card or self.x_mt is None or self.y_mt is None:
                raise ReplayError("PLAY_CARD requires card and placement coordinates")
        elif self.actor_uid is None:
            raise ReplayError("ACTIVATE_ABILITY requires actor_uid")

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "tick": self.tick, "player": self.player, "type": self.command_type,
        }
        if self.command_type == "PLAY_CARD":
            value.update({"card": self.card, "x_mt": self.x_mt, "y_mt": self.y_mt})
        else:
            value["actor_uid"] = self.actor_uid
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "Command":
        return cls(
            int(value["tick"]), int(value["player"]), str(value.get("type", "")),
            None if value.get("card") is None else str(value["card"]),
            None if value.get("x_mt") is None else int(value["x_mt"]),
            None if value.get("y_mt") is None else int(value["y_mt"]),
            None if value.get("actor_uid") is None else int(value["actor_uid"]),
        )


@dataclass(frozen=True)
class MatchReplay:
    initial_state: InitialState
    commands: tuple[Command, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ReplayError(f"unsupported replay schema {self.schema_version}")
        previous = -1
        for command in self.commands:
            if command.tick < previous:
                raise ReplayError("commands must be ordered by nondecreasing tick")
            previous = command.tick
        if self.initial_state.duration_ticks < 0:
            raise ReplayError("duration_ticks must be nonnegative")
        if self.commands and self.commands[-1].tick > self.initial_state.duration_ticks:
            raise ReplayError("command occurs after replay duration")
        if self.initial_state.tick_ms != arena.TICK_MS:
            raise ReplayError("current Match requires a 50ms tick")
        if self.initial_state.initial_elixir != START_ELIXIR:
            raise ReplayError("current Match requires its fixed initial elixir")
        if self.initial_state.max_elixir != MAX_ELIXIR:
            raise ReplayError("current Match requires its fixed elixir cap")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "schema": SCHEMA_NAME,
            "simulator_revision": self.initial_state.simulator_revision,
            "game_data_hash": self.initial_state.game_data_hash,
            "initial_state": self.initial_state.to_dict(),
            "commands": [command.to_dict() for command in self.commands],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "MatchReplay":
        if int(value.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ReplayError("unsupported command replay schema")
        initial = InitialState.from_dict(value["initial_state"])
        if str(value.get("simulator_revision", initial.simulator_revision)) != initial.simulator_revision:
            raise ReplayError("top-level simulator revision does not match initial state")
        if str(value.get("game_data_hash", initial.game_data_hash)) != initial.game_data_hash:
            raise ReplayError("top-level game-data hash does not match initial state")
        commands = tuple(Command.from_dict(item) for item in value.get("commands", ()))
        replay = cls(initial, commands, int(value["schema_version"]))
        replay.validate()
        return replay


def create_initial_state(
    decks: tuple[Sequence[str], Sequence[str]], seed: int, *, level: int = 11,
    duration_ticks: int = OVERTIME_END_MS // arena.TICK_MS,
    auto_abilities: bool = False,
    evolution_slots: Mapping[int, Mapping[str, str]] | None = None,
) -> InitialState:
    slots = tuple(
        (int(side), tuple(sorted((str(card), str(evolved))
                                 for card, evolved in mapping.items())))
        for side, mapping in sorted((evolution_slots or {}).items())
    )
    initial = InitialState(
        game_data_hash=game_data_hash(), simulator_revision=simulator_revision(),
        level=int(level), seed=int(seed), duration_ticks=int(duration_ticks),
        decks=(tuple(str(item) for item in decks[0]), tuple(str(item) for item in decks[1])),
        auto_abilities=bool(auto_abilities), evolution_slots=slots,
    )
    if not initial.decks[0] or not initial.decks[1]:
        raise ReplayError("both decks are required")
    return initial


def _match_from_initial(initial: InitialState) -> Match:
    if initial.game_data_hash != game_data_hash():
        raise ReplayError("game-data hash mismatch; replay requires the recorded data version")
    if initial.simulator_revision != simulator_revision():
        raise ReplayError("simulator revision mismatch; replay requires the recorded engine version")
    all_cards = load_gamedata(level=initial.level)
    needed = sorted(set(initial.decks[0]) | set(initial.decks[1]))
    cards = resolve_deck(all_cards, needed)
    missing = [name for name in needed if name not in cards]
    if missing:
        raise ReplayError("replay deck cards unavailable: " + ", ".join(missing))
    spells = load_spells(initial.level)
    evolution = {
        side: dict(mapping) for side, mapping in initial.evolution_slots
    }
    return Match(cards=cards, decks=(list(initial.decks[0]), list(initial.decks[1])),
                 seed=initial.seed, spells=spells, level=initial.level,
                 auto_abilities=initial.auto_abilities, evolution_slots=evolution)


@dataclass(frozen=True)
class StateCheckpoint:
    tick: int
    time_ms: int
    digest: str
    state: Mapping[str, Any]


@dataclass
class ReplayExecution:
    initial_state: InitialState
    match: Match
    checkpoints: list[StateCheckpoint]

    @property
    def final(self) -> StateCheckpoint:
        return self.checkpoints[-1]


class ReplayRunner:
    """Run only canonical commands against a fresh Match."""

    def __init__(self, initial_state: InitialState):
        self.initial_state = initial_state
        self.match = _match_from_initial(initial_state)
        self.checkpoints = [self._checkpoint()]

    @property
    def tick(self) -> int:
        return self.match.elapsed_ms // self.initial_state.tick_ms

    def _checkpoint(self) -> StateCheckpoint:
        state = state_payload(self.match)
        return StateCheckpoint(self.tick, self.match.elapsed_ms,
                               hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest(),
                               state)

    def _replace_checkpoint(self) -> None:
        checkpoint = self._checkpoint()
        if self.checkpoints and self.checkpoints[-1].tick == checkpoint.tick:
            self.checkpoints[-1] = checkpoint
        else:
            self.checkpoints.append(checkpoint)

    def advance_to(self, tick: int) -> None:
        if tick < self.tick:
            raise ReplayError(f"cannot move backwards from tick {self.tick} to {tick}")
        while self.tick < tick:
            if self.match.finished:
                raise ReplayError("command stream continues after match termination")
            self.match.step(self.initial_state.tick_ms)
            self.checkpoints.append(self._checkpoint())

    def apply(self, command: Command) -> bool:
        if command.tick != self.tick:
            raise ReplayError(f"command tick {command.tick} does not match current tick {self.tick}")
        if command.command_type == "PLAY_CARD":
            accepted = self.match.play_card(command.player, command.card or "",
                                            arena.Point(command.x_mt or 0, command.y_mt or 0))
        else:
            accepted = self.match.activate_ability(command.player, command.actor_uid or 0)
        self._replace_checkpoint()
        return accepted

    def run_until(self, tick: int) -> ReplayExecution:
        self.advance_to(tick)
        return ReplayExecution(self.initial_state, self.match, self.checkpoints)


class CommandRecorder:
    """Record only external commands while executing a live Match instance."""

    def __init__(self, initial_state: InitialState):
        self.runner = ReplayRunner(initial_state)
        self.commands: list[Command] = []

    @property
    def match(self) -> Match:
        return self.runner.match

    def advance_to(self, tick: int) -> None:
        self.runner.advance_to(tick)

    def play_card(self, player: int, card: str, at: arena.Point) -> bool:
        command = Command(self.runner.tick, player, "PLAY_CARD", card=card,
                          x_mt=int(at.x), y_mt=int(at.y))
        accepted = self.runner.apply(command)
        self.commands.append(command)
        return accepted

    def activate_ability(self, player: int, actor_uid: int) -> bool:
        command = Command(self.runner.tick, player, "ACTIVATE_ABILITY",
                          actor_uid=int(actor_uid))
        accepted = self.runner.apply(command)
        self.commands.append(command)
        return accepted

    def run_until(self, tick: int) -> MatchReplay:
        self.runner.run_until(tick)
        replay = MatchReplay(self.runner.initial_state, tuple(self.commands))
        replay.validate()
        return replay

    def execution(self) -> ReplayExecution:
        return ReplayExecution(self.runner.initial_state, self.runner.match,
                                self.runner.checkpoints)


def execute_replay(replay: MatchReplay, *, until_tick: int | None = None) -> ReplayExecution:
    replay.validate()
    runner = ReplayRunner(replay.initial_state)
    for command in replay.commands:
        runner.advance_to(command.tick)
        runner.apply(command)
    runner.advance_to(replay.initial_state.duration_ticks if until_tick is None else until_tick)
    return ReplayExecution(replay.initial_state, runner.match, runner.checkpoints)


def write_replay(path: str | Path, replay: MatchReplay) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(replay.to_dict()) + "\n", encoding="utf-8")


def read_replay(path: str | Path) -> MatchReplay:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError(f"invalid command replay: {path}") from exc
    if not isinstance(value, Mapping):
        raise ReplayError("command replay root must be an object")
    return MatchReplay.from_dict(value)


def _first_difference(original: Any, replay: Any, path: tuple[str, ...] = ()) -> tuple[tuple[str, ...], Any, Any] | None:
    if type(original) is not type(replay):
        return path, original, replay
    if isinstance(original, Mapping):
        keys = sorted(set(original) | set(replay), key=str)
        for key in keys:
            if key not in original or key not in replay:
                return path + (str(key),), original.get(key), replay.get(key)
            difference = _first_difference(original[key], replay[key], path + (str(key),))
            if difference is not None:
                return difference
        return None
    if isinstance(original, list):
        if len(original) != len(replay):
            return path + ("length",), len(original), len(replay)
        for index, (left, right) in enumerate(zip(original, replay)):
            difference = _first_difference(left, right, path + (str(index),))
            if difference is not None:
                return difference
        return None
    if original != replay:
        return path, original, replay
    return None


def first_divergence(original: ReplayExecution, replay: ReplayExecution) -> dict[str, Any] | None:
    left = {item.tick: item for item in original.checkpoints}
    right = {item.tick: item for item in replay.checkpoints}
    for tick in sorted(set(left) | set(right)):
        left_checkpoint, right_checkpoint = left.get(tick), right.get(tick)
        if left_checkpoint is None or right_checkpoint is None:
            difference = ((), left_checkpoint.digest if left_checkpoint else None,
                          right_checkpoint.digest if right_checkpoint else None)
        elif left_checkpoint.digest == right_checkpoint.digest:
            continue
        else:
            difference = _first_difference(left_checkpoint.state, right_checkpoint.state)
        path, expected, actual = difference
        entity = None
        field = ".".join(path)
        if len(path) >= 2 and path[0] == "entities":
            uid = path[1]
            entity_name = (left_checkpoint.state.get("entities", {}).get(uid, {})
                           if left_checkpoint else {}).get("name", "Entity")
            entity = f"{entity_name}#{uid}"
            field = ".".join(path[2:]) or "state"
        return {
            "tick": tick,
            "time_ms": tick * original.initial_state.tick_ms,
            "entity": entity,
            "field": field,
            "original": expected,
            "replay": actual,
            "original_digest": left_checkpoint.digest if left_checkpoint else None,
            "replay_digest": right_checkpoint.digest if right_checkpoint else None,
        }
    return None


def demo_replay(seed: int = 7, duration_ticks: int = 60) -> MatchReplay:
    deck = ("cannon", "fireball", "hog_rider", "ice_golem",
            "ice_spirit", "musketeer", "skeletons", "the_log")
    initial = create_initial_state((deck, deck), seed, duration_ticks=duration_ticks)
    recorder = CommandRecorder(initial)
    for player, position in ((1, (4500, 24500)), (-1, (13500, 7500))):
        card = recorder.match.players[player].hand[0]
        recorder.play_card(player, card, arena.Point(*position))
    recorder.advance_to(min(20, duration_ticks))
    for player, position in ((1, (13500, 24500)), (-1, (4500, 7500))):
        player_state = recorder.match.players[player]
        affordable = [card for card in player_state.hand
                      if recorder.match.cards.get(card)
                      and recorder.match.cards[card].cost * 1000 <= player_state.elixir]
        if affordable:
            recorder.play_card(player, affordable[0], arena.Point(*position))
    return recorder.run_until(duration_ticks)


def verify_replay(replay: MatchReplay) -> dict[str, Any]:
    first = execute_replay(replay)
    second = execute_replay(replay)
    divergence = first_divergence(first, second)
    return {
        "commands": len(replay.commands),
        "duration_ms": first.final.time_ms,
        "checkpoints": len(first.checkpoints),
        "first_divergence": divergence,
        "final_digest": first.final.digest,
        "result": "deterministic replay PASS" if divergence is None else "FAIL",
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="HastyCR command-only replay audit")
    subparsers = parser.add_subparsers(dest="command", required=True)
    record = subparsers.add_parser("record-command-replay")
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--seed", type=int, default=7)
    record.add_argument("--duration-ticks", type=int, default=60)
    verify = subparsers.add_parser("verify-command-replay")
    verify.add_argument("replay", type=Path)
    args = parser.parse_args()
    if args.command == "record-command-replay":
        replay = demo_replay(args.seed, args.duration_ticks)
        write_replay(args.output, replay)
        print(json.dumps({"status": "PASS", "commands": len(replay.commands),
                          "output": str(args.output)}, indent=2))
    else:
        print(json.dumps(verify_replay(read_replay(args.replay)), indent=2))
