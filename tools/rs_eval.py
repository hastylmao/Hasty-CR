"""Ghost screen in RoyaleSim: a token-policy checkpoint plays the Hog 2.6 side
of held-out recorded matches while the other side replays what the real
opponent did, tick for tick.

    .venvs/royalegym/Scripts/python.exe tools/rs_eval.py --ckpt runs/tokens/rs_bc/best.pt \
        --matches 300 [--search]

Two numbers per run, on the same matches:
* `pro`: the recorded Hog player's own plays replayed against the same ghost.
  This is what the real player achieves in this engine - the bar.
* `agent`: the checkpoint in that seat.

Matches come from the test split (hash of the tag, as the row builders use),
so no training row ever came from them. The ghost cannot react - it plays the
recorded commands even when the board has changed - which flatters an agent
that disrupts a scripted push; the `pro` row is measured the same way, so the
comparison between the two is fair even if both numbers are optimistic.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from statistics import mode

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import rs_rows as RR  # noqa: E402
from royalesim_redrive import CORPUS, base_key, deal_order  # noqa: E402

DECIDE = 10           # ticks between agent decisions (0.5 s)


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def to_world(ox, oy, team):
    """Acting player's own frame (millitiles) -> RoyaleSim world millitiles."""
    return (ox, 32_000 - oy) if team == 0 else (18_000 - ox, oy)


