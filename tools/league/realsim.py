"""RealBattle: a drop-in for royalesim.Battle that runs the real Clash Royale
engine (vendor/re/headless, loader.c SERVE mode) instead of RoyaleSim.

It speaks RoyaleSim's API and state schema closely enough for actor.py and
obs.py: set_command_delay_ticks, reset, step, check_deploy, state_json,
catalogue_json, unit_types_json. Catalogue ids and unit_type indexes are
RoyaleSim's, so a model trained on either sees the same vocabulary.

Known gaps (each one marked where it lives):
  - spell rows take the aim point from the shim's own record of plays;
  - ability rows: availability and cooldown come from the engine's own check;
  - target_uid is the combat component's current target (towers keep one even when idle).
"""
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
HEADLESS = ROOT / "vendor" / "re" / "headless"
sys.path.insert(0, str(HEADLESS))
import engine  # noqa: E402

import royalesim  # noqa: E402

SUB = royalesim.SUBTILE_PER_MILLITILE
REBUILD = os.environ.get("HASTY_SEARCH_REBUILD") == "1"
R = {n: i for i, n in enumerate(royalesim.DEPLOY_REASONS)}
TMP = HEADLESS / "tmp_battles"
SUPPORT = 159000000      # King_PrincessTowers
REGULAR, OVERTIME = 3600, 2400
PENDING_MAX = 40
SPELL_KEEP = 200         # how long a spell play's aim point is kept for its objects

# Hero forms RoyaleSim cannot load (its reset raises "no loadable hero form"), so
# their ability row cannot come from RoyaleSim's template. card -> ability elixir
# cost. IceWizard: ManaCost 2 in characters/hero_form/ice_wizard_hero.toml and 2.0
# elixir measured in the engine (2026-11-11).
# Hero Electro Wizard is absent with the old engine code: on the build 160635007
# tables it loads and deploys, but 24 of 42 pilot games with it ended before 3:00
# (8% for other games), so it does not run faithfully there.
# Its ManaCost is 2 in electro_wizard_hero.toml if the engine is ever ported.
HERO_COST = {"IceWizard": 2}
if os.environ.get("HASTY_HERO_TEST"):          # engine controls only: "Card=cost,Card=cost"
    HERO_COST.update((k, int(v)) for k, v in (kv.split("=") for kv in os.environ["HASTY_HERO_TEST"].split(",")))
# Not on the ported build 160635007 engine either (LOADER=loader_new): there it
# attacks every 10 ticks instead of 36 (tools/league/controls/unit_hits.py
# ElectroWizard 2) - it starts in its ability attack sequence. Cause not found.
# ManaCost is 2 in electro_wizard_hero.toml for when that is fixed.
# Engine unit names RoyaleSim has no unit type for -> the name the model sees
# (the same mapping as scripts/gamestate/live_bridge.py UNIT_ALIASES).
UNIT_ALIASES = {"IceWizardHero": "IceWizard", "IceWizardHero_IceCube": "IceWizard",
                "IceWizardHeroFloatingCube": "IceWizard"}
# Bodies that belong to a hero but cannot take its ability command (abilitycheck 1006).
NOT_ABILITY_UNITS = {"IceWizardHeroFloatingCube", "IceWizardHero_IceCube"}

# HASTY_UNIT_FALLBACK=1: name bodies as the live reader does (unitmap.py). Off by default
# so rows and evaluations already made stay comparable; on for new collections.
UNIT_FALLBACK = os.environ.get("HASTY_UNIT_FALLBACK") == "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unitmap  # noqa: E402

_shared = {}
def parse_buffs(text):
    """'Freeze:3400,Rage:850' -> [['Freeze', 3400], ['Rage', 850]] (engine and live reader format)."""
    out = []
    for part in (text or "").split(","):
        name, _, ms = part.partition(":")
        if name and ms.lstrip("-").isdigit():
            out.append([name, int(ms)])
    return out


_spell_of = {}             # engine object name -> spell catalogue id or None


