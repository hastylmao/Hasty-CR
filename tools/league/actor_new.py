"""League actor: many RoyaleSim matches in lockstep, decisions batched on the GPU.

Each match: two seats, each driven by the learner's current weights or a
frozen snapshot from the pool. Seats on current weights are recorded (both,
when both are); snapshot seats are the opposition. One seat usually plays
the owner's Hog 2.6 with its real forms, the other a ladder deck with its
real forms (tools/league/meta_decks.py).

Live parity: 26-tick command delay on both seats, a decision every 5 ticks,
no lookahead, the observation of tools/league/obs.py, the opponent's plays
revealed to a seat only when they execute.

Run by tools/league/learner.py; nothing here touches the emulator.
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

DELAY = 26
DECIDE = 5
LOCKOUT = 90            # engine refuses deploys before this tick
MAX_TICKS = 6400
GAMMA, LAMBDA = 0.997, 0.95
LEAK_PENALTY = 0.003    # per decision sat on 10 elixir with a playable card
TILE_EXPLORE = 0.03     # share of tile probability spread over all legal tiles
# Every crown tower's lost hp counts the same, plus a bonus per tower taken.
# Weighting the king double (the first version) rewarded chipping the king,
# which is the owner's complaint about the live bot: after one princess falls
# it keeps hitting the king instead of taking the second princess.
# 2026-10-14 evening: equal weights still let king chip pay as much as
# princess damage; live, a Hog sent at the king after the first princess fell
# lost a game the second princess would have won. King hp only matters if the
# king dies (the crown bonus pays for that), so it now counts a quarter, and
# taking a tower pays double what it did.
TOWER_W = (0.25, 1.0, 1.0)  # king, princesses
CROWN_BONUS = 0.5
FULL_HP = (7728, 4858, 4858)  # level 16 king, princess (engine, measured 2026-10-13)
# Unanswered threats (ClashAI's habit term, adapted 2026-11-07). Live the bot
# sometimes sat still while cheap troops walked into a tower: tower damage from
# a few Skeletons barely moves the win/loss, so nothing taught it to answer.
# A threat = enemy troops on our half whose distinct cards cost >= --idle-threat
# elixir in total; left unanswered THREAT_TICKS while a card was affordable, the
# seat loses --idle-w once per threat, at most IDLE_CAP per match.
THREAT_TICKS = 80       # 4 s
IDLE_CAP = 0.3

TAGS = ("hog", "gen", "gen2")   # learning brains; gen2 only where the run has it
GENS = ("gen", "gen2")
SNIPERS = ("Princess", "BlowdartGoblin", "Firecracker", "Archer", "Musketeer", "EliteArcher")
HOG = ["Cannon", "Musketeer", "IceGolemite", "HogRider", "Skeletons", "IceSpirits", "Log", "Fireball"]
# The owner's deck: Evo Cannon, Hero Ice Golem, and Musketeer as hero or evo
# (both are owned; the engine takes one form per card, so matches alternate).
HOG_FORMS_HERO = [1, 2, 2, 0, 0, 0, 0, 0]
HOG_FORMS_EVO = [1, 1, 2, 0, 0, 0, 0, 0]


def tower_damage(player):
    lost = sum(w * (m - max(0, h)) / max(1, m)
               for w, h, m in zip(TOWER_W, player["tower_hp"], player["tower_max_hp"]))
    return lost / sum(TOWER_W)


class Match:
    def __init__(self, env, cfg, rng):
        self.b = env
        self.cfg = cfg
        self.rng = rng
        self.tracker = OBS.Tracker()
        self.mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}}
        self.reveal = []                       # (tick, team, card+2)
        self.recs = {0: [], 1: []}
        self.dmg = {0: 0.0, 1: 0.0}
        self.done = False
        # threat state per seat: [since tick or None, answered, charged, total charged]
        self.thr = {0: [None, False, False, 0.0], 1: [None, False, False, 0.0]}
        self.blind = {0: (-1, False), 1: (-1, False)}   # observer -> (enemy card hidden, all bodies?)
        self.style = None                               # (seat, aggression, cheap bias, lane bias)


def _hidden(m, team, e, drop):
    """Reader noise (2026-11-07): is this enemy body invisible to `team`?

    Live, the memory bridge dropped the bodies of evolved and hero forms it
    could not name - every Evolved Witch skeleton (4.5% of enemy body-frames
    in the recorded games) and, earlier, the Mini Pekka hero - so the model met
    swarms and troops it could not see. Those names are mapped now, but each
    game update adds forms. Training with some bodies missing teaches the
    model to act on what it can see (tower damage, its own units fighting)
    instead of freezing. Per match one enemy card may be "unknown": its
    spawned bodies hidden, or all of its bodies; plus a small share of single
    bodies hidden for their whole life.
    """
    if e[F_TEAM] == team or e[F_SLOT] >= 0:
        return False
    card, every = m.blind[team]
    if card >= 0 and e[F_CARD] == card and (every or e[F_UT] != PRIMARY.get(card, -2)):
        return True
    return drop > 0 and (hash((e[F_UID], team)) % 10_000) < drop * 10_000


def _load_policy(path, dev):
    import torch
    from league.model import LeaguePolicy
    blob = torch.load(path, map_location="cpu", weights_only=False)
    m = blob["meta"]
    net = LeaguePolicy(m["n_cards"], m["n_units"], d=m["d"], layers=m["layers"], heads=m["heads"], obs_v=m.get("obs_v", 1))
    net.load_state_dict(blob["model"])
    return net.to(dev).eval(), blob.get("version", 0)


def run(args):
    global OBS
    import torch
    from league import obs as OBS_
    from league.model import gate_logq
    import rs_rows as RR
    OBS = OBS_
    global F_TEAM, F_SLOT, F_CARD, F_UT, F_UID, PRIMARY
    torch.set_num_threads(1)
    dev = "cuda"
    royalesim, names, ids, cat = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    learn = set(args.learn.split(","))
    F = OBS.setup(royalesim)
    Fi = {k: i for i, k in enumerate(royalesim.ENTITY_FIELDS)}
    F_TEAM, F_SLOT, F_CARD, F_UT, F_UID = Fi["team"], Fi["tower_slot"], Fi["card_id"], Fi["unit_type"], Fi["uid"]
    F_HP, F_Y, F_KIND = Fi["hp"], Fi["y"], Fi["kind"]
    from rs_eval import _spawn_tables
    PRIMARY = _spawn_tables()[0]
    COST = {i: row[2] for i, row in enumerate(cat)}
    run_dir = Path(args.run)
    vocab = json.loads((run_dir / "vocab.json").read_text())
    unit_tok = np.asarray([vocab["units"].get(n, 0) for n in vocab["engine_units"]], np.int64)
    meta = json.loads((ROOT / "data" / "league" / "meta_decks.json").read_text())
    top, tail = meta[:300], meta[300:5000]
    top_w = np.asarray([d["seen"] for d in top], np.float64)
    top_w /= top_w.sum()
    # Air decks (Lava Hound / Balloon / minion swarms) are ~3% of ladder play,
    # and live the bot misplayed a Lava push (2026-10-14). Oversampled.
    AIR = {"LavaHound", "Balloon", "MinionHorde", "Minions", "MegaMinion", "InfernoDragon"}
    air = [d for d in meta[:5000] if len(AIR & set(d["cards"])) >= 2 or "LavaHound" in d["cards"]]
    rng = np.random.default_rng(args.seed)
    prand = random.Random(args.seed)

    # Two learning brains: "hog" plays the owner's Hog 2.6, "gen" (from the
    # replay-imitation general model) pilots the ladder decks. Both learn;
    # past snapshots of each are a minority of opponents, so neither forgets.
    nets, vers, paths, mtimes = {}, {}, {}, {}
    if args.eval:
        paths["hog"] = Path(args.ckpt)
    else:
        for tag in TAGS:
            if (run_dir / tag / "latest.pt").exists():
                paths[tag] = run_dir / tag / "latest.pt"
    for tag, pth in paths.items():
        nets[tag], vers[tag] = _load_policy(pth, dev)
        mtimes[tag] = pth.stat().st_mtime
    pool_models, pools, pool_checked = {}, {t: [] for t in TAGS}, 0.0
    if args.eval:
        pool_models[Path(args.eval)] = _load_policy(Path(args.eval), dev)[0]
        pools["gen"] = [Path(args.eval)]

    # Fixed opponent shares for the focus seat (--opp-shares "il,gen,snap", 2026-11-11):
    # the all-decks imitation model, the best general model (both frozen, on ladder
    # decks) and past focus snapshots (mirror match, PFSP-weighted). Off when empty.
    opp_shares = [float(x) for x in args.opp_shares.split(",")] if args.opp_shares else None
    fixed = {}
    if opp_shares and not args.eval:
        assert len(opp_shares) == 3 and args.opp_il and args.opp_gen, "--opp-shares needs --opp-il and --opp-gen"
        fixed = {"il": Path(args.opp_il), "gen": Path(args.opp_gen)}
        for pth in fixed.values():
            pool_models[pth] = _load_policy(pth, dev)[0]

    def refresh_pool():
        keep_all = list(fixed.values())
        for tag in TAGS:
            got = sorted((run_dir / tag / "pool").glob("*.pt"))
            if not got:
                continue
            # The parent, plus up to 2 others (recent-weighted).
            keep, rest = [got[0]], got[1:]
            if rest:
                w = np.arange(1, len(rest) + 1, dtype=np.float64)
                pick = rng.choice(len(rest), size=min(2, len(rest)), replace=False, p=w / w.sum())
                keep += [rest[i] for i in sorted(pick)]
            pools[tag] = keep
            keep_all += keep
        in_use = set()
        try:
            in_use = {pol for m in matches for pol in m.cfg["pols"] if isinstance(pol, Path)}
        except NameError:
            pass                          # first call, before any match exists
        for p in list(pool_models):
            if p not in keep_all and p not in in_use:
                del pool_models[p]
        for p in keep_all:
            if p not in pool_models:
                pool_models[p], _ = _load_policy(p, dev)

    if not args.eval:
        refresh_pool()

    def opponent_gen():
        """A general (meta-deck) opponent: one of the learning general brains,
        or a frozen snapshot of one."""
        live = [g for g in GENS if g in nets]
        tag = live[rng.integers(len(live))]
        if pools.get(tag) and rng.random() < args.snapshot_share:
            return pools[tag][int(rng.choice(len(pools[tag]), p=pfsp_weights(pools[tag])))]
        return tag

    # Prioritised fictitious self-play (AlphaStar; royalegym.selfplay "hard"):
    # frozen opponents the focus brain still loses to come up more often.
    # p = P(focus beats it) with a Beta(1, 1) prior, weight (1 - p) ** 2.
    snap_wl = {}                          # snapshot path -> [focus wins, games]

    def pfsp_weights(paths):
        w = []
        for pth in paths:
            wins, games = snap_wl.get(pth, (0, 0))
            p = (wins + 1) / (games + 2)
            w.append((1 - p) ** 2 + 1e-3)
        w = np.asarray(w)
        return w / w.sum()

    # A run's focus deck (the "hog" brain's deck): runs/league/<name>/focus_deck.json
    # = {"cards": [8 names], "forms": [[8 forms], ...]}, one form list drawn per
    # match. Absent: the owner's Hog 2.6.
    fp = Path(args.run) / "focus_deck.json"
    focus = json.loads(fp.read_text()) if fp.exists() else None
    # Optional per-card "levels" (same order as "cards") and "tower_level": the
    # owner's real levels. Absent: --hog-level for every card, tower 16.
    focus_levels = (focus or {}).get("levels") or [args.hog_level] * 8
    focus_tower = int((focus or {}).get("tower_level", 16))

    # Opponent decks (--deck-shares "common,worst,pool", 2026-11-11): the most common
    # ladder decks, the decks the focus brain scores worst against (per-deck results of
    # every actor, kept in <run>/deck_wl/), and the general pool. Off when empty.
    deck_shares = [float(x) for x in args.deck_shares.split(",")] if args.deck_shares else None
    common = top[:args.common_decks]
    common_w = np.asarray([d["seen"] for d in common], np.float64)
    common_w /= common_w.sum()
    wl_dir = run_dir / "deck_wl"
    wl_own, wl_other = {}, {}             # index in `top` -> [focus wins, games]
    if deck_shares and not args.eval:
        wl_dir.mkdir(exist_ok=True)
        try:
            wl_own = {int(k): v for k, v in json.loads((wl_dir / f"a{args.actor}.json").read_text()).items()}
        except (OSError, ValueError):
            pass

    def read_other_wl():
        wl_other.clear()
        for f in wl_dir.glob("a*.json"):
            if f.name == f"a{args.actor}.json":
                continue
            try:
                for k, (w_, g_) in json.loads(f.read_text()).items():
                    rec = wl_other.setdefault(int(k), [0, 0])
                    rec[0] += w_
                    rec[1] += g_
            except (OSError, ValueError):
                pass

    def worst_weights():
        """(1 - p) ** 2 with p = the focus brain's win rate against the deck, Beta(1, 1) prior."""
        w = np.empty(len(top))
        for i in range(len(top)):
            a_, b_ = wl_own.get(i, (0, 0)), wl_other.get(i, (0, 0))
            w[i] = (1 - (a_[0] + b_[0] + 1) / (a_[1] + b_[1] + 2)) ** 2 + 1e-3
        return w / w.sum()

    def draw_deck():
        """(deck, index in `top` or -1)."""
        if deck_shares and not args.eval:
            u = rng.random()
            if u < deck_shares[0]:
                i = int(rng.choice(len(common), p=common_w))
                return top[i], i
            if u < deck_shares[0] + deck_shares[1]:
                i = int(rng.choice(len(top), p=worst_weights()))
                return top[i], i
        u = rng.random()
        if air and u < args.air_share:
            return air[rng.integers(len(air))], -1
        if u < 0.7:
            i = int(rng.choice(len(top), p=top_w))
            return top[i], i
        return tail[rng.integers(len(tail))], -1

    def new_match(env):
        hog_seat = int(rng.integers(2)) if rng.random() < args.hog_share else -1
        decks, forms = [], []
        opp_kind, deck_idx = None, -1
        if opp_shares and hog_seat >= 0 and not args.eval:
            u = rng.random()
            opp_kind = "il" if u < opp_shares[0] else "gen" if u < opp_shares[0] + opp_shares[1] else "snap"
            if opp_kind == "snap" and not pools.get("hog"):
                opp_kind = "il"
        mirror = hog_seat >= 0 and (opp_kind == "snap" or bool(args.eval and args.eval_mirror))
        focus_seats = ({hog_seat, 1 - hog_seat} if mirror else {hog_seat}) if hog_seat >= 0 else set()
        for seat in (0, 1):
            if seat in focus_seats:
                if focus:
                    decks.append(focus["cards"])
                    fs = focus["forms"]
                    forms.append([0] * 8 if args.hog_base else fs[rng.integers(len(fs))])
                else:
                    decks.append(HOG)
                    forms.append([0] * 8 if args.hog_base else
                                 HOG_FORMS_HERO if rng.random() < 0.75 else HOG_FORMS_EVO)
            else:
                d, deck_idx = draw_deck()
                decks.append(d["cards"])
                forms.append(d["forms"])
        if args.eval:
            pols = [pools["gen"][0], pools["gen"][0]]
            pols[hog_seat if hog_seat >= 0 else 0] = "hog"
        elif hog_seat >= 0:
            pols = [None, None]
            pols[hog_seat] = "hog"
            if opp_kind == "snap":
                pols[1 - hog_seat] = pools["hog"][int(rng.choice(len(pools["hog"]), p=pfsp_weights(pools["hog"])))]
            elif opp_kind:
                pols[1 - hog_seat] = fixed[opp_kind]
            else:
                pols[1 - hog_seat] = opponent_gen()
        else:
            live = [g for g in GENS if g in nets]
            pols = [live[rng.integers(len(live))], opponent_gen()]
            if rng.random() < 0.5:
                pols.reverse()
        # Advanced starts. Top-ladder replays almost never get past one
        # fallen tower, so imitation never learned the pocket or turning to
        # the second princess. A share of games starts with towers already
        # down (enemy's, ours, or both), mid-match, with random elixir.
        start, elixir, hp, spawns = 0, [5000, 5000], None, []
        hand_first = []
        if hog_seat >= 0 and not args.eval and rng.random() < args.threat_start:
            # Defence starts: 1-3 troops from the opponent's deck already
            # crossing the bridge at one of our towers. Live, the bot lost
            # Training Camp games to a Balloon it barely reacted to, and the
            # same model in RoyaleSim, given that exact Balloon, mostly waited
            # (2026-10-14). Defence was rare and late in ordinary starts.
            opp = 1 - hog_seat
            troops = [c for c in decks[opp] if cat[ids[c]][8] not in ("SPELL", "BUILDING")]
            # Kite starts (owner 2026-10-20): live the Ice Golem went to the attacker's side
            # of centre about half the time; in the real engine the opposite side drags a
            # ground troop across to the other lane (both princesses hit it). A share of
            # defence starts uses ground attackers and puts the Ice Golem in hand.
            if (args.real and "IceGolemite" in decks[hog_seat] and rng.random() < args.kite_share):
                ground = [c for c in troops if not cat[ids[c]][5]]
                if ground:
                    troops = ground
                    hand_first.append((hog_seat, ids["IceGolemite"]))
            if troops:
                x = 3500 if rng.random() < 0.5 else 14500
                y = 16500 if hog_seat == 0 else 15500        # just over the river, toward us
                for c in rng.choice(troops, size=int(rng.integers(1, 4)), replace=True):
                    spawns.append((opp, ids[c], int(x + rng.integers(-800, 801)) * sub,
                                   int(y + rng.integers(-500, 501)) * sub, -1))
                # Snipers: live (2026-10-14) a Princess at the enemy bridge
                # took half a tower while the bot held Log at 9 elixir. A share
                # of defence starts adds a long-range troop on THEIR side of
                # the bridge, out of reach of everything but spells and range.
                if rng.random() < args.sniper_share:
                    snipers = [c for c in SNIPERS if c in ids]
                    c = snipers[rng.integers(len(snipers))]
                    sy = 18500 if hog_seat == 0 else 13500
                    spawns.append((opp, ids[c], int(x + rng.integers(-500, 501)) * sub,
                                   int(sy + rng.integers(-500, 501)) * sub, -1))
                start = int(rng.integers(300, 3300))
                elixir = [int(rng.integers(3000, 10001)), int(rng.integers(3000, 10001))]
        if args.eval_tower:
            focal = hog_seat if hog_seat >= 0 else 0
            hp = [list(FULL_HP), list(FULL_HP)]
            hp[1 - focal][1 + int(rng.integers(2))] = 0
            start = int(rng.integers(600, 3300))
            elixir = [int(rng.integers(2000, 10001)), int(rng.integers(2000, 10001))]
        elif not args.eval and rng.random() < args.tower_start:
            # Every phase x tower combination the owner listed: 1x, 2x (last
            # minute) and overtime clocks; 0-2 princesses down on each side.
            focal = hog_seat if hog_seat >= 0 else int(rng.integers(2))
            phase = rng.choice(3, p=[0.3, 0.4, 0.3])
            if phase == 2:
                # Overtime ends at once on unequal crowns: equal counts only.
                n_e = n_f = int(rng.choice(3, p=[0.2, 0.5, 0.3]))
                start = int(rng.integers(3700, 5200))
            else:
                n_e = int(rng.choice(3, p=[0.25, 0.5, 0.25]))      # enemy towers down
                n_f = int(rng.choice(3, p=[0.55, 0.35, 0.10]))     # ours down
                start = int(rng.integers(600, 2400) if phase == 0 else rng.integers(2400, 3500))
            hp = [list(FULL_HP), list(FULL_HP)]
            for t, n in ((1 - focal, n_e), (focal, n_f)):
                for k in rng.permutation([1, 2])[:n]:
                    hp[t][int(k)] = 0
            for t in (0, 1):
                for k in range(3):
                    if hp[t][k] and rng.random() < 0.5:
                        hp[t][k] = int(hp[t][k] * rng.uniform(0.3, 1.0))
            # Finishing starts: live (2026-10-14) the bot spent every Fireball
            # on troops and never spell-cycled a low tower it could see. Some
            # tower starts leave an enemy princess within one or two spells.
            if rng.random() < args.finish_share:
                alive = [k for k in (1, 2) if hp[1 - focal][k]]
                if alive:
                    k = alive[rng.integers(len(alive))]
                    hp[1 - focal][k] = int(rng.integers(150, 1200))
            elixir = [int(rng.integers(2000, 10001)), int(rng.integers(2000, 10001))]
        env.set_command_delay_ticks(DELAY, DELAY)
        env.reset(seed=int(rng.integers(2**31)), decks=[[ids[c] for c in d] for d in decks],
                  shuffle=1, start_tick=start, elixir_milli=elixir, tower_hp=hp, spawns=spawns,
                  forms=forms, levels=[list(focus_levels) if seat in focus_seats else [16] * 8 for seat in (0, 1)],
                  tower_levels=[focus_tower if seat in focus_seats else 16 for seat in (0, 1)], **({"hand_first": hand_first} if args.real else {}))
        m = Match(env, dict(decks=decks, forms=forms, pols=pols, hog_seat=hog_seat,
                            opp_kind=opp_kind, deck_idx=deck_idx), rng)
        m.mem["t0"] = start          # the opponent-elixir count starts here, at 5
        if not args.eval:
            for team in (0, 1):
                if rng.random() < args.blind_share:
                    units = [c for c in decks[1 - team] if cat[ids[c]][8] != "SPELL"]
                    if units:
                        m.blind[team] = (ids[units[rng.integers(len(units))]], bool(rng.random() < 0.3))
            # Opponent styles: the Hog brain's opponent plays more or less
            # aggressively, prefers one lane, or spams cheap cards (the owner's
            # "eyes closed, spam 1-2 elixir swarms" test). A styled seat's own
            # rows are not recorded: its actions are not its policy's.
            if hog_seat >= 0 and rng.random() < args.style_share:
                spam = rng.random() < 0.4
                m.style = (1 - hog_seat,
                           float(rng.uniform(0.5, 2.0) if spam else rng.uniform(-1.0, 1.5)),
                           float(rng.uniform(1.0, 3.0) if spam else 0.0),
                           float(rng.uniform(-1.5, 1.5)))
        return m

    if args.real:
        # The real game engine (vendor/re/headless) through RoyaleSim's API;
        # one loader process per env. See realsim.py for its known gaps.
        import realsim
        envs = [realsim.RealBattle() for _ in range(args.envs)]
    else:
        envs = [royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]]) for _ in range(args.envs)]
    for e in envs:
        e.set_command_delay_ticks(DELAY, DELAY)
    matches = [new_match(e) for e in envs]
    out_dir = run_dir / "rollouts"
    out_dir.mkdir(parents=True, exist_ok=True)
    bufs, seq = {t: [] for t in TAGS}, 0
    stats = dict(matches=0, hog_wins=0, hog_games=0, ticks=0, t0=time.time())
    tile_world = np.zeros((576, 2), np.int64)
    for t in range(576):
        tile_world[t] = (t % 18) * 1000 + 500, (t // 18) * 1000 + 500
    LEFT = np.where(np.arange(576) % 18 < 9, 1.0, -1.0)

    def to_world(ox, oy, team):
        return (ox, 32_000 - oy) if team == 0 else (18_000 - ox, oy)

    def legal_tiles(m, team, sl):
        tm = np.zeros(576, bool)
        for t in range(576):
            wx, wy = to_world(int(tile_world[t, 0]), int(tile_world[t, 1]), team)
            tm[t] = m.b.check_deploy(team, sl, wx * sub, wy * sub) == 0
        return tm

    def emit_play(i, m, team, sl, tile):
        wx, wy = to_world(int(tile_world[tile, 0]), int(tile_world[tile, 1]), team)
        cmds[i].append((team, sl, wx * sub, wy * sub))
        c = states[i]["players"][team]["hand"][sl]
        if args.eval and key == "hog":
            pc = stats.setdefault("play_cnt", {})
            pc[cat[c][0]] = pc.get(cat[c][0], 0) + 1
            # Lane choice once one enemy princess is down (live 2026-11-13:
            # Mortar kept going into the dead lane). Lane = side of x;
            # slot 1 is the princess at x < 9000.
            ehp = states[i]["players"][1 - team]["tower_hp"]
            if (ehp[1] > 0) != (ehp[2] > 0):
                dead = 1 if ehp[1] <= 0 else 2
                lane = "dead" if (1 if wx < 9000 else 2) == dead else "live"
                ln = stats.setdefault("lane_cnt", {})
                kk = f"{cat[c][0]}:{lane}"
                ln[kk] = ln.get(kk, 0) + 1
        m.reveal.append((states[i]["tick"] + DELAY, team, c + 2))
        m.reveal.sort()

    def card_search(net, cls_row, hand_row, m, team, o, msk, ai, tile, tmask, own_score):
        """Card search (2026-11-15, --search-cards K): the placement search only moves the
        tile of the card the policy chose, so it can never teach which card answers a
        push, that a Fireball ends a tower, or that nothing should be played. Here the
        policy's choice (`ai`: 0 wait, 1-4 a hand slot at `tile`) is compared, in forked
        copies of the game, with waiting and with every other playable card at its K
        best tiles. Scores carry --search-elixir, so an answer that holds for less
        elixir wins: that is the over-defending / under-defending trade.
        -> (ai, tile, tmask) to play. Writes one label row when --search-labels is set."""
        import torch
        opts = {}                                           # gate action -> (score, tile, tile mask)
        w = m.b.try_wait(team, args.search_horizon, args.search_material, args.search_elixir, args.search_win)
        if w is not None:
            opts[0] = (w, -1, np.zeros(576, bool))
        if 1 <= ai <= 4:
            if own_score is None:
                wx, wy = to_world(int(tile_world[tile, 0]), int(tile_world[tile, 1]), team)
                own_score = m.b.try_plays(team, ai - 1, [(wx * sub, wy * sub)], args.search_horizon,
                                          args.search_material, args.search_elixir, args.search_win)[0]
            if own_score is not None:
                opts[ai] = (own_score, tile, tmask)
        slots = [s2 for s2 in range(4) if msk[1 + s2] and s2 + 1 != ai]
        if slots:
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                tla = net.tile_logits(cls_row[None].expand(len(slots), -1), hand_row[slots]).float().cpu().numpy()
            for q, s2 in enumerate(slots):
                tm = legal_tiles(m, team, s2)
                if not tm.any():
                    continue
                top = [int(t) for t in np.argsort(-np.where(tm, tla[q], -1e9))[:args.search_cards]]
                cells = []
                for t in top:
                    cx, cy = to_world(int(tile_world[t, 0]), int(tile_world[t, 1]), team)
                    cells.append((cx * sub, cy * sub))
                sc = m.b.try_plays(team, s2, cells, args.search_horizon, args.search_material, args.search_elixir, args.search_win)
                ok = [(v, -n) for n, v in enumerate(sc) if v is not None]
                if ok:
                    opts[s2 + 1] = (max(ok)[0], top[-max(ok)[1]], tm)
        stats["card_searches"] = stats.get("card_searches", 0) + 1
        if ai not in opts or len(opts) < 2:
            return ai, tile, tmask
        best = max(opts, key=lambda k_: opts[k_][0])
        if opts[best][0] <= opts[ai][0] + args.search_margin:
            best = ai
        if best != ai:
            kk = "wait_to_play" if ai == 0 else "play_to_wait" if best == 0 else "other_card"
            stats["card_moved_" + kk] = stats.get("card_moved_" + kk, 0) + 1
        if args.search_labels:
            gs = np.full(5, np.nan, np.float32)
            for k_, (v, _, _) in opts.items():
                gs[k_] = v
            cd = np.full(args.search_k + 1, -1, np.int64)
            cs = np.full(args.search_k + 1, np.nan, np.float32)
            cd[0], cs[0] = opts[best][1], opts[best][0]
            labels.append(dict(obs=o, mask=msk, a=best, tile=opts[best][1], tmask=np.packbits(opts[best][2]),
                               cand=cd, score=cs, policy_tile=opts[best][1], gate_score=gs, policy_a=ai))
            if len(labels) >= 2000:
                write_labels()
        return best, opts[best][1], opts[best][2]

    def finish(m, state):
        w = state["winner"]
        for team in (0, 1):
            recs = m.recs[team]
            tag = m.cfg["pols"][team]
            if not recs:
                continue
            final = 1.0 if w == team else -1.0 if w in (0, 1) else 0.0
            recs[-1]["r"] += final
            # GAE over this seat's decisions; terminal value 0.
            adv, nxt_v, gae = np.zeros(len(recs), np.float32), 0.0, 0.0
            for i in range(len(recs) - 1, -1, -1):
                delta = recs[i]["r"] + GAMMA * nxt_v - recs[i]["v"]
                gae = delta + GAMMA * LAMBDA * gae
                adv[i] = gae
                nxt_v = recs[i]["v"]
            for i, r in enumerate(recs):
                r["adv"] = adv[i]
                r["ret"] = adv[i] + r["v"]
            bufs[tag].extend(recs)
        hs = m.cfg["hog_seat"]
        stats["matches"] += 1
        if args.eval:
            me = hs if hs >= 0 else m.cfg["pols"].index("hog")
            stats.setdefault("res", []).append(1.0 if w == me else 0.0 if w in (0, 1) else 0.5)
            stats.setdefault("crowns", []).append(state["players"][me]["crowns"]
                                                  - state["players"][1 - me]["crowns"])
            stats.setdefault("two_plus", []).append(int(state["players"][me]["crowns"] >= 2))
            return
        if hs >= 0:
            k = "vs_" + (m.cfg["opp_kind"] or ("gen" if m.cfg["pols"][1 - hs] in GENS else "snap"))
            if deck_shares and m.cfg["deck_idx"] >= 0:
                rec = wl_own.setdefault(m.cfg["deck_idx"], [0, 0])
                rec[0] += int(w == hs)
                rec[1] += 1
            if k == "vs_snap":
                rec = snap_wl.setdefault(m.cfg["pols"][1 - hs], [0, 0])
                rec[0] += int(w == hs)
                rec[1] += 1
            stats[k + "_games"] = stats.get(k + "_games", 0) + 1
            stats[k + "_wins"] = stats.get(k + "_wins", 0) + int(w == hs)

    def write(tag, buf):
        arr = {}
        for k in OBS.KEYS:
            arr[k] = np.stack([r["obs"][k] for r in buf])
        for k in ("mask", "a", "tile", "logp", "v", "adv", "ret"):
            arr[k] = np.asarray([r[k] for r in buf])
        arr["tmask"] = np.stack([r["tmask"] for r in buf])
        arr["version"] = np.asarray([r["ver"] for r in buf], np.int32)
        tmp = out_dir / f".a{args.actor}_{tag}_{seq:06d}.npz"
        np.savez(tmp, **arr)
        os.replace(tmp, out_dir / f"a{args.actor}_{tag}_{seq:06d}.npz")

    labels, label_seq = [], [0]

    def write_labels():
        """Search labels as engine_bc rows (rows_*.npz): engine_bc.py --train-only --tile-only reads them."""
        if not labels:
            return
        d = ROOT / args.search_labels
        d.mkdir(parents=True, exist_ok=True)
        arr = {k: np.stack([r["obs"][k] for r in labels]) for k in OBS.KEYS}
        arr["mask"] = np.stack([r["mask"] for r in labels])
        arr["a"] = np.asarray([r["a"] for r in labels], np.int64)
        arr["tile"] = np.asarray([r["tile"] for r in labels], np.int64)
        arr["tmask"] = np.stack([r["tmask"] for r in labels])
        arr["cand"] = np.stack([r["cand"] for r in labels])
        arr["score"] = np.stack([r["score"] for r in labels])
        arr["policy_tile"] = np.asarray([r["policy_tile"] for r in labels], np.int64)
        # Card search (--search-cards): scores of [wait, slot 0..3] (nan = not tried) and
        # what the policy chose; `a` is then the search's choice, not the policy's.
        arr["gate_score"] = np.stack([r["gate_score"] for r in labels])
        arr["policy_a"] = np.asarray([r["policy_a"] for r in labels], np.int64)
        name = f"rows_a{args.actor}_s{args.seed}_{label_seq[0]:05d}.npz"
        np.savez(d / ("." + name), **arr)
        os.replace(d / ("." + name), d / name)
        label_seq[0] += 1
        labels.clear()

    def flush():
        nonlocal seq
        for tag in TAGS:
            if bufs[tag]:
                write(tag, bufs[tag])
                bufs[tag] = []
        if deck_shares and not args.eval:
            tmp = wl_dir / f".a{args.actor}.tmp"
            tmp.write_text(json.dumps(wl_own))
            os.replace(tmp, wl_dir / f"a{args.actor}.json")
        el = time.time() - stats["t0"]
        (out_dir / f"stats_a{args.actor}.json").write_text(json.dumps(
            dict(stats, seconds=el, matches_per_s=stats["matches"] / max(1, el))))
        seq += 1

    while args.eval or not (run_dir / "STOP").exists():   # evals finish regardless
        if args.eval and stats["matches"] >= args.eval_matches:
            res = stats["res"][:args.eval_matches]
            k, n = sum(res), len(res)
            z, ph = 1.96, k / n
            lo = (ph + z * z / (2 * n) - z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / (1 + z * z / n)
            hi = (ph + z * z / (2 * n) + z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))) / (1 + z * z / n)
            write_labels()
            print(json.dumps(dict(candidate=str(args.ckpt), opponent=str(args.eval), matches=n,
                                  win_rate=round(ph, 4), ci95=[round(lo, 3), round(hi, 3)],
                                  crown_diff=round(float(np.mean(stats["crowns"][:n])), 3),
                                  two_crowns_rate=round(float(np.mean(stats["two_plus"][:n])), 3),
                                  plays_per_game=round(sum(stats.get("play_cnt", {}).values()) / max(1, stats["matches"]), 1),
                                  plays=stats.get("play_cnt", {}),
                                  lanes=dict(sorted(stats.get("lane_cnt", {}).items())),
                                  searches=stats.get("searches", 0), search_moved=stats.get("search_moved", 0),
                                  hand_share={k_: round(v_ / max(1, stats.get("dec", 1)), 2)
                                              for k_, v_ in sorted(stats.get("hand_cnt", {}).items(),
                                                                   key=lambda kv: -kv[1])},
                                  tower_start=args.eval_tower,
                                  hog_share=args.hog_share, seconds=round(time.time() - stats["t0"]))))
            return
        # New weights from the learner?
        for tag in (() if args.eval else [t for t in TAGS if t in paths]):
            try:
                mt = paths[tag].stat().st_mtime
            except OSError:
                continue
            if mt != mtimes[tag]:
                try:
                    nets[tag], vers[tag] = _load_policy(paths[tag], dev)
                    mtimes[tag] = mt
                except Exception:
                    pass                  # mid-write; next round
        if time.time() - pool_checked > 300 and not args.eval:
            pool_checked = time.time()
            refresh_pool()
            if deck_shares:
                read_other_wl()

        states, todo = [], []          # todo: (match index, team, policy key, obs, mask, state)
        for i, m in enumerate(matches):
            s = json.loads(m.b.state_json())
            states.append(s)
            if s["game_over"] or s["tick"] >= MAX_TICKS:
                finish(m, s)
                matches[i] = new_match(envs[i])
                states[i] = None
                continue
            tick = s["tick"]
            m.tracker.update(s["entities"], tick, sub)
            while m.reveal and m.reveal[0][0] <= tick:
                _, team, c = m.reveal.pop(0)
                m.mem["seen"][team].add(c)
                m.mem["last"][team].append((c, tick))
            if tick < LOCKOUT:
                continue
            for team in (0, 1):
                p = s["players"][team]
                # Shaping since this seat's previous decision.
                d_opp = tower_damage(s["players"][1 - team])
                d_own = tower_damage(p)
                recs = m.recs[team]
                cr_me, cr_op = p["crowns"], s["players"][1 - team]["crowns"]
                if ("o", team) not in m.dmg:          # first look: baseline, no reward
                    m.dmg[("o", team)], m.dmg[("s", team)] = d_opp, d_own
                    m.dmg[("c", team)] = (cr_me, cr_op)
                shaped = (d_opp - m.dmg[("o", team)]) - (d_own - m.dmg[("s", team)])
                pc_me, pc_op = m.dmg[("c", team)]
                shaped += CROWN_BONUS * ((cr_me - pc_me) - (cr_op - pc_op))
                m.dmg[("o", team)], m.dmg[("s", team)] = d_opp, d_own
                m.dmg[("c", team)] = (cr_me, cr_op)
                if recs:
                    # Shaping sums to (tower damage + crowns) at the end, up to ~2.5 against
                    # the +-1 of the result; royalegym's rule: the terminal term is the
                    # objective, shaping must not outweigh it. --shape-w scales it.
                    recs[-1]["r"] += args.shape_w * shaped
                pend = p.get("pending") or []
                bar = p["elixir_milli"] - 1000 * int(p.get("pending_cost", 0) or 0)
                pend_cards = {row[1] for row in pend if row[0] == 0}
                pend_btn = {row[1] for row in pend if row[0] == 1}
                mask = np.zeros(7, bool)
                mask[0] = True
                for k in range(4):
                    if k < len(p["hand"]) and p["hand"][k] >= 0 and p["hand"][k] not in pend_cards \
                            and bar >= p["hand_costs"][k] * 1000:
                        mask[1 + k] = True
                for k, row in enumerate((p.get("abilities") or [])[:2]):
                    if row[0] and not row[1] and bar >= row[2] * 1000 and (4 + k) not in pend_btn:
                        mask[5 + k] = True
                if recs and p["elixir_milli"] >= 10_000 and mask[1:5].any():
                    recs[-1]["r"] -= LEAK_PENALTY
                if args.idle_w > 0 and recs:
                    cards = set()
                    for e in s["entities"]:
                        if e[F_TEAM] != team and e[F_SLOT] < 0 and e[F_HP] > 0 and e[F_KIND] != 1:
                            oy = (32_000 - e[F_Y] / sub) if team == 0 else e[F_Y] / sub
                            if oy >= 16_000:              # on our half (own frame: our king at the bottom)
                                cards.add(e[F_CARD])
                    th = m.thr[team]
                    if sum(COST.get(c, 0) for c in cards) >= args.idle_threat:
                        if th[0] is None:
                            th[0], th[1], th[2] = tick, False, False
                        elif (not th[1] and not th[2] and tick - th[0] >= THREAT_TICKS
                              and mask[1:5].any() and th[3] < IDLE_CAP):
                            recs[-1]["r"] -= args.idle_w
                            th[2], th[3] = True, th[3] + args.idle_w
                            stats["idle_charges"] = stats.get("idle_charges", 0) + 1
                    else:
                        th[0] = None
                if not args.eval and (m.blind[team][0] >= 0 or args.drop_body > 0):
                    s_obs = dict(s, entities=[e for e in s["entities"]
                                              if not _hidden(m, team, e, args.drop_body)])
                else:
                    s_obs = s
                pk = m.cfg["pols"][team]
                pnet = nets[pk] if pk in nets else pool_models[pk]
                o = OBS.build(s_obs, team, m.mem, tick, m.tracker, unit_tok, sub, obs_v=pnet.obs_v)
                todo.append((i, team, pk, o, mask))
                if args.eval and m.cfg["pols"][team] == "hog":
                    # How the candidate uses its hand (2026-11-12: live, two cards sat in
                    # hand most of each game; the win rate alone did not show it).
                    stats["dec"] = stats.get("dec", 0) + 1
                    hc = stats.setdefault("hand_cnt", {})
                    for c_ in p["hand"][:4]:
                        hc[cat[c_][0]] = hc.get(cat[c_][0], 0) + 1

        cmds = {i: [] for i in range(len(matches))}
        groups = {}
        for item in todo:
            groups.setdefault(item[2], []).append(item)
        for key, items in groups.items():
            if key not in nets and key not in pool_models:
                # A snapshot the pool refresh dropped while a match still uses it.
                pool_models[key], _ = _load_policy(key, dev)
            net = nets[key] if key in nets else pool_models[key]
            b = OBS.trim({k: torch.as_tensor(np.stack([it[3][k] for it in items])).to(dev) for k in OBS.KEYS})
            mask = torch.as_tensor(np.stack([it[4] for it in items])).to(dev)
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                gate, cls, val = net.heads(b)
            g_in = gate.float()
            # Play/wait gate temperature. Live plays near-greedy (0.1, +13 pp over
            # sampling at 1.0); training used to sample at 1.0, so PPO learned from a
            # weaker version of the bot than the one fielded (RoyaleSim's RL2 had the
            # same flaw). Training now samples at --train-gate-temp (the learner
            # scores the same tempered policy); evals put both seats at --gate-temp.
            # With --opp-shares: the imitation opponent decodes at --opp-il-temp (an
            # imitation model never plays near-greedy), past focus snapshots as the
            # focus brain does, the general model at --opp-gate-temp.
            temp = (args.gate_temp if args.eval else
                    args.train_gate_temp if key in learn else
                    args.opp_il_temp if key == fixed.get("il") else
                    args.train_gate_temp if (fixed and key != fixed.get("gen")) else args.opp_gate_temp)
            if temp != 1.0:
                g_in = g_in / temp
            styled = [j for j, it in enumerate(items)
                      if matches[it[0]].style is not None and matches[it[0]].style[0] == it[1]]
            if styled:
                g_in = g_in.clone()
                hand_np = b["hand"].cpu().numpy()
                for j in styled:
                    _, aggr, cheap, _ = matches[items[j][0]].style
                    g_in[j, 0] -= aggr
                    if cheap:
                        for k in range(4):
                            c = int(hand_np[j, k]) - 2
                            if c >= 0 and COST.get(c, 9) <= 2:
                                g_in[j, 1 + k] += cheap
            lq = gate_logq(g_in, mask, DECIDE)
            # Split decoding (eval, the candidate only; --card-temp > 0): play-or-wait
            # sampled at --time-temp, the card / button among the allowed ones at
            # --card-temp, the tile at --tile-temp without the exploration share.
            # daybreak-cr decodes this way (sharp card and tile, sampled timing); the
            # single gate temperature also sharpens the timing, at which an imitation
            # model never plays (version 0 of the Mortar deck: 0% at 0.1, 2026-11-12).
            split = bool(args.eval and key == "hog" and args.card_temp > 0)
            if split:
                g0 = gate.float()
                lw = gate_logq(g0 / args.time_temp, mask, DECIDE)[:, :1]
                l_act = torch.log1p(-lw.exp().clamp(max=1 - 1e-6))
                la = torch.log_softmax((g0[:, 1:] / args.card_temp).masked_fill(~mask[:, 1:], -1e9), 1)
                lq = torch.cat([lw, la + l_act], 1).masked_fill(~mask, -1e9)
            a = torch.distributions.Categorical(logits=lq).sample()
            hand = b["hand"]
            slot = (a - 1).clamp(0, 3)
            card = hand.gather(1, slot[:, None])[:, 0]
            with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
                tl = net.tile_logits(cls, card).float()
            tl = tl.cpu().numpy()
            a = a.cpu().numpy()
            lq = lq.cpu().numpy()
            val = val.float().cpu().numpy()
            for j, (i, team, _, o, msk) in enumerate(items):
                m = matches[i]
                if args.eval and key == "hog" and args.hide_inflight:
                    m.b.hold = {1 - team}        # the opponent's plays in flight stay out of search copies
                ai = int(a[j])
                logp = float(lq[j, ai])
                tile, tmask, own_score = -1, np.zeros(576, bool), None
                if 1 <= ai <= 4:
                    sl = ai - 1
                    for t in range(576):
                        wx, wy = to_world(int(tile_world[t, 0]), int(tile_world[t, 1]), team)
                        tmask[t] = m.b.check_deploy(team, sl, wx * sub, wy * sub) == 0
                    if not tmask.any():
                        ai, logp = 0, float(lq[j, 0])
                    else:
                        lg = tl[j].astype(np.float64)
                        if m.style is not None and m.style[0] == team and m.style[3]:
                            lg = lg + m.style[3] * LEFT        # lane preference, own frame
                        if split or (args.eval and args.eval_tile_temp > 0):
                            # --eval-tile-temp: every seat's tile near-greedy, as the live bot
                            # places (tools/league/live.py takes the argmax tile). Without it
                            # an evaluation samples tiles at temperature 1 plus the training
                            # exploration share: version 0 scored 57.5% that way and 66.5%
                            # with sharp tiles (same 200 seeds, 2026-11-12).
                            lg = np.where(tmask, lg / (args.tile_temp if split else args.eval_tile_temp), -1e9)
                            pr = np.exp(lg - lg.max())
                        else:
                            # --train-tile-temp (training; the learner's --tile-temp must match):
                            # tiles sampled nearer to the best one, as the fielded bot places.
                            lg = np.where(tmask, lg / (1.0 if args.eval else args.train_tile_temp), -1e9)
                            pr = np.exp(lg - lg.max())
                            pr = (1 - TILE_EXPLORE) * pr / pr.sum() + TILE_EXPLORE * tmask / tmask.sum()
                        tile = int(rng.choice(576, p=pr / pr.sum()))
                        logp += math.log(pr[tile])
                        if args.eval and key == "hog" and args.search_k > 0:
                            # Placement search (eval, the candidate only): the policy's tile
                            # and its --search-k best tiles are each tried in a forked copy
                            # of the game (realsim.try_plays); the best score is played.
                            # The copy holds opponent plays still in flight (up to the
                            # command delay), which the policy cannot see: a small leak.
                            cand = [tile] + [int(t) for t in np.argsort(-lg)[:args.search_k] if tmask[t] and t != tile]
                            cells = []
                            for t in cand:
                                cx, cy = to_world(int(tile_world[t, 0]), int(tile_world[t, 1]), team)
                                cells.append((cx * sub, cy * sub))
                            sc = m.b.try_plays(team, sl, cells, args.search_horizon, args.search_material, args.search_elixir, args.search_win)
                            ok = [(v, -n) for n, v in enumerate(sc) if v is not None]
                            stats["searches"] = stats.get("searches", 0) + 1
                            own_score = sc[0]
                            if ok:
                                best = cand[-max(ok)[1]]
                                if args.search_labels and len(ok) > 1:
                                    # one imitation row (engine_bc format) whose tile is the search's
                                    # best; the candidates and scores are kept for soft targets
                                    cd = np.full(args.search_k + 1, -1, np.int64)
                                    cs = np.full(args.search_k + 1, np.nan, np.float32)
                                    cd[:len(cand)] = cand
                                    cs[:len(sc)] = [np.nan if v is None else v for v in sc]
                                    labels.append(dict(obs=o, mask=msk, a=ai, tile=best, tmask=np.packbits(tmask),
                                                       cand=cd, score=cs, policy_tile=cand[0],
                                                       gate_score=np.full(5, np.nan, np.float32), policy_a=ai))
                                    if len(labels) >= 2000:
                                        write_labels()
                                if max(ok)[0] > (sc[0] if sc[0] is not None else -1e9) + args.search_margin:
                                    stats["search_moved"] = stats.get("search_moved", 0) + 1
                                    tile, own_score = best, max(ok)[0]
                        if args.eval and key == "hog" and args.search_cards > 0:
                            ai, tile, tmask = card_search(net, cls[j], hand[j], m, team, o, msk, ai, tile, tmask, own_score)
                            sl = ai - 1
                        if ai != 0:
                            emit_play(i, m, team, sl, tile)
                elif ai >= 5:
                    cmds[i].append((team, 4 + (ai - 5), 0, 0))
                elif (args.eval and key == "hog" and args.search_cards > 0 and args.search_at_wait > 0
                      and bool(np.any(msk[1:5])) and rng.random() < args.search_at_wait):
                    # The policy waits: is a play better? (under-defending is a wait that costs a tower)
                    ai, tile, tmask = card_search(net, cls[j], hand[j], m, team, o, msk, 0, -1, tmask, None)
                    if ai != 0:
                        emit_play(i, m, team, ai - 1, tile)
                if 1 <= ai <= 6:
                    m.thr[team][1] = True            # the current threat was answered
                if key in learn and not args.eval and not (m.style is not None and m.style[0] == team):
                    m.recs[team].append(dict(obs=o, mask=msk, a=ai, tile=tile,
                                             tmask=np.packbits(tmask), logp=logp, v=float(val[j]),
                                             r=0.0, ver=vers[key]))
        for i, m in enumerate(matches):
            if states[i] is None:
                continue
            m.b.step(cmds[i], DECIDE)
            stats["ticks"] += DECIDE
        if sum(len(b) for b in bufs.values()) >= args.flush_rows:
            flush()
    flush()


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--actor", type=int, default=0)
    ap.add_argument("--envs", type=int, default=64)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--hog-share", type=float, default=0.85)
    ap.add_argument("--threat-start", type=float, default=0.2,
                    help="share of Hog games that start with enemy troops crossing the bridge at us")
    ap.add_argument("--finish-share", type=float, default=0.3, help="tower starts with an enemy princess at 150-1200 hp")
    ap.add_argument("--sniper-share", type=float, default=0.4, help="defence starts adding a ranged troop at their bridge")
    ap.add_argument("--air-share", type=float, default=0.15, help="opponent decks drawn from air decks")
    ap.add_argument("--tower-start", type=float, default=0.5,
                    help="share of games that start mid-match with towers already down")
    ap.add_argument("--snapshot-share", type=float, default=0.3,
                    help="share of games against a frozen past snapshot instead of the live brain")
    ap.add_argument("--flush-rows", type=int, default=40_000)
    ap.add_argument("--eval", default="", help="opponent checkpoint: evaluate --ckpt against it")
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--eval-matches", type=int, default=400)
    ap.add_argument("--hog-base", action="store_true", help="Hog cards in base form (a control)")
    ap.add_argument("--gate-temp", type=float, default=0.1, help="eval only: gate temperature of both seats (live: 0.1)")
    ap.add_argument("--eval-tower", action="store_true",
                    help="eval games start with one enemy princess already down")
    ap.add_argument("--real", action="store_true", help="play in the real engine (realsim.RealBattle)")
    # Live (2026-10-17 reader frames) the owner's cards were level 14 against level-16
    # opponents (towers 16 on both sides); training at 16 vs 16 hid that gap.
    # Unverified for the Hog cards: read them from a --record-frames live game.
    ap.add_argument("--kite-share", type=float, default=0.5,
                    help="real engine: share of defence starts that are Ice Golem kite starts")
    ap.add_argument("--shape-w", type=float, default=1.0, help="weight of the tower/crown shaping reward")
    ap.add_argument("--learn", default="hog,gen,gen2",
                    help="brains that learn; the others are frozen opponents (no rows recorded)")
    ap.add_argument("--opp-gate-temp", type=float, default=1.0,
                    help="training: gate temperature of frozen opponents (human-like: 0.1)")
    ap.add_argument("--train-gate-temp", type=float, default=1.0,
                    help="training: play/wait gate temperature (the learner must use the same)")
    ap.add_argument("--hog-level", type=int, default=16, help="card level of the focus (hog) seat")
    ap.add_argument("--blind-share", type=float, default=0.0,
                    help="share of (match, seat) where one enemy card's bodies are unseen (reader noise)")
    ap.add_argument("--drop-body", type=float, default=0.0,
                    help="share of single enemy bodies unseen for their whole life (reader noise)")
    ap.add_argument("--idle-w", type=float, default=0.0, help="penalty per threat left unanswered 4 s")
    ap.add_argument("--idle-threat", type=float, default=3.0,
                    help="elixir of distinct enemy cards on our half that counts as a threat")
    ap.add_argument("--style-share", type=float, default=0.0,
                    help="share of Hog games whose opponent plays a random style (aggression, lane, cheap spam)")
    ap.add_argument("--opp-shares", default="",
                    help="focus seat's opponents: shares of imitation model, general model, past focus "
                         "snapshots (mirror), e.g. 0.4,0.4,0.2; needs --opp-il and --opp-gen")
    ap.add_argument("--opp-il", default="", help="frozen all-decks imitation checkpoint (league format)")
    ap.add_argument("--opp-il-temp", type=float, default=1.0, help="gate temperature of the imitation opponent")
    ap.add_argument("--opp-gen", default="", help="frozen best general checkpoint (league format)")
    ap.add_argument("--deck-shares", default="",
                    help="opponent decks: shares of most common, worst-matchup, general pool, e.g. 0.3,0.3,0.4")
    ap.add_argument("--common-decks", type=int, default=30, help="how many top ladder decks count as 'most common'")
    ap.add_argument("--card-temp", type=float, default=0.0,
                    help="eval: split decoding of the candidate, card temperature (0 = off, one gate temperature)")
    ap.add_argument("--time-temp", type=float, default=1.0, help="eval, split decoding: play-or-wait temperature")
    ap.add_argument("--tile-temp", type=float, default=1.0, help="eval, split decoding: tile temperature")
    ap.add_argument("--train-tile-temp", type=float, default=1.0,
                    help="training: tile temperature (the learner must use the same)")
    ap.add_argument("--search-k", type=int, default=0,
                    help="eval: placement search over the candidate's k best tiles (needs the loader_fork engine build)")
    ap.add_argument("--hide-inflight", action="store_true",
                    help="eval, real engine: the opponent's plays reach the engine at their tick, so a search copy "
                         "does not hold plays the candidate cannot see yet (the 26-tick command delay)")
    ap.add_argument("--search-labels", default="",
                    help="eval with --search-k: folder for the searched plays as imitation rows (the tile = the search's best)")
    ap.add_argument("--search-horizon", type=int, default=160)
    ap.add_argument("--search-material", type=float, default=0.3)
    ap.add_argument("--search-win", type=float, default=0.0,
                    help="search score added for winning (subtracted for losing) when the copy reaches the end of the game")
    ap.add_argument("--search-cards", type=int, default=0,
                    help="card search: also try waiting and every other playable card at its K best tiles (0 = off)")
    ap.add_argument("--search-at-wait", type=float, default=0.0,
                    help="share of the policy's wait decisions (with a playable card) that get a card search")
    ap.add_argument("--search-elixir", type=float, default=0.0,
                    help="search score per elixir of bank difference at the end, in princess towers "
                         "(UNVERIFIED constant; 0 = a card is free in the copy)")
    ap.add_argument("--search-margin", type=float, default=0.0,
                    help="move off the policy's tile only when the best score beats its score by more than this")
    ap.add_argument("--eval-tile-temp", type=float, default=0.0,
                    help="eval: tile temperature of both seats, no exploration share (0 = off; live = argmax)")
    ap.add_argument("--eval-mirror", action="store_true", help="eval: the opponent plays the focus deck too")
    args = ap.parse_args()
    if args.search_k > 0:
        os.environ["LOADER"] = "loader_fork"      # the engine build with "try" (vendor/re/headless/loader_fork.c)
    run(args)


if __name__ == "__main__":
    main()
