"""Live play: reader frame -> model -> taps on instance 3, battle after battle.

    .venvs\\royalegym\\Scripts\\python.exe scripts\\gamestate\\live_play.py ^
        --ckpt runs\\tokens\\rs_big_hog\\best.pt

Between battles it navigates with the old bot's screen logic
(scripts/gamestate/nav.py, ported from scripts/cr_bot.py): Battle in the
lobby, the end screen's button, chest / card-reveal screens, connection-lost
RELOAD, popup close buttons, and an app relaunch after 75 s stuck. It plays every battle
until Ctrl+C or a file named STOP in the repo root (--no-queue: you press
Battle yourself).
After each battle it prints the result and the running record, kept in
reports/live_play/record.json. Every tap, every opponent play and every result
is logged to reports/live_play/<time>.jsonl.

Ladder play was authorised by the owner on 2026-10-10.

Decision = the evaluator's (tools/rs_eval.RSAgent.act) with the measured live
configuration: the board is rebuilt from what is on screen and run 21 ticks
ahead (`--lead -21`, 47.0% vs 32.0% without, 300 matches) before deciding,
because a tap lands about 1.1 s after it is sent. The placement is checked in
the rebuilt battle (`check_deploy`), so an illegal tile is never tapped.

Added here, not measured in the evaluator: at 9.5+ elixir the agent does not
wait if a card is affordable (the dry run sat at 10 elixir for half a minute).

Instance safety: scripts/emulator.verify() refuses anything that is not the
Clash Royale instance; the Clash of Clans instance is never touched.
"""
from __future__ import annotations

import argparse
import json
import struct
import subprocess
import threading
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts"), str(ROOT / "tools")]

import emulator  # noqa: E402
from gamestate.live_bridge import CARD_MAP, CROWN_TOWERS, card_of_form, rs_state_from_frame  # noqa: E402
from gamestate.memread import GameMemory  # noqa: E402
from gamestate.nav import Navigator  # noqa: E402
from gamestate.bm import BMController, PriorityInput  # noqa: E402

ADB = r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe"
CARD_CENTRES = ((334, 1711), (538, 1711), (742, 1711), (946, 1711))   # mumu_overnight_bot
# Grid tile -> MuMu 1080x1920 pixel, copied from scripts/brain/arena.py (measured
# against the live emulator there; importing brain pulls in PIL and the old bot).
_X0, _XS, _Y0, _YS = 103.5, 51.0, 171.9, 41.4
PLAY_WINDOW = 20          # ticks: same card, same opponent play
DECIDE_LIVE = 1           # ticks: decide on every new frame (the evaluator used 10)
PENDING_TICKS = 60        # a sent play not seen after 3 s is assumed lost
AWAITING_MAX_AGE = 80     # ticks: drop unmatched tap records older than 4 s
AWAITING_MAX_MISS = 2500  # millitiles: appearance must land near the aimed tile
# Ticks from the tap decision to the troop on the board, MEASURED live on
# 2026-10-10: 25-27 over a session (RoyaleSim's client figure was 21, plus the
# tap itself). The look-ahead runs this far.
LEAD = 26
TRACE_TICKS = 10              # decision trace cadence (0.5 s)
FROZEN_FRAMES = 60            # tick unchanged this many frames (3 s) = battle over
CAP_ELIXIR = 9500         # milli; never sit here with an affordable card
FILLER = ["Knight", "Archer", "Giant", "Fireball", "Arrows", "Minions", "Valkyrie", "Goblins"]


# Wrong-lane guard (hand-written rule, not learned). Live logs of 2026-10-09:
# 24% of defensive plays within 3 s of an opponent's play went to the other
# lane, e.g. a Cannon across from a Royal Giant. When one lane clearly holds
# the threat, defensive cards may only go to that lane or the centre.
GUARD_CARDS = {"Cannon"}   # Ice Golem left out: pros pull with it into the other lane 17% of the time
GUARD_MIN_HP = 1200       # enemy hp on our side of the river before the rule acts
GUARD_SHARE = 0.75        # share of that hp in one lane for it to be "the" lane
GUARD_CENTRE = (7, 10)    # own-frame tile columns always allowed


def threat_lane(state, team, sub, own):
    """0 / 1 (own-frame x half) holding the enemy push, or None."""
    hp = [0.0, 0.0]
    for e in state["entities"]:
        if e[1] == team or e[2] == 1 or e[4] >= 0:      # buildings and towers (tower_slot >= 0)
            continue
        ox, oy = own(e[5], e[6], team, sub)
        if oy < 13_000:          # still deep on their side
            continue
        hp[0 if ox < 9_000 else 1] += max(0, e[7])
    tot = hp[0] + hp[1]
    if tot < GUARD_MIN_HP:
        return None
    for lane in (0, 1):
        if hp[lane] >= GUARD_SHARE * tot:
            return lane
    return None


def screen_tile(tx, ty):
    """Model tile (own frame, a half turn of the world) -> screen tile.

    The own frame is the replay convention: the board turned so we are at the
    bottom. The screen also puts us at the bottom, but as a MIRROR of that
    frame, not the same picture: the 2026-10-10 friendly (reader side 1)
    defended every left push in the right lane. Mirroring x fixes it; the
    derivation says the same holds for side 0, which is UNVERIFIED live.
    Every tile printed and logged here is a screen tile, x 0 = screen left.
    """
    return 17 - tx, ty


class Tapper:
    """One adb shell kept open; a play is two `input tap` lines written to it.

    A fresh `adb shell` per play cost a ~40 ms connection each time
    (measured 2026-10-10: round trip 39 ms, input tap 46-50 ms in total).
    """

    def __init__(self, serial):
        self.serial = serial
        self._open()

    def _open(self):
        import queue
        self.acks = queue.Queue()
        self.p = subprocess.Popen([ADB, "-s", self.serial, "shell"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        def read_acks():
            for line in self.p.stdout:
                if '__HCR_INPUT_DONE__' in line:
                    self.acks.put(True)
        threading.Thread(target=read_acks, daemon=True).start()

    def _send(self, cmd):
        self.p.stdin.write(cmd + '; echo __HCR_INPUT_DONE__\n')
        self.p.stdin.flush()
        # Worker waits for execution, not just a successful pipe write.
        self.acks.get(timeout=1)

    def tap(self, xy):
        self._send(f"input tap {xy[0]} {xy[1]}")

    def tap_pair(self, a, b):
        self._send(f"input tap {a[0]} {a[1]}; input tap {b[0]} {b[1]}")

    def close(self):
        try:
            self.p.stdin.close()
            self.p.terminate()
        except (OSError, ValueError):
            pass


def other_bots():
    """PIDs of other live_play processes (a venv launcher and its child count as one run)."""
    import os
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*live_play*' } | "
         "ForEach-Object { \"$($_.ProcessId) $($_.ParentProcessId)\" }"],
        capture_output=True, text=True, timeout=30).stdout.split()
    pairs = [(int(out[i]), int(out[i + 1])) for i in range(0, len(out) - 1, 2)]
    mine = {os.getpid(), os.getppid()}
    return [p for p, parent in pairs if p not in mine and parent not in mine]


