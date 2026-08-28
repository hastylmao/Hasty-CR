"""Live Clash Royale runner driven by the `brain` policy.

Differences from the old `mumu_katacr.py` runner that matter for play quality:

* No learned checkpoint in the hot path *by default* (see --rl).  The StARformer policy cost roughly a
  second per decision on CPU and its choices lost 90 crowns to 11 across sixty
  matches; it is available behind --model but off by default.
* One capture per action instead of three.  The old runner re-detected before
  the card tap and again before the target tap, which tripled reaction latency
  in exchange for a guard that only ever mattered outside a battle.
* Every finished match is written to `matches/*.json` so the review loop can
  read outcomes without parsing prose logs.
"""

from __future__ import annotations

import argparse
import json
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
import popup_guard  # noqa: E402
import reward_screen  # noqa: E402
from sprite_harvest import SpriteHarvester  # noqa: E402
import connection_lost  # noqa: E402
import tower_hp  # noqa: E402
from emulator import verify as verify_emulator  # noqa: E402
from brain import arena  # noqa: E402
from brain.knowledge import BOOK  # noqa: E402
from brain.policy import Brain  # noqa: E402
from clashroyalebuildabot.detectors.detector import Detector  # noqa: E402
from clashroyalebuildabot.namespaces.cards import Cards  # noqa: E402

DECK = [
    Cards.CANNON, Cards.FIREBALL, Cards.HOG_RIDER, Cards.ICE_GOLEM,
    Cards.ICE_SPIRIT, Cards.MUSKETEER, Cards.SKELETONS, Cards.THE_LOG,
]
IDLE_REPORT_SECONDS = 8
UNKNOWN_POPUP_SECONDS = 15
UNKNOWN_RECOVER_SECONDS = 75
UNKNOWN_RECOVER_COOLDOWN = 150


def _threat_names(obs) -> str:
    """The two biggest things coming at us, by name.

    The log recorded `threat=8/2` - a score and a count - which says a push is
    happening but not what it is made of. Every defensive question worth asking
    needs the names: the Cannon-versus-Musketeer fault was invisible in the log
    and had to be caught by eye. Two names keep the line readable; the score
    already says how much else is behind them.
    """
    if not getattr(obs, "threats", None):
        return ""
    from brain.knowledge import BOOK

    biggest = sorted(obs.threats, key=lambda t: BOOK.threat(t.name), reverse=True)
    return "vs=" + ",".join(t.name for t in biggest[:2]) + " "


def patch_tower_numbers(state, full, hp_filter=None, now=0.0):
    """Replace BuildABot's princess-tower readings with the calibrated ones.

    The bundled reader mistakes the translucent overlay for a full bar; every
    lane decision downstream depends on these four numbers being right.

    `hp_filter` adds the temporal half of that: the calibrated reader is still
    a single-frame measurement, and a bar behind a troop reads the same as a
    destroyed tower.  Passing the filter makes the policy and the match record
    share one set of numbers, so the report says what the bot was acting on.
    """
    from clashroyalebuildabot.namespaces.numbers import NumberDetection, Numbers

    if hp_filter is not None:
        ally, enemy = hp_filter.fractions(full, now)
    else:
        ally = tower_hp.ally_tower_fractions(full)
        enemy = tower_hp.enemy_tower_fractions(full)
    old = state.numbers
    state.numbers = Numbers(
        left_enemy_princess_hp=NumberDetection(
            old.left_enemy_princess_hp.bbox,
            enemy.get("left", old.left_enemy_princess_hp.number)),
        right_enemy_princess_hp=NumberDetection(
            old.right_enemy_princess_hp.bbox,
            enemy.get("right", old.right_enemy_princess_hp.number)),
        left_ally_princess_hp=NumberDetection(
            old.left_ally_princess_hp.bbox,
            ally.get("left", old.left_ally_princess_hp.number)),
        right_ally_princess_hp=NumberDetection(
            old.right_ally_princess_hp.bbox,
            ally.get("right", old.right_ally_princess_hp.number)),
        elixir=old.elixir,
    )
    return state, ally, enemy


