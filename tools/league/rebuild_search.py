"""Placement search on a REBUILT engine copy (2026-11-22, experiment).

The fork search (realsim.try_plays, +20 points in the engine on 2026-11-13) cannot
run live: there is no engine copy of a real game. A live bot only sees what the
memory reader gives: each unit's name, owner, position and hit points, the
towers' hit points, our elixir and the clock. This module builds an engine game
from exactly that and runs the same `try` trials in it, so the engine can measure
how much of the fork search's gain survives the rebuild before anything is built
for live play.

What the rebuild drops (all UNVERIFIED in effect, which is what the test measures):
attack timers, targets, buffs, projectiles and spells in flight, plays in flight,
the clock (the copy starts at tick 90, so elixir rate and overtime differ), the
opponent's elixir, unit levels (all at the deck's max level), and death spawns
of units trimmed during the rebuild.

Used by realsim.RealBattle.try_plays / try_wait when HASTY_SEARCH_REBUILD=1.
"""
import json
import os

import realsim

# HASTY_REBUILD_COMBAT=1 (2026-11-23): also copy each unit's attack clock and target
# into the rebuilt copy (engine command setcombat, LOADER=loader_set). UNVERIFIED gain.
COMBAT = os.environ.get("HASTY_REBUILD_COMBAT") == "1"
# HASTY_REBUILD_DEPLOY=1 (2026-11-23): a rebuilt unit is freshly spawned and stands in its
# deploy animation (state 4) for ~1 s. Copy the source's deploy timer instead (0 when the
# source unit has finished deploying). Engine command setdeploy, LOADER=loader_set.
DEPLOY = os.environ.get("HASTY_REBUILD_DEPLOY") == "1"
# HASTY_REBUILD_PENDING=own|both (2026-11-23): re-send plays still in flight into the copy
# at their landing ticks. Live, only our own are known ("own"); "both" is the engine ceiling.
PENDING = os.environ.get("HASTY_REBUILD_PENDING", "")

SUB = realsim.SUB
SCRATCH = (9000, 4000)          # milli-tiles; units are spawned here first, never seen by trials