def probe_side(dev, default):
    """Which player record is ours: the one holding a real hand.

    Reads only the two hand-index vectors, to tell the records apart; neither
    is kept and the opponent's is never used. Our hand is 4 distinct deck
    indexes; the opponent's read as -1 in the first friendly. If both look
    valid the default is kept and a warning printed.
    """
    b = dev.battle()
    if not b:
        return default
    ps = dev.u64(b + 0xA8)
    valid = []
    for k in range(2):
        p = dev.u64(ps + 0xE0 + 8 * k)
        if not p:
            continue
        raw = dev.read(p, 0x220)
        side = struct.unpack_from("<i", raw, 0x78)[0]
        vec, size = struct.unpack_from("<Q", raw, 0x210)[0], struct.unpack_from("<i", raw, 0x21C)[0]
        if size != 4 or not vec:
            continue
        hand = struct.unpack("<4i", dev.read(vec, 16))
        if len(set(hand)) == 4 and all(0 <= h < 8 for h in hand):
            valid.append(side)
    if len(valid) == 1:
        return valid[0]
    print(f"  side probe ambiguous ({valid}), using side {default}")
    return default


def battle_result(frame, my_side):
    """(our crowns, their crowns, outcome) from the last battle frame.

    A destroyed princess tower leaves the entity list; a destroyed king stays
    with 0 hp and is 3 crowns (both seen in the 2026-10-10 friendly). Equal
    crowns: the lower lowest-tower hp loses (the game's tiebreak; UNVERIFIED
    that the reader's last frame shows the final hp), equal hp is a draw.
    """
    towers = {0: [], 1: []}
    for u in (frame or {}).get("u", []):
        name = u[10] if len(u) > 10 else ""
        if name in CROWN_TOWERS and u[3] in towers:
            towers[u[3]].append((name, u[8]))

    def crowns_against(side):
        ts = towers[side]
        if any("King" in n and hp <= 0 for n, hp in ts):
            return 3
        return 2 - sum(1 for n, hp in ts if 'King' not in n and hp > 0)

    def lowest(side):
        return min((hp for _, hp in towers[side] if hp > 0), default=0)

    ours, theirs = crowns_against(1 - my_side), crowns_against(my_side)
    if ours != theirs:
        return ours, theirs, "win" if ours > theirs else "loss"
    if lowest(my_side) != lowest(1 - my_side):
        return ours, theirs, "win" if lowest(my_side) > lowest(1 - my_side) else "loss"
    return ours, theirs, "draw"


