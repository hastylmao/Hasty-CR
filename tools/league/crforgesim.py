"""CrforgeBattle: a drop-in for royalesim.Battle that runs crforge
(github.com/voonhous/crforge, a tick-exact Java re-implementation held to recorded
battles of data version 16.635.8, the version Null's build 160635007 serves).

Same API subset as realsim.RealBattle: set_command_delay_ticks, reset, step,
check_deploy, state_json, catalogue_json, unit_types_json. Catalogue ids and
unit types are RoyaleSim's, so models see the same vocabulary.

Setup (2026-11-21, experiment, not yet used by any promoted model):
  crforge checkout at CRFORGE_HOME (default D:/crwork/crforge), built with
  ./gradlew :env:installDist :tables:gameTables -Pcrforge.assetSource=file:///D:/crwork/cdn/
  (tables built from our own build 160635007 files; music.csv and texts_patch.csv
  came from an older build, presentation only). crforge_env installed in the venv.

Known gaps:
  - reset: elixir_milli, tower_hp, spawns and hand_first are not applied (raise when
    given, so drill scenarios are not silently wrong); full games only.
  - the opening hand is crforge's own shuffle of the seed, not the shim's permutation.
  - command delay is crforge's fixed 20 ticks.
  - spells: aim point is the row's aim (or its position); age is 0. Buffs: 3 slots per unit.
  - entities are those seat 0's player sees (crforge SeatView): invisible units are absent.
"""
import json
import os

import numpy as np
import royalesim

from crforge_env import LadderConfig, SideSetup, VectorBattle
from crforge_env import _jvm as _cf_jvm

# Every VectorBattle loads its own copy of the game tables (VectorEnv.tables); with one
# battle per env that is dozens of copies and ran the machine out of memory (2026-11-21).
# Share one load per folder across the process.
_real_java_class = _cf_jvm.java_class
_tables_cache = {}


class _SharedTablesVectorEnv:
    def __init__(self, cls):
        self._cls = cls

    def tables(self, folder):
        key = str(folder)
        if key not in _tables_cache:
            _tables_cache[key] = self._cls.tables(folder)
        return _tables_cache[key]

    def __getattr__(self, name):
        return getattr(self._cls, name)

    def __call__(self, *a):
        return self._cls(*a)


def _java_class(name):
    c = _real_java_class(name)
    return _SharedTablesVectorEnv(c) if name == "org.crforge.env.VectorEnv" else c


_cf_jvm.java_class = _java_class

HOME = os.environ.get("CRFORGE_HOME", "D:/crwork/crforge")
INSTALL = f"{HOME}/env/build/install/env"
TABLES = os.environ.get("CRFORGE_TABLES", os.path.expanduser("~/.crforge/tables/16.635.8"))
SUB = royalesim.SUBTILE_PER_MILLITILE
R = {n: i for i, n in enumerate(royalesim.DEPLOY_REASONS)}
REGULAR, OVERTIME = 3600, 2400
W, H = 18000, 32000
UNIT_ALIASES = {"IceWizardHero": "IceWizard", "IceWizardHero_IceCube": "IceWizard",
                "IceWizardHeroFloatingCube": "IceWizard"}
HERO_COST = {"IceWizard": 2}
_shared = {}


def _tables():
    if not _shared:
        b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        _shared["cat_json"] = b.catalogue_json()
        _shared["ut_json"] = b.unit_types_json()
        _shared["cat"] = json.loads(_shared["cat_json"])
        _shared["ut"] = {n: i for i, n in enumerate(json.loads(_shared["ut_json"]))}
        _shared["cat_id"] = {row[0]: i for i, row in enumerate(_shared["cat"])}
    return _shared


def _abs(seat, x, y):
    """seat frame -> absolute game units (crforge Schema.toSeatX/Y are their own inverse)"""
    return (W - x, y) if seat == 0 else (x, H - y)