class Shadow:
    def __init__(self, src):
        self.src = src
        self.b = realsim.RealBattle()
        self.units_of = {}       # card id -> sorted unit names one spawn of it makes
        self.card_for = {}       # unit name -> card id that makes it
        self.key = None          # (battle id, tick) the shadow was last rebuilt for
        self.n_rebuilds = 0
        self.team_own = 0          # the searching seat (live: our side)

    # ---- unit name -> card -------------------------------------------------
    # A `spawn` lands 2 ticks after it is sent (measured 2026-11-22), and a card's
    # units appear at fixed offsets from the spawn point. _learn records both.
    APPEAR = 2

    def _spawn_line(self, team, card, x, y):
        b = self.b
        lvl = max(self.src.levels[team]) - 1
        return "spawn " + json.dumps({"ct": 153, "c": {"t": b.eng.t, "t2": b.eng.t, "idHi": 0,
                "idLo": team + 1, "px": int(x), "py": int(y), "sid": 0,
                "sel": {"os": b._eid(card), "pd": lvl << 10}}}, separators=(",", ":"))

    def _learn(self, cards):
        todo = [c for c in set(cards) if c not in self.units_of]
        if not todo:
            return
        b, src = self.b, self.src
        for c in todo:
            self.units_of[c] = {}
            for team in (0, 1):
                b.reset(seed=0, decks=[list(src.deck[0]), list(src.deck[1])], shuffle=0,
                        forms=src.forms, levels=src.levels)
                before = {o[6] for o in b.s["objects"]}
                py = 8000 if team == 0 else 24000
                b.eng._call(self._spawn_line(team, c, 9000, py))
                b.step([], n=self.APPEAR)
                b._sync()
                offs = [(o[0], o[2] - 9000, o[3] - py) for o in b.s["objects"]
                        if o[6] not in before and o[5] > 0 and b._tower_slot(o[0], o[2]) < 0]
                self.units_of[c][team] = offs
                for n, dx, dy in offs:
                    self.card_for.setdefault((n, team), (c, dx, dy))

    # ---- rebuild ---------------------------------------------------------------
    def rebuild(self):
        src = self.src
        key = (id(src.s), src.eng.t)
        if key == self.key:
            return
        self.key = key
        self._learn(src.deck[0] + src.deck[1])
        b = self.b
        b.reset(seed=src.eng.t, decks=[list(src.deck[0]), list(src.deck[1])], shuffle=0,
                forms=src.forms, levels=src.levels)
        want = [o for o in src.s["objects"] if o[1] in (0, 1) and o[5] > 0 and o[4] > 0
                and src._tower_slot(o[0], o[2]) < 0 and src._spell_card(o[0]) is None]
        # one spawn per live unit, placed so that unit's body lands on its spot
        before = {o[6] for o in b.s["objects"]}
        for name, owner, x, y, *_ in want:
            cf = self.card_for.get((name, owner))
            if cf is not None:
                c, dx, dy = cf
                b.eng._call(self._spawn_line(owner, c, x - dx, y - dy))
        b.step([], n=self.APPEAR)
        b._sync()
        new = [o for o in b.s["objects"] if o[6] not in before and o[5] > 0 and b._tower_slot(o[0], o[2]) < 0]
        used = set()
        gmap = {}                                  # source game id -> copy game id
        for w in want:
            name, owner, x, y, h = w[:5]
            cand = [o for o in new if o[6] not in used and o[0] == name and o[1] == owner]
            if not cand:
                continue
            o = min(cand, key=lambda o: (o[2] - x) ** 2 + (o[3] - y) ** 2)
            used.add(o[6])
            gmap[w[6]] = o[6]
            if DEPLOY:
                left = 0
                if len(w) > 8 and w[8] == 4:            # source still deploying: copy its timer
                    d = src.eng._call(f"objdump {w[6]}")
                    if isinstance(d, dict) and "w" in d:
                        left = max(0, int(d["w"][0x15c // 4]))
                b.eng._call(f"setdeploy {o[6]} {left}")
            if int(h) != o[4]:
                b.eng._call(f"sethp {o[6]} {int(h)}")
        for o in new:
            if o[6] not in used:
                b.eng._call(f"sethp {o[6]} 0")
        # towers
        hp_now, _ = src._towers()
        for name, owner, x, y, h, m, gid, *_ in b.s["objects"]:
            k = b._tower_slot(name, x)
            if k >= 0 and owner in (0, 1) and hp_now[owner][k] != h:
                b.eng._call(f"sethp {gid} {max(1, int(hp_now[owner][k])) if hp_now[owner][k] > 0 else 0}")
        if COMBAT:
            for name, owner, x, y, h, m, gid, *rest in b.s["objects"]:
                k = b._tower_slot(name, x)
                if k >= 0 and owner in (0, 1):
                    for so in src.s["objects"]:
                        if so[1] == owner and src._tower_slot(so[0], so[2]) == k:
                            gmap[so[6]] = gid
            for w in want:
                if w[6] in gmap and len(w) > 10:
                    tgt = w[9]
                    r = b.eng._call(f"setcombat {gmap[w[6]]} {int(w[10])} {gmap.get(tgt, -1) if tgt >= 0 else -1}")
                    self.n_setcombat = getattr(self, "n_setcombat", 0) + 1
                    if not (isinstance(r, dict) and r.get("ok")):
                        self.setcombat_err = r
        for t in (0, 1):
            b.eng._call(f"setelixir {t} {int(src._elixir_milli(t))}")
        if PENDING:
            teams = (0, 1) if PENDING == "both" else (self.team_own,)
            for team, tick, c, x, y in getattr(src, "inflight", []):
                if team in teams and tick > src.eng.t:
                    self.n_pending = getattr(self, "n_pending", 0) + 1
                    b.eng._call(self._play_spawn(team, c, x * SUB, y * SUB, b.eng.t + (tick - src.eng.t)))
        b._refresh()
        self.n_rebuilds += 1
        if os.environ.get("HASTY_REBUILD_DEBUG"):
            import sys
            print(f"rebuild t={src.eng.t} want={len(want)} matched={len(gmap) if COMBAT else '-'} "
                  f"setcombat={getattr(self, 'n_setcombat', 0)} err={getattr(self, 'setcombat_err', None)} "
                  f"sample={[w[:11] for w in want[:2]]}", file=sys.stderr, flush=True)

    def _play_spawn(self, team, card, x_sub, y_sub, tick):
        lvl = max(self.src.levels[team]) - 1
        return "spawn " + json.dumps({"ct": 153, "c": {"t": tick, "t2": tick, "idHi": 0, "idLo": team + 1,
                                      "px": int(x_sub / SUB), "py": int(y_sub / SUB), "sid": 0,
                                      "sel": {"os": self.b._eid(card), "pd": lvl << 10}}}, separators=(",", ":"))

    def try_wait(self, team, horizon, material, elixir, win):
        self.rebuild()
        b = self.b
        try:
            b.eng._call(f"try {int(horizon)} step 0")
            return b._score(b.eng.recv(), team, material, elixir, win, self.src.eng.t + int(horizon))
        except RuntimeError:
            return None

    def try_plays(self, team, hi, cells, horizon, material, elixir, win):
        src = self.src
        src._sync()
        ds = src._slot_at(team, hi)
        legal = [ds is not None and src.check_deploy(team, hi, x, y) == 0 for x, y in cells]
        if not any(legal):
            return [None] * len(cells)
        self.rebuild()
        b = self.b
        card = src.deck[team][ds]
        out = []
        for ok, (x_sub, y_sub) in zip(legal, cells):
            if not ok:
                out.append(None)
                continue
            try:
                b.eng._call(f"try {int(horizon)} {self._play_spawn(team, card, x_sub, y_sub, b.eng.t + src.delay[team])}")
                out.append(b._score(b.eng.recv(), team, material, elixir, win, src.eng.t + int(horizon)))
            except RuntimeError:
                out.append(None)
        return out