def main() -> int:
    parser = argparse.ArgumentParser(description="HastyCR live runner")
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", default="127.0.0.1:16480")
    parser.add_argument("--hours", type=float, default=8.0)
    parser.add_argument("--max-matches", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-queue", action="store_true", help="do not start matches")
    parser.add_argument("--harvest-sprites", action="store_true",
                        help="save reference crops of enemy units for a future detector")
    parser.add_argument("--advisor", action="store_true",
                        help="consult the local LLM for intent (needs Ollama running)")
    parser.add_argument("--vision", choices=("buildabot", "yolo"), default="buildabot",
                        help="unit perception: upstream detector, or the one trained "
                             "here (0.959 mAP50) plus the ally/enemy classifier")
    parser.add_argument("--rl", type=Path,
                        help="play with a checkpoint trained in the simulator "
                             "instead of the hand-written brain, e.g. "
                             "tmp/rl/hog26v5_best.pt")
    parser.add_argument("--rl-temperature", type=float, default=0.0,
                        help="0 is greedy, which is the right default live - "
                             "sampling is exploration and there is nothing to "
                             "explore on ladder")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--log", type=Path, default=ROOT / "tmp" / "live" / "cr_bot.log")
    parser.add_argument("--matches-dir", type=Path, default=ROOT / "tmp" / "live" / "matches")
    args = parser.parse_args()

    # Refuse to drive the wrong emulator. The other MuMu instance on this
    # machine runs a Clash of Clans bot; a wrong --serial used to be silent,
    # because the runner would connect, fail to recognise the screen, and go
    # on tapping into somebody else's village.
    verify_emulator(args.serial, args.adb)

    if not args.verbose:
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.matches_dir.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        print(line, flush=True)
        with args.log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    detector = Detector(DECK)
    vision = None
    if args.vision == "yolo":
        from brain.vision import YoloVision  # noqa: E402
        vision = YoloVision()
        if not vision.ready:
            log(f"VISION unavailable ({vision.error}); staying on buildabot")
            vision = None
        else:
            log(f"VISION yolo weights={vision.weights.name} "
                f"side_classifier={'yes' if vision.sides.ready else 'NO'} "
                f"side_accuracy={vision.sides.accuracy:.3f}")
    if args.rl:
        from brain.rl_policy import RLBrain
        brain = RLBrain(args.rl, temperature=args.rl_temperature)
        log(f"BRAIN learned checkpoint {args.rl.name} "
            f"trained to {brain.step_trained:,} steps, "
            f"temperature={args.rl_temperature}")
    else:
        brain = Brain(use_advisor=args.advisor)
    harvester = SpriteHarvester() if args.harvest_sprites else None
    log(f"READY units={BOOK.source} dry_run={args.dry_run} queue={not args.no_queue} "
        f"advisor={'on' if args.advisor else 'off'}")

    deadline = time.monotonic() + args.hours * 3600
    in_match = False
    match_started = last_nav = 0.0
    finished = queued = ticks = 0
    last_screen = None
    unknown_since = last_popup = last_recover = last_reward_tap = time.monotonic()
    reward_taps = 0
    match_log: list[str] = []
    hp_trace: list[tuple[int, str]] = []
    last_towers = "?"
    hp_filter = tower_hp.TowerHpFilter()
    last_decision = last_idle_log = time.monotonic()
    guard_blocked_since = None
    last_guard_report = 0.0
    last_reload = 0.0
    last_bars_report = 0.0
    bars_frame_saved = False
    guard_frame_saved = False

    while time.monotonic() < deadline:
        try:
            full, state = guarded.detect(detector, args.adb, args.serial)
            if state is None:
                time.sleep(0.4)
                continue
            now = time.monotonic()
            screen = state.screen.name
            if screen != last_screen:
                log(f"SCREEN {last_screen}->{screen}")
                last_screen = screen
            if screen != "in_game":
                # The guard is *supposed* to reject the lobby, the end-of-game
                # screen and the reward flow, so time spent there is not time
                # spent blocked. Without this reset the counter accumulated
                # across a whole inter-match gap and then reported "38s blocked"
                # on the first frame of the next battle, one second before
                # MATCH_START - an alarm about nothing.
                guard_blocked_since = None

            if screen == "lobby":
                in_match = False
                if not args.no_queue and not args.dry_run and now - last_nav > 5:
                    if guarded.home_guard(full, state):
                        guarded.tap(args.adb, args.serial, guarded.HOME_BATTLE)
                        last_nav = now
                        queued += 1
                        log(f"QUEUE #{queued}")
                unknown_since = now
                time.sleep(0.7)
                continue

            if screen in {"end_of_game", "bypass_end_of_game"}:
                if in_match:
                    finished += 1
                    # The end-of-game screen covers the arena, so reading the
                    # bars off it returns whatever was last painted there.  The
                    # score of the match is the last reading taken while the
                    # battle was still on screen.
                    record = {
                        "index": finished,
                        "ended_at": datetime.now().isoformat(timespec="seconds"),
                        "duration_s": round(now - match_started),
                        "towers": last_towers,
                        "hp_trace": hp_trace[-40:],
                        # Card-classifier instability corrupts everything
                        # downstream, so it is reported per match rather than
                        # left to be rediscovered from odd-looking card shares.
                        "hand_flips": brain.hand_tracker.flips,
                        "classifier_overrides": brain.classifier_overrides,
                        "advice_used": brain.advice_used,
                        "advisor_failures": getattr(brain.advisor, "failures", None),
                        "summary": brain.summary(),
                        "play_counts": dict(brain.play_counts),
                        "plays": brain.plays,
                        "actions": match_log[-200:],
                    }
                    path = args.matches_dir / f"{datetime.now():%Y%m%d_%H%M%S}_m{finished:03d}.json"
                    path.write_text(json.dumps(record, indent=1), encoding="utf-8")
                    shot = args.matches_dir / f"{path.stem}.png"
                    full.resize((540, 960)).save(shot, optimize=True)
                    if brain.book is not None:
                        brain.book.save()
                        brain.book.trim_log()
                        resolved = len(brain.book.completed)
                        log(f"LEARN episodes={resolved} "
                            f"situations={len(brain.book.learned)} "
                            f"matchups={len(brain.book.matchups)}")
                    if harvester is not None:
                        harvester.write_index()
                        log(f"SPRITES classes={len(harvester.counts)} "
                            f"images={sum(harvester.counts.values())}")
                    log(f"MATCH_END #{finished} dur={record['duration_s']}s "
                        f"towers={record['towers']} {record['summary']} file={path.name}")
                    in_match = False
                    if args.max_matches and finished >= args.max_matches:
                        log(f"STOP max_matches={finished}")
                        return 0
                if not args.no_queue and not args.dry_run and now - last_nav > 4:
                    xy = state.screen.click_xy
                    guarded.tap(args.adb, args.serial,
                                (round(xy[0] * 1.5), round(xy[1] * 1.5)))
                    last_nav = now
                unknown_since = now
                time.sleep(0.7)
                continue

            if screen == "unknown":
                # A pending chest survives an app relaunch, so the generic
                # recovery path cannot clear it.  Only act when the screen is
                # positively identified as a reward screen - see reward_screen
                # for why that test cannot match a shop or an offer dialog.
                if now - last_reward_tap > 1.5 and reward_screen.is_reward_screen(full):
                    last_reward_tap = now
                    reward_taps += 1
                    spot = reward_screen.advance_point(reward_taps)
                    if not args.dry_run:
                        guarded.tap(args.adb, args.serial, spot)
                    edges = reward_screen.top_band_edges(full)
                    log(f"REWARD advance tap #{reward_taps} at={spot} "
                        f"top_edges={edges[0]:.2f}/{edges[1]:.2f}%")
                    unknown_since = now
                    time.sleep(0.5)
                    continue
                # "Connection lost - another device is connecting to this
                # game" has no X to close, only a RELOAD link, so the popup
                # guard failed on it and the bot sat here until the 75-second
                # recovery relaunched the app - three times in five minutes.
                # This dialog is unambiguous, so answer it at once rather than
                # waiting out UNKNOWN_POPUP_SECONDS first.
                reload_spot = connection_lost.find_reload(full)
                if reload_spot is not None and now - last_reload > 8:
                    last_reload = now
                    if not args.dry_run:
                        guarded.tap(args.adb, args.serial, reload_spot)
                    log(f"RELOAD connection_lost at={reload_spot}")
                    unknown_since = now
                    time.sleep(1.5)
                    continue
                if now - unknown_since > UNKNOWN_POPUP_SECONDS and now - last_popup > 25:
                    spot = popup_guard.find_close_button(full)
                    last_popup = now
                    if spot is not None and not args.dry_run:
                        guarded.tap(args.adb, args.serial, spot)
                        log(f"POPUP dismiss at={spot}")
                    else:
                        log("POPUP no_close_button")
                if (now - unknown_since > UNKNOWN_RECOVER_SECONDS
                        and now - last_recover > UNKNOWN_RECOVER_COOLDOWN):
                    last_recover = now
                    try:
                        guarded.adb(args.adb, args.serial, "shell", "monkey", "-p",
                                    "com.supercell.clashroyale", "-c",
                                    "android.intent.category.LAUNCHER", "1")
                        log("RECOVER relaunched_app")
                    except Exception as exc:
                        log(f"RECOVER failed {type(exc).__name__}: {exc}")
                time.sleep(0.7)
                continue
            unknown_since = now

            # Calibrate the tower bars BEFORE the guard reads them. The guard
            # needs two of four princess bars above 10% to believe it is looking
            # at a battle, and upstream's reader is exactly what this function
            # exists to replace: measured live it reported our own two towers at
            # 0.00 while both stood at full health, leaving the guard balanced on
            # the opponent's two readings alone. One flicker there and the guard
            # rejects every frame of the match - observed as 84 seconds of a live
            # battle with no MATCH_START and not a single card played, which is
            # a thrown game rather than a hiccup.
            state, ally_hp, enemy_hp = patch_tower_numbers(
                state, full, hp_filter, now)

            if not guarded.battle_guard(state):
                # Silence here is how a whole match gets thrown. Observed live:
                # the screen read `in_game` for 68 seconds, the guard rejected
                # every frame, nothing was logged, no MATCH_START fired and not
                # one card was played - the match was lost without the bot ever
                # believing it had begun, and without a MATCH_END to show for it.
                # Report what the guard actually saw so the cause is named
                # rather than guessed at.
                if guard_blocked_since is None:
                    guard_blocked_since = now
                elif now - guard_blocked_since > 5 and now - last_guard_report > 10:
                    last_guard_report = now
                    hp = (state.numbers.left_ally_princess_hp.number,
                          state.numbers.right_ally_princess_hp.number,
                          state.numbers.left_enemy_princess_hp.number,
                          state.numbers.right_enemy_princess_hp.number)
                    hand = [c.name for c in state.cards[1:]]
                    log(f"GUARD_BLOCKED {round(now - guard_blocked_since)}s "
                        f"screen={screen} bars={tuple(round(v, 2) for v in hp)} "
                        f"above_10pct={sum(v > 0.10 for v in hp)} hand={hand}")
                    # There are at least two distinct causes - bars reading zero
                    # on a live match, and the hand reading blank - so keep one
                    # frame of each run to identify them from the pixels rather
                    # than from the symptom.
                    if not guard_frame_saved:
                        guard_frame_saved = True
                        shot = (args.matches_dir /
                                f"guard_blocked_{datetime.now():%H%M%S}.png")
                        try:
                            full.save(shot)
                            log(f"GUARD_BLOCKED saved {shot.name}")
                        except Exception as exc:
                            log(f"GUARD_BLOCKED save failed: {type(exc).__name__}")
                time.sleep(0.4)
                continue
            guard_blocked_since = None

            # The guard now passes on a single live bar, so a degraded reading no
            # longer costs a match - but it is still a broken reading, and it is
            # what makes lane choice and the finisher unreliable. Report it, and
            # keep one frame per run so the reader can be fixed against a real
            # example rather than a reconstruction.
            bars = (state.numbers.left_ally_princess_hp.number,
                    state.numbers.right_ally_princess_hp.number,
                    state.numbers.left_enemy_princess_hp.number,
                    state.numbers.right_enemy_princess_hp.number)
            if sum(v > 0.10 for v in bars) < 2 and now - last_bars_report > 30:
                last_bars_report = now
                log(f"BARS_DEGRADED {tuple(round(v, 2) for v in bars)}")
                if not bars_frame_saved:
                    bars_frame_saved = True
                    shot = args.matches_dir / f"bars_degraded_{datetime.now():%H%M%S}.png"
                    try:
                        full.save(shot)
                        log(f"BARS_DEGRADED saved {shot.name}")
                    except Exception as exc:
                        log(f"BARS_DEGRADED save failed: {type(exc).__name__}")

            # Unit perception is swapped after the guard, which reads cards and
            # tower bars rather than units.
            if vision is not None:
                vision.apply(state, full)
                if ticks % 60 == 0:
                    ours, theirs = vision.last_counts
                    log(f"VISION ours={ours} theirs={theirs} "
                        f"{vision.detect_ms:.0f}ms")
            if not in_match:
                brain.reset()
                in_match = True
                match_started = now
                match_log = []
                hp_trace = []
                # Both towers are full again; without this the filter's
                # never-rise rule would hold last match's zeros all game.
                hp_filter.reset()
                last_decision = last_idle_log = now
                log("MATCH_START")

            elapsed = now - match_started
            ticks += 1
            # Produces nothing under --vision yolo, which is how the bot runs:
            # brain/vision.py builds its detections with bbox=(0, 0, 0, 0), so
            # every crop is zero-sized and skipped, and SPRITES logs classes=0
            # for the whole run. Carrying the real box through the vision layer
            # would fix it, but that is the perception path and it is working;
            # it is not worth the risk for reference art capped at 6 per class.
            if harvester is not None and ticks % 4 == 0:
                harvester.harvest(full, [
                    (str(e.unit.name), e.position.bbox) for e in state.enemies
                ])
            last_towers = tower_hp.format_summary(ally_hp, enemy_hp)
            if ticks % 12 == 0:
                hp_trace.append((round(elapsed), last_towers))

            decision = brain.decide(state, elapsed, now, frame=full)
            if decision is None:
                # A long silence in the middle of a battle is always a bug -
                # either every candidate was filtered out or perception stopped
                # producing a usable hand.  Without this line the log shows a
                # gap and nothing to explain it.
                if now - last_decision > IDLE_REPORT_SECONDS and now - last_idle_log > IDLE_REPORT_SECONDS:
                    last_idle_log = now
                    obs = brain.last_obs
                    hand = list(obs.hand) if obs else []
                    log(f"IDLE {round(now - last_decision)}s elixir={state.numbers.elixir.number} "
                        f"hand={hand} threat={obs.threat_score:.0f}/{len(obs.threats)} "
                        f"spent={brain.committed_elixir:.0f} t={round(elapsed)}")
                time.sleep(0.15)
                continue
            last_decision = now

            target = arena.to_pixels(decision.x, decision.y)
            obs = brain.last_obs
            line = (f"{decision.card} slot={decision.slot} grid=({decision.x},{decision.y}) "
                    f"tag={decision.tag} score={decision.score:.1f} "
                    f"elixir={state.numbers.elixir.number} "
                    f"enemy_elixir={obs.enemy_elixir:.1f} "
                    f"threat={obs.threat_score:.0f}/{len(obs.threats)} "
                    f"{_threat_names(obs)}"
                    f"spent={brain.committed_elixir:.0f} t={round(elapsed)}")
            if args.dry_run:
                log(f"DRY {line}")
                time.sleep(0.25)
                continue

            guarded.tap(args.adb, args.serial, guarded.CARD_CENTRES[decision.slot])
            time.sleep(0.08)
            guarded.tap(args.adb, args.serial, target)
            brain.confirm(decision, now)
            match_log.append(f"{round(elapsed)}s {decision.card} ({decision.x},{decision.y}) {decision.tag}")
            log(f"PLAY #{brain.plays} {line}")
            time.sleep(0.12)
        except Exception as exc:
            log(f"ERROR {type(exc).__name__}: {exc}")
            time.sleep(1)

    log(f"STOP deadline matches={finished} queued={queued}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