class RSAgent:
    lead = 0      # ticks to look ahead before deciding (delay compensation)

    _CAT = None

    def cat_kind(self, card):
        if RSAgent._CAT is None:
            import royalesim
            RSAgent._CAT = json.loads(royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
                                      .catalogue_json())
        return RSAgent._CAT[card][8]

    def aim_spell(self, order, state, team, card, sub, top=5):
        """Among the model's top tiles for a spell, the one whose radius holds
        the most enemy hit points on the visible board. The model picks the
        spell and the neighbourhood; this only corrects the aim. Public only."""
        F = RR.F
        radius = (RSAgent._CAT[card][4] or 2500) / 1000          # tiles
        enemies = [(e[F["x"]] / sub / 1000, e[F["y"]] / sub / 1000, e[F["hp"]])
                   for e in state["entities"] if e[F["team"]] != team and e[F["hp"]] > 0]
        if not enemies:
            return order
        best, best_hp = None, 0.0
        for t in order[:top]:
            tx, ty = int(t % 18), int(t // 18)
            wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
            wx, wy = wx / 1000, wy / 1000
            hp = sum(h for ex, ey, h in enemies if (ex - wx) ** 2 + (ey - wy) ** 2 <= radius ** 2)
            if hp > best_hp:
                best, best_hp = t, hp
        if best is None:
            return order
        return np.concatenate([[best], [t for t in order if t != best]])

    def ahead(self, battle, state):
        """The board `lead` ticks from now, with nothing new played.

        A play sent now lands ~21 ticks later, so the board worth deciding on
        is that one, not the present. Pending plays (ours) execute in the
        copy, which is what they will do. Live, the same is done on a rebuilt
        battle; here the engine's own copy is used.
        """
        if not self.lead:
            return state
        if getattr(self, "shadow", None) is not None:
            # The live-capable path: look ahead on the shadow re-drive, with our
            # own pending plays issued at the ticks they will execute.
            now = state["tick"]
            sim = self.shadow.battle(now)
            saved = sim.save()
            pend = sorted(self.shadow.pending_own(now))
            t = now
            for (te, team, card, x, y) in pend:
                if te >= now + self.lead:
                    break
                if te > t:
                    sim.step([], te - t)
                    t = te
                st = json.loads(sim.state_json())
                hand = st["players"][team]["hand"]
                if card in hand:
                    sim.step([(team, hand.index(card), x, y)], 1)
                    t += 1
            shadow_now = json.loads(sim.state_json())
            if now + self.lead > t:
                sim.step([], now + self.lead - t)
            future = json.loads(sim.state_json())
            sim.load(saved)
            # The shadow drifts over a match (opponent plays seen late, a few
            # refused), so its towers are not trusted outright: the view keeps
            # the REAL tower hit points plus only the change the shadow
            # predicts over the look-ahead.
            for k in (0, 1):
                real = state["players"][k]["tower_hp"]
                a = shadow_now["players"][k]["tower_hp"]
                z = future["players"][k]["tower_hp"]
                future["players"][k]["tower_hp"] = [max(0, r - max(0, x - y))
                                                    for r, x, y in zip(real, a, z)]
                future["players"][k]["tower_max_hp"] = state["players"][k]["tower_max_hp"]
            for k in (0, 1):
                for key in ("hand", "hand_costs", "elixir_milli", "deck", "next_card"):
                    future["players"][k][key] = state["players"][k].get(key, future["players"][k].get(key))
            return future
        if getattr(self, "lead_extrapolate", False):
            # Public dead reckoning: each unit moves on by its own velocity over
            # the last decision interval. No engine, nothing hidden; units that
            # stop to attack overshoot, new units are not predicted.
            F = RR.F
            prev = getattr(self, "_prev", {})
            dt = max(1, state["tick"] - getattr(self, "_prev_tick", state["tick"] - DECIDE))
            future = json.loads(json.dumps(state))
            for e in future["entities"]:
                uid = e[F["uid"]]
                if e[F["tower_slot"]] < 0 and uid in prev:
                    px, py = prev[uid]
                    e[F["x"]] = int(e[F["x"]] + (e[F["x"]] - px) * self.lead / dt)
                    e[F["y"]] = int(e[F["y"]] + (e[F["y"]] - py) * self.lead / dt)
            self._prev = {e[F["uid"]]: (e[F["x"]], e[F["y"]]) for e in state["entities"]}
            self._prev_tick = state["tick"]
            return future
        if getattr(self, "lead_rebuild", False):
            if getattr(self, 'memory_observation', False):
                # Match the memory bridge's measured-board fallback for heroes
                # and child forms. Rebuilding them as base cards loses abilities.
                names = _unit_names()
                if any('Hero' in names[e[27]] or names[e[27]]=='MusketeerTurret'
                       for e in state['entities'] if 0<=e[27]<len(names)):
                    return state
            if state.get("unmodelled_forms"):
                # Keep measured bodies that the reset API cannot restore exactly.
                return state
            # The live case: only what a player can see is carried forward, so
            # nothing hidden can leak into the view. Our own plays still in
            # flight are known to us and are replayed at the ticks they land;
            # leaving them out made the agent play again on top of them.
            import royalesim
            now = state["tick"]
            pend = [p for p in getattr(self, "sent", []) if p[0] > now]
            sim = self.rebuilt(state, self._team, royalesim,
                               first=[c for (_, c, _, _) in pend])
            if sim is None:
                return state
            t = now
            for (te, card, x, y) in sorted(pend):
                if te >= now + self.lead:
                    break
                if te > t:
                    sim.step([], te - t)
                    t = te
                hand = json.loads(sim.state_json())["players"][self._team]["hand"]
                if card in hand:
                    sim.step([(self._team, hand.index(card), x, y)], 1)
                    t += 1
            if now + self.lead > t:
                sim.step([], now + self.lead - t)
            future = json.loads(sim.state_json())
            for t in (0, 1):
                # A reset's default tower maximum can differ from live tower
                # levels. Preserve measured maxima for normalized model input.
                future['players'][t]['tower_max_hp'] = state['players'][t]['tower_max_hp']
                future["players"][t]["hand"] = state["players"][t]["hand"]
                future["players"][t]["hand_costs"] = state["players"][t]["hand_costs"]
                future["players"][t]["elixir_milli"] = state["players"][t]["elixir_milli"]
                future["players"][t]["deck"] = state["players"][t]["deck"]
                future["players"][t]["next_card"] = state["players"][t].get("next_card", -1)
            return future
        saved = battle.save()
        battle.step([], self.lead)
        future = json.loads(battle.state_json())
        battle.load(saved)
        # No peeking: the copy also lands the OPPONENT's pending plays, which a
        # real player cannot see until they appear. Drop every unit that does
        # not exist now unless it is ours (our own pending plays are known to
        # us). Residual leak: an enemy spell landing inside the window still
        # changes hit points in the view; measured separately by --rebuild.
        F = RR.F
        now = {e[F["uid"]] for e in state["entities"]}
        team = self._team
        future["entities"] = [e for e in future["entities"]
                              if e[F["uid"]] in now or e[F["team"]] == team]
        # Keep the present hand and elixir: the decision is about what we can
        # tap now; only the board is advanced.
        for t in (0, 1):
            future["players"][t]["hand"] = state["players"][t]["hand"]
            future["players"][t]["hand_costs"] = state["players"][t]["hand_costs"]
            future["players"][t]["elixir_milli"] = state["players"][t]["elixir_milli"]
        return future

    def rebuilt(self, state, team, royalesim, first=()):
        """A fresh Battle holding only what a player can see - the live case.

        Units as single spawns (card, team, position, hit points), tower hit
        points, the clock, our own deck in hand-then-queue order and our own
        elixir. The opponent's elixir is unknown and set to 0 (it makes no plays
        in the lookahead anyway). Lost: spells and projectiles in flight, attack
        timers, targets, deploy timers - which is exactly what this measures.
        """
        F = RR.F
        me = state["players"][team]
        deck = list(me["deck"])
        hand = list(me["hand"])
        nxt = me.get("next_card", -1)
        hand = [c for c in hand if c >= 0 and c not in first]
        lead_cards = [c for c in first if c in deck]
        rest = [c for c in deck if c not in hand and c != nxt and c not in lead_cards]
        mine = lead_cards + hand + ([nxt] if nxt >= 0 and nxt not in lead_cards else []) + rest
        # dedupe while keeping order, then pad to the deck
        seen_c, ordered = set(), []
        for c in mine + deck:
            if c not in seen_c:
                seen_c.add(c)
                ordered.append(c)
        mine = ordered[:8]
        opp = state["players"][1 - team]["deck"]
        spawns = []
        prim, by_unit = _spawn_tables()
        for e in state["entities"]:
            if e[F["tower_slot"]] >= 0 or e[F["hp"]] <= 0:
                continue
            # A unit reports the card that made it, so a Witch's skeleton
            # would be rebuilt as a Witch. Rebuild it as the card whose own
            # unit it is; skip a unit no card produces.
            card, unit = e[F["card_id"]], e[F["unit_type"]]
            if prim.get(card) != unit:
                # An evolved or hero form of the card's own unit (Skeleton_EV1,
                # MusketeerHero, IceGolemiteHero) is the card itself, not a
                # child. Treating forms as children dropped every evolved or
                # hero unit from the rebuild: 98.5% of the units it lost.
                names_ = _unit_names()
                base_name = names_[prim[card]].lower() if card in prim else ""
                if base_name and names_[unit].lower().startswith(base_name):
                    pass
                else:
                    card = by_unit.get(unit)
                    if card is None:
                        continue
            spawns.append((e[F["team"]], card, e[F["x"]], e[F["y"]], e[F["hp"]]))
        b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
        decks = [None, None]
        decks[team], decks[1 - team] = mine[:8], list(opp)[:8]
        elixir = [0, 0]
        elixir[team] = me["elixir_milli"]
        towers = [state["players"][t]["tower_hp"] for t in (0, 1)]
        try:
            b.reset(seed=0, decks=decks, shuffle=0, start_tick=state["tick"],
                    elixir_milli=elixir, tower_hp=towers, spawns=spawns)
        except Exception as exc:
            self.rebuild_error = f"{type(exc).__name__}: {exc}"
            return None
        return b

    def __init__(self, ckpt, seed=0, wait_keep=0.35):
        import torch
        torch.set_num_threads(1)
        from sim.model_tokens import TokenPolicy
        blob = torch.load(ckpt, map_location="cpu")
        meta = blob["meta"]
        self.unit_token_map = None
        if not meta.get("live_compat", False) and meta.get("units"):
            self.unit_token_map = np.asarray([0, 1] +
                [meta["units"].get(name, 0) for name in _unit_names()], dtype=np.int64)
        if meta.get("cards"):
            import royalesim
            catalogue = json.loads(royalesim.Battle(card_names=None, slot_of_k=[[0,1,2],[0,1,2]]).catalogue_json())
            for name, token in meta["cards"].items():
                if token-2 >= len(catalogue) or catalogue[token-2][0] != name:
                    raise ValueError(f"checkpoint card vocabulary mismatch: {name}")
        self.torch = torch
        self.model = TokenPolicy(meta["n_cards"], meta["n_units"], d=meta.get("d", 192),
                                 layers=meta.get("layers", 4), heads=meta.get("heads", 6)).eval()
        self.model.load_state_dict(blob["model"])
        # A live-compatible checkpoint was trained on card-id unit tokens.
        self.live = bool(meta.get("live_compat", False))
        self.memory_observation = bool(meta.get('memory_observation', False))
        self.rng = np.random.default_rng(seed)
        # Waits were subsampled to `wait_keep` in training, so the wait logit
        # is low by log(1 / wait_keep). Read the value the checkpoint was
        # trained with: a fixed 0.35 against a 0.25-trained model
        # under-corrected and the agent overplayed (~47 plays a match).
        args_json = Path(ckpt).with_name("args.json")
        if args_json.exists():
            try:
                wait_keep = float(json.loads(args_json.read_text())["wait_keep"])
            except (KeyError, ValueError):
                pass
        self.wait_bias = math.log(1 / wait_keep)

    def batch(self, row):
        t = self.torch
        keys = ("unit_ids", "unit_feats", "towers", "scalars", "hand", "opp_seen",
                "opp_last", "opp_last_age")
        b = {k: t.as_tensor(np.asarray(row[k])[None]) for k in keys}
        if getattr(self, "unit_token_map", None) is not None:
            raw = np.asarray(row["unit_ids"], dtype=np.int64)
            b["unit_ids"] = t.as_tensor(self.unit_token_map[raw][None])
        for k in ("unit_ids", "hand", "opp_seen", "opp_last"):
            b[k] = b[k].long()
        b["unit_feats"] = b["unit_feats"].float()
        if getattr(self, 'memory_observation', False):
            b['unit_feats'][...,6] = 0
        b["opp_last_age"] = b["opp_last_age"].float()
        b["next"] = t.as_tensor([int(row["next"])]).long()
        return b

    def act(self, battle, state, team, mem, tick, sub, royalesim):
        self._team = team
        if getattr(self, "hold_pending", False) and battle.pending_commands(team):
            # Our own last tap has not landed yet. Deciding again now means
            # deciding on a board that does not show it - the double-play the
            # delay produces. We always know what we sent, so this is public.
            self.ahead(battle, state)        # keep the velocity memory current
            return None
        view = self.ahead(battle, state)
        row = RR.obs_row(view, team, sub, mem, tick + self.lead, live=self.live)
        b = self.batch(row)
        with self.torch.no_grad():
            gate, _, _ = self.model(b, card_ids=b["hand"][:, 0].clamp(min=0))
        g = gate[0].float().numpy()
        g[0] += self.wait_bias
        p = state["players"][team]
        pending_cost = int(p.get("pending_cost", 0) or 0)
        for slot in range(4):
            cost = p["hand_costs"][slot] if slot < len(p["hand_costs"]) else 99
            if (slot >= len(p["hand"]) or p["elixir_milli"] - pending_cost * 1000 < cost * 1000
                    or p["hand"][slot] < 0):
                g[1 + slot] = -1e9
        pr = np.exp(g - g.max())
        pr /= pr.sum()
        if self.rng.random() < float(pr[0]) ** (DECIDE / 20) or g[1:].max() < -1e8:
            return None
        slot = int(np.argmax(g[1:]))
        with self.torch.no_grad():
            _, tile, _ = self.model(b, card_ids=b["hand"][:, slot])
        order = np.argsort(-tile[0].float().numpy())
        card = p["hand"][slot]
        if getattr(self, "spell_aim", False) and self.cat_kind(card) == "SPELL":
            order = self.aim_spell(order, view, team, card, sub)
        for t in order[:60]:
            tx, ty = int(t % 18), int(t // 18)
            wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
            if battle.check_deploy(team, slot, wx * sub, wy * sub) == 0:
                return (team, slot, wx * sub, wy * sub)
        return None


_SPAWN = {}
_UNITS = []


def _unit_names():
    if not _UNITS:
        import royalesim
        _UNITS.extend(json.loads(royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
                                 .unit_types_json()))
    return _UNITS


def _spawn_tables():
    """card id -> the unit type a spawn of it makes, and the inverse."""
    if not _SPAWN:
        raw = json.loads((ROOT / "data" / "rs_rows" / "spawn_primary.json").read_text())
        # This file was generated with an older engine. Its indices must be
        # translated through that file's vocabulary, just like model tokens.
        old = json.loads((ROOT / 'data' / 'rs_rows' / 'vocab.json').read_text())['units']
        old_names = {token-2:name for name,token in old.items()}
        current = {name:i for i,name in enumerate(_unit_names())}
        prim = {int(k):current[old_names[v]] for k,v in raw['primary'].items()
                if old_names.get(v) in current}
        by_unit = {}
        for card, unit in sorted(prim.items()):
            by_unit.setdefault(unit, card)
        _SPAWN.update(prim=prim, by_unit=by_unit)
    return _SPAWN["prim"], _SPAWN["by_unit"]


AGENT_CLASS = RSAgent   # tools/rs_selfplay.py swaps in its sampling agent


class RSSearchAgent(RSAgent):
    """RSAgent whose chosen play is checked in the engine first.

    When the gate decides to play, the model's top `k_cards` cards x `k_tiles`
    legal tiles are each played in a restored copy of the battle (RoyaleSim
    `save` / `load`) and run `horizon` ticks forward with nobody else playing.
    Score = own-frame tower swing over the horizon + the value head's 10 s
    prediction at the horizon + `prior` * model log-probability. The opponent
    makes no plays inside the copies, so its hidden hand is never consulted.
    """

    def __init__(self, ckpt, seed=0, k_cards=2, k_tiles=3, horizon=60, prior=0.05,
                 rebuild=False):
        super().__init__(ckpt, seed)
        self.k_cards, self.k_tiles, self.horizon, self.prior = k_cards, k_tiles, horizon, prior
        self.rebuild = rebuild

    def act(self, battle, state, team, mem, tick, sub, royalesim):
        row = RR.obs_row(state, team, sub, mem, tick, live=self.live)
        b = self.batch(row)
        with self.torch.no_grad():
            gate, _, _ = self.model(b, card_ids=b["hand"][:, 0].clamp(min=0))
        g = gate[0].float().numpy()
        g[0] += self.wait_bias
        p = state["players"][team]
        for slot in range(4):
            cost = p["hand_costs"][slot] if slot < len(p["hand_costs"]) else 99
            if slot >= len(p["hand"]) or p["elixir_milli"] < cost * 1000:
                g[1 + slot] = -1e9
        pr = np.exp(g - g.max())
        pr /= pr.sum()
        if self.rng.random() < float(pr[0]) ** (DECIDE / 20) or g[1:].max() < -1e8:
            return None
        slots = [s for s in np.argsort(-g[1:]) if g[1 + s] > -1e8][:self.k_cards]
        cands = []
        for slot in slots:
            with self.torch.no_grad():
                _, tile, _ = self.model(b, card_ids=b["hand"][:, slot])
            t = tile[0].float().numpy()
            logz = np.logaddexp.reduce(t)
            n = 0
            for k in np.argsort(-t)[:40]:
                tx, ty = int(k % 18), int(k // 18)
                wx, wy = to_world(tx * 1000 + 500, ty * 1000 + 500, team)
                if battle.check_deploy(team, int(slot), wx * sub, wy * sub) == 0:
                    cands.append(((team, int(slot), wx * sub, wy * sub),
                                  float(np.log(pr[1 + slot]) + t[k] - logz)))
                    n += 1
                    if n >= self.k_tiles:
                        break
        if not cands:
            return None
        if getattr(self, "shadow", None) is not None:
            sim = self.shadow.battle(state["tick"])
        else:
            sim = self.rebuilt(state, team, royalesim) if self.rebuild else battle
            if (sim is not None and self.rebuild and getattr(self, "lead_rebuild", False)
                    and self.lead):
                # Delay-aware search: a play sent now lands `lead` ticks later,
                # so candidates are tried on the board at that moment - with
                # our own plays already in flight landed first - rather than
                # on the present one. (Stacked naively, search scored the
                # present board and fought the look-ahead: 41.7% vs 47.0%.)
                now = state["tick"]
                pend = [p for p in getattr(self, "sent", []) if p[0] > now]
                sim = self.rebuilt(state, team, royalesim, first=[c for (_, c, _, _) in pend])
                if sim is not None:
                    t = now
                    for (te, card, x, y) in sorted(pend):
                        if te >= now + self.lead:
                            break
                        if te > t:
                            sim.step([], te - t)
                            t = te
                        hand = json.loads(sim.state_json())["players"][team]["hand"]
                        if card in hand:
                            sim.step([(team, hand.index(card), x, y)], 1)
                            t += 1
                    if now + self.lead > t:
                        sim.step([], now + self.lead - t)
        if sim is None:
            return cands[0][0]
        saved = sim.save()
        before = (RR.towers_vec(json.loads(sim.state_json()), team)
                  if (self.rebuild or getattr(self, "shadow", None) is not None)
                  else RR.towers_vec(state, team))
        best, best_score = None, -1e18
        for cmd, logp in cands:
            sim.load(saved)
            if (self.rebuild or getattr(self, "shadow", None) is not None):
                # The shadow's hand order is its own; play by card, not slot.
                st = json.loads(sim.state_json())
                card = state["players"][team]["hand"][cmd[1]]
                sh = st["players"][team]["hand"]
                if card not in sh:
                    continue
                cmd_sim = (cmd[0], sh.index(card), cmd[2], cmd[3])
                if sim.check_deploy(*cmd_sim) != 0:
                    continue
                sim.step([cmd_sim], self.horizon)
                after_state = json.loads(sim.state_json())
                after = RR.towers_vec(after_state, team)
                swing = float((before[3:] - after[3:]).sum() - (before[:3] - after[:3]).sum())
                arow = RR.obs_row(after_state, team, sub, mem, tick + self.horizon, live=self.live)
                with self.torch.no_grad():
                    _, _, v = self.model(self.batch(arow), card_ids=self.batch(arow)["hand"][:, 0].clamp(min=0))
                score = swing + float(v[0, 0]) + self.prior * logp
                if score > best_score:
                    best, best_score = cmd, score
                continue
            sim.step([cmd], self.horizon)
            after_state = json.loads(sim.state_json())
            after = RR.towers_vec(after_state, team)
            swing = float((before[3:] - after[3:]).sum() - (before[:3] - after[:3]).sum())
            arow = RR.obs_row(after_state, team, sub, mem, tick + self.horizon, live=self.live)
            with self.torch.no_grad():
                _, _, v = self.model(self.batch(arow), card_ids=self.batch(arow)["hand"][:, 0].clamp(min=0))
            score = swing + float(v[0, 0]) + self.prior * logp
            if score > best_score:
                best, best_score = cmd, score
        if not self.rebuild and getattr(self, "shadow", None) is None:
            battle.load(saved)
        else:
            sim.load(saved)
        return best if best is not None else cands[0][0]




def play(args):
    payload_text, ckpt, mode_, seed = args[:4]
    opp_ckpt = args[4] if len(args) > 4 else ""
    delay = args[5] if len(args) > 5 else 0
    royalesim, names, ids, cat = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    p = json.loads(payload_text)
    battle = p["battle"]
    decks, forms, levels = [], [], []
    for side in ("team", "opponent"):
        deck, form, level = [], [], []
        for card in battle[side]["players"][0]["deck"]:
            key, f = base_key(card["card_key"])
            deck.append(names[key])
            form.append(f)
            level.append(int(card.get("level") or 11))
        decks.append(deck)
        forms.append(form)
        levels.append(level)
    events = sorted((e for e in p["events"] if e["kind"] == "play_card"),
                    key=lambda e: (e["replay_tick_20hz"], e["source_index"]))
    plays = {0: [], 1: []}
    for e in events:
        seat = 0 if e["side"] == "team" else 1
        u = e["coordinates"]["native_world_units"]
        plays[seat].append((int(e["replay_tick_20hz"]), names[base_key(e["card_key"])[0]],
                            int(u["x"]), int(u["y"])))
    ys = sorted(y for _, _, _, y in plays[0]) or [0]
    team_seat = 0 if ys[len(ys) // 2] < 16_000 else 1
    rs = {0: team_seat, 1: 1 - team_seat}
    seat_of = {rs[0]: 0, rs[1]: 1}
    hog_seat = 0 if frozenset(decks[0]) == RR.HOG26 else 1
    hog_team = rs[hog_seat]
    dealt = []
    for seat in (0, 1):
        order = deal_order(decks[seat], [c for _, c, _, _ in plays[seat]])
        if order is None:
            return None
        dealt.append(order)
    perm = [[decks[s].index(c) for c in dealt[s]] for s in (0, 1)]
    tower = max(1, min(16, mode([lv for s in levels for lv in s])))
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    if delay:
        # Real taps land 21-22 ticks after they are sent (RoyaleSim's measured
        # client delay). Both seats get it; the recorded ghost commands were
        # logged at the tick they executed, so they are sent `delay` early.
        # It must be set BEFORE reset: it is battle configuration, and set
        # after reset it silently does nothing (found when a delayed run came
        # back identical, match for match, to an undelayed one).
        b.set_command_delay_ticks(delay, delay)
    b.reset(seed=seed, decks=[[ids[c] for c in dealt[seat_of[t]]] for t in (0, 1)],
            shuffle=0, start_tick=0, elixir_milli=[6000, 6000], tower_hp=None, spawns=[],
            forms=[[forms[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            levels=[[levels[seat_of[t]][i] for i in perm[seat_of[t]]] for t in (0, 1)],
            tower_levels=[tower, tower])
    lead = args[6] if len(args) > 6 else 0
    hold = args[7] if len(args) > 7 else False
    spell_aim = args[9] if len(args) > 9 else False
    agent = (None if mode_ == "pro" else
             RSSearchAgent(ckpt, seed=seed) if mode_ == "search" else
             RSSearchAgent(ckpt, seed=seed, rebuild=True) if mode_ == "search_rebuild" else
             AGENT_CLASS(ckpt, seed=seed))
    use_shadow = args[8] if len(args) > 8 else False
    if agent is not None and use_shadow:
        from rs_shadow import Shadow
        prim, _ = _spawn_tables()
        me_seat = seat_of[hog_team]
        agent.shadow = Shadow(royalesim, cat, hog_team,
                              [ids[c] for c in dealt[me_seat]],
                              [levels[me_seat][i] for i in perm[me_seat]], tower, prim)
    if agent is not None:
        agent.lead = abs(lead) % 1000
        agent.lead_rebuild = -1000 < lead < 0
        agent.lead_extrapolate = lead >= 1000
        agent.hold_pending = hold
        agent.spell_aim = spell_aim
    ghost_team = 1 - hog_team
    opponent = RSAgent(opp_ckpt, seed=seed + 7) if opp_ckpt else None
    scripted = [(t, rs[s], c, x, y) for s in (0, 1) for (t, c, x, y) in plays[s]
                if (mode_ == "pro" or rs[s] == ghost_team) and not
                (opponent is not None and rs[s] == ghost_team)]
    if delay:
        scripted = [(max(0, t - delay), team, c, x, y) for (t, team, c, x, y) in scripted]
    scripted.sort()
    mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}}
    i, tick, n_agent = 0, 0, 0
    while tick < 6200:
        state = json.loads(b.state_json())
        if state["game_over"]:
            break
        cmds = []
        while i < len(scripted) and scripted[i][0] <= tick:
            _, team, card, x, y = scripted[i]
            i += 1
            hand = state["players"][team]["hand"]
            cid = ids[card]
            if cid in hand:
                if team_seat == 1:
                    x, y = 18_000 - x, 32_000 - y
                cmds.append((team, hand.index(cid), x * sub, y * sub))
                mem["seen"][team].add(cid + 2)
                mem["last"][team].append((cid + 2, tick))
        if agent is not None and getattr(agent, "shadow", None) is not None:
            agent.shadow.observe(state)
        if agent is not None and tick % DECIDE == 0 and tick >= 90:
            cmd = agent.act(b, state, hog_team, mem, tick, sub, royalesim)
            if cmd is not None:
                cmds.append(cmd)
                agent.sent = getattr(agent, "sent", []) + [
                    (tick + delay, state["players"][hog_team]["hand"][cmd[1]], cmd[2], cmd[3])]
                if getattr(agent, "shadow", None) is not None:
                    agent.shadow.own_play(tick + delay, state["players"][hog_team]["hand"][cmd[1]],
                                          cmd[2], cmd[3])
                card = state["players"][hog_team]["hand"][cmd[1]]
                mem["seen"][hog_team].add(card + 2)
                mem["last"][hog_team].append((card + 2, tick))
                n_agent += 1
        if opponent is not None and tick % DECIDE == 0 and tick >= 90:
            cmd = opponent.act(b, state, ghost_team, mem, tick, sub, royalesim)
            if cmd is not None:
                cmds.append(cmd)
                card = state["players"][ghost_team]["hand"][cmd[1]]
                mem["seen"][ghost_team].add(card + 2)
                mem["last"][ghost_team].append((card + 2, tick))
        nxt = scripted[i][0] if i < len(scripted) else 6000
        step = max(1, min(nxt, (tick // DECIDE + 1) * DECIDE) - tick)
        b.step(cmds, step)
        tick += step
    state = json.loads(b.state_json())
    w = state["winner"]
    real = str(battle.get("result", "")).lower()
    real_hog = (("win" if real in ("victory", "win") else "loss" if real in ("defeat", "loss") else "draw")
                if hog_seat == 0 else
                ("loss" if real in ("victory", "win") else "win" if real in ("defeat", "loss") else "draw"))
    return {"tag": p["source"]["replay_tag"], "mode": mode_, "real": real_hog,
            "game_over": state["game_over"], "end_tick": state["tick"],
            "result": "win" if w == hog_team else "loss" if w in (0, 1) else "draw",
            "crowns": [state["players"][hog_team]["crowns"], state["players"][1 - hog_team]["crowns"]],
            "agent_plays": n_agent,
            "records": getattr(agent, "records", None),
            "hog_team": hog_team}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--matches", type=int, default=300)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--pro", action="store_true", help="run the recorded-pro baseline instead")
    ap.add_argument("--search", action="store_true", help="decision-time search")
    ap.add_argument("--spell-aim", action="store_true",
                    help="aim spells at the most enemy hp among the model's top tiles")
    ap.add_argument("--shadow", action="store_true",
                    help="search / lead on a shadow re-drive of public plays (live-capable)")
    ap.add_argument("--hold-pending", action="store_true",
                    help="no new play while our own last play is still pending")
    ap.add_argument("--lead", type=int, default=0,
                    help="delay compensation: decide on the board this many ticks ahead "
                         "(negative = look ahead on a battle rebuilt from public observation; "
                         "1000 + n = extrapolate unit motion n ticks, no engine)")
    ap.add_argument("--delay", type=int, default=0,
                    help="command delay in ticks for both seats (real client: ~21)")
    ap.add_argument("--rebuild", action="store_true",
                    help="search on a battle rebuilt from public observation (the live case)")
    ap.add_argument("--opponent-ckpt", default="",
                    help="a reactive opponent: this checkpoint plays the recorded opponent's "
                         "deck instead of the ghost replaying its commands")
    args = ap.parse_args()
    import pyarrow.parquet as pq
    royalesim, names, ids, cat = RR._setup()
    picked = []
    for part in sorted((CORPUS / "replays").glob("part-*.parquet")):
        acts = None
        for r in pq.read_table(part, columns=["replay_tag", "game_mode", "payload_json"]).to_pylist():
            if r["game_mode"] not in RR.MODES or RR.split_of(r["replay_tag"]) != "test":
                continue
            p = json.loads(r["payload_json"])
            try:
                sides = [frozenset(names.get(base_key(c["card_key"])[0])
                                   for c in p["battle"][s]["players"][0]["deck"]) for s in ("team", "opponent")]
            except (KeyError, IndexError):
                continue
            if any(None in s for s in sides) or RR.HOG26 not in sides or sides[0] == sides[1]:
                continue
            p.setdefault("source", {})["replay_tag"] = r["replay_tag"]
            picked.append(json.dumps(p))
            if len(picked) >= args.matches:
                break
        if len(picked) >= args.matches:
            break
    mode_ = ("pro" if args.pro else "search_rebuild" if args.search and args.rebuild
             else "search" if args.search else "agent")
    t0 = time.time()
    with ProcessPoolExecutor(args.workers) as pool:
        rows = []
        for r in pool.map(play, [(t, args.ckpt, mode_, k, args.opponent_ckpt, args.delay, args.lead,
                                 args.hold_pending, args.shadow, args.spell_aim)
                                for k, t in enumerate(picked)]):
            if r:
                rows.append(r)
                if len(rows) % 8 == 0:
                    print(f'evaluation: {len(rows)}/{len(picked)} matches ({time.time()-t0:.0f}s)',flush=True)
    wins = sum(r["result"] == "win" for r in rows)
    draws = sum(r["result"] == "draw" for r in rows)
    lo, hi = wilson(wins, len(rows))
    cd = sum(r["crowns"][0] - r["crowns"][1] for r in rows) / max(1, len(rows))
    name = ("recorded pro" if args.pro else
            Path(args.ckpt).parent.name + (" +search" if args.search else "")
            + (" (rebuilt)" if args.rebuild else "")
            + (f" delay {args.delay}" if args.delay else "")
            + (f" lead {args.lead}" if args.lead else "")
            + (" hold" if args.hold_pending else "")
            + (" shadow" if args.shadow else "")
            + (" spell-aim" if args.spell_aim else "")
            + (f" vs reactive {Path(args.opponent_ckpt).parent.name}" if args.opponent_ckpt else " vs ghost"))
    real_w = sum(r["real"] == "win" for r in rows)
    print(f"  real result of the Hog player in these matches: {real_w}/{len(rows)} "
          f"({real_w / max(1, len(rows)):.1%}); unfinished in engine: "
          f"{sum(not r['game_over'] for r in rows)}")
    print(f"{name}: {wins}/{len(rows)} wins ({wins / max(1, len(rows)):.1%}, 95% [{lo:.1%}, {hi:.1%}]) "
          f"{draws} draws, crown diff {cd:+.2f}, agent plays/match "
          f"{sum(r['agent_plays'] for r in rows) / max(1, len(rows)):.1f} ({time.time() - t0:.0f}s)")
    out = ROOT / "reports" / "rs_ghost.jsonl"
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"name": name, "ckpt": args.ckpt, "wins": wins, "n": len(rows),
                            "ci": [lo, hi], "crown_diff": cd,
                            "rows": rows}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
