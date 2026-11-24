"""Live search through a shadow battle (2026-11-24, first live version, UNTESTED live).

The live bot (scripts/gamestate/live_play.py --shadow-search) keeps a copy of the
battle running in the real engine (shadow_live.LiveShadow). Every play either side
makes is fed into it from what the memory reader sees, and before each card play the
model's top tiles are tried in forks of that copy. The best tile is played if it beats
the model's own tile by more than `margin`; on any error, or when the copy has drifted
from the live towers, the model's tile is played as before.

Measured offline (D:/crwork/shadow_harness.py, 3 engine games, plays fed as a reader
would see them): mean tower difference 707 hp, first divergence 750-1200 ticks; search
on the copy picks the same best tile as search on the true game 43% of the time, with a
mean regret of 0.12 score. Search costs ~10 ms per tile at a 200-tick horizon.

How plays are read from reader frames (unit row u = [addr, ?, ?, side, x, y,
native card id, level - 1, hp, max hp, name, deploy ms, ...]), checked on
reports/live_play/20261122_200214.jsonl:
  * a troop or building play: a new body with deploy ms > 0. Bodies a card makes later
    (a Witch's skeletons) have deploy 0; a Skeleton Balloon's death skeletons do not,
    so a card's later bodies count only under the names its first play showed.
  * a spell: objects named *Spell; fed when the last of them is gone, at their mean
    last position, with the tick they were first seen. Goblin Barrel and Rocket come
    from projectile_predict (landing point predicted in flight).
  * a Log-like roller (*ProjectileRolling): at its first position.
Command tick = first seen - LAG. Ability presses are not fed (drift source, known).
"""
from __future__ import annotations

import os
import time

# The engine the league trains on (runs/league/league_split2/launch.sh): build 160635007
# with Hero Electro Wizard. Set before realsim / engine are imported.
for _k, _v in (("HASTY_ASSET_ROOT", "/root/assets_new_full/"),
               ("HASTY_LIBG", "../target/build_160635007/dump/libg_mem.so"),
               ("LOADER", "loader_new"), ("HASTY_UNIT_FALLBACK", "1"),
               ("HASTY_HERO_TEST", "ElectroWizard=2"), ("MSYS_NO_PATHCONV", "1")):
    os.environ.setdefault(_k, _v)

import realsim        # noqa: E402
import shadow_live    # noqa: E402
from projectile_predict import ProjectilePredictor, FLYING   # noqa: E402

LAG = 5               # reader first sight - command tick (harness: 3-5)
SKIP = ("Projectile", "Container", "AEO", "AeO", "Aeo", "Explosion", "Dummy", "appear")
TOWERS = ("KingTower", "PrincessTower")


def _base(name):
    return name.replace("_EV1", "").replace("Hero", "").replace("_rework", "")


