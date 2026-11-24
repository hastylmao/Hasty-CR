"""Live shadow battle (2026-11-23, prototype, UNTESTED live).

Measured on 2026-11-23 (D:/crwork/shadow_test.py): the real engine replays a battle
exactly from its plays (33 of 33 checkpoints identical, any seed), and opponent plays
off by 1-2 ticks leave towers within a few hit points. So instead of rebuilding a live
board field by field (rebuild_search.py: projectiles, timers and buildings all lost),
the search can fork a shadow battle that has been fed every play as it happened.

    sh = LiveShadow(cat_ids, deck, forms, levels, opp_level=16)
    sh.play(team, card_id, x, y, exec_tick, form=0, level=None)   # ours: the tap's tick
                                                                  # theirs: first seen - APPEAR
    sh.advance(tick)            # step the shadow to the live tick
    drift = sh.compare(towers)  # tower hit points against the reader's
    scores = sh.search(team, slot_card, cells, horizon=160)       # fork, try each tile

Both sides' plays go in as engine `spawn` commands with the card's form bits, so the
shadow needs neither the opponent's deck nor anyone's elixir or hand order. Our own
elixir can be set from the reader (setelixir) before a search.

Open questions (to measure in the engine before live): whether a spawned play behaves
exactly like a card played from the hand (evolution counters, hero forms, King Tower
activation by spells); the exact tick offset between a unit first being seen by the
reader and its command tick; drift over a whole game.
"""
import json

import realsim          # puts vendor/re/headless on sys.path
import engine  # noqa: E402

SUB = realsim.SUB
APPEAR = 2          # a command lands 2 ticks after its tick (rebuild_search, measured)


_FS = None