def _tables():
    """RoyaleSim catalogue / unit types and the engine's card ids, loaded once."""
    if not _shared:
        b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        _shared["cat_json"] = b.catalogue_json()
        _shared["ut_json"] = b.unit_types_json()
        cat = json.loads(_shared["cat_json"])
        _shared["cat"] = cat
        _shared["ut"] = {n: i for i, n in enumerate(json.loads(_shared["ut_json"]))}
        _shared["eids"] = json.load(open(HEADLESS / "engine_cards.json"))
        _shared["buildings"] = {row[0] for row in cat if row[8] == "BUILDING"}
        _shared["spells"] = {row[0].lower(): i for i, row in enumerate(cat) if row[8] == "SPELL"}
    return _shared


class RealBattle:
    def __init__(self, card_names=None, slot_of_k=None):
        t = _tables()
        self.cat, self.ut, self.eids = t["cat"], t["ut"], t["eids"]
        # One forking engine server per process (loader SERVE_PORT): every env is
        # a fork sharing the loaded data, ~3 MB each instead of ~150 MB.
        if "port" not in _shared:
            _shared["port"] = engine.start_server()
        self.eng = engine.RealEngine(_shared["port"])
        self.eng._call("setrow 72 6 0x60 256")      # Ladder row: FixedDeckOrder on
        self.delay = [20, 20]
        self.dropped = 0
        TMP.mkdir(exist_ok=True)
        self.path = TMP / f"rs_{os.getpid()}_{id(self)}.json"
        self.s = None
        self.grids = {}
        self.waiting = 0              # replies not read yet
        # Teams whose card plays reach the engine only in the step that holds their
        # tick, not when they are decided. A forked copy (try_plays) then does not
        # contain that team's plays still in flight, which the other seat cannot see.
        self.hold = set()
        self.held = []

    # -- RoyaleSim API ------------------------------------------------------
    def catalogue_json(self):
        return _shared["cat_json"]

    def unit_types_json(self):
        return _shared["ut_json"]

    def set_command_delay_ticks(self, a, b):
        self.delay = [int(a), int(b)]

    def reset(self, seed=0, decks=None, shuffle=1, start_tick=0, elixir_milli=None, tower_hp=None,
              spawns=None, forms=None, levels=None, tower_levels=None, hand_first=None, **_):
        self._sync()
        self.inflight = []
        rng = np.random.default_rng(seed)
        self.deck = [list(d) for d in decks]
        self.forms = [list(f) for f in (forms or [[0] * 8, [0] * 8])]
        self.levels = [list(lv) for lv in (levels or [[11] * 8, [11] * 8])]
        if shuffle:
            for t in (0, 1):
                p = rng.permutation(8)
                self.deck[t] = [self.deck[t][i] for i in p]
                self.forms[t] = [self.forms[t][i] for i in p]
                self.levels[t] = [self.levels[t][i] for i in p]
        # hand_first: [(team, card)] put into the starting hand (deck slots 0-3 under
        # FixedDeckOrder), e.g. an Ice Golem for a kite start.
        for team, card in hand_first or []:
            if card in self.deck[team]:
                i = self.deck[team].index(card)
                if i >= 4:
                    j = int(rng.integers(4))
                    for arr in (self.deck[team], self.forms[team], self.levels[team]):
                        arr[i], arr[j] = arr[j], arr[i]
        tl = tower_levels or [11, 11]
        j = {"rndSeed": int(seed) % (2 ** 31), "time": 0, "endTick": 9000, "battle": {
            "gamemode": 72000006, "location": 15000006, "arena": 54000001,
            "avatar0": {"accountID.hi": 0, "accountID.lo": 1, "name": "A", "expLevel": 60, "arena": 54000001},
            "avatar1": {"accountID.hi": 0, "accountID.lo": 2, "name": "B", "expLevel": 60, "arena": 54000001},
            "hbd": [{"di": 0, "em": {}, "kt": tl[0]}, {"di": 1, "em": {}, "kt": tl[1]}]}, "cmd": [], "evt": []}
        for t in (0, 1):
            j["battle"][f"deck{t}"] = {
                "sp": [dict({"d": self._eid(c), "l": lv - 1}, **({"el": f} if f else {}))
                       for c, f, lv in zip(self.deck[t], self.forms[t], self.levels[t])],
                "sc": [{"d": SUPPORT, "l": tl[t] - 1}]}
        self.path.write_text(json.dumps(j))
        self.eng.new_battle(str(self.path.relative_to(HEADLESS)).replace("\\", "/"))
        self.pending = [[], []]       # (exec tick, deck slot, cost)
        self.held = []                # (exec tick, command line) of plays of teams in self.hold
        self.queue = [list(range(4, 8)), list(range(4, 8))]   # deck slots waiting, in deal order
        self.spell_pos = {}           # spell object game id -> last position
        self.casts = []               # (exec tick, team, card, x, y) of spell plays, for "spells"
        # Ability buttons: RoyaleSim's rows for this deck ([available, spent, cost,
        # card, cooldown]) as the template; availability comes from engine units.
        rs = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        extra = [[], []]
        # Forms RoyaleSim cannot load (its reset raises ValueError naming the card):
        # the template is built without that form. A hero's ability row is added
        # from HERO_COST; an evolution has no button. The engine itself runs the form.
        tf = [list(f) for f in self.forms]
        for _ in range(17):
            try:
                rs.reset(seed=0, decks=self.deck, shuffle=0, start_tick=0, elixir_milli=[5000, 5000],
                         tower_hp=None, spawns=[], forms=tf, levels=self.levels, tower_levels=tl)
                break
            except ValueError as e:
                bad = str(e).split(" ")[0]
                hit = [(t, i) for t in (0, 1) for i, c in enumerate(self.deck[t])
                       if tf[t][i] and self.cat[c][0] == bad]
                if not hit or (any(tf[t][i] == 2 for t, i in hit) and bad not in HERO_COST):
                    raise
                for t, i in hit:
                    if tf[t][i] == 2:
                        extra[t].append([0, 0, HERO_COST[bad], self.deck[t][i], 0])
                    tf[t][i] = 0
        self.abil = [[list(r) for r in p["abilities"]] + extra[t]
                     for t, p in enumerate(json.loads(rs.state_json())["players"])]
        self.pressed = [{}, {}]       # unit game id -> tick until which its ability press is pending
        if start_tick > 0:
            self.eng.step(int(start_tick))
        s = self.eng.state()
        if elixir_milli is not None:
            for t in (0, 1):
                self.eng._call(f"setelixir {t} {int(elixir_milli[t])}")
        if tower_hp is not None:
            for name, owner, x, y, hp, mhp, gid, *_ in s["objects"]:
                k = self._tower_slot(name, x)
                if k >= 0 and owner in (0, 1) and tower_hp[owner][k] != hp:
                    self.eng._call(f"sethp {gid} {int(tower_hp[owner][k])}")
        # Scenario units (the actor's threat / sniper starts): loader `spawn` places
        # each card now, free and without touching hands (pd has no slot bits).
        for sp in spawns or []:
            team, c, x_sub, y_sub = sp[:4]
            lvl = max(self.levels[team]) - 1
            self.eng._call("spawn " + json.dumps({"ct": 153, "c": {
                "t": self.eng.t, "t2": self.eng.t, "idHi": 0, "idLo": team + 1, "px": int(x_sub / SUB),
                "py": int(y_sub / SUB), "sid": 0, "sel": {"os": self._eid(c), "pd": lvl << 10}}}))
        self._refresh()

    def check_deploy(self, team, slot, x_sub, y_sub):
        self._sync()
        s = self.s
        if s is None or self._over():
            return R["GAME_OVER"]
        if not 0 <= slot < 4:
            return R["BAD_SLOT"]
        ds = self._slot_at(team, slot)
        if ds is None:
            return R["EMPTY_SLOT"]
        if any(p[1] == ds for p in self.pending[team]):
            return R["CARD_PENDING"]
        if self.eng.t < 90:
            return R["TOO_EARLY"]
        cost = self.cat[self.deck[team][ds]][2]
        if self._elixir_milli(team) < cost * 1000:
            return R["NOT_ENOUGH_ELIXIR"]
        x, y = x_sub / SUB, y_sub / SUB
        if not (0 <= x < 18000 and 0 <= y < 32000):
            return R["OUT_OF_ARENA"]
        return self._grid(team, self.deck[team][ds])[int(y // 1000) * 18 + int(x // 1000)]

    def step(self, cmds, n=1):
        """Sends the plays, the step and a state read without waiting for the
        engine; the replies are read on the next call (see _sync)."""
        self._sync()
        rows = []
        for team, hi, x_sub, y_sub in cmds:
            if hi >= 4:
                rows.append(self._ability(team, hi - 4))
                continue
            r = self.check_deploy(team, hi, x_sub, y_sub)
            ds = self._slot_at(team, hi)
            card = self.deck[team][ds] if ds is not None else -1
            tick = self.eng.t + self.delay[team]
            if r == 0:
                self._play(team, ds, int(x_sub / SUB), int(y_sub / SUB), tick)
            rows.append((card, r, tick, x_sub, y_sub))
        if self.held:
            due = [h for h in self.held if h[0] <= self.eng.t + int(n)]
            self.held = [h for h in self.held if h[0] > self.eng.t + int(n)]
            for _, line in sorted(due):
                self._send(line)
        if not self._over():
            self._send(f"step {int(n)}")
        self._send("state")
        return rows

    def state_json(self):
        self._sync()
        return json.dumps(self._state())

    def close(self):
        self.eng.close()
        try:
            self.path.unlink()
        except OSError:
            pass

    # -- internals ------------------------------------------------------------
    def _eid(self, c):
        name = self.cat[c][0]
        if name not in self.eids:
            raise KeyError(f"card {name} has no engine id")
        return self.eids[name]

    @staticmethod
    def _tower_slot(name, x):
        if name == "KingTower":
            return 0
        if name == "PrincessTower":
            return 1 if x < 9000 else 2
        return -1

    def _send(self, line):
        self.eng.send(line)
        self.waiting += 1

    def _sync(self):
        """Read the replies of everything sent; the last one is the state."""
        if not self.waiting:
            return
        r = None
        while self.waiting:
            r = self.eng.recv()
            self.waiting -= 1
        if "t" in r:                  # a state read (a play inside step() syncs only its cmd reply)
            self.eng.t = r["t"]
            self._refresh(r)

    def _refresh(self, s=None):
        self.s = s if s is not None else self.eng.state()
        t = self.eng.t
        for team in (0, 1):
            # A play stays pending (its cost held back) until the card has left
            # the hand: the engine debits elixir a few ticks after the play's
            # tick. A play the engine refused is dropped after PENDING_MAX ticks.
            hands = self.s["hands"][team]
            self.pending[team] = [p for p in self.pending[team]
                                  if t <= p[0] or (p[1] >= 0 and 0 <= hands[p[1]] <= 3 and t <= p[0] + PENDING_MAX)
                                  or (p[1] < 0 and t <= p[0] + 2)]

    def _over(self):
        return bool(self.s["flags"][0]) or self.eng.t >= REGULAR + OVERTIME

    def _slot_at(self, team, pos):
        for ds, p in enumerate(self.s["hands"][team]):
            if p == pos:
                return ds
        return None

    def _elixir_milli(self, team):
        raw = self.s["elixirraw"][team] // 10
        return max(0, min(10000, raw) - 1000 * sum(p[2] for p in self.pending[team]))

    def _towers(self):
        hp = [[0, 0, 0], [0, 0, 0]]
        mx = [[1, 1, 1], [1, 1, 1]]
        for name, owner, x, y, h, m, *_ in self.s["objects"]:
            k = self._tower_slot(name, x)
            if k >= 0 and owner in (0, 1):
                hp[owner][k], mx[owner][k] = max(0, h), m
        return hp, mx

    def _grid(self, team, c):
        """The engine's own placement rule per tile (loader `snapgrid`: the card
        command's tile check plus the deploy snap, accepted only when the card
        lands in the tile it was aimed at). Cached until a tower falls."""
        hp, _ = self._towers()
        key = (team, c, tuple(h > 0 for side in hp for h in side))
        g = self.grids.get(key)
        if g is None:
            m = self.eng._call(f"snapgrid {team} {self._eid(c)}")["mask"]
            g = [R["OK"] if ch == "1" else R["OUT_OF_TERRITORY"] for ch in m]
            self.grids[key] = g
        return g

    def _territory(self, team, x, y):
        """Unused fallback (unverified): own half, plus the pocket behind a destroyed enemy
        princess tower; tower footprints are blocked. Mirrored for team 1."""
        hp, _ = self._towers()
        fy = y if team == 0 else 32000 - y
        fx = x if team == 0 else 18000 - x
        ok = fy < 15000
        if not ok and fy < 22000:
            left, right = (1, 2) if team == 0 else (2, 1)
            ok = (fx < 9000 and hp[1 - team][left] <= 0) or (fx >= 9000 and hp[1 - team][right] <= 0)
        if not ok:
            return R["OUT_OF_TERRITORY"]
        for name, owner, tx, ty, h, *_ in self.s["objects"]:
            k = self._tower_slot(name, tx)
            if k < 0 or h <= 0:
                continue
            half = 2000 if k == 0 else 1500
            if abs(x - tx) < half and abs(y - ty) < half:
                return R["OCCUPIED"]
        return R["OK"]

    @staticmethod
    def _play_line(team, x, y, tick, sel):
        return "cmd " + json.dumps({"ct": 153, "c": {"t": tick, "t2": tick, "idHi": 0, "idLo": team + 1,
                                                     "px": x, "py": y, "sid": 0, "sel": sel}}, separators=(",", ":"))

    def _sel(self, team, ds):
        c = self.deck[team][ds]
        cost, form = self.cat[c][2], self.forms[team][ds]
        sel = {"os": self._eid(c), "pd": engine.pd(ds, self.levels[team][ds] - 1, cost) | (form << 19)}
        pos = self.s["hands"][team][ds]
        card = self.s["handcards"][team][pos]
        if form == 1 and self.s["evoready"][team][ds]:
            sel["pd"] |= 1
            sel["fs"] = card[3]
        elif form == 2:
            sel["pd"] |= 2
            sel["fs"] = card[4]
        return c, cost, sel

    def try_wait(self, team, horizon=160, material=0.3, elixir=0.0, win=0.0):
        """The score of playing nothing for `horizon` ticks, in a forked copy: what the
        plays of try_plays are compared with when the search may also wait or pick
        another card (2026-11-15). None if the copy failed."""
        if REBUILD:
            return self._shadow().try_wait(team, horizon, material, elixir, win)
        self._sync()
        try:
            self.eng._call(f"try {int(horizon)} step 0")
            return self._score(self.eng.recv(), team, material, elixir, win, self.eng.t + int(horizon))
        except RuntimeError:
            return None

    def try_plays(self, team, hi, cells, horizon=160, material=0.3, elixir=0.0, win=0.0):
        """Placement search (2026-11-13, after daybreak-cr's cr/search.py): hand slot `hi`
        of `team` at each (x_sub, y_sub) of `cells`, each in a forked copy of this game
        (loader_fork's "try": the play, `horizon` ticks with no further plays, the
        state). This game does not change. -> one score per cell, None where the play
        is not legal or the copy failed. Score, from `team`'s side: crowns + tower hp
        fractions (theirs lost minus ours lost) + material x (our units' hp - theirs)
        in princess-tower hp. Needs LOADER=loader_fork. UNVERIFIED constants: horizon
        160 and material 0.3 are daybreak-cr's, not measured here."""
        if REBUILD:
            return self._shadow().try_plays(team, hi, cells, horizon, material, elixir, win)
        self._sync()
        ds = self._slot_at(team, hi)
        out = []
        for x_sub, y_sub in cells:
            if ds is None or self.check_deploy(team, hi, x_sub, y_sub) != 0:
                out.append(None)
                continue
            _, _, sel = self._sel(team, ds)
            line = self._play_line(team, int(x_sub / SUB), int(y_sub / SUB), self.eng.t + self.delay[team], sel)
            try:
                self.eng._call(f"try {int(horizon)} {line}")
                out.append(self._score(self.eng.recv(), team, material, elixir, win, self.eng.t + int(horizon)))
            except RuntimeError:
                out.append(None)
        return out

    def _shadow(self):
        """HASTY_SEARCH_REBUILD=1 (2026-11-22): search in an engine game rebuilt from
        what a live reader sees (tools/league/rebuild_search.py), not a fork."""
        if getattr(self, "_shadow_obj", None) is None:
            import rebuild_search
            self._shadow_obj = rebuild_search.Shadow(self)
        return self._shadow_obj

    def _score(self, s, team, material, elixir=0.0, win=0.0, end_tick=0):
        """`elixir`: weight of the elixir difference left at the end (per elixir, in
        princess towers). Without it a card is free in the copy, so the search prefers
        the biggest answer; with it a 2-elixir answer that holds beats a 5-elixir one,
        and at 10 elixir spending costs nothing (the bank is capped), as in the game.
        UNVERIFIED constant: no value has been measured."""
        keep, self.s = self.s, s
        try:
            hp, mx = self._towers()
        finally:
            self.s = keep
        frac = [sum(h / m for h, m in zip(hp[t], mx[t])) for t in (0, 1)]
        crowns = engine.RealEngine.crowns(s)
        units = [0, 0]
        for name, owner, x, y, h, m, *_ in s["objects"]:
            if owner in (0, 1) and m > 0 and h > 0 and self._tower_slot(name, x) < 0                     and self._spell_card(name) is None:
                units[owner] += h
        # A destroyed tower leaves mx at its default 1, so once both of team 0's princess
        # towers fell the material term was divided by 1 and scores reached the thousands
        # (2026-11-24 fix). Use the largest princess max hp seen in this battle instead.
        seen = max(mx[0][1], mx[0][2], mx[1][1], mx[1][2])
        if seen > 1:
            self.princess_ref = max(getattr(self, "princess_ref", 0), seen)
        princess = max(getattr(self, "princess_ref", 0), seen, 1)
        o = 1 - team
        bank = [min(10000, s["elixirraw"][t] // 10) / 1000.0 for t in (0, 1)] if elixir else [0.0, 0.0]
        score = ((crowns[team] - crowns[o]) + (frac[team] - frac[o])
                 + material * (units[team] - units[o]) / princess + elixir * (bank[team] - bank[o]))
        if win and (s["flags"][0] or end_tick >= REGULAR + OVERTIME):
            # The copy reached the end of the game (2026-11-15): add +-`win` for the result,
            # so a Fireball that wins on the clock outranks a troop that would have chipped
            # more later. More crowns wins; equal crowns at the end of overtime go to the
            # side whose weakest standing tower has more hit points (the game's tiebreaker,
            # by hit points; UNVERIFIED against the engine's own result flag).
            if crowns[team] != crowns[o]:
                score += win if crowns[team] > crowns[o] else -win
            else:
                low = [min([h for h in hp[t] if h > 0] or [0]) for t in (0, 1)]
                if low[team] != low[o]:
                    score += win if low[team] > low[o] else -win
        return score

    def _play(self, team, ds, x, y, tick):
        c, cost, sel = self._sel(team, ds)
        if team in self.hold:
            self.held.append((tick, self._play_line(team, x, y, tick, sel)))
        else:
            self._send(self._play_line(team, x, y, tick, sel))
        # Where each play lands (2026-11-23): a rebuilt copy (rebuild_search) re-sends the
        # plays still in flight. (team, exec tick, card id, x, y), kept until the tick
        # passes. Only plays affordable when sent: the engine refuses the others at their
        # tick, while the copy's spawn command would not.
        self.inflight = [q for q in getattr(self, "inflight", []) if q[1] > self.eng.t]
        if self._elixir_milli(team) >= 1000 * cost:
            self.inflight.append((team, tick, c, x, y))
        self.pending[team].append((tick, ds, cost))
        if self.cat[c][8] == "SPELL":
            self.casts.append((tick, team, c, x, y))
        q = self.queue[team]
        q.append(ds)

    def _ability_unit(self, team, k):
        """The newest live own unit for ability button k: the hero form is
        named <Card>Hero, a champion by its card name."""
        if k >= len(self.abil[team]):
            return None
        name = self.cat[self.abil[team][k][3]][0].lower()
        cand = [o for o in self.s["objects"] if o[1] == team and o[4] > 0 and o[0].lower().startswith(name)
                and self._tower_slot(o[0], o[2]) < 0 and o[0] not in NOT_ABILITY_UNITS]
        return max(cand, key=lambda o: o[6]) if cand else None

    def _ability_check(self, team, gid):
        """The engine's own readiness check (loader `abilitycheck`: 0 = may fire,
        1014 = no use left, 1005 = cooling down) and the slots' cooldowns."""
        self._sync()                  # replies to plays sent earlier in this step come first
        return self.eng._call(f"abilitycheck {team} {gid}")

    def _ability(self, team, k):
        """Hero / champion ability: command type 189 with that unit's game id.
        Uses and cooldowns are the engine's (one use per deploy for most
        champions and heroes in this game version; Boss Bandit has more)."""
        u = self._ability_unit(team, k)
        if u is None:
            return (-1, R["NO_HERO"], self.eng.t, 0, 0)
        card, cost = self.abil[team][k][3], self.abil[team][k][2]
        if self.pressed[team].get(u[6], -1) >= self.eng.t:
            return (card, R["CARD_PENDING"], self.eng.t, 0, 0)
        code = self._ability_check(team, u[6])["code"]
        if code == 1014:
            return (card, R["ABILITY_SPENT"], self.eng.t, 0, 0)
        if code != 0:
            return (card, R["ABILITY_NOT_READY"], self.eng.t, 0, 0)
        if self._elixir_milli(team) < cost * 1000:
            return (card, R["NOT_ENOUGH_ELIXIR"], self.eng.t, 0, 0)
        t = self.eng.t + self.delay[team]
        self._send("cmd " + json.dumps({"ct": 189, "c": {"t": t, "t2": t + 1, "idHi": 0, "idLo": team + 1,
                                                             "cgid": u[6]}}))
        self.pressed[team][u[6]] = t + 2      # until the engine has run it
        self.pending[team].append((t, -1, cost))  # its cost is held back like a card's
        return (card, R["OK"], t, 0, 0)

    def _abilities(self, team):
        """RoyaleSim rows [available, spent, cost, card, cooldown] from the engine."""
        rows = []
        for k, r in enumerate(self.abil[team]):
            u = self._ability_unit(team, k)
            avail, spent, cool = 0, 0, 0
            if u is not None:
                c = self._ability_check(team, u[6])
                pending = self.pressed[team].get(u[6], -1) >= self.eng.t
                avail = int(c["code"] == 0 and not pending)
                spent = int(c["code"] == 1014)
                cool = max(0, c["cool"][k] if k < len(c["cool"]) else 0)
            rows.append([avail, spent, r[2], r[3], cool])
        return rows

    def _state(self):
        s, t = self.s, self.eng.t
        hp, mx = self._towers()
        crowns = engine.RealEngine.crowns(s)
        over = self._over()
        winner = -1
        if over:
            if crowns[0] != crowns[1]:
                winner = 0 if crowns[0] > crowns[1] else 1
            else:
                tot = [sum(h) for h in hp]
                winner = 0 if tot[0] > tot[1] else 1 if tot[1] > tot[0] else 2
        players = []
        for team in (0, 1):
            hand_slots = sorted((p, ds) for ds, p in enumerate(s["hands"][team]) if 0 <= p <= 3)
            hand = [self.deck[team][ds] for _, ds in hand_slots]
            waiting = [ds for ds in self.queue[team] if not 0 <= s["hands"][team][ds] <= 3]
            # keep the queue to cards actually out of hand, in the order they left it
            self.queue[team] = waiting + [ds for ds in range(8) if ds not in waiting
                                          and not 0 <= s["hands"][team][ds] <= 3]
            players.append({
                "team": team, "elixir_milli": self._elixir_milli(team), "hand": hand,
                "hand_costs": [self.cat[c][2] for c in hand], "mirror_target": -1,
                "deck": list(self.deck[team]), "forms": list(self.forms[team]),
                "pending_cost": sum(p[2] for p in self.pending[team]),
                "pending": [[p[0], self.deck[team][p[1]]] for p in self.pending[team] if p[1] >= 0],
                "evo": [], "abilities": self._abilities(team),
                "next_card": self.deck[team][self.queue[team][0]] if self.queue[team] else -1,
                "crowns": crowns[team], "tower_hp": hp[team], "tower_max_hp": mx[team],
                "king_active": hp[team][0] < mx[team][0] or min(hp[team][1:]) <= 0})
        ents = []
        nf = len(royalesim.ENTITY_FIELDS)
        F = {k: i for i, k in enumerate(royalesim.ENTITY_FIELDS)}
        for o in s["objects"]:
            name, owner, x, y, h, m, gid = o[:7]
            # spells and projectiles are not units (spells go to "spells")
            if owner not in (0, 1) or m <= 0 or self._spell_card(name) is not None:
                continue
            k = self._tower_slot(name, x)
            row = [0] * nf
            row[F["uid"]], row[F["team"]] = gid, owner
            row[F["kind"]] = 2 if k == 0 else 3 if k > 0 else 1 if name in _shared["buildings"] else 0
            row[F["card_id"]] = -1
            row[F["tower_slot"]] = k
            row[F["x"]], row[F["y"]] = x * SUB, y * SUB
            row[F["hp"]], row[F["max_hp"]] = h, m
            row[F["flying"]] = bool(o[7]) if len(o) > 7 else False
            row[F["deploy_ticks"]] = 1 if len(o) > 8 and o[8] == 4 else 0
            row[F["target_uid"]] = o[9] if len(o) > 9 else -1
            row[F["mount_uid"]] = -1
            row[F["dest_x"]] = row[F["dest_y"]] = -1
            row[F["unit_type"]] = (unitmap.resolve(name, self.ut) if UNIT_FALLBACK
                                   else self.ut.get(UNIT_ALIASES.get(name, name), -1))
            if len(o) > 11:                       # cues: attack clock (ms), buffs "Name:ms,..."
                row[F["attack_phase"]] = o[10]
                row[F["buffs"]] = parse_buffs(o[11])
            ents.append(row)
        ot = t >= REGULAR
        return {"tick": t, "tick_ms": 50, "regular_ticks": REGULAR, "overtime_ticks": OVERTIME,
                "elixir_rate": 3 if ot else 2 if t >= 2400 else 1, "overtime": ot, "game_over": over,
                "winner": winner, "players": players, "entities": ents, "spells": self._spells(t), "cues": True,
                "projectiles": []}

    def _spell_card(self, name):
        """Catalogue id of the spell an engine object belongs to (FireballSpell,
        LogProjectileRolling, GoblinBarrelSpell, Tornado ...), else None."""
        if name not in _spell_of:
            base = name
            for suf in ("ProjectileRolling", "Projectile", "Spell"):
                if base.endswith(suf) and len(base) > len(suf):
                    base = base[: -len(suf)]
                    break
            _spell_of[name] = _shared["spells"].get(base.lower())
        return _spell_of[name]

    def _spells(self, t):
        """Spell rows from the engine's own spell objects (true positions), in
        RoyaleSim's SPELL_FIELDS order. The aim point comes from the play the
        shim sent for that side and card; without one it is the position."""
        self.casts = [c for c in self.casts if t < c[0] + SPELL_KEEP]
        rows, seen = [], {}
        for o in self.s["objects"]:
            c = self._spell_card(o[0])
            if c is None or o[1] not in (0, 1):
                continue
            team, x, y = o[1], o[2], o[3]
            aim = [(cx, cy, t0) for t0, tm, cc, cx, cy in self.casts if tm == team and cc == c and t0 <= t]
            ax, ay, t0 = aim[-1] if aim else (x, y, t)
            # A moving spell (Fireball, Log, Barrel) aims along its motion, as the
            # live bridge extrapolates it from reader positions.
            prev = self.spell_pos.get(o[6])
            if prev is not None and (prev[0], prev[1]) != (x, y):
                ax, ay = x + (x - prev[0]) * 10, y + (y - prev[1]) * 10
            seen[o[6]] = (x, y)
            rows.append([team, c, 0, x * SUB, y * SUB, int(ax * SUB), int(ay * SUB), 0, 0, 0, 0, t - t0])
        self.spell_pos = seen
        return rows
