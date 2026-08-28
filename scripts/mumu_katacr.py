from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor" / "ClashRoyaleBuildABot"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from loguru import logger  # noqa: E402

import mumu_overnight_bot as guarded  # noqa: E402
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402
import heuristic_policy  # noqa: E402
import policy_shims  # noqa: E402
import popup_guard  # noqa: E402
import tower_hp  # noqa: E402
from hastycr.adapters.katacr import KataPolicy, MODEL_DECK_NAMES, grid_to_mumu  # noqa: E402


DEFAULT_CHECKPOINT = (
    ROOT / "vendor" / "KataCR" / "logs" / "Policy"
    / "StARformer_3L_v0.8_golem_ai_cnn_blocks__nbc128__ep30__step50__0__20240512_181646"
    / "ckpt"
)


DECK = [
    Cards.CANNON,
    Cards.FIREBALL,
    Cards.HOG_RIDER,
    Cards.ICE_GOLEM,
    Cards.ICE_SPIRIT,
    Cards.MUSKETEER,
    Cards.SKELETONS,
    Cards.THE_LOG,
]
CARD_CENTRES = guarded.CARD_CENTRES
ANYWHERE = {"fireball", "the_log"}
UNKNOWN_POPUP_SECONDS = 20
UNKNOWN_RECOVER_SECONDS = 90
UNKNOWN_RECOVER_COOLDOWN = 180


def valid_model_hand(state) -> bool:
    names = {card.name for card in state.cards[1:] if card.name != "blank"}
    return len(names) >= 3 and names <= MODEL_DECK_NAMES


