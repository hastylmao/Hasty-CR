"""League checkpoint in the live loop (scripts/gamestate/live_play.py).

Same observation as training (league.obs.build on the bridge's state), same
sampling (league.model.gate_logq with the ticks since the last decision), and
ability presses. The memory reader does not read the ability buttons yet, so
their state is derived from the board: a button is available while our hero
of that card stands, and spent once we pressed it for that body. UNVERIFIED:
whether every hero's charge works this way, and the button screen positions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]

from league import obs as OBS          # noqa: E402
from league.model import LeaguePolicy, gate_logq   # noqa: E402

# Screen centres of the ability buttons, 1080x1920. The first hero on the field has
# its button bottom RIGHT, just above the hand; a second hero placed later gets the
# mirrored spot bottom left (owner, 2026-11-13). Right centre read off the owner's
# screenshot of that day (Hero Ice Wizard, one hero): about (972, 1455). The left
# one is its mirror, not seen on a screenshot: UNVERIFIED. Until 2026-11-13 this
# was the wrong way round ((100, 1470) first), so a single hero's button was never
# hit: the 19 taps of the first live games landed on empty ground.
BUTTON_PX = ((972, 1455), (108, 1455))
# Hero unit name and ability cost per card, for the buttons derived from the board.
HERO_UNIT = {"Musketeer": ("MusketeerHero", 3), "IceGolemite": ("IceGolemiteHero", 2),
             "Knight": ("KnightHero", 2), "Giant": ("GiantHero", 2),
             "MiniPekka": ("MiniPekkaHero", 2),
             # live_bridge.UNIT_ALIASES names the hero, its floating cube and the ice cube
             # all "IceWizard" (RoyaleSim has no unit type for them). Cost 2: the engine's
             # ManaCost. UNVERIFIED live (added 2026-11-12, no live game yet).
             "IceWizard": ("IceWizard", 2),
             # Hero Electro Wizard (Giant Skeleton bait, 2026-11-23). The live bridge maps
             # hero bodies to the base name by suffix fallback, as for Ice Wizard. Cost 2
             # (electro_wizard_hero.toml ManaCost). UNVERIFIED live: no live game yet.
             "ElectroWizard": ("ElectroWizard", 2)}


def is_league(path):
    import torch
    blob = torch.load(path, map_location="cpu", weights_only=False)
    return bool(blob.get("meta", {}).get("league")), blob


class LeagueLive:
    def __init__(self, blob, unit_names, deck_names, hero_cards, seed=0, gate_temp=0.1):
        import torch
        torch.set_num_threads(2)
        self.torch = torch
        m = blob["meta"]
        self.net = LeaguePolicy(m["n_cards"], m["n_units"], d=m["d"], layers=m["layers"], heads=m["heads"], obs_v=m.get("obs_v", 1))
        self.net.load_state_dict(blob["model"])
        self.net.eval()
        self.unit_tok = np.arange(len(unit_names), dtype=np.int64) + 2
        self.rng = np.random.default_rng(seed)
        # Near-greedy play/wait/card choice. Measured 2026-10-14 on v8 snap 70,
        # 300 sim games each: T 1.0 74%, 0.3 83%, 0.1 87% (as ClashAI found:
        # a sampled gate costs ~20 pp).
        self.gate_temp = gate_temp
        # Buttons in deck order of the hero cards, as the engine orders them.
        self.hero_cards = list(hero_cards)
        self.buttons = [c for c in deck_names if c in hero_cards]
        # 2026-11-23: deck_names comes from deck_order.json, which the bot itself rewrites
        # and which once held a stale mix without Electro Wizard: the button list was then
        # empty for a whole session. --heroes says the card is in the deck, so use it.
        if not self.buttons:
            self.buttons = list(self.hero_cards)
        print(f"hero buttons: {self.buttons} (deck {list(deck_names)})", flush=True)
        self.legal_cache = {}
        self.reset()

    def legal_tiles(self, team, card, players, sub):
        """Own-frame tiles where `card` may go, from the engine's territory
        rule given which crown towers are down - the same check training
        uses, so the pocket after a fallen princess is offered live too."""
        import royalesim
        down = tuple(tuple(int(h <= 0) for h in players[t]["tower_hp"]) for t in (0, 1))
        key = (team, card, down)
        if key not in self.legal_cache:
            b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
            filler = [c for c in range(8) if c != card][:7]
            # A king at 0 hp (the match is ending) cannot be reset; territory
            # depends only on the princesses, so keep the king standing here.
            hp = [[(full if k == 0 else 0) if d else full
                   for k, (d, full) in enumerate(zip(down[t], (7728, 4858, 4858)))] for t in (0, 1)]
            legal = np.zeros(576, bool)
            try:
                b.reset(seed=0, decks=[[card] + filler, [card] + filler], shuffle=0, start_tick=2000,
                        elixir_milli=[10000, 10000], tower_hp=hp, spawns=[])
                for t in range(576):
                    ox, oy = (t % 18) * 1000 + 500, (t // 18) * 1000 + 500
                    wx, wy = (ox, 32_000 - oy) if team == 0 else (18_000 - ox, oy)
                    legal[t] = b.check_deploy(team, 0, wx * sub, wy * sub) == 0
            except Exception:
                # Never let a legality check stop the bot mid-match (2026-10-14:
                # a 0-hp king crashed it): our own half, spells anywhere.
                legal[17 * 18:] = True
            self.legal_cache[key] = legal
        return self.legal_cache[key]

    def reset(self):
        self.spell_hist = {}
        self.tracker = OBS.Tracker()
        self.spent_for = {}           # button -> uid of the hero body it was used on

    def spell_rows(self, seen, tick):
        """Reader spell objects -> RoyaleSim-shaped spell rows. The engine
        gives each spell's aim; the reader does not, so the aim is the
        position carried on along its last ~10 ticks of movement (only the
        direction is used). A spell that has not moved (a Poison) has none."""
        rows, alive = [], set()
        for addr, team, card, x, y in seen:
            alive.add(addr)
            h = self.spell_hist.setdefault(addr, [])
            h.append((tick, x, y))
            while len(h) > 2 and tick - h[1][0] >= 10:
                h.pop(0)
            (t0, x0, y0) = h[0]
            ax, ay = (x + (x - x0) * 10, y + (y - y0) * 10) if tick > t0 else (x, y)
            rows.append([team, card, 0, x, y, ax, ay, 0, 0, 0, 0, 0])
        for a in [a for a in self.spell_hist if a not in alive]:
            del self.spell_hist[a]
        return rows

    def hero_rows(self, state, team, names, F):
        """Ability rows like the engine's: [available, spent, cost, card, cooldown]."""
        rows, uids = [], []
        for k, card in enumerate(self.buttons[:OBS.N_BUTTONS]):
            unit, cost = HERO_UNIT.get(card, ("", 2))
            body = next((e for e in state["entities"] if e[F["team"]] == team and e[F["hp"]] > 0
                         and 0 <= e[F["unit_type"]] < len(names) and names[e[F["unit_type"]]] == unit), None)
            uid = body[F["uid"]] if body is not None else None
            if card == "IceWizard":
                # Several bodies carry the name (hero, cubes), so a uid cannot mark the
                # use: one press per deploy, cleared when no such body is left.
                if uid is None:
                    self.spent_for.pop(k, None)
                spent = uid is not None and k in self.spent_for
            else:
                spent = uid is not None and self.spent_for.get(k) == uid
            rows.append([1 if (uid is not None and not spent) else 0, 1 if spent else 0, cost, 0, 0])
            uids.append(uid)
        return rows, uids

    def decide(self, state, team, mem, tick, dt, sub, blocked, spendable, names, cat):
        """-> dict(kind='wait'|'card'|'button', slot, tile, k, p_wait)."""
        torch = self.torch
        F = OBS.F
        self.tracker.update(state["entities"], tick, sub)
        p = state["players"][team]
        rows, uids = self.hero_rows(state, team, names, F)
        # Hero button debug (2026-11-23): live, Hero Electro Wizard's button was never
        # offered although an offline replay of a recorded frame offers it. Every 100
        # ticks while a button is unavailable, log what our own bodies are.
        bucket = int(tick) // 100
        if self.buttons and bucket != getattr(self, "_dbg_bucket", None):
            self._dbg_bucket = bucket
            try:
                own = sorted({(names[e[F["unit_type"]]] if 0 <= e[F["unit_type"]] < len(names) else e[F["unit_type"]],
                               int(e[F["hp"]] > 0)) for e in state["entities"] if e[F["team"]] == team})
                with open(ROOT / "reports" / "live_play" / "hero_debug.log", "a") as f:
                    f.write(json.dumps({"tick": int(tick), "team": int(team), "buttons": list(self.buttons),
                                        "rows": [[int(v) for v in r] for r in rows],
                                        "own": [[str(a), int(b)] for a, b in own]}) + "\n")
            except Exception as ex:          # never let debug logging stop play
                try:
                    with open(ROOT / "reports" / "live_play" / "hero_debug.log", "a") as f:
                        f.write(f"debug error: {type(ex).__name__}: {ex}\n")
                except Exception:
                    pass
        # Elixir as training shows it: realsim.elixir() holds back the cost of plays
        # still in flight (the 26-tick command delay). Live passed the raw bank, so
        # right after a play the model saw elixir it had already spent and nothing of
        # the play itself, and could commit a second card to the same target
        # (Goblin Gang + Rascals on one Princess, 2026-11-18 log 20261118_191137).
        p = dict(p, abilities=rows, elixir_milli=max(0, spendable))
        st = dict(state, players=[p if i == team else state["players"][i] for i in (0, 1)],
                  spells=self.spell_rows(state.get("spells_seen") or [], tick))
        o = OBS.build(st, team, mem, tick, self.tracker, self.unit_tok, sub, obs_v=self.net.obs_v)
        mask = np.zeros(7, bool)
        mask[0] = True
        for s in range(4):
            if s < len(p["hand"]) and s not in blocked and spendable >= p["hand_costs"][s] * 1000:
                mask[1 + s] = True
        for k, r in enumerate(rows):
            if r[0] and spendable >= r[2] * 1000:
                mask[5 + k] = True
        b = {k: torch.as_tensor(o[k][None]) for k in OBS.KEYS}
        with torch.no_grad():
            gate, cls, _ = self.net.heads(b)
            lq = gate_logq(gate / self.gate_temp, torch.as_tensor(mask[None]), max(1, dt))[0].numpy()
        pr = np.exp(lq - lq.max())
        pr /= pr.sum()
        a = int(self.rng.choice(7, p=pr))
        out = dict(kind="wait", p_wait=float(pr[0]), mask=mask.tolist())
        if a == 0:
            return out
        if a >= 5:
            k = a - 5
            self.spent_for[k] = uids[k]
            return dict(out, kind="button", k=k, card=self.buttons[k])
        slot = a - 1
        card = p["hand"][slot]
        with torch.no_grad():
            tl = self.net.tile_logits(cls, torch.as_tensor([card + 2]))[0].numpy()
        legal = self.legal_tiles(team, card, state["players"], sub)
        tl = np.where(legal, tl, -1e9)
        # Legal tiles best first, for the shadow search (shadow_search.py) to re-rank.
        order = [int(t) for t in np.argsort(-tl)[:24] if legal[t]]
        # The other playable cards' best tiles too (2026-11-24): the search compares cards
        # by result minus elixir spent, so a cheap card that holds can replace a dear one.
        orders = {slot: order}
        for s2 in range(4):
            if s2 == slot or not mask[1 + s2]:
                continue
            c2 = p["hand"][s2]
            with torch.no_grad():
                tl2 = self.net.tile_logits(cls, torch.as_tensor([c2 + 2]))[0].numpy()
            lg2 = self.legal_tiles(team, c2, state["players"], sub)
            tl2 = np.where(lg2, tl2, -1e9)
            orders[s2] = [int(t) for t in np.argsort(-tl2)[:24] if lg2[t]]
        return dict(out, kind="card", slot=slot, tile=int(np.argmax(tl)), order=order, orders=orders)