class ShadowSearch:
    def __init__(self, deck_names, forms, levels=16, horizon=200, material=0.3, margin=0.0, own_tol=0.01,
                 k=12, our_delay=20, max_drift=3000, log=None):
        self.b0 = realsim.RealBattle()
        self.idx = {r[0]: i for i, r in enumerate(self.b0.cat)}
        self.deck = [self.idx[c] for c in deck_names]
        self.forms = list(forms)
        self.levels = [levels] * 8
        self.horizon, self.material, self.margin, self.k = horizon, material, margin, k
        self.our_delay, self.max_drift = our_delay, max_drift
        self.log = log or (lambda rec: None)
        self.sh = None
        self.side = 0
        self.hp_sync = True
        # Score per elixir spent, in princess towers (1.0 = a whole princess tower). 0.04:
        # 5 elixir = 0.2 tower = about 970 hp of a 4858 hp princess. UNVERIFIED first value.
        self.elixir_w = 0.04
        self.own_tol = own_tol      # 0.01 = 1% of one tower, ~49 hp of a princess
        self.k_other = 6            # tiles tried for each card the model did not pick
        self.window = 200      # replay base: 10 s back (best of 200/400/600/1000 on recordings)
        self.stats = dict(searches=0, changed=0, errors=0)

    # ---- battle lifetime -------------------------------------------------------
    def new_battle(self, side, frame):
        tl = [16, 16]
        for u in frame.get("u", []):
            if len(u) > 10 and u[10] == "KingTower" and u[3] in (0, 1):
                tl[0 if u[5] < 16000 else 1] = int(u[7]) + 1
        t0 = time.perf_counter()
        if self.sh is None:
            self.sh = shadow_live.LiveShadow(self.deck, self.forms, self.levels, opp_level=16,
                                             tower_levels=tl)
        else:
            self.sh._init = (list(self.deck), list(self.forms), list(self.levels), 16, list(tl))
            self.sh.events, self.sh.queue, self.sh.log = [], [], []
            self.sh.replay_to(0)
        # Engine team 0 owns low y, as RoyaleSim's (live_bridge.rs_state_from_frame):
        # which reader side that is comes from where our king stands.
        low = any(len(u) > 10 and u[10] == "KingTower" and u[3] == side and u[5] < 16000
                  for u in frame.get("u", []))
        self.team_of = {side: 0 if low else 1, 1 - side: 1 if low else 0}
        side = self.team_of[side]
        self.side = side
        # Our cards' level for the forks: the event's level (towers read level 11 in a
        # level-11 event, 2026-11-24); was a fixed 16, overrating our candidates.
        self.our_level = tl[side]
        self.sh.window = self.window
        self.sh.tower_hist = []
        self.last_sync = -10**9
        self.pp = ProjectilePredictor()
        self.known = {}             # addr -> name in the previous frame
        self.play_names = {}        # (side, card) -> base names of its first play's bodies
        self.spells = {}            # (side, card) -> dict(first, pos{addr: (x, y)}, last, form)
        self.opp_levels = []
        self.pressed = {}           # (side, card) -> tick of the last ability press fed
        self.broken = None          # reason the shadow is not trusted for the rest of the battle
        self.drift = 0
        self.last_check = 0
        self.log({"shadow": "new_battle", "side": side, "tower_levels": tl,
                  "ms": round(1000 * (time.perf_counter() - t0))})

    # ---- feeding ---------------------------------------------------------------
    def _card(self, u, card_of, cat):
        c = card_of(u)
        if c is None or c < 0:
            return None
        return self.idx.get(cat[c][0])

    def _form(self, u):
        nat, name = int(u[6]), u[10]
        if nat // 1000000 == 203 or "Hero" in name:
            return 2
        if nat // 1000000 == 13 or "_EV" in name:
            return 1
        return 0

    def _feed(self, team, card, x, y, tick, form, level, seen):
        for e in self.sh.events:      # several bodies of one play (Barbarians, Rascals) = one play
            if (not e.get("ability") and e["team"] == team and e["card"] == card and abs(e["tick"] - tick) <= 5
                    and abs(e["x"] - x) + abs(e["y"] - y) < 6000):
                return
        # a deck form the engine cannot load (a hero of a card without one) falls back to base
        if form == 1 and self.sh.fs.get(card, (None, None))[0] is None and team == self.side:
            form = 0
        self.sh.play(team, card, int(x), int(y), int(tick), form=form, level=level, observed_tick=seen)

    def observe(self, f, card_of, cat):
        """One reader frame. card_of(u) -> live catalogue id (live_play.card_of)."""
        if self.sh is None or self.broken:
            return
        now = int(f["t"])
        alive = set()
        cur = {}
        for u in f.get("u", []):
            if len(u) <= 11 or u[3] not in (0, 1):
                continue
            name = u[10] or ""
            if name in TOWERS:
                continue
            addr, side, x, y = u[0], self.team_of[u[3]], u[4], u[5]
            if "Spell" in name:
                if name in FLYING:
                    continue                      # Goblin Barrel / Rocket: projectile_predict
                c = self._card(u, card_of, cat)
                if c is None:
                    continue
                g = self.spells.setdefault((side, c), dict(first=now, pos={}, last=now, form=self._form(u)))
                g["pos"][addr] = (x, y)
                g["last"] = now
                alive.add(addr)
                continue
            cur[addr] = name
            if self.known.get(addr) == name:
                continue                          # seen last frame (addresses get reused)
            if int(u[6]) // 1000000 == 203 and any(a in name for a in ("Aeo", "AEO", "AeO")):
                c = self._card(u, card_of, cat)        # a hero ability's effect: its press
                if c is not None and now - self.pressed.get((side, c), -10**9) > 100:
                    self.pressed[(side, c)] = now
                    self.sh.ability(side, c, now - LAG, observed_tick=now)
                continue
            rolling = "ProjectileRolling" in name
            if not rolling and (any(s in name for s in SKIP) or not u[11]):
                continue
            c = self._card(u, card_of, cat)
            if c is None:
                continue
            key, bn = (side, c), _base(name)
            names = self.play_names.get(key)
            if names is None:
                self.play_names[key] = [now, {bn}]          # first play of this card
            elif now - names[0] <= 3:
                names[1].add(bn)                            # another body of the same play
            elif bn in names[1]:
                names[0] = now                              # a new play of the card
            else:
                continue                                    # a later body (death skeletons)
            lvl = int(u[7]) + 1 if 0 <= int(u[7]) < 20 else 16
            if side != self.side:
                self.opp_levels.append(lvl)
            self._feed(side, c, x, y, now - LAG, self._form(u), lvl, now)
        self.known = cur
        # live board summary for the fidelity check in choose_cards (units per engine team, towers)
        lu, lt = [0, 0], [[0, 0, 0], [0, 0, 0]]
        for u in f.get("u", []):
            if len(u) <= 10 or u[3] not in (0, 1):
                continue
            tm = self.team_of[u[3]]
            if u[10] in TOWERS:
                lt[tm][0 if u[10] == "KingTower" else (1 if u[4] < 9000 else 2)] = u[8]
            elif u[8] > 0 and u[9] > 0 and u[11] and "Projectile" not in u[10]:
                lu[tm] += 1
        self.live_board = (lu, lt)
        # spells whose objects are all gone: landed
        for key, g in list(self.spells.items()):
            if g["last"] < now:
                xs = [p[0] for p in g["pos"].values()]
                ys = [p[1] for p in g["pos"].values()]
                self._feed(key[0], key[1], sum(xs) / len(xs), sum(ys) / len(ys), g["first"] - LAG,
                           g["form"], self._opp_level() if key[0] != self.side else 16, g["first"])
                del self.spells[key]
        for p in self.pp.update(f):
            c = self.idx.get(p["name"])
            if c is not None:
                team = self.team_of.get(p["side"], p["side"])
                if not any(e["team"] == team and e["card"] == c and abs(e["tick"] - (p["seen_tick"] - LAG)) < 100
                           for e in self.sh.events):
                    self._feed(team, c, p["x"], p["y"], p["seen_tick"] - LAG, 0,
                               self._opp_level() if team != self.side else 16, p["seen_tick"])
                    # the goblins that come out later are this play, not a new one
                    self.play_names.setdefault((team, c), [now + 10**6, set()])
        self.sh.advance(now)

    def _opp_level(self):
        if not self.opp_levels:
            return 16
        return max(set(self.opp_levels), key=self.opp_levels.count)

    def sync(self, f, now, every=50):
        """Every `every` ticks: record the live towers (rebase points) and set shadow hp
        to the live hp (towers and matched units)."""
        if self.sh is None or self.broken or now - getattr(self, "last_sync", -10**9) < every:
            return
        self.last_sync = now
        towers = [[0, 0, 0], [0, 0, 0]]
        units = []
        for u in f.get("u", []):
            if len(u) <= 10 or u[3] not in (0, 1):
                continue
            if u[10] in TOWERS:
                k = 0 if u[10] == "KingTower" else (1 if u[4] < 9000 else 2)
                towers[self.team_of[u[3]]][k] = u[8]
            elif u[8] > 0 and u[9] > 0 and "Projectile" not in u[10]:
                units.append((u[10], self.team_of[u[3]], u[4], u[5], u[8]))
        self.sh.tower_hist.append((now, towers))
        if self.hp_sync:
            self.sh.sync_hp(units, towers)
            if self.sh.tower_lost:          # shadow destroyed a tower that stands live
                self.sh.replay_to(now)
                self.sh.sync_hp(units, towers)
                self.rebuilds = getattr(self, "rebuilds", 0) + 1
        return towers

    def check_towers(self, now, towers):
        """towers[team] = [king, left, right] live hit points, in engine team order."""
        if self.sh is None or self.broken or now - self.last_check < 100:
            return
        self.last_check = now
        self.drift = self.sh.compare(towers)
        rec = {"shadow": "drift", "t": now, "tower_diff": self.drift, "events": len(self.sh.events)}
        if self.drift > self.max_drift:
            self.broken = f"tower drift {self.drift}"
            rec["off"] = self.broken
        self.log(rec)

    # ---- search ----------------------------------------------------------------
    BUILDINGS = {"FirespiritHut", "Furnace", "GoblinHut", "BarbarianHut", "Mortar", "XBow", "Cannon", "Tesla",
                 "InfernoTower", "BombTower", "Tombstone", "ElixirCollector", "GoblinCage", "GoblinDrill"}

    def choose_cards(self, team, options, now, spendable):
        """Compare cards and tiles. options: [(slot, card_name, form, cost, cands)], the
        model's own card FIRST with its tiles best first; cands = [(tile, wx, wy)].
        Each fork is scored as in choose(), minus `elixir_w` per elixir spent. Elixir that
        would be wasted at the 10 cap costs nothing (spendable over 10 after the cost).
        -> (option index, tile index, info). (0, 0) = the model's play."""
        info = {"shadow": "search", "t": now}
        if self.sh is None or self.broken:
            info["skip"] = self.broken or "no shadow"
            return 0, 0, info
        t0 = time.perf_counter()
        # 2026-11-24 live: search swapped the model's Firespirit Hut for another card 7 of 8
        # times. A 200-tick fork sees a building's cost but little of its value (spawns over
        # its lifetime, and the passive fork opponent never attacks it). When the model picks
        # a building, only its placement is searched.
        if options and options[0][1] in self.BUILDINGS:
            options = options[:1]
            info["building"] = options[0][1]
        best, base, base_own, rows, cand = None, None, None, [], []
        for oi, (slot, name, form, cost, cands) in enumerate(options):
            c = self.idx.get(name)
            if c is None:
                continue
            k = self.k if oi == 0 else self.k_other
            try:
                sc = self.sh.search_card(team, c, [(wx, wy) for _, wx, wy in cands[:k]], self.horizon,
                                         self.material, delay=self.our_delay, form=form, level=getattr(self, "our_level", 16))
            except Exception as ex:
                self.stats["errors"] += 1
                info["error"] = f"{type(ex).__name__}: {ex}"[:200]
                continue
            # elixir past the cap is lost anyway: only the part that would have been kept counts
            overflow = max(0.0, (spendable + self.our_delay * 1000 / 56) / 1000 - 10)   # 1 elixir per 56 ticks
            pay = max(0.0, cost - overflow)
            own = list(getattr(self.sh, "last_own", [None] * len(sc)))
            row = {"card": name, "cost": cost, "tiles": [t for t, _, _ in cands[:k]],
                   "scores": [None if v is None else round(v, 3) for v in sc],
                   "own": [None if v is None else round(v, 3) for v in own]}
            rows.append(row)
            for ti, v in enumerate(sc):
                if v is None:
                    continue
                adj = v - self.elixir_w * pay
                if oi == 0 and ti == 0:
                    base, base_own = adj, own[ti]
                cand.append((adj, oi, ti, own[ti]))
        # 2026-11-24 live: with the opponent passive in the fork and their towers counted
        # like ours, a counter-push on the other lane outscored defending a Skeleton Balloon
        # (t 234, 1197, 1828). An override must leave our own towers no worse than the
        # model's play does (within own_tol of a tower).
        for adj, oi, ti, ow in cand:
            if base is not None and (oi, ti) != (0, 0):
                if ow is None or base_own is None or ow < base_own - self.own_tol:
                    continue
            if best is None or adj > best[0]:
                best = (adj, oi, ti)
        info["ms"] = round(1000 * (time.perf_counter() - t0))
        info["options"] = rows
        try:
            lb = getattr(self, "live_board", None)
            hp, _ = self.sh.b._towers()
            su = [sum(1 for o in self.sh.b.s["objects"] if o[1] == t and o[4] > 0 and o[5] > 0
                      and self.sh.b._tower_slot(o[0], o[2]) < 0 and "Projectile" not in o[0]) for t in (0, 1)]
            info["fidelity"] = {"shadow_units": su, "live_units": lb[0] if lb else None,
                                "tower_diff": sum(abs(a - b) for t in (0, 1) for a, b in zip(hp[t], lb[1][t])) if lb else None}
        except Exception:
            pass
        self.stats["searches"] += 1
        if base is None or best is None:
            info["skip"] = "model play not scored"
            return 0, 0, info
        info["base"], info["best"] = round(base, 3), round(best[0], 3)
        if (best[1], best[2]) != (0, 0) and best[0] - base > self.margin:
            self.stats["changed"] += 1
            info["chosen"] = [best[1], best[2]]
            return best[1], best[2], info
        info["chosen"] = [0, 0]
        return 0, 0, info

    def choose(self, team, card_name, form, cands, now):
        """cands: [(tile, wx, wy)] in model order (best first), world millitiles.
        -> (index into cands, info dict). Index 0 = the model's tile."""
        info = {"shadow": "search", "t": now, "card": card_name}
        if self.sh is None or self.broken:
            info["skip"] = self.broken or "no shadow"
            return 0, info
        c = self.idx.get(card_name)
        if c is None:
            info["skip"] = "card not in engine"
            return 0, info
        t0 = time.perf_counter()
        try:
            cells = [(wx, wy) for _, wx, wy in cands[:self.k]]
            sc = self.sh.search_card(team, c, cells, self.horizon, self.material, delay=self.our_delay,
                                     form=form, level=16)
        except Exception as ex:
            self.stats["errors"] += 1
            info["error"] = f"{type(ex).__name__}: {ex}"[:200]
            return 0, info
        info["ms"] = round(1000 * (time.perf_counter() - t0))
        info["scores"] = [None if v is None else round(v, 3) for v in sc]
        info["tiles"] = [t for t, _, _ in cands[:self.k]]
        self.stats["searches"] += 1
        if sc[0] is None or not any(v is not None for v in sc):
            info["skip"] = "model tile not scored"
            return 0, info
        best = max((i for i, v in enumerate(sc) if v is not None), key=lambda i: sc[i])
        if best != 0 and sc[best] - sc[0] > self.margin:
            self.stats["changed"] += 1
            info["chosen"] = best
            return best, info
        info["chosen"] = 0
        return 0, info