def main() -> int:
    parser = argparse.ArgumentParser(description="Guarded sequence-model runner for MuMu")
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--model-root", dest="kata_root", type=Path, default=ROOT / "vendor" / "KataCR")
    parser.add_argument("--verbose", action="store_true", help="show upstream library debug logs")
    parser.add_argument("--shims", action="store_true", help="apply hand-written strategy guards")
    parser.add_argument("--heuristic", action="store_true", help="hand-written policy decides first, model is the fallback")
    parser.add_argument("--max-matches", type=int, help="exit cleanly after N finished matches")
    parser.add_argument("--epoch", type=int, default=3)
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--auto-queue", action="store_true")
    parser.add_argument("--max-actions", type=int)
    parser.add_argument("--log", type=Path, default=ROOT / "tmp" / "live" / "katacr.log")
    args = parser.parse_args()
    # Upstream perception logs one DEBUG line per frame, which buries this
    # runner's own PLAY/BLOCK output. Keep warnings, drop the per-frame noise.
    if not args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    result_dir = args.log.parent / "katacr_results"
    result_dir.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        print(line, flush=True)
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    log("LOAD policy checkpoint epoch=%03d" % args.epoch)
    detector = Detector(DECK)
    policy = KataPolicy(args.kata_root, args.checkpoint, args.epoch)
    log(f"READY n_step={policy.n_step} dry_run={args.dry_run} auto_queue={args.auto_queue}")

    deadline = time.monotonic() + args.hours * 3600
    in_match = False
    match_started = last_action = last_nav = 0.0
    match_action_start = 0
    actions = matches = candidates = finished = popups = recoveries = 0
    last_screen = None
    last_towers = "?"
    last_confirmed_live_towers = "?"
    unknown_since = last_popup = last_recover = time.monotonic()

    while time.monotonic() < deadline:
        try:
            full, state = guarded.detect(detector, args.adb, args.serial)
            if state is None:
                time.sleep(0.5)
                continue
            screen = state.screen.name
            now = time.monotonic()
            if screen != last_screen:
                log(f"SCREEN {last_screen}->{screen}")
                last_screen = screen

            # Guarded lobby -> battle queue.
            if screen == "lobby":
                in_match = False
                last_confirmed_live_towers = "?"
                if args.auto_queue and not args.dry_run and now - last_nav > 5:
                    if guarded.home_guard(full, state):
                        guarded.tap(args.adb, args.serial, guarded.HOME_BATTLE)
                        last_nav = now
                        matches += 1
                        log(f"QUEUE match={matches}")
                time.sleep(0.7)
                continue

            if screen in {"end_of_game", "bypass_end_of_game"}:
                if in_match:
                    result_path = result_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{screen}.png"
                    full.save(result_path)
                    logged_towers = last_confirmed_live_towers if last_confirmed_live_towers != "?" else last_towers
                    log(
                        f"MATCH_RESULT screen={screen} match_actions={actions - match_action_start} "
                        f"total_actions={actions} duration={round(now - match_started)} "
                        f"towers={logged_towers} screenshot={result_path.name}"
                    )
                    in_match = False
                    finished += 1
                    if args.max_matches is not None and finished >= args.max_matches:
                        log(f"STOP max_matches finished={finished} actions={actions}")
                        return 0
                if args.auto_queue and not args.dry_run and now - last_nav > 5:
                    _, check = guarded.detect(detector, args.adb, args.serial)
                    if check is not None and check.screen.name == screen:
                        xy = state.screen.click_xy
                        guarded.tap(args.adb, args.serial, (round(xy[0] * 1.5), round(xy[1] * 1.5)))
                        last_nav = now
                        log("RESULT_EXIT")
                time.sleep(0.7)
                continue

            # An offer dialog covers the lobby and reads as `unknown`, which
            # would otherwise stall the run until the deadline. Dismiss only a
            # positively-identified close button, never a confirm control.
            if screen == "unknown":
                if now - unknown_since > UNKNOWN_POPUP_SECONDS and now - last_popup > 30:
                    spot = popup_guard.find_close_button(full)
                    if spot is not None:
                        _, check = guarded.detect(detector, args.adb, args.serial)
                        if check is not None and check.screen.name == "unknown":
                            guarded.tap(args.adb, args.serial, spot)
                            last_popup = now
                            popups += 1
                            log(f"POPUP dismiss at={spot} count={popups}")
                    else:
                        log("POPUP unknown_screen no_close_button")
                        last_popup = now
                # A crash or a stuck non-popup screen would otherwise park the
                # run until the deadline. Bring the game back to the front.
                if now - unknown_since > UNKNOWN_RECOVER_SECONDS and now - last_recover > UNKNOWN_RECOVER_COOLDOWN:
                    last_recover = now
                    recoveries += 1
                    try:
                        guarded.adb(
                            args.adb, args.serial, "shell", "monkey", "-p",
                            "com.supercell.clashroyale", "-c",
                            "android.intent.category.LAUNCHER", "1",
                        )
                        log(f"RECOVER relaunched_app count={recoveries}")
                    except Exception as exc:
                        log(f"RECOVER failed {type(exc).__name__}: {exc}")
                time.sleep(0.7)
                continue
            unknown_since = now

            if not guarded.battle_guard(state):
                time.sleep(0.5)
                continue
            # Read robust tower fractions directly from the full frame
            ally_hp = tower_hp.ally_tower_fractions(full)
            enemy_hp = tower_hp.enemy_tower_fractions(full)
            
            # Construct updated Numbers object (Numbers and NumberDetection are frozen dataclasses)
            from clashroyalebuildabot.namespaces.numbers import Numbers, NumberDetection
            old_n = state.numbers
            l_ally = ally_hp.get("left", old_n.left_ally_princess_hp.number)
            r_ally = ally_hp.get("right", old_n.right_ally_princess_hp.number)
            l_enemy = enemy_hp.get("left", old_n.left_enemy_princess_hp.number)
            r_enemy = enemy_hp.get("right", old_n.right_enemy_princess_hp.number)
            
            state.numbers = Numbers(
                left_enemy_princess_hp=NumberDetection(old_n.left_enemy_princess_hp.bbox, l_enemy),
                right_enemy_princess_hp=NumberDetection(old_n.right_enemy_princess_hp.bbox, r_enemy),
                left_ally_princess_hp=NumberDetection(old_n.left_ally_princess_hp.bbox, l_ally),
                right_ally_princess_hp=NumberDetection(old_n.right_ally_princess_hp.bbox, r_ally),
                elixir=old_n.elixir,
            )
            last_towers = tower_hp.tower_summary(full)
            last_confirmed_live_towers = last_towers
            if not valid_model_hand(state):
                hand = [card.name for card in state.cards[1:]]
                log(f"REFUSE incompatible_deck hand={hand}")
                time.sleep(2)
                continue
            if not in_match:
                policy.reset()
                in_match = True
                match_started = now
                match_action_start = actions
                log("MATCH_START")

            elapsed = round(now - match_started)
            slot, x, y, delay = policy.predict(state, elapsed)
            # The hand-written policy decides first when it has an opinion; the
            # model keeps running so its causal history stays intact and it
            # still covers every situation the heuristic declines.
            heuristic_note = None
            if args.heuristic:
                choice = heuristic_policy.decide(state)
                if choice is not None:
                    slot, x, y, heuristic_note = choice
                    delay = 0
            if heuristic_note is not None:
                log(f"HEUR {heuristic_note} slot={slot} grid=({x},{y}) elixir={state.numbers.elixir.number}")
            elif args.shims:
                shimmed = policy_shims.apply(state, slot, x, y, delay)
                if shimmed is None:
                    log(f"SHIM veto card={state.cards[slot].name if 1 <= slot <= 4 else 'blank'} grid=({x},{y})")
                    time.sleep(0.25)
                    continue
                slot, x, y, delay, note = shimmed
                if note:
                    log(f"SHIM {note} -> slot={slot} grid=({x},{y})")
            # Match KataCR's published evaluator: never bank at full elixir just
            # because the learned delay head predicted a pause.
            effective_delay = 0 if state.numbers.elixir.number >= 9.5 else delay
            candidates += 1
            slot_index = slot - 1
            card = state.cards[slot] if 1 <= slot <= 4 else Cards.BLANK
            # The model occasionally emits coordinates outside the arena
            # (observed (-2,28) and (-2,33)), which raised out of the loop and
            # threw the decision away. Clamp instead and record it.
            cx, cy = max(0, min(17, x)), max(0, min(31, y))
            if (cx, cy) != (x, y):
                log(f"CLAMP_OOB grid=({x},{y})->({cx},{cy})")
                x, y = cx, cy
            target = grid_to_mumu(x, y)
            log(
                f"CANDIDATE #{candidates} card={card.name} slot={slot} grid=({x},{y}) "
                f"target={target} delay={delay} elixir={state.numbers.elixir.number}"
            )
            if args.dry_run:
                time.sleep(0.25)
                continue
            if args.max_actions is not None and actions >= args.max_actions:
                log("STOP max_actions")
                return 0
            if effective_delay > 8 or now - last_action < 1.3:
                time.sleep(0.25)
                continue
            if not (0 <= slot_index < 4) or slot_index not in state.ready:
                log("BLOCK slot_not_ready")
                time.sleep(0.25)
                continue
            if card.name == "blank" or state.numbers.elixir.number < card.cost:
                log("BLOCK unaffordable_or_blank")
                time.sleep(0.25)
                continue
            if card.name not in ANYWHERE and y < 16:
                log("BLOCK troop_target_enemy_half")
                time.sleep(0.25)
                continue

            checked = guarded.validate_battle(
                detector, args.adb, args.serial, slot_index, card.name, count=1
            )
            if checked is None:
                log("BLOCK pre_card_guard")
                time.sleep(0.3)
                continue
            _, _, actual_slot = checked
            guarded.tap(args.adb, args.serial, CARD_CENTRES[actual_slot])
            time.sleep(0.10)
            checked_target = guarded.validate_battle(detector, args.adb, args.serial, count=1)
            if checked_target is None:
                log("BLOCK pre_target_guard")
                time.sleep(0.3)
                continue
            guarded.tap(args.adb, args.serial, target)
            policy.record_action(slot, x, y)
            actions += 1
            last_action = time.monotonic()
            # Tower state at play time makes push conversion measurable later:
            # diffing enemy HP after a hog_rider PLAY shows whether it connected.
            log(f"PLAY #{actions} {card.name} grid=({x},{y}) target={target} towers={last_towers}")
            time.sleep(0.35)
        except Exception as exc:
            log(f"ERROR {type(exc).__name__}: {exc}")
            time.sleep(1)

    log(f"STOP deadline matches={matches} actions={actions} candidates={candidates}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