def _fs_table(name):
    """(evo form id, hero form id) for any card (shadow_fs.json, built 2026-11-24 by
    dealing each card with each form in the training engine). A value that is the plain
    card id means the card has no such form."""
    global _FS
    if _FS is None:
        import os
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow_fs.json")) as f:
                _FS = json.load(f)
        except OSError:
            _FS = {}
    e, h = _FS.get(name, (None, None))
    return (e if e and e // 1000000 == 13 else None, h if h and h // 1000000 == 203 else None)


class LiveShadow:
    def __init__(self, deck, forms, levels, opp_level=16, tower_levels=(16, 16), own_side=0):
        self.b = realsim.RealBattle()
        self.levels = levels
        self._init = (list(deck), list(forms), list(levels), opp_level, list(tower_levels))
        self.own_side = own_side   # the reader's side value for us
        self.opp_level = opp_level
        # Form spell ids (2026-11-24): a hero or evolved play carries pd |= 2 / |= 1 and
        # "fs" = the form's spell id, read from the card in hand (realsim._sel). spawn sent
        # only the bits, so a Hero Electro Wizard came out as the base unit. Deal the deck
        # twice (cards 0-3, then 4-7 in hand) to read every card's ids once.
        self.fs = {}
        for rot in (0, 4):
            d = list(deck[rot:]) + list(deck[:rot])
            f = list(forms[rot:]) + list(forms[:rot])
            self.b.reset(seed=0, decks=[d, d], shuffle=0, forms=[f, f], levels=[levels, levels],
                         tower_levels=list(tower_levels))
            self.b._sync()
            for ds in range(8):
                pos = self.b.s["hands"][0][ds]
                if 0 <= pos <= 3:
                    hc = self.b.s["handcards"][0][pos]
                    self.fs[d[ds]] = (hc[3], hc[4])
        self.b.reset(seed=0, decks=[list(deck), list(deck)], shuffle=0, forms=[forms, forms],
                     levels=[levels, [opp_level] * 8], tower_levels=list(tower_levels))
        self.log = []
        self.events = []     # every play fed so far (for resync by replay)
        self.queue = []      # plays not yet due
        self.replay_late = True   # late plays: replay from the start (exact) instead of landing them now
        # Rebase (2026-11-24): replays start `window` ticks back from a tick whose live
        # tower hp is known, not from tick 0, so drift does not pile up for the whole game.
        self.window = None
        self.tower_hist = []      # (tick, towers [[king, left, right], ...]) read live

    @property
    def t(self):
        return self.b.eng.t

    def _spawn(self, team, card, x, y, tick, form, level):
        cost = self.b.cat[card][2]
        pd = engine.pd(0, level - 1, cost) | (form << 19)
        sel = {"os": self.b._eid(card), "pd": pd}
        evo_fs, hero_fs = self.fs.get(card, (None, None))
        if evo_fs is None and hero_fs is None:
            evo_fs, hero_fs = _fs_table(self.b.cat[card][0])
        if form == 1 and evo_fs is not None:
            sel["pd"] |= 1
            sel["fs"] = evo_fs
        elif form == 2 and hero_fs is not None:
            sel["pd"] |= 2
            sel["fs"] = hero_fs
        return "spawn " + json.dumps({"ct": 153, "c": {"t": int(tick), "t2": int(tick), "idHi": 0, "idLo": team + 1,
                                      "px": int(x), "py": int(y), "sid": 0, "sel": sel}}, separators=(",", ":"))

    def play(self, team, card, x, y, exec_tick, form=0, level=None, observed_tick=None):
        """Queue a play at engine coordinates (x, y in engine units) for exec_tick.

        The engine's `spawn` places a card NOW, ignoring the tick inside the command
        (loader_new.c spawn calls deploy with now(gm); Codex review 2026-11-23), so plays
        are held here and sent when the shadow reaches their tick (advance()). Every event
        is kept with its estimated and observed tick so a resync can replay from it."""
        lvl = level or (max(self.levels) if team == 0 else self.opp_level)
        ev = dict(team=team, card=card, x=int(x), y=int(y), tick=int(exec_tick), form=form, level=lvl,
                  observed=observed_tick)
        self.events.append(ev)
        if exec_tick <= self.t:
            self.log.append(("late", team, card, int(exec_tick), self.t))
            if self.replay_late:
                self.replay_to(self.t)          # exact: rebuild with the play at its true tick
            else:
                self._send(ev)
        else:
            self.queue.append(ev)
            self.queue.sort(key=lambda e: e["tick"])

    def ability(self, team, card, tick, observed_tick=None):
        """A hero ability press (command type 189) for `team`'s newest hero of `card`,
        executed at `tick`. Kept as an event, so replays repeat it."""
        ev = dict(team=team, card=card, x=0, y=0, tick=int(tick), form=2, level=0,
                  observed=observed_tick, ability=True)
        self.events.append(ev)
        if tick <= self.t:
            self.log.append(("late", team, card, int(tick), self.t))
            self.replay_to(self.t)
        else:
            self.queue.append(ev)
            self.queue.sort(key=lambda e: e["tick"])

    def _press(self, ev):
        self.b._sync()
        name = self.b.cat[ev["card"]][0].lower()
        cand = [o for o in self.b.s["objects"] if o[1] == ev["team"] and o[4] > 0
                and o[0].lower().startswith(name) and "hero" in o[0].lower()]
        if not cand:
            return
        u = max(cand, key=lambda o: o[6])
        t = self.t + 1
        try:
            self.b.eng._call("cmd " + json.dumps({"ct": 189, "c": {"t": t, "t2": t + 1, "idHi": 0,
                             "idLo": ev["team"] + 1, "cgid": u[6]}}))
        except RuntimeError:
            pass

    def _send(self, ev):
        if ev.get("ability"):
            return self._press(ev)
        self.b.eng._call(self._spawn(ev["team"], ev["card"], ev["x"], ev["y"], self.t, ev["form"], ev["level"]))

    def feed_projectile(self, pred, card_ids, lag=3):
        """A predicted flying Goblin Barrel / Rocket (projectile_predict.ProjectilePredictor)
        -> the opponent's play, aimed at the predicted landing point, issued at the tick the
        barrel was first seen minus `lag` (reader lag, UNVERIFIED here: units are first seen
        ~3 ticks after they appear). The engine then flies it exactly as the real game does.
        `card_ids`: card name -> engine catalogue id."""
        c = card_ids.get(pred["name"])
        if c is None:
            return False
        team = 1 if pred["side"] != self.own_side else 0
        if team == 0:
            return False                     # our own barrels are fed by play() already
        self.play(1, c, pred["x"], pred["y"], pred["seen_tick"] - lag, observed_tick=pred["seen_tick"])
        return True

    def advance(self, tick):
        """Step to `tick`, sending each queued play at its own tick."""
        while self.queue and self.queue[0]["tick"] < int(tick):
            ev = self.queue.pop(0)
            if ev["tick"] > self.t:
                self.b.step([], n=ev["tick"] - self.t)
                self.b._sync()             # step is asynchronous: eng.t updates on sync
            self._send(ev)
        n = int(tick) - self.t
        if n > 0:
            self.b.step([], n=n)
        self.b._sync()

    def compare(self, towers):
        """Sum of |shadow - live| tower hit points; towers = [[king, left, right], [...]]."""
        hp, _ = self.b._towers()
        return sum(abs(a - b) for s in (0, 1) for a, b in zip(hp[s], towers[s]))

    def set_elixir(self, team, milli):
        self.b.eng._call(f"setelixir {team} {int(milli)}")

    def search(self, team, hand_slot, cells, horizon=160, material=0.3):
        """Fork the shadow per candidate tile (realsim.try_plays) -> scores.

        KNOWN GAPS (Codex review 2026-11-23, to fix before live): plays still queued
        (not yet due) are not inside the forks; the candidate card comes from the shadow's
        hand, which spawn-fed plays do not cycle like the live hand; two-card defences
        (Skeletons then Ice Spirit) need a timed sequence per fork, not one command."""
        return self.b.try_plays(team, hand_slot, cells, horizon, material, 0.0, 0.0)


    def search_card(self, team, card, cells, horizon=160, material=0.3, delay=26, form=0, level=None):
        """Score playing `card` at each cell (engine units) in a forked copy of the shadow,
        `delay` ticks from now (the tap's command delay). The card comes from the caller
        (the live hand), not the shadow's hand, which spawn-fed plays never cycle. Uses the
        engine's `try <horizon> <command>` fork, as rebuild_search does. -> [score|None]."""
        lvl = level or (max(self.levels) if team == 0 else self.opp_level)
        b = self.b
        b._sync()
        end = self.t + int(horizon)
        out, own = [], []
        for x, y in cells:
            try:
                b.eng._call(f"try {int(horizon)} " + self._spawn(team, card, x, y, self.t + delay, form, lvl))
                st = b.eng.recv()
                out.append(b._score(st, team, material, 0.0, 0.0, end))
                keep, b.s = b.s, st
                try:
                    hp, mx = b._towers()
                finally:
                    b.s = keep
                # our own towers at the end, as a fraction (search_card.own): lets the caller
                # refuse a play that trades our tower hp for theirs
                own.append(sum(h / max(m, 1) for h, m in zip(hp[team], mx[team])))
            except RuntimeError:
                out.append(None)
                own.append(None)
        self.last_own = own
        return out


    def replay_to(self, tick):
        """Reset the shadow and replay every recorded play at its own tick up to `tick`
        (2026-11-24). Used when an opponent play is seen after the shadow passed its tick:
        the result is the game as if the play had been known in time. With `window`, the
        replay starts at the newest recorded tower reading at least `window` ticks back."""
        deck, forms, levels, opp_level, tl = self._init
        base, hp = 0, None
        if self.window:
            for t_, h_ in reversed(self.tower_hist):
                if t_ <= tick - self.window:
                    base, hp = t_, h_
                    break
        self.b.reset(seed=0, decks=[deck, deck], shuffle=0, forms=[forms, forms],
                     levels=[levels, [opp_level] * 8], tower_levels=tl, start_tick=base, tower_hp=hp)
        self.b._sync()
        pending = sorted([e for e in self.events if e["tick"] >= base], key=lambda e: e["tick"])
        self.queue = [e for e in pending if e["tick"] >= int(tick)]
        for ev in [e for e in pending if e["tick"] < int(tick)]:
            if ev["tick"] > self.t:
                self.b.step([], n=ev["tick"] - self.t)
                self.b._sync()             # step is asynchronous: eng.t updates on sync
            self._send(ev)
        n = int(tick) - self.t
        if n > 0:
            self.b.step([], n=n)
        self.b._sync()

    def sync_hp(self, units, towers):
        """Set shadow hit points to the live ones (engine `sethp`): towers by slot,
        units by same name and side, nearest within 2 tiles. units: [(name, side, x, y, hp)]."""
        self.b._sync()
        n = 0
        objs = [o for o in self.b.s["objects"] if o[4] > 0]
        alive = {(o[1], self.b._tower_slot(o[0], o[2])) for o in objs}
        self.tower_lost = [(t, k) for t in (0, 1) for k in range(3)
                           if towers[t][k] > 0 and (t, k) not in alive]
        used = set()
        for o in objs:
            name, owner, x, y, hp, mhp, gid = o[:7]
            k = self.b._tower_slot(name, x)
            if k >= 0:
                if owner in (0, 1) and towers[owner][k] != hp:
                    self.b.eng._call(f"sethp {gid} {int(towers[owner][k])}"); n += 1
                continue
            best, bd = None, 2000 ** 2
            for i, (nm, sd, ux, uy, uhp) in enumerate(units):
                if i in used or nm != name or sd != owner:
                    continue
                d = (ux - x) ** 2 + (uy - y) ** 2
                if d < bd:
                    best, bd = i, d
            if best is not None:
                used.add(best)
                uhp = units[best][4]
                if 0 < uhp != hp:
                    self.b.eng._call(f"sethp {gid} {int(uhp)}"); n += 1
            elif owner in (0, 1) and not any(sd == owner and ((ux - x) ** 2 + (uy - y) ** 2) < 3000 ** 2
                                             for nm, sd, ux, uy, uhp in units):
                # 2026-11-24 live: the shadow kept up to 16 troops the game no longer had
                # (fidelity shadow_units 16 vs live 0), and search played against them. A
                # shadow troop with no live body of its side within 3 tiles is removed.
                self.b.eng._call(f"sethp {gid} 0"); n += 1
                self.ghosts_removed = getattr(self, "ghosts_removed", 0) + 1
        self.b._sync()
        return n