class CrforgeBattle:
    def __init__(self, card_names=None, slot_of_k=None):
        t = _tables()
        self.cat, self.ut, self.cat_id = t["cat"], t["ut"], t["cat_id"]
        cfg = LadderConfig(decision_ticks=1, max_ticks=REGULAR + OVERTIME + 40, mask_version=2)
        self.v = VectorBattle(1, 1, install=INSTALL, tables=TABLES, config=cfg,
                              jvm_args=[os.environ.get("CRFORGE_XMX", "-Xmx700m")])
        self.v.set_autoreset(False)
        self.s = self.v.schema
        self.voc = self.v.vocabulary
        self.n = 0
        self.done_seen = False

    def catalogue_json(self):
        return _shared["cat_json"]

    def unit_types_json(self):
        return _shared["ut_json"]

    def set_command_delay_ticks(self, a, b):
        pass                          # crforge's play delay is the game's 20 ticks

    def close(self):
        try:
            self.v.close()
        except Exception:
            pass

    # -- reset ---------------------------------------------------------------
    def reset(self, seed=0, decks=None, shuffle=1, start_tick=0, elixir_milli=None, tower_hp=None,
              spawns=None, forms=None, levels=None, tower_levels=None, hand_first=None, **_):
        if tower_hp is not None or spawns or hand_first:
            raise NotImplementedError("crforgesim: scenario starts (tower_hp/spawns/hand_first) not supported")
        self.deck = [list(d) for d in decks]
        self.forms = [list(f) for f in (forms or [[0] * 8, [0] * 8])]
        lv = [list(x) for x in (levels or [[11] * 8, [11] * 8])]
        tl = tower_levels or [11, 11]
        names = [[self.cat[c][0] for c in self.deck[t]] for t in (0, 1)]
        slots = [[2 if f == 2 else 1 if f == 1 else 0 for f in self.forms[t]] for t in (0, 1)]
        setups = [SideSetup(towers="King_PrincessTowers", king_level=int(tl[t]), tower_level=int(tl[t]),
                            card_levels=[int(x) for x in lv[t]]) for t in (0, 1)]
        self.v.reset([int(seed) % (2 ** 31)], names[0], names[1], slots[0], slots[1], setups[0], setups[1])
        self.pending = [[], []]       # (exec tick, card id, cost)
        self.done_seen = False
        self.result = None
        if elixir_milli is not None and any(int(e) != 5000 for e in elixir_milli):
            raise NotImplementedError("crforgesim: elixir_milli other than the 5-elixir start not supported")
        if start_tick > 0:
            self._advance(int(start_tick), [])

    # -- stepping --------------------------------------------------------------
    def _obs(self, seat):
        return self.v.observations[0, seat]

    def _mask(self, seat):
        return self.v.masks[0, seat]

    def _tick(self):
        return int(self.s.field(self._obs(0), "tick"))

    def _over(self):
        return self.done_seen or self._tick() >= REGULAR + OVERTIME

    def _advance(self, n, acts):
        """n ticks; acts = {seat: action} given on the first tick."""
        for k in range(n):
            if self._over():
                return
            a = np.zeros((1, 2), dtype=np.int32)
            if k == 0:
                for seat, act in acts:
                    a[0, seat] = act
            self.v.step(a)
            if self.v.dones[0]:
                self.done_seen = True
                self.result = int(self.v.info(0).get("winner", -1)) if hasattr(self.v, "info") else -1

    def _action(self, team, slot, x_sub, y_sub):
        x, y = x_sub / SUB, y_sub / SUB
        sx, sy = (W - x, y) if team == 0 else (x, H - y)
        col, row = int(sx // 1000), int(sy // 1000)
        if not (0 <= col < self.s.cols and 0 <= row < self.s.rows):
            return None
        return self.s.play(slot, col, row)

    def check_deploy(self, team, slot, x_sub, y_sub):
        if self._over():
            return R["GAME_OVER"]
        if not 0 <= slot < 4:
            return R["BAD_SLOT"]
        o = self._obs(team)
        hand = self.s.field(o, "hand_card")
        if hand[slot] < 0:
            return R["EMPTY_SLOT"]
        if self.s.field(o, "hand_pending")[slot]:
            return R["CARD_PENDING"]
        cost = int(self.s.field(o, "hand_cost")[slot])
        if self._elixir_milli(team) < cost * 1000:
            return R["NOT_ENOUGH_ELIXIR"]
        a = self._action(team, slot, x_sub, y_sub)
        if a is None:
            return R["OUT_OF_ARENA"]
        if not self._mask(team)[a]:
            return R["TOO_EARLY"] if self._tick() < 90 else R["OUT_OF_TERRITORY"]
        return R["OK"]

    def step(self, cmds, n=1):
        rows, acts = [], []
        tick = self._tick() + 20
        for team, hi, x_sub, y_sub in cmds:
            if hi >= 4:
                rows.append(self._ability(team, hi - 4, acts))
                continue
            r = self.check_deploy(team, hi, x_sub, y_sub)
            hand = self.s.field(self._obs(team), "hand_card")
            card = self.cat_id.get(self.voc[hand[hi]], -1) if 0 <= hi < 4 and hand[hi] >= 0 else -1
            if r == 0:
                acts.append((team, self._action(team, hi, x_sub, y_sub)))
                self.pending[team].append((tick, card, self.cat[card][2] if card >= 0 else 0))
            rows.append((card, r, tick, x_sub, y_sub))
        self._advance(int(n), acts)
        t = self._tick()
        for team in (0, 1):
            self.pending[team] = [p for p in self.pending[team] if p[0] > t]
        return rows

    def _ability(self, team, k, acts):
        a = self.s.first_ability + k
        card = self._hero_card(team)
        if card is None:
            return (-1, R["NO_HERO"], self._tick(), 0, 0)
        if a >= len(self._mask(team)) or not self._mask(team)[a]:
            return (card, R["ABILITY_NOT_READY"], self._tick(), 0, 0)
        acts.append((team, a))
        return (card, R["OK"], self._tick() + 20, 0, 0)

    def _spell_card(self, name):
        sp = _shared.setdefault("spell_ids", {row[0].lower(): i for i, row in enumerate(self.cat) if row[8] == "SPELL"})
        memo = _shared.setdefault("spell_of", {})
        if name not in memo:
            base = name
            for suf in ("ProjectileRolling", "Projectile", "Spell"):
                if base.endswith(suf) and len(base) > len(suf):
                    base = base[: -len(suf)]
                    break
            memo[name] = sp.get(base.lower())
        return memo[name]

    def _hero_card(self, team):
        for c, f in zip(self.deck[team], self.forms[team]):
            if f == 2:
                return c
        return None

    # -- state -----------------------------------------------------------------
    def _elixir_milli(self, team):
        return max(0, min(10000, int(self.s.field(self._obs(team), "elixir")) // 10))

    def _towers(self):
        o = self._obs(0)
        f = lambda n: int(self.s.field(o, n))
        # seat 0's frame mirrors x: its "left" is absolute x > 9000. RoyaleSim's
        # slot 1 is absolute x < 9000, slot 2 x >= 9000 (realsim._tower_slot).
        hp = [[f("own_king_hp"), f("own_right_hp"), f("own_left_hp")],
              [f("enemy_king_hp"), f("enemy_right_hp"), f("enemy_left_hp")]]
        mx = [[max(1, f("own_king_max_hp")), max(1, f("own_right_max_hp")), max(1, f("own_left_max_hp"))],
              [max(1, f("enemy_king_max_hp")), max(1, f("enemy_right_max_hp")), max(1, f("enemy_left_max_hp"))]]
        return hp, mx

    def state_json(self):
        return json.dumps(self._state())

    def _state(self):
        t = self._tick()
        hp, mx = self._towers()
        crowns = [int(self.s.field(self._obs(0), "crowns")), int(self.s.field(self._obs(0), "crowns_enemy"))]
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
            o = self._obs(team)
            hand_ids = [self.cat_id.get(self.voc[h], -1) for h in self.s.field(o, "hand_card") if h >= 0]
            nxt = int(self.s.field(o, "next_card"))
            abil = []
            hc = self._hero_card(team)
            if hc is not None:
                a = self.s.first_ability
                avail = int(a < len(self._mask(team)) and bool(self._mask(team)[a]))
                cool = max(0, int(self.s.field(o, "ability_cooldown_ms")[0]) // 50)
                abil.append([avail, 0, HERO_COST.get(self.cat[hc][0], 2), hc, cool])
            players.append({
                "team": team, "elixir_milli": self._elixir_milli(team), "hand": hand_ids,
                "hand_costs": [int(c) for c in self.s.field(o, "hand_cost")][:len(hand_ids)], "mirror_target": -1,
                "deck": list(self.deck[team]), "forms": list(self.forms[team]),
                "pending_cost": sum(p[2] for p in self.pending[team]),
                "pending": [[p[0], p[1]] for p in self.pending[team]],
                "evo": [], "abilities": abil,
                "next_card": self.cat_id.get(self.voc[nxt], -1) if nxt >= 0 else -1,
                "crowns": crowns[team], "tower_hp": hp[team], "tower_max_hp": mx[team],
                "king_active": hp[team][0] < mx[team][0] or min(hp[team][1:]) <= 0})
        F = {k: i for i, k in enumerate(royalesim.ENTITY_FIELDS)}
        nf = len(royalesim.ENTITY_FIELDS)
        c = self.s.columns(self._obs(0))
        flags = self.s.flag_names
        bit = {n: 1 << i for i, n in enumerate(flags)}
        ents = []
        for i in range(len(c["id"])):
            kind = int(c["kind"][i])
            if kind not in (1, 2) or c["hp"][i] <= 0:
                continue
            name = self.voc[int(c["row"][i])] if c["row"][i] >= 0 else ""
            x, y = _abs(0, int(c["x"][i]), int(c["y"][i]))
            side = int(c["side"][i])
            fl = int(c["flags"][i])
            if kind == 2:
                k = 0 if fl & bit["king"] else (1 if x < 9000 else 2)
            else:
                k = -1
            row = [0] * nf
            row[F["uid"]], row[F["team"]] = int(c["id"][i]), side
            row[F["kind"]] = 2 if k == 0 else 3 if k > 0 else 1 if fl & bit["building"] else 0
            row[F["card_id"]] = -1
            row[F["tower_slot"]] = k
            row[F["x"]], row[F["y"]] = x * SUB, y * SUB
            row[F["hp"]], row[F["max_hp"]] = int(c["hp"][i]), int(c["max_hp"][i])
            row[F["flying"]] = bool(fl & bit["air"])
            row[F["deploy_ticks"]] = 1 if int(c["state"][i]) == 4 else 0
            row[F["target_uid"]] = int(c["target"][i]) if c["target"][i] >= 0 else -1
            row[F["mount_uid"]] = -1
            row[F["dest_x"]] = row[F["dest_y"]] = -1
            row[F["unit_type"]] = self.ut.get(UNIT_ALIASES.get(name, name), -1)
            # cues as realsim gives them: attack clock (ms) and buffs [[name, ms], ...]
            row[F["attack_phase"]] = max(0, int(c["attack_ms"][i]))
            bl = []
            for q in range(3):
                b_id = int(c[f"buff_{q}"][i])
                if b_id >= 0 and b_id < len(self.v.buff_names):
                    bl.append([self.v.buff_names[b_id], int(c[f"buff_ms_{q}"][i])])
            row[F["buffs"]] = bl
            ents.append(row)
        # spells: projectile / area rows that belong to a spell card (realsim._spells order)
        spells = []
        for i in range(len(c["id"])):
            if int(c["kind"][i]) not in (3, 4) or c["row"][i] < 0:
                continue
            cid = self._spell_card(self.voc[int(c["row"][i])])
            if cid is None:
                continue
            x, y = _abs(0, int(c["x"][i]), int(c["y"][i]))
            ax, ay = int(c["aim_x"][i]), int(c["aim_y"][i])
            ax, ay = _abs(0, ax, ay) if (ax or ay) else (x, y)
            spells.append([int(c["side"][i]), cid, 0, x * SUB, y * SUB, ax * SUB, ay * SUB, 0, 0, 0, 0, 0])
        ot = t >= REGULAR
        return {"tick": t, "tick_ms": 50, "regular_ticks": REGULAR, "overtime_ticks": OVERTIME,
                "elixir_rate": 3 if ot else 2 if t >= 2400 else 1, "overtime": ot, "game_over": over,
                "winner": winner, "players": players, "entities": ents, "spells": spells, "cues": True, "projectiles": []}
