from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mumu_overnight_bot as guarded  # noqa: E402
from clashroyalebuildabot.actions import (  # noqa: E402
    ArchersAction,
    BabyDragonAction,
    CannonAction,
    GoblinBarrelAction,
    KnightAction,
    MinipekkaAction,
    MusketeerAction,
    WitchAction,
)
from clashroyalebuildabot.constants import (  # noqa: E402
    ALL_TILES,
    ALLY_TILES,
    DISPLAY_HEIGHT,
    LEFT_PRINCESS_TILES,
    RIGHT_PRINCESS_TILES,
    TILE_HEIGHT,
    TILE_INIT_X,
    TILE_INIT_Y,
    TILE_WIDTH,
)
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402


ACTIONS = (
    ArchersAction,
    GoblinBarrelAction,
    BabyDragonAction,
    CannonAction,
    KnightAction,
    MinipekkaAction,
    MusketeerAction,
    WitchAction,
)
DECK = [action.CARD for action in ACTIONS]
CARDS_TO_ACTIONS = {action.CARD: action for action in ACTIONS}


def tile_centre(tile_x: int, tile_y: int) -> tuple[int, int]:
    x720 = TILE_INIT_X + (tile_x + 0.5) * TILE_WIDTH
    y1280 = DISPLAY_HEIGHT - TILE_INIT_Y - (tile_y + 0.5) * TILE_HEIGHT
    return round(x720 * 1.5), round(y1280 * 1.5)


def choose_native(state):
    valid_tiles = list(ALLY_TILES)
    if state.numbers.left_enemy_princess_hp.number == 0:
        valid_tiles += LEFT_PRINCESS_TILES
    if state.numbers.right_enemy_princess_hp.number == 0:
        valid_tiles += RIGHT_PRINCESS_TILES

    best_score = [0]
    best_action = None
    for slot in state.ready:
        card = state.cards[slot + 1]
        action_type = CARDS_TO_ACTIONS.get(card)
        if action_type is None or state.numbers.elixir.number < card.cost:
            continue
        tiles = ALL_TILES if card.target_anywhere else valid_tiles
        for tile_x, tile_y in tiles:
            candidate = action_type(slot, tile_x, tile_y)
            score = candidate.calculate_score(state)
            if score > best_score:
                best_score = score
                best_action = candidate
    return best_action, best_score


def validate_battle(detector, adb_path, serial, slot=None, card_name=None, count=2):
    latest = None
    for _ in range(count):
        full, state = guarded.detect(detector, adb_path, serial)
        if state is None or not guarded.battle_guard(state):
            return None
        if slot is not None and state.cards[slot + 1].name != card_name:
            return None
        latest = (full, state)
        time.sleep(0.22)
    return latest


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded native BuildABot policy on MuMu")
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument(
        "--log",
        type=Path,
        default=ROOT / "tmp" / "live" / "buildabot-native.log",
    )
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    detector = Detector(DECK)
    deadline = time.monotonic() + args.hours * 3600
    last_action = last_nav = 0.0
    actions = matches = 0

    def log(message: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line, flush=True)
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    log("START native BuildABot scoring with guarded MuMu controls")
    while time.monotonic() < deadline:
        try:
            full, state = guarded.detect(detector, args.adb, args.serial)
            if state is None:
                time.sleep(1)
                continue
            now = time.monotonic()
            screen = state.screen.name

            if guarded.home_guard(full, state) and now - last_nav > 8:
                full2, state2 = guarded.detect(detector, args.adb, args.serial)
                if state2 is not None and guarded.home_guard(full2, state2):
                    guarded.tap(args.adb, args.serial, guarded.HOME_BATTLE)
                    last_nav = now
                    matches += 1
                    log(f"QUEUE match={matches}")
                time.sleep(1)
                continue

            if screen in {"end_of_game", "bypass_end_of_game"} and now - last_nav > 5:
                _, state2 = guarded.detect(detector, args.adb, args.serial)
                if state2 is not None and state2.screen.name == screen:
                    xy720 = state.screen.click_xy
                    guarded.tap(
                        args.adb,
                        args.serial,
                        (round(xy720[0] * 1.5), round(xy720[1] * 1.5)),
                    )
                    last_nav = now
                    log(f"RESULT exit screen={screen}")
                time.sleep(1)
                continue

            if not guarded.battle_guard(state) or now - last_action < 2.2:
                time.sleep(0.7)
                continue
            action, score = choose_native(state)
            if action is None:
                time.sleep(0.7)
                continue
            card_name = action.CARD.name
            checked = validate_battle(
                detector,
                args.adb,
                args.serial,
                action.index,
                card_name,
                count=2,
            )
            if checked is None:
                log("BLOCK pre-card battle validation failed")
                time.sleep(1)
                continue
            guarded.tap(args.adb, args.serial, guarded.CARD_CENTRES[action.index])
            time.sleep(0.15)
            checked = validate_battle(detector, args.adb, args.serial, count=1)
            if checked is None:
                log("BLOCK pre-target battle validation failed")
                time.sleep(1)
                continue
            target = tile_centre(action.tile_x, action.tile_y)
            guarded.tap(args.adb, args.serial, target)
            actions += 1
            last_action = time.monotonic()
            log(
                f"PLAY #{actions} {card_name} tile=({action.tile_x},{action.tile_y}) "
                f"target={target} score={score} elixir={state.numbers.elixir.number}"
            )
            time.sleep(0.7)
        except Exception as exc:
            log(f"ERROR {type(exc).__name__}: {exc}")
            time.sleep(2)
    log(f"STOP deadline matches={matches} actions={actions}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