def discover_build(dev, args, minutes=12):
    """A game update moved the battle global. Queue a battle (or wait for one
    the owner starts), find the chain to it with the on-device probe, keep the
    candidate whose clock moves, check a reader frame shows both sides' crown
    towers, save it to offsets.json and return True. Read-only throughout; the
    battle it is found in is then played from that point on.
    """
    print(f"client build {dev.version} is new: finding its memory addresses in the next battle "
          f"(reads only). Queueing a battle...")
    nav = Navigator(dev.serial, queue=not args.no_queue)
    first, t_end, last_nav = {}, time.monotonic() + 60 * minutes, 0.0
    while time.monotonic() < t_end:
        if (ROOT / "STOP").exists():
            return False
        cands = dev.find_battle()
        if not cands:
            if time.monotonic() - last_nav > 2.0:
                last_nav = time.monotonic()
                try:
                    note = nav.step()
                except Exception as exc:
                    note = f"    navigation error {type(exc).__name__}: {exc}"
                if note:
                    print(note)
            time.sleep(1)
            continue
        moving = [c for c in cands if (c[0], c[1], c[2]) in first and c[3] > first[(c[0], c[1], c[2])]]
        for c in cands:
            first.setdefault((c[0], c[1], c[2]), c[3])
        if not moving:
            print(f"    battle seen: {len(cands)} candidate chain(s); checking which clock moves")
            time.sleep(2)
            continue
        # Prefer the old hop pair (0x18, 0x90) when several chains reach the battle.
        moving.sort(key=lambda c: (c[1] != 0x18 or c[2] != 0x90, c[0]))
        for g, h1, h2, tick in moving:
            env = f"HCR_GLOBAL={g:x} HCR_HOP1={h1:x} HCR_HOP2={h2:x}"
            out = subprocess.run([ADB, "-s", dev.serial, "exec-out",
                                  f"{env} /data/local/tmp/hcr_reader {dev.pid} {dev.libg:x} 25 1"],
                                 capture_output=True, text=True, timeout=30).stdout
            try:
                f = json.loads(out.strip().splitlines()[-1])
            except (ValueError, IndexError):
                continue
            towers = [u for u in f.get("u", []) if len(u) > 10 and u[10] in CROWN_TOWERS]
            sides = {u[3] for u in towers}
            if "me" in f and len(towers) >= 4 and sides == {0, 1}:
                dev.learn_build(g, h1, h2, f"found live by hcr_findbattle {time.strftime('%Y-%m-%d %H:%M')}, "
                                           f"tick {tick}; {len(towers)} crown towers read")
                print(f"    build {dev.version}: battle global libg+{g:#x}, hops {h1:#x} {h2:#x}. "
                      f"Saved to offsets.json; playing.")
                return True
            print(f"    chain libg+{g:#x} {h1:#x} {h2:#x} reaches a battle but its units do not read "
                  f"({len(towers)} towers); the unit layout may have changed too")
        time.sleep(2)
    print("no battle found in time, or no chain whose units read correctly. The update may have "
          "changed the battle layout itself; send me the console output.")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--deck", default="",
                    help="optional: the deck's cards. Normally omitted: the deck and its order come from game "
                         "memory (reports/live_play/deck_order.json, corrected and extended in every battle)")
    ap.add_argument("--side", type=int, default=1,
                    help="fallback when the side probe is ambiguous")
    ap.add_argument("--no-cap-rule", action="store_true")
    ap.add_argument("--no-bm", action="store_true", help="disable memory-triggered emotes")
    ap.add_argument("--no-personality", action="store_true", help="disable the robot overlay")
    ap.add_argument("--personality", action="store_true", help="enable the optional robot overlay")
    ap.add_argument("--no-queue", action="store_true", help="do not press Battle / OK")
    ap.add_argument("--card-audit", action="store_true", help="persistent opponent card audit; forces --no-queue")
    ap.add_argument("--audit-expected", default="", help="comma-separated opponent test cards for this friendly")
    ap.add_argument("--no-lane-guard", action="store_true",
                    help="let Cannon / Ice Golem go to the lane without the enemy push")
    ap.add_argument("--old-lookahead", action="store_true",
                    help="the 2026-10-12 hero-board prediction, for comparison")
    ap.add_argument("--gate-temp", type=float, default=0.1,
                    help="league checkpoints: play/wait temperature (0.1 near-greedy; 1.0 = as trained)")
    ap.add_argument("--heroes", default="Musketeer,IceGolemite",
                    help="our cards played in hero form (league checkpoints: ability buttons)")
    ap.add_argument("--button-px", default="",
                    help="screen position 'x,y' of the first hero ability button (default: league.live.BUTTON_PX[0])")
    ap.add_argument('--no-tactical-guards',action='store_true',help='use the unmodified policy for defence comparisons')
    # Off by default: the owner found the hand-written Hog rule made play
    # worse (2026-10-14); post-tower play is taught in training instead.
    ap.add_argument('--hog-guard',action='store_true',help='force Hog toward a surviving princess (hand-written rule)')
    ap.add_argument('--shadow-search', action='store_true',
                    help='league checkpoints: re-rank the model tile in a shadow copy of the battle (tools/league/shadow_search.py)')
    ap.add_argument('--evos', default='BattleRam,RageBarbarian', help='our cards played evolved (shadow search forms)')
    ap.add_argument('--search-k', type=int, default=8, help='shadow search: model tiles tried')
    ap.add_argument('--search-margin', type=float, default=0.0, help='shadow search: score gain needed to override the model (bench C 2026-11-24: 0)')
    ap.add_argument('--search-own-tol', type=float, default=0.01, help='shadow search: override may cost our towers at most this tower fraction (not benched)')
    ap.add_argument('--search-horizon', type=int, default=200, help='shadow search: ticks simulated per tile')
    ap.add_argument('--record-frames', type=int, default=0,
                    help='log every unit on the board every N ticks (engine comparison; 0 = off)')
    args = ap.parse_args()
    if args.card_audit:
        args.no_queue = True
    emulator.verify()
    others = other_bots()
    if others:
        print(f"refusing: another bot is already running (pids {others}). Two would both tap.")
        return 2
    stop_file = ROOT / "STOP"
    if stop_file.exists():
        print(f"refusing: {stop_file} exists. Delete it to run.")
        return 2

    import rs_rows as RR
    from rs_eval import DECIDE, RSAgent, _unit_names, to_world
    royalesim, names, ids, cat = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    unit_types = _unit_names()
    audit = None
    if args.card_audit:
        from gamestate.card_audit import CardAudit
        audit = CardAudit(ROOT / 'reports' / 'card_audit' / 'coverage.json',
                          cat, unit_types, CARD_MAP, card_of_form, args.audit_expected)
        print(f"Friendly card audit: {audit.path} (ladder queue disabled)")
    # The deck comes from memory: deck_order.json is the order the in-battle check
    # learned (a card's slot is fixed the first time it is played). --deck only seeds
    # it when there is no learned order yet.
    # The in-game deck order, learned from memory (see the deck check below)
    # and kept across runs. A wrong --deck swaps cards: on 2026-10-14 a stale
    # order turned every Cannon into a Musketeer and every Ice Golem into Ice
    # Spirits for a whole morning of games.
    deck_file = ROOT / "reports" / "live_play" / "deck_order.json"
    learned = None
    try:
        learned = json.loads(deck_file.read_text())
    except (OSError, ValueError):
        pass
    given = [c for c in args.deck.split(",") if c]
    if learned and (not given or sorted(learned) == sorted(given)):
        deck_names = learned
        print(f"deck from memory (deck_order.json): {deck_names}")
    elif given:
        deck_names = given
        print(f"deck from --deck (memory will correct it in the first battle): {deck_names}")
    else:
        sys.exit("no deck known yet: play once with --deck <8 cards> (any order); memory fixes the order")
    deck_rs = [ids[c] for c in deck_names]
    deck_check = {"count": None, "seen": 0, "hand": None}
    # A league checkpoint (tools/league) has its own observation, sampling and
    # ability buttons; everything else (reader, bridge, taps, logs) is shared.
    from league.live import BUTTON_PX, LeagueLive, is_league
    if args.button_px:
        BUTTON_PX = (tuple(int(v) for v in args.button_px.split(",")),) + tuple(BUTTON_PX[1:])
    from league import obs as LOBS
    league_ckpt, league_blob = is_league(args.ckpt)
    league = None
    if league_ckpt:
        LOBS.setup(royalesim)
        hero_cards = [c.strip() for c in args.heroes.split(",") if c.strip()]
        league = LeagueLive(league_blob, unit_types, deck_names, hero_cards,
                            gate_temp=args.gate_temp)
        agent = league
        print(f"League checkpoint; ability buttons for {league.buttons}")
    else:
        agent = RSAgent(args.ckpt)
    torch = agent.torch
    shadow = None
    # Every shadow call runs on one worker thread with a time limit (2026-11-24: the first
    # live game froze at t 3902 with no decisions until the end, most likely an engine
    # reply that never came). A call over the limit turns the shadow off for the battle;
    # the stuck thread is abandoned and the model plays alone.
    import concurrent.futures
    _shadow_pool = concurrent.futures.ThreadPoolExecutor(1)

    _stuck = []

    def shadow_call(fn, timeout):
        fut = _shadow_pool.submit(fn)
        try:
            return fut.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            # 2026-11-24: one slow overtime call (>1 s) used to switch search off for the
            # whole session (4 games ran model-only). Now it is off only until that call
            # has finished; the next battle start revives it (shadow_alive).
            shadow.dead = True
            _stuck[:] = [fut]
            raise RuntimeError(f"shadow call over {timeout} s")

    def shadow_alive():
        if getattr(shadow, "dead", False) and _stuck and _stuck[0].done():
            shadow.dead = False
            _stuck.clear()
            print("shadow search revived: the slow call has finished")
        return not getattr(shadow, "dead", False)
    if args.shadow_search and league:
        try:
            sys.path.insert(0, str(ROOT / "tools" / "league"))
            from shadow_search import ShadowSearch
            evos = [c for c in args.evos.split(",") if c]
            forms = [2 if c in hero_cards else 1 if c in evos else 0 for c in deck_names]
            shadow = ShadowSearch(deck_names, forms, k=args.search_k, margin=args.search_margin,
                                  horizon=args.search_horizon,
                                  own_tol=args.search_own_tol,
                                  log=lambda rec: (logf.write(json.dumps(rec) + "\n"), logf.flush()))
            print(f"shadow search on: forms {forms}, k {args.search_k}, margin {args.search_margin}")
        except Exception as exc:
            print(f"shadow search unavailable, model alone: {type(exc).__name__}: {exc}")
            shadow = None

    log_dir = ROOT / "reports" / "live_play"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / time.strftime("%Y%m%d_%H%M%S.jsonl")
    logf = log_path.open("a", encoding="utf-8")
    # Which checkpoint and flags produced this log; earlier logs could not say.
    logf.write(json.dumps({"session": {"ckpt": str(args.ckpt), "argv": sys.argv[1:],
                                       "lead": LEAD}}) + "\n")
    logf.flush()
    record_path = log_dir / "record.json"
    try:
        record = json.loads(record_path.read_text())
    except (OSError, ValueError):
        record = {"win": 0, "loss": 0, "draw": 0}

    dev = GameMemory(allow_new=True)
    side = args.side
    if not dev.known:
        if not discover_build(dev, args):
            return 2

    def start_reader(side_):
        p = subprocess.Popen(
            [ADB, "-s", dev.serial, "exec-out",
             f"{dev.reader_env()} HCR_SIDE={side_} /data/local/tmp/hcr_reader {dev.pid} {dev.libg:x} 25"],
            stdout=subprocess.PIPE, text=True)
        # A thread drains the pipe and keeps only the newest frame. Reading
        # line by line, a decision slower than the 50 ms frame interval left
        # a growing queue behind it, so the bot acted on ever older frames.
        p.latest, p.seq, p.cv = None, 0, threading.Condition()

        def pump():
            for line in p.stdout:
                with p.cv:
                    p.latest, p.seq = line, p.seq + 1
                    p.cv.notify()
            with p.cv:
                p.latest, p.seq = "", p.seq + 1
                p.cv.notify()
        threading.Thread(target=pump, daemon=True).start()
        return p

    def next_line(p, last_seq):
        with p.cv:
            p.cv.wait_for(lambda: p.seq != last_seq, timeout=5)
            return p.latest, p.seq

    proc = start_reader(side)
    tapper = PriorityInput(Tapper(dev.serial))
    bm = BMController()
    print(f"LIVE: tapping on {dev.serial}. Stop: Ctrl+C, or create {stop_file}.")
    print(f"Log: {log_path}   record so far: {record}")
    in_battle, last_frame, plays = False, None, 0
    ended_at, last_nav = None, 0.0
    nav = Navigator(dev.serial, queue=not args.no_queue)
    prev_tick_seen = None
    delays, misses = [], []
    prev_present = {0: set(), 1: set()}
    side_confirmed = False
    frozen_n, last_tick, last_end_tick = 0, -1, None
    seq = 0
    from extras.personality.lifecycle import start as start_personality, stop as stop_personality
    personality = start_personality(side, log_path) if args.personality and not args.no_personality else None
    from gamestate.unknown_capture import UnknownCapture
    unknown_capture = UnknownCapture(ROOT / 'reports' / 'card_audit' / 'unknown_captures', ADB, dev.serial)
    from gamestate.tactics import defence_plan, defence_order, hog_order
    last_reader_warning = 0.0
    last_defence_t = -10000
    track = {}
    last_trace = -10**9
    last_rec = -10**9
    try:
        while True:
            line, seq_new = next_line(proc, seq)
            if seq_new == seq:
                continue                    # no frame for 5 s; keep waiting
            seq = seq_new
            if not line:
                tapper.battle(False)
                print("reader exited; restarting it.")
                time.sleep(1)
                proc = start_reader(side)
                seq = 0
                continue
            if stop_file.exists():
                print("STOP file found, stopping.")
                break
            try:
                f = json.loads(line)
            except json.JSONDecodeError:
                print(f"reader said (not JSON): {line.rstrip()!r}")
                continue
            if f.get('registry_valid') is False:
                if time.monotonic()-last_reader_warning>2:
                    last_reader_warning=time.monotonic()
                    logf.write(json.dumps({'reader_warning':'invalid registry; refusing empty-board decisions',
                                           't':f.get('t'),'registry_count':f.get('registry_count')})+'\n')
                    logf.flush()
                continue
            frozen = in_battle and f.get("t", -1) >= 0 and f.get("t") == last_tick
            frozen_n = frozen_n + 1 if frozen else 0
            last_tick = f.get("t", -1)
            # After a battle the client keeps its battle object (end screen) with
            # the clock stopped; those frames are not a new battle.
            stale = not in_battle and last_end_tick is not None and f.get("t") == last_end_tick
            # Out of a battle, a battle object whose clock is not moving (the
            # end screen, also when the bot is started on it) is not a battle.
            if not in_battle and not stale:
                stale = prev_tick_seen is None or f.get("t") == prev_tick_seen
            prev_tick_seen = f.get("t")
            if f.get("t", -1) < 0 or "me" not in f or frozen_n >= FROZEN_FRAMES or stale:
                if in_battle:
                    tapper.battle(False)
                if in_battle:
                    in_battle = False
                    ours, theirs, outcome = battle_result(last_frame, side)
                    if delays:
                        ds = sorted(delays)
                        print(f"    tap->board delay over {len(ds)} plays: median {ds[len(ds) // 2]} ticks, "
                              f"min {ds[0]}, max {ds[-1]} (look-ahead assumes {LEAD})")
                    if misses:
                        mx = sorted(m[0] for m in misses)[len(misses) // 2]
                        my = sorted(m[1] for m in misses)[len(misses) // 2]
                        print(f"    placement vs aim, median over {len(misses)}: x {mx:+.2f} y {my:+.2f} tiles "
                              f"(+y = toward the enemy)")
                    if plays == 0:
                        # Not a battle we played: a finished battle's object
                        # read at startup scored "win 0-0, 0 plays" (2026-10-10).
                        print("    battle ended with no plays from us; not counted")
                        ended_at = time.monotonic()
                        last_end_tick = f.get("t", -1)
                        continue
                    record[outcome] += 1
                    record_path.write_text(json.dumps(record))
                    n = sum(record.values())
                    logf.write(json.dumps({"result": outcome, "crowns": [ours, theirs],
                                           "plays": plays, "record": record}) + "\n")
                    logf.flush()
                    print(f"=== {outcome.upper()} {ours}-{theirs}   record W{record['win']} "
                          f"L{record['loss']} D{record['draw']}  "
                          f"({100 * record['win'] / max(1, n):.0f}% of {n})")
                    ended_at = time.monotonic()
                    last_end_tick = f.get("t", -1)
                if time.monotonic() - last_nav > 1.0:
                    last_nav = time.monotonic()
                    try:
                        note = nav.step()
                    except Exception as exc:          # a bad screenshot must not end the run
                        note = f"    navigation error {type(exc).__name__}: {exc}"
                    if note:
                        print(note)
                continue
            if not in_battle:
                # New battle: find our side, reset everything kept per battle.
                new_side = probe_side(dev, side)
                if new_side != side:
                    side = new_side
                    proc.terminate()
                    proc = start_reader(side)
                    seq = 0
                    print(f"--- our side is {side}; reader restarted")
                    continue
                in_battle = True
                tapper.battle(True)
                bm.reset()
                ended_at = None
                print(f"--- battle started, our side {side}")
                if league:
                    league.reset()
                    if shadow and shadow_alive():
                        try:
                            shadow_call(lambda: shadow.new_battle(side, f), 3.0)
                        except Exception as exc:
                            print(f"shadow new battle failed: {type(exc).__name__}: {exc}")
                else:
                    agent.lead, agent.lead_rebuild, agent.sent = LEAD, True, []
                mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}}
                deck_check.update(count=None, seen=0, hand=None, frozen=False)
                known, last_opp_play = set(), {}
                plays, last_decide = 0, -10**9
                pending = []
                last_defence_t = -10000
                awaiting = []
                prev_present = {0: set(), 1: set()}
                track = {}
                last_trace = -10**9
                last_rec = -10**9
                last_rebuild_error = None
                side_confirmed = False
            last_frame = f
            now = f["t"]
            # Board recording for comparing the engine with the real game:
            # [addr, side, x, y, level, hp, max hp, name, deploy ms] per unit.
            if args.record_frames and now - last_rec >= args.record_frames:
                last_rec = now
                logf.write(json.dumps({"f": now, "u": [[u[0], u[3], u[4], u[5], u[7], u[8], u[9],
                                                       u[10] if len(u) > 10 else "",
                                                       u[11] if len(u) > 11 else 0] for u in f["u"]],
                                       # the whole reader frame and our side, so the model's
                                       # input can be rebuilt offline exactly as live built it
                                       "raw": f, "side": side}) + "\n")
            # Side check from the board: a unit of a card that is not in our
            # deck is the opponent's. If one stands on "our" side, the side is
            # wrong - switch before another decision is made on their hand.
            if not side_confirmed:
                for u in f["u"]:
                    name = u[10] if len(u) > 10 else ""
                    if name in CROWN_TOWERS or "Projectile" in name or "Container" in name:
                        continue
                    entry = CARD_MAP.get(str(u[6]))
                    c = entry["rs_id"] if entry else card_of_form(name, cat)
                    if c >= 0 and c not in deck_rs:
                        side_confirmed = True
                        if u[3] == side:
                            side = 1 - side
                            print(f"--- {cat[c][0]} is on side {u[3]}: we are side {side}; reader restarted")
                            proc.terminate()
                            proc = start_reader(side)
                            seq = 0
                            in_battle = False
                            tapper.battle(False)
                        break
                if not in_battle:
                    continue
            # Deck check: when a card is played for the first time, memory adds
            # its id to our played list (reader me[5]); the deck index that just
            # left the hand is that card. Fix deck_rs in place on a mismatch.
            me_ = f.get("me") or []
            if len(me_) > 5 and isinstance(me_[5], list):
                hand_idx, count, played = me_[2], me_[4], [c for c in me_[5] if c >= 0]
                prev = deck_check
                if (prev["count"] is not None and count == prev["count"] + 1 and prev["hand"]
                        and len(played) == prev["seen"] + 1):
                    left = [i for i in prev["hand"] if i not in hand_idx]
                    entry = CARD_MAP.get(str(played[-1]))
                    if len(left) == 1 and entry is not None and 0 <= left[0] < len(deck_rs):
                        actual, k = entry["rs_id"], left[0]
                        if actual not in deck_rs:
                            # 2026-11-24: in some battles me[5] holds the OPPONENT's played
                            # cards (Mortar, Ice Wizard, Barbarian Barrel showed up as ours and
                            # turned an Arrows slot into "Heal"). A card outside the deck is
                            # taken as that, and corrections stop for the rest of the battle.
                            if not deck_check.get("frozen"):
                                print(f"--- deck check: {cat[actual][0]} is not in our deck; ignoring memory deck checks this battle")
                                logf.write(json.dumps({"t": f.get("t"), "deck_check_frozen": cat[actual][0]}) + "\n")
                            deck_check["frozen"] = True
                        elif deck_check.get("frozen"):
                            pass
                        elif deck_rs[k] != actual:
                            if actual in deck_rs:          # known card, wrong slot: swap
                                j = deck_rs.index(actual)
                                deck_rs[k], deck_rs[j] = deck_rs[j], deck_rs[k]
                            else:                          # a card not in the known deck: the deck changed
                                deck_rs[k] = actual
                            names_now = [cat[c][0] for c in deck_rs]
                            if league:                     # ability buttons follow the deck order
                                league.buttons = [c for c in names_now if c in league.hero_cards]
                            print(f"--- deck order corrected from memory: slot {k} is {cat[actual][0]}; now {names_now}")
                            logf.write(json.dumps({"t": f.get("t"), "deck_corrected": names_now}) + "\n")
                            try:
                                deck_file.write_text(json.dumps(names_now))
                            except OSError:
                                pass
                deck_check.update(count=count, seen=len(played), hand=list(hand_idx))
            state = rs_state_from_frame(f, side, deck_rs, unit_types, cat, sub)
            # Positions over the last ~10 ticks per unit, for the velocity
            # extrapolation used when the engine lookahead is unavailable.
            F = RR.F
            alive = set()
            for e in state["entities"]:
                uid = e[F["uid"]]
                alive.add(uid)
                hist = track.setdefault(uid, [])
                hist.append((f["t"], e[F["x"]], e[F["y"]]))
                while len(hist) > 2 and f["t"] - hist[1][0] >= 10:
                    hist.pop(0)
            for uid in [u for u in track if u not in alive]:
                del track[uid]
            unknown_capture.observe(f, side, state)
            if audit:
                audit.observe(f, side, state)
            if not args.no_bm:
                bm.observe(f, side)
            for event in tapper.drain():
                logf.write(json.dumps(dict(event, t=now)) + "\n")
                if 'input_error' in event:
                    raise RuntimeError(f"input worker failed: {event['input_error']}")
            team = next((t for t in (0, 1) if state["players"][t]["hand"]), None)
            if team is None:
                continue
            # Opponent plays, from the raw frame so spells count too (they are
            # not units). One play = the first new entity of a card; more of
            # the same card within PLAY_WINDOW ticks (3 Skeletons, a Log and
            # its roller, Ice Spirits and the freeze) are the same play.
            # Which card each object belongs to, and which cards were on the
            # board last frame. A new object is a PLAY only if its card had
            # nothing on the board in the previous frame, and only once per
            # frame. Shots (TowerCannonball, MinionSpit, ArcherArrow), spawns
            # (a Witch's or a Graveyard's skeletons) and explosions all appear
            # while their source is alive; counted as plays, they filled the
            # model's "opponent's last 4 plays" input with junk in exactly the
            # busy fights where it then played badly (2026-10-10 log: 11
            # "Cannon" plays that were cannonballs, 10 "Minions" that were spit).
            def card_of(u):
                entry = CARD_MAP.get(str(u[6]))
                return entry["rs_id"] if entry else card_of_form(u[10] if len(u) > 10 else "", cat)
            present = {0: set(), 1: set()}
            counted = set()
            for u in f["u"]:
                if u[3] in present:
                    present[u[3]].add(card_of(u))
            for u in f["u"]:
                addr, uside, x, y, card_native = u[0], u[3], u[4], u[5], u[6]
                if addr in known:
                    continue
                c_here = card_of(u)
                fresh = (c_here >= 0 and c_here not in prev_present.get(uside, set())
                         and (uside, c_here) not in counted)
                if not fresh:
                    known.add(addr)
                    continue
                counted.add((uside, c_here))
                if uside == side and addr not in known:
                    # Our own play appearing: tap -> on-board delay, measured
                    # per play. The look-ahead assumes LEAD ticks; this says
                    # what it really is on this rig.
                    known.add(addr)
                    entry = CARD_MAP.get(str(card_native))
                    name = u[10] if len(u) > 10 else ""
                    c = entry["rs_id"] if entry else card_of_form(name, cat)
                    # Appearance attribution: match the awaiting tap whose aim
                    # is NEAREST where this unit appeared (within 2.5 tiles).
                    # First-same-card pairing misattributed taps when a stale
                    # request matched a later deployment - it printed delays
                    # of hundreds of ticks that were matching bugs, not lag.
                    best_k, best_d = None, AWAITING_MAX_MISS ** 2
                    for k, (t_tap, c_tap, w_tap, aim, tm) in enumerate(awaiting):
                        if c_tap != c:
                            continue
                        ax, ay = RR.own(aim[0], aim[1], tm, sub)
                        lx, ly = RR.own(x * sub, y * sub, tm, sub)
                        d = (lx - ax) ** 2 + (ly - ay) ** 2
                        if d < best_d or (d == best_d and t_tap < awaiting[best_k][0]):
                            best_k, best_d = k, d
                    if best_k is None:
                        continue            # mirrored card or spawn we did not send
                    t_tap, c_tap, w_tap, aim, tm = awaiting.pop(best_k)
                    lag = now - t_tap
                    delays.append(lag)
                    ax, ay = RR.own(aim[0], aim[1], tm, sub)
                    lx, ly = RR.own(x * sub, y * sub, tm, sub)
                    dx, dy = (lx - ax) / 1000, (ay - ly) / 1000
                    misses.append((dx, dy))
                    logf.write(json.dumps({"t": now, "landed": cat[c][0], "delay_ticks": lag,
                                           "wall_ms": round(1000 * (time.monotonic() - w_tap)),
                                           "miss_tiles": [round(dx, 2), round(dy, 2)]}) + "\n")
                    print(f"t={now:5d}   landed {cat[c][0]} {lag} ticks after the tap decision "
                          f"({round(1000 * (time.monotonic() - w_tap))} ms wall), "
                          f"off aim by x {dx:+.1f} y {dy:+.1f} tiles")
                    continue
                if uside == side or addr in known:
                    continue
                known.add(addr)
                entry = CARD_MAP.get(str(card_native))
                name = u[10] if len(u) > 10 else ""
                card = entry["rs_id"] if entry else card_of_form(name, cat)
                # A Wall Breaker's projectile, a Skeleton Barrel's container, a
                # Blowdart Goblin's dart carry the card id too: not new plays.
                if "Projectile" in name or "Container" in name:
                    continue
                if card < 0 or now - last_opp_play.get(card, -10**9) < PLAY_WINDOW:
                    continue
                last_opp_play[card] = now
                mem["seen"][1 - team].add(card + 2)
                mem["last"][1 - team].append((card + 2, now))
                ox, oy = RR.own(x * sub, y * sub, team, sub)
                sx, sy = screen_tile(int(ox // 1000), int(oy // 1000))
                rec = {"t": now, "opp": cat[card][0], "unit": name, "tile": [sx, sy]}
                logf.write(json.dumps(rec) + "\n")
                print(f"t={now:5d}   opp  {rec['opp']} ({name or 'spell'}) tile ({sx},{sy})")
            prev_present = present
            if shadow and shadow.sh is not None and not shadow.broken and not getattr(shadow, "dead", False):
                try:
                    shadow_call(lambda: (shadow.observe(f, card_of, cat), shadow.sync(f, now)), 1.5)
                except Exception as exc:          # never let the shadow stop play (or hang it)
                    shadow.broken = f"{type(exc).__name__}: {exc}"[:200]
                    logf.write(json.dumps({"t": now, "shadow": "off", "why": shadow.broken}) + "\n")
                    print(f"t={now:5d} shadow off: {shadow.broken}")
            # Expire unmatched tap records after 4 s: a request that old either
            # was never executed or its unit was filtered; keeping it would let
            # it match a later deployment of the same card (the 600-tick bug).
            if awaiting:
                awaiting = [a for a in awaiting if now - a[0] < AWAITING_MAX_AGE]
            # Opponent deck for the rebuild: cards seen so far, padded. It makes
            # no plays in the look-ahead, so the padding never acts.
            opp_seen = [c - 2 for c in sorted(mem["seen"][1 - team])]
            state["players"][1 - team]["deck"] = (opp_seen + [ids[n] for n in FILLER
                                                             if ids[n] not in opp_seen])[:8]
            p = state["players"][team]
            # Plays sent but not yet shown by the reader (~1.1 s). Instead of
            # freezing until they land, their slot is blocked and their cost
            # is taken off the elixir we can spend, so a second card can
            # follow at once (a two-card defence) without double-playing.
            pending = [(sl, c, cost, t0) for (sl, c, cost, t0) in pending
                       if sl < len(p["hand"]) and p["hand"][sl] == c and now - t0 < PENDING_TICKS]
            spendable = p["elixir_milli"] - 1000 * sum(cost for _, _, cost, _ in pending)
            blocked = {sl for sl, _, _, _ in pending}
            if now - last_decide < DECIDE_LIVE:
                continue
            dt = min(DECIDE, max(1, now - last_decide))
            last_decide = now
            t_decide = time.perf_counter()
            if league:
                try:
                    dec = league.decide(state, team, mem, now, dt, sub, blocked, spendable, unit_types, cat)
                except Exception as exc:          # one bad frame must not end the match for us
                    logf.write(json.dumps({"t": now, "decide_error": f"{type(exc).__name__}: {exc}"}) + "\n")
                    continue
                if now - last_trace >= TRACE_TICKS:
                    last_trace = now
                    logf.write(json.dumps({"trace": now, "elixir": p["elixir_milli"], "spendable": spendable,
                                           "p_wait": round(dec["p_wait"], 3), "blocked": sorted(blocked),
                                           "hand": [cat[c][0] for c in p["hand"]], "look": "league",
                                           "mask": dec["mask"]}) + "\n")
                if dec["kind"] == "wait":
                    # Emotes while waiting, as the older agent path does; the
                    # league path skipped this, so league models never BM'd.
                    if not args.no_bm:
                        proposal = bm.proposal()
                        if proposal and tapper.offer(*proposal):
                            bm.accepted()
                elif dec["kind"] == "button":
                    tapper.tap(BUTTON_PX[dec["k"]])
                    logf.write(json.dumps({"t": now, "ability": dec["card"], "button": dec["k"],
                                           "px": BUTTON_PX[dec["k"]], "elixir": p["elixir_milli"]}) + "\n")
                    logf.flush()
                    print(f"t={now:5d} ABILITY {dec['card']} (button {dec['k']})")
                elif dec["kind"] == "card":
                    slot, t = dec["slot"], dec["tile"]
                    card = p["hand"][slot]
                    sinfo = None
                    if shadow and dec.get("order") and not getattr(shadow, "dead", False):
                        try:
                            def tiles_of(order, first=None):
                                tl_ = ([first] if first is not None else []) + [tt for tt in order if tt != first]
                                return [(tt,) + tuple(to_world((tt % 18) * 1000 + 500, (tt // 18) * 1000 + 500, team))
                                        for tt in tl_]
                            orders = dec.get("orders") or {slot: dec["order"]}
                            options = [(slot, cat[card][0], 2 if cat[card][0] in hero_cards else 0,
                                        p["hand_costs"][slot], tiles_of(orders.get(slot, dec["order"]), t))]
                            for s2, o2 in orders.items():
                                if s2 != slot and o2:
                                    c2 = p["hand"][s2]
                                    options.append((s2, cat[c2][0], 2 if cat[c2][0] in hero_cards else 0,
                                                    p["hand_costs"][s2], tiles_of(o2)))
                            try:
                                oi, ti, sinfo = shadow_call(lambda: shadow.choose_cards(team, options, now, spendable), 1.0)
                            except Exception as exc:
                                shadow.broken = f"search {type(exc).__name__}: {exc}"[:200]
                                print(f"t={now:5d} shadow off: {shadow.broken}")
                                raise
                            slot = options[oi][0]
                            card = p["hand"][slot]
                            t = options[oi][4][ti][0]
                            logf.write(json.dumps(sinfo) + "\n")
                        except Exception as exc:
                            logf.write(json.dumps({"t": now, "search_error": f"{type(exc).__name__}: {exc}"[:200]}) + "\n")
                    tx, ty = t % 18, t // 18
                    wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
                    sx, sy = screen_tile(tx, ty)
                    px = (round(_X0 + _XS * sx), round(_Y0 + _YS * sy))
                    tapper.tap_pair(CARD_CENTRES[slot], px)
                    plays += 1
                    pending.append((slot, card, p["hand_costs"][slot], now))
                    awaiting.append((now, card, time.monotonic(), (wx * sub, wy * sub), team))
                    mem["seen"][team].add(card + 2)
                    rec = {"t": now, "card": cat[card][0], "slot": slot, "tile": [sx, sy],
                           "model_tile": [tx, ty], "px": px, "elixir": p["elixir_milli"],
                           "p_wait": dec["p_wait"], "hand": [cat[c][0] for c in p["hand"]],
                           "ms": round((time.perf_counter() - t_decide) * 1000)}
                    logf.write(json.dumps(rec) + "\n")
                    logf.flush()
                    print(f"t={now:5d} PLAY #{plays} {rec['card']} tile ({sx},{sy}) elixir "
                          f"{p['elixir_milli'] / 1000:.1f}  [{rec['ms']} ms]"
                          + (f"  search: {'CHANGED from model ' + str(sinfo.get('chosen')) if sinfo.get('chosen') != [0, 0] else 'kept model'}"
                             f" (best {sinfo.get('best')} vs model {sinfo.get('base')}, {sinfo.get('ms')} ms)"
                             if sinfo and 'options' in sinfo else ""))
                continue
            agent._team = team
            # Extra 12-tick guard grace is heuristic, unverified live; avoids
            # spending another splash before the first input can land.
            defence = None if args.no_tactical_guards or now-last_defence_t<LEAD+12 else defence_plan(state,team,sub,cat,blocked,spendable)
            view = state if defence else agent.ahead(None, state)
            look = "engine" if view is not state else "none"
            if view is state and state.get("unmodelled_forms"):
                look = "velocity"
                # No engine anticipation for hero/aliased bodies: carry each
                # unit forward LEAD ticks at its own measured velocity, so the
                # wait decision still sees the push that is about to land.
                # Units that stop to attack overshoot; new units are not
                # predicted. The earlier fixed-target walk sent enemies toward
                # their OWN king (team 0 owns low y) and moved buildings.
                import copy as _copy
                view = _copy.deepcopy(state)
                for e in view["entities"]:
                    if args.old_lookahead:
                        # The 2026-10-12 behaviour, kept for comparison: a
                        # fixed 0.6 tile/s walk toward a fixed point. It sends
                        # enemies toward their own king and moves buildings.
                        if e[F["tower_slot"]] < 0 and e[F["hp"]] > 0:
                            step = 0.6 * LEAD / 20 * 1000 * sub
                            kx = 9000 * sub
                            ky = (29000 if e[F["team"]] != team and team == 0 else
                                  3000 if e[F["team"]] != team else 16000) * sub
                            dx, dy = kx - e[F["x"]], ky - e[F["y"]]
                            nn_ = max(1, (dx * dx + dy * dy) ** 0.5)
                            e[F["x"]] = int(e[F["x"]] + dx / nn_ * min(step, abs(dx)))
                            e[F["y"]] = int(e[F["y"]] + dy / nn_ * min(step, abs(dy)))
                        continue
                    if e[F["tower_slot"]] >= 0 or e[F["hp"]] <= 0:
                        continue
                    hist = track.get(e[F["uid"]])
                    if not hist or now - hist[0][0] < 4:
                        continue                # too new to have a velocity
                    t0, x0, y0 = hist[0]
                    k = LEAD / (now - t0)
                    e[F["x"]] = int(e[F["x"]] + (e[F["x"]] - x0) * k)
                    e[F["y"]] = int(e[F["y"]] + (e[F["y"]] - y0) * k)
            row = RR.obs_row(view, team, sub, mem, now + agent.lead, live=agent.live)
            if audit:
                audit.model(row, agent.live, now)
            b = agent.batch(row)
            with torch.no_grad():
                gate, _, _ = agent.model(b, card_ids=b["hand"][:, 0].clamp(min=0))
            g = gate[0].float().numpy()
            g[0] += agent.wait_bias
            for slot in range(4):
                if (slot >= len(p["hand"]) or slot in blocked
                        or spendable < p["hand_costs"][slot] * 1000):
                    g[1 + slot] = -1e9
            if now - last_trace >= TRACE_TICKS:
                # Cheap decision trace, also on the frames where we wait: what
                # the bot saw and why it did not play. One line per 0.5 s.
                last_trace = now
                gl = g - g.max()
                pw = float(np.exp(gl[0]) / np.exp(gl).sum()) if g[1:].max() > -1e8 else 1.0
                foes = [e for e in state["entities"] if e[F["team"]] != team
                        and e[F["tower_slot"]] < 0 and e[F["hp"]] > 0]
                near = sum(1 for e in foes if RR.own(e[F["x"]], e[F["y"]], team, sub)[1] > 16000)
                logf.write(json.dumps({"trace": now, "elixir": p["elixir_milli"], "spendable": spendable,
                                       "p_wait": round(pw, 3), "blocked": sorted(blocked),
                                       "hand": [cat[c][0] for c in p["hand"]], "look": look,
                                       "forms": sorted(set(state.get("unmodelled_forms") or []))[:6],
                                       "foes": len(foes), "foes_our_half": near,
                                       "unknown": len(state.get("unknown_units") or [])}) + "\n")
            if g[1:].max() < -1e8:
                if not args.no_bm:
                    proposal = bm.proposal()
                    if proposal and tapper.offer(*proposal):
                        bm.accepted()
                continue
            pr = np.exp(g - g.max())
            pr /= pr.sum()
            capped = not args.no_cap_rule and spendable >= CAP_ELIXIR
            # Same wait rate per second as the 0.5 s evaluator cadence, at any cadence.
            if not defence and not capped and agent.rng.random() < float(pr[0]) ** (dt / 20):
                if not args.no_bm:
                    proposal = bm.proposal()
                    if proposal and tapper.offer(*proposal):
                        bm.accepted()
                continue
            slot = defence['slot'] if defence else int(np.argmax(g[1:]))
            with torch.no_grad():
                _, tile, _ = agent.model(b, card_ids=b["hand"][:, slot])
            order = np.argsort(-tile[0].float().numpy())
            check = agent.rebuilt(state, team, royalesim)
            if check is None:
                why = getattr(agent, "rebuild_error", "?")
                if why != last_rebuild_error:
                    print(f"t={now} rebuild failed ({why}); deciding without lookahead")
                    last_rebuild_error = why
                # Do not freeze: pick the model's best tile and let the game's
                # own legality at tap time decide. A skipped decision in a
                # live push costs more than an occasional bad tile.
                target = None
                for t in order:
                    tx, ty = int(t % 18), int(t // 18)
                    wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
                    if check is None:
                        # No engine legality: troops go only on our own half
                        # (own frame: row 31 is our back line, 17-31 ours);
                        # spells are legal anywhere. Pockets are not offered.
                        if cat[p["hand"][slot]][8] != "SPELL" and ty < 17:
                            continue
                        target = (tx, ty, wx, wy)
                        break
                    if check.check_deploy(team, slot, wx * sub, wy * sub) == 0:
                        target = (tx, ty, wx, wy)
                        break
                if target is None:
                    continue
                tx, ty, wx, wy = target
                card = p["hand"][slot]
                sx, sy = screen_tile(tx, ty)
                px = (round(_X0 + _XS * sx), round(_Y0 + _YS * sy))
                tapper.tap_pair(CARD_CENTRES[slot], px)
                if defence:
                    last_defence_t = now
                plays += 1
                agent.sent.append((now + LEAD, card, wx * sub, wy * sub))
                pending.append((slot, card, p["hand_costs"][slot], now))
                awaiting.append((now, card, time.monotonic(), (wx * sub, wy * sub), team))
                rec = {"t": now, "card": cat[card][0], "slot": slot, "tile": [sx, sy],
                       "model_tile": [tx, ty], "px": px, "elixir": p["elixir_milli"],
                       "p_wait": float(pr[0]), "capped": capped,
                       "hand": [cat[c][0] for c in p["hand"]],
                       "ms": round((time.perf_counter() - t_decide) * 1000),
                       "fallback": "no-rebuild"}
                logf.write(json.dumps(rec) + "\n")
                logf.flush()
                print(f"t={now:5d} PLAY #{plays} {rec['card']} tile ({sx},{sy}) elixir "
                      f"{p['elixir_milli'] / 1000:.1f} (fallback)  [{rec['ms']} ms]")
                continue
            last_rebuild_error = None
            tactic = defence['reason'] if defence else None
            if defence:
                order = defence_order(defence,order)
            elif args.hog_guard and cat[p['hand'][slot]][0]=='HogRider':
                order,tactic = hog_order(order,state,team,sub,slot,check)
            target = None
            lane = (threat_lane(state, team, sub, RR.own)
                    if cat[p["hand"][slot]][0] in GUARD_CARDS and not args.no_lane_guard else None)
            for t in order:
                tx, ty = int(t % 18), int(t // 18)
                if (lane is not None and not GUARD_CENTRE[0] <= tx <= GUARD_CENTRE[1]
                        and (0 if tx < 9 else 1) != lane):
                    continue
                wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
                if check.check_deploy(team, slot, wx * sub, wy * sub) == 0:
                    target = (tx, ty, wx, wy)
                    break
            if target is None:
                continue
            tx, ty, wx, wy = target
            card = p["hand"][slot]
            sx, sy = screen_tile(tx, ty)
            px = (round(_X0 + _XS * sx), round(_Y0 + _YS * sy))
            tapper.tap_pair(CARD_CENTRES[slot], px)
            if defence:
                last_defence_t = now
            plays += 1
            agent.sent.append((now + LEAD, card, wx * sub, wy * sub))
            pending.append((slot, card, p["hand_costs"][slot], now))
            awaiting.append((now, card, time.monotonic(), (wx * sub, wy * sub), team))
            rec = {"t": now, "card": cat[card][0], "slot": slot, "tile": [sx, sy],
                   "model_tile": [tx, ty], "px": px, "elixir": p["elixir_milli"],
                   "p_wait": float(pr[0]), "capped": capped,
                   "hand": [cat[c][0] for c in p["hand"]],
                   "ms": round((time.perf_counter() - t_decide) * 1000)}
            if tactic:
                rec['tactic']=tactic
            if defence:
                rec['visible_cluster_count']=defence['count']
            logf.write(json.dumps(rec) + "\n")
            logf.flush()
            print(f"t={now:5d} PLAY #{plays} {rec['card']} tile ({sx},{sy}) elixir "
                  f"{p['elixir_milli'] / 1000:.1f}{' (cap rule)' if capped else ''}  [{rec['ms']} ms]")
    except KeyboardInterrupt:
        print("Ctrl+C, stopping.")
    finally:
        proc.terminate()
        tapper.close()
        logf.close()
        stop_personality(personality)
        unknown_capture.close()
    print(f"record: {record}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
