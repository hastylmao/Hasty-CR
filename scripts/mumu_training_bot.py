from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
BUILDABOT = ROOT / "vendor" / "ClashRoyaleBuildABot"
sys.path.insert(0, str(BUILDABOT))

from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402


DECK = [
    Cards.TORNADO,
    Cards.TESLA,
    Cards.ICE_WIZARD,
    Cards.X_BOW,
    Cards.ROCKET,
    Cards.KNIGHT,
    Cards.THE_LOG,
    Cards.SKELETONS,
]

CARD_CENTRES = ((334, 1711), (538, 1711), (742, 1711), (946, 1711))


def adb(adb_path: Path, serial: str, *args: str, binary: bool = False):
    result = subprocess.run(
        [str(adb_path), "-s", serial, *args],
        capture_output=True,
        check=True,
    )
    return result.stdout if binary else result.stdout.decode(errors="replace")


def frame(adb_path: Path, serial: str) -> Image.Image:
    raw = adb(adb_path, serial, "exec-out", "screencap", "-p", binary=True)
    return Image.open(io.BytesIO(raw)).convert("RGB").resize((368, 652))


def tap(adb_path: Path, serial: str, x: int, y: int) -> None:
    adb(adb_path, serial, "shell", "input", "tap", str(x), str(y))


def choose(state):
    available = []
    for slot in state.ready:
        card = state.cards[slot + 1]
        if card.name != "blank" and state.numbers.elixir.number >= card.cost:
            available.append((slot, card))
    if not available:
        return None

    by_name = {card.name: (slot, card) for slot, card in available}
    enemies = list(state.enemies)
    defending = bool(enemies)
    lane_x = 300
    if enemies:
        avg_x = sum(enemy.position.tile_x for enemy in enemies) / len(enemies)
        lane_x = 300 if avg_x < 9 else 780

    if defending:
        order = ["tesla", "knight", "ice_wizard", "skeletons"]
        if len(enemies) >= 2:
            order += ["tornado", "the_log"]
        if len(enemies) >= 3 and state.numbers.elixir.number >= 9:
            order += ["rocket"]
        order += ["x_bow"]
    else:
        order = ["x_bow", "skeletons", "knight", "ice_wizard"]

    name = next((candidate for candidate in order if candidate in by_name), None)
    if name is None:
        return None
    slot, card = by_name[name]

    if name == "x_bow":
        target = (300, 970)
    elif name == "tesla":
        target = (540, 1130)
    elif name in {"tornado", "the_log"}:
        target = (lane_x, 1090)
    elif name == "rocket":
        target = (lane_x, 880)
    elif defending:
        target = (lane_x, 1230)
    else:
        target = (lane_x, 1430)
    return slot, card, target, defending, len(enemies)


def main() -> int:
    parser = argparse.ArgumentParser(description="One bounded MuMu Training Camp trial")
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", default="127.0.0.1:7555")
    parser.add_argument("--max-seconds", type=float, default=260)
    parser.add_argument("--log", type=Path, default=ROOT / "tmp" / "live" / "training-bot.log")
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    detector = Detector(DECK)
    started = time.monotonic()
    saw_match = False
    last_action = 0.0
    action_count = 0

    def log(message: str) -> None:
        line = f"{datetime.now():%H:%M:%S} {message}"
        print(line, flush=True)
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    log("START bounded Training Camp heuristic; ladder navigation disabled")
    while time.monotonic() - started < args.max_seconds:
        state = detector.run(frame(args.adb, args.serial))
        if state is None:
            log("WAIT detector returned no state")
            time.sleep(1)
            continue
        screen = state.screen.name
        if screen == "in_game":
            saw_match = True
        elif saw_match:
            log(f"STOP screen={screen}; actions={action_count}")
            return 0
        else:
            log(f"WAIT screen={screen}")
            time.sleep(1)
            continue

        now = time.monotonic()
        hand = [card.name for card in state.cards[1:]]
        if now - last_action < 3.2:
            time.sleep(0.7)
            continue
        decision = choose(state)
        if decision is None:
            log(f"WAIT elixir={state.numbers.elixir.number} hand={hand} ready={state.ready}")
            time.sleep(1)
            continue
        slot, card, target, defending, enemies = decision
        card_xy = CARD_CENTRES[slot]
        tap(args.adb, args.serial, *card_xy)
        time.sleep(0.12)
        tap(args.adb, args.serial, *target)
        action_count += 1
        last_action = time.monotonic()
        log(
            f"PLAY #{action_count} {card.name} slot={slot + 1} target={target} "
            f"elixir={state.numbers.elixir.number} enemies={enemies} mode={'defend' if defending else 'cycle'}"
        )
        time.sleep(0.8)

    log(f"STOP time limit; actions={action_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
