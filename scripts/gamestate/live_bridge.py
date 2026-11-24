"""Live bridge, dry run: reader frame -> live-compatible observation -> model
decision, printed. It never taps.

    py -3.12 scripts/gamestate/live_bridge.py --ckpt runs/tokens/rs_live/best.pt

Run it during a friendly match the owner starts; it prints what the bot WOULD
play each half second next to what the reader saw. Tapping is a separate,
later step and needs the owner's go-ahead.

The observation is built exactly as `tools/rs_rows.py --live-compat` builds
training rows, so the model sees live what it saw in training:
    unit id = creating card (native id -> RoyaleSim id via card_map.json),
    own / x / y / hp fraction / flying / building (card catalogue) / log max hp,
    towers as hit point fractions, own elixir, clock, own hand and next card,
    the opponent's seen cards and last four plays (from units appearing).

Open items, each needing a live battle to check (frame.validate covers 1-3):
 1. which reader side is ours, and which end of the board it owns
    (taken from our king tower's y; checked against the first plays);
 2. tower entities: told apart from troops by position and max hp until the
    tower card ids are known;
 3. hand: the reader gives deck indexes; the deck's card ids come from the
    avatar chain (root +0x30 ... entry +0x10 -> data +0x40) that the native
    reader does not walk yet - until then the deck is passed with --deck;
 4. evolution ids (13xxxxxx) are not in card_map.json. The native reader now
    emits each unit's character name (11th field; entity +0x48 -> data name,
    e.g. "Skeleton_EV1"). Those are the client's names, and RoyaleSim's
    `unit_types_json()` uses the same ones, so the unit-type model (`rs_hog`,
    the stronger one) can run live: unit id = unit_types.index(name) + 2.
    Check in the first battle that every name read is in that list;
 5. delay: the bot decides on a frame ~100 ms old and a tap lands ~1.1 s
    later (RoyaleSim measured 21-22 ticks); the board should be advanced by
    that much before deciding - not done here yet.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from gamestate.memread import GameMemory, _sh  # noqa: E402

CARD_MAP = json.loads((Path(__file__).with_name("card_map.json")).read_text())["cards"]
TOWER_MIN_HP = 2000          # crown towers; no troop starts this high except a few tanks
MAX_UNITS, UF = 48, 7


class LiveObs:
    def __init__(self, deck_rs_ids, catalogue):
        self.deck = deck_rs_ids                       # our 8 cards, RoyaleSim ids
        self.cat = catalogue
        self.seen_opp, self.last_opp = set(), []
        self.known_units = set()

    def from_frame(self, f, my_side):
        units = f["u"]
        my_king = [u for u in units if u[3] == my_side and u[9] >= TOWER_MIN_HP]
        low = (min(u[5] for u in my_king) < 16_000) if my_king else True
        def own(x, y):                                # our end -> bottom, high y
            return (x, 32_000 - y) if low else (18_000 - x, y)
        troops = []
        for addr, cat, kind, side, x, y, card, level, hp, mx in units:
            entry = CARD_MAP.get(str(card))
            if entry is None:
                continue                              # towers, evo ids, unknowns
            troops.append((addr, side, x, y, entry["rs_id"], hp, mx))
            if side != my_side and addr not in self.known_units:
                self.seen_opp.add(entry["rs_id"] + 2)
                self.last_opp.append((entry["rs_id"] + 2, f["t"]))
            self.known_units.add(addr)
        kx, ky = own(9000, 3000 if low else 29_000)
        troops.sort(key=lambda t: (t[2] - kx) ** 2 + (t[3] - ky) ** 2)
        ids = np.zeros(MAX_UNITS, np.int64)
        feats = np.zeros((MAX_UNITS, UF), np.float32)
        for k, (addr, side, x, y, rs, hp, mx) in enumerate(troops[:MAX_UNITS]):
            ox, oy = own(x, y)
            row = self.cat[rs]
            ids[k] = rs + 2
            feats[k] = (1.0 if side == my_side else 0.0, ox / 18_000, oy / 32_000,
                        hp / max(1, mx), 1.0 if row[5] else 0.0,
                        1.0 if row[8] == "BUILDING" else 0.0, math.log1p(max(0, mx)) / 10)
        return ids, feats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--deck", default="Musketeer,Cannon,IceSpirits,HogRider,Skeletons,IceGolemite,Log,Fireball",
                    help="deck in the deck-screen order (left to right, top row first); "
                         "the reader's hand indexes are positions in this list")
    ap.add_argument("--side", type=int, default=1,
                    help="our player record's side; 1 in the 2026-10-10 friendlies, UNVERIFIED always")
    ap.add_argument("--seconds", type=int, default=240)
    args = ap.parse_args()
    print("DRY RUN: decisions are printed, nothing is tapped.")
    # The decision code mirrors tools/rs_eval.RSAgent.act, so live and the
    # 300-match screens use the same gate, wait bias and tile head.
    sys.path.insert(0, str(ROOT / "tools"))
    import rs_rows as RR
    from rs_eval import DECIDE, RSAgent, _unit_names
    royalesim, names, ids, cat = RR._setup()
    sub = royalesim.SUBTILE_PER_MILLITILE
    unit_types = _unit_names()
    deck_rs = [ids[c] for c in args.deck.split(",")]
    agent = RSAgent(args.ckpt)
    torch = agent.torch
    mem = {"seen": {0: set(), 1: set()}, "last": {0: [], 1: []}}
    known = set()
    dev = GameMemory()
    reader = "/data/local/tmp/hcr_reader"
    proc = subprocess.Popen(
        [r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
         "-s", dev.serial, "exec-out",
         f"HCR_SIDE={args.side} {reader} {dev.pid} {dev.libg:x} 100"],
        stdout=subprocess.PIPE, text=True)
    t0, last_decide = time.time(), -10**9
    for line in proc.stdout:
        if time.time() - t0 > args.seconds:
            break
        try:
            f = json.loads(line)
        except json.JSONDecodeError:
            print(f"reader said (not JSON): {line.rstrip()!r}")
            continue
        if f.get("t", -1) < 0 or "me" not in f:
            continue
        state = rs_state_from_frame(f, args.side, deck_rs, unit_types, cat, sub)
        team = next((t for t in (0, 1) if state["players"][t]["hand"]), None)
        if team is None:
            continue
        # Opponent memory from public information only: units appearing on their side.
        for e in state["entities"]:
            if e[1] != team and e[0] not in known and e[3] >= 0:
                mem["seen"][1 - team].add(e[3] + 2)
                mem["last"][1 - team].append((e[3] + 2, f["t"]))
            known.add(e[0])
        if f["t"] - last_decide < DECIDE:
            continue
        last_decide = f["t"]
        row = RR.obs_row(state, team, sub, mem, f["t"], live=agent.live)
        b = agent.batch(row)
        with torch.no_grad():
            gate, _, _ = agent.model(b, card_ids=b["hand"][:, 0].clamp(min=0))
        g = gate[0].float().numpy()
        g[0] += agent.wait_bias
        p = state["players"][team]
        for slot in range(4):
            if slot >= len(p["hand"]) or p["elixir_milli"] < p["hand_costs"][slot] * 1000:
                g[1 + slot] = -1e9
        pr = np.exp(g - g.max())
        pr /= pr.sum()
        hand_names = [cat[c][0] for c in p["hand"]]
        head = f"t={f['t']:5d} elixir {p['elixir_milli'] / 1000:4.1f} hand {hand_names}"
        if g[1:].max() < -1e8 or agent.rng.random() < float(pr[0]) ** (DECIDE / 20):
            print(f"{head}  -> wait (p_wait {pr[0]:.2f})")
            continue
        slot = int(np.argmax(g[1:]))
        with torch.no_grad():
            _, tile, _ = agent.model(b, card_ids=b["hand"][:, slot])
        t = int(np.argmax(tile[0].float().numpy()))
        print(f"{head}  -> PLAY {hand_names[slot]} at tile ({t % 18},{t // 18}), "
              f"own frame, row 31 = our back line (p {pr[1 + slot]:.2f}, placement unchecked)")
    proc.terminate()
    return 0




# ----------------------------------------------------------------------------
# Reader frame -> RoyaleSim-shaped state, so the tested code paths run live:
# `tools/rs_rows.obs_row` builds the model input from it, and
# `tools/rs_eval.RSAgent.rebuilt` rebuilds a battle from it for the look-ahead
# (`--lead -21`: the best public-only configuration, 47.0% vs 32.0% without).
#
# UNVALIDATED until a battle is read. Assumptions to check in the first
# friendly, each one printed by `--check-frame`:
#   * a tower is a body whose name contains "Tower" (or, failing names, a
#     body with max hp >= TOWER_MIN_HP at a tower position); king = the one
#     on the centre line; left / right by x;
#   * reader x / y are native world units (1000 per tile), RoyaleSim's
#     sub-tile = native * SUBTILE_PER_MILLITILE;
#   * our hand comes as deck indexes; the deck's RoyaleSim ids are passed in
#     (`--deck`) until the reader walks the avatar chain.
# ----------------------------------------------------------------------------

_FORM_SUFFIXES = ("_EV1", "_EV2", "Hero")
_CARD_BY_NAME = {}
# ChefTowerKing (2026-11-15): the king of a Royal Chef player has its own unit name. It
# was missing here, so against those opponents the king was dropped as an unknown unit
# and the model's tower vector read their king as destroyed (capture of 2026-11-14).
CROWN_TOWERS = {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower','ChefTowerKing'}
# Observed 203000076 transformation. The simulator lacks a separate bear
# unit, so preserve it as Berserker with measured position/HP; ability
# mechanics remain an approximation, rather than silently dropping it.
UNIT_ALIASES = {"BerserkerHero_BearForm": "BerserkerHero",
                "TombstoneHeroSkeleton": "Skeleton", "BarrelGoblin": "Goblin",
                "GoblinCurseGoblin": "Goblin", "IceWizardHero": "IceWizard",
                "IceWizardHero_IceCube": "IceWizard",
                "IceWizardHeroFloatingCube": "IceWizard",
                # 2026-11-23: Hero Electro Wizard (Giant Skeleton bait). Without this the
                # hero body got unit type -1: the model never saw it and its ability
                # button was never offered (first live games: 0 presses).
                "ElectroWizardHero": "ElectroWizard"}


def _unit_card(unit_type):
    """The card whose own (primary) unit this unit type is, else -1."""
    sys.path.insert(0, str(ROOT / "tools"))
    from rs_eval import _spawn_tables
    return _spawn_tables()[1].get(unit_type, -1)


def _fallback_unit(name, ut_index):
    """Unit type for a body whose exact name the simulator lacks, from the
    last known part of its name: "Witch_EV1_Skeleton_Interval" -> Skeleton.

    Recorded live frames (2026-10-21, 5 sessions): 4.5% of enemy body-frames
    had names the simulator does not list, every one an Evolved Witch's
    skeleton. They were dropped, so the model never saw that swarm. -1 when
    no part of the name is a known unit (spell effects stay out).
    """
    if not name or any(k in name.lower() for k in ("projectile", "container", "dummy")):
        return -1
    for part in reversed(name.split("_")):
        for cand in (part, *(part[:-len(suf)] for suf in ("EvoGhost", "Hero", "EV1", "EV2")
                             if part.endswith(suf) and len(part) > len(suf))):
            if cand in ut_index:
                return ut_index[cand]
    return -1


def card_of_form(name, catalogue):
    """RoyaleSim card id for an evolved or hero unit, from its character name.

    Evolutions and heroes have their own native card ids (13000096 for an
    evolved Cannon, 203000014 for the Musketeer hero, seen in the 2026-10-10
    friendly) that card_map.json does not list, so these units were dropped
    from the rebuild and the bot never saw a hero Musketeer or Ice Golem. The
    name is the base unit's name plus a suffix ("Cannon_EV1",
    "MusketeerHero"); the card is the one whose own unit that base is.
    """
    if not _CARD_BY_NAME:
        for i, row in enumerate(catalogue):
            _CARD_BY_NAME[row[0].lower()] = i
        sys.path.insert(0, str(ROOT / "tools"))
        from rs_eval import _spawn_tables, _unit_names
        prim, by_unit = _spawn_tables()
        for unit, card in by_unit.items():
            _CARD_BY_NAME.setdefault(_unit_names()[unit].lower(), card)
    if name in UNIT_ALIASES:
        base = UNIT_ALIASES[name]
        return _CARD_BY_NAME.get(base.removesuffix('Hero').lower(), -1)
    base = name
    for suf in _FORM_SUFFIXES:
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    if base == name:
        return -1
    return _CARD_BY_NAME.get(base.lower(), -1)


def rs_state_from_frame(frame, my_side, deck_rs, unit_types, catalogue, sub):
    """A dict with the keys rs_rows.obs_row and RSAgent.rebuilt read."""
    ut_index = {name: i for i, name in enumerate(unit_types)}
    teams = {}                                  # reader side -> RoyaleSim team
    units = frame["u"]
    def is_tower(u):
        name = u[10] if len(u) > 10 else ""
        return name in CROWN_TOWERS or (not name and
            u[9] >= TOWER_MIN_HP and abs(u[4] - 9000) in (0, 5500))
    towers = [u for u in units if is_tower(u)]
    # RoyaleSim team 0 owns low y. Our side's king tells which end is ours.
    mine_low = any(u[3] == my_side and u[5] < 16_000 for u in towers)
    teams[my_side] = 0 if mine_low else 1
    teams[1 - my_side] = 1 - teams[my_side]
    entities, tower_hp = [], {0: [0, 0, 0], 1: [0, 0, 0]}
    has_cues = [False]
    uncertain = []
    unknown = []
    spells_seen = []            # (addr, team, card, x_sub, y_sub): spell objects in play
    tower_max = {0: [1, 1, 1], 1: [1, 1, 1]}
    for u in units:
        addr, cat, kind, side, x, y, card, level, hp, mx = u[:10]
        name = u[10] if len(u) > 10 else ""
        team = teams.get(side)
        if team is None:
            continue
        if is_tower(u):
            slot = 0 if abs(x - 9000) < 2000 else (1 if x < 9000 else 2)
            tower_hp[team][slot], tower_max[team][slot] = max(0, hp), max(1, mx)
            # Towers are entities in training (RoyaleSim and the engine): the model finds
            # its own king among them and reads "this unit targets a structure / a live
            # body" against them. Left out live (until 2026-10-20), every unit attacking a
            # tower looked target-less and units were sorted from a default king position.
            if hp > 0:
                row = [0] * 28
                row[0], row[1], row[2], row[3], row[4] = addr, team, 2 if slot == 0 else 3, -1, slot
                row[5], row[6], row[7], row[8] = x * sub, y * sub, hp, mx
                row[21], row[22] = level, -1
                row[24], row[25] = -1, -1
                # Training battles always use the Tower Princess, so the only tower tokens the
                # model has trained are KingTower / PrincessTower: every tower troop maps to
                # them (obs_v 7 shows towers as tokens). The troop's different damage and
                # range are a known gap between training and live, not fixed here.
                row[27] = ut_index.get("KingTower" if slot == 0 else "PrincessTower", -1)
                row[15] = u[12] if len(u) > 12 and u[12] else -1
                entities.append(row)
            continue
        unit_type = ut_index.get(name, ut_index.get(UNIT_ALIASES.get(name, ""), -1))
        if unit_type < 0:
            unit_type = _fallback_unit(name, ut_index)
        # Only characters are units. Spells and their effects (the Log's
        # roller, Ice Spirits' freeze) are entities with no character name;
        # RoyaleSim keeps those out of its unit list, so the model never saw
        # them as units, and counting them logged one Log as two plays.
        if unit_type >= 0 and 'dummy' in name.lower():
            continue        # e.g. EliteArcherHero_Dummy: a visual, not a body
        if unit_type < 0:
            entry_s = CARD_MAP.get(str(card))
            if entry_s is not None and catalogue[entry_s["rs_id"]][8] == "SPELL":
                spells_seen.append((addr, team, entry_s["rs_id"], x * sub, y * sub))
                continue
            if hp>0 and mx>0 and not any(s in name.lower() for s in ('dummy','projectile','container')):
                unknown.append({'uid':addr,'team':team,'x':x,'y':y,'hp':hp,'max_hp':mx,'name':name,'native_card':card})
            continue
        entry = CARD_MAP.get(str(card))
        rs_card = entry["rs_id"] if entry else card_of_form(name, catalogue)
        if rs_card < 0 and "_" in name:
            # A spawned body of an evolved card ("Witch_EV1_Healing_Skeleton"):
            # the card is the one its name starts with (the Witch).
            parts = name.split("_")
            for k in range(len(parts) - 1, 0, -1):
                head = "_".join(parts[:k])
                rs_card = card_of_form(head, catalogue)
                if rs_card < 0:
                    rs_card = _CARD_BY_NAME.get(head.lower(), -1)
                if rs_card >= 0:
                    break
        if rs_card < 0:
            # Last resort: the card whose own unit this body is (a Skeleton ->
            # Skeletons), from the simulator's spawn table.
            sys.path.insert(0, str(ROOT / "tools"))
            from rs_eval import _spawn_tables
            by_unit = _spawn_tables()[1]
            rs_card = by_unit.get(unit_type, -1)
            base = name.split("_")[0]
            for suf in ("EvoGhost", "Hero", "Trooper"):
                if rs_card < 0 and base.endswith(suf) and base[:-len(suf)] in ut_index:
                    rs_card = by_unit.get(ut_index[base[:-len(suf)]], -1)
            if rs_card < 0 and base in ut_index:
                rs_card = by_unit.get(ut_index[base], -1)
            if rs_card < 0:
                # Catalogue names: GoblinHero -> Goblins, Furnace_EV1 -> FirespiritHut
                # (the Furnace's RoyaleSim card).
                names = {row[0].lower(): i for i, row in enumerate(catalogue)}
                stem = base[:-4] if base.endswith("Hero") else base
                for cand in (stem, stem + "s", {"Furnace": "FirespiritHut"}.get(stem, "")):
                    if cand.lower() in names:
                        rs_card = names[cand.lower()]
                        break
        if rs_card < 0 and name == 'GoblinCurseGoblin':
            rs_card = next((i for i,c in enumerate(catalogue) if c[0]=='Goblins'),-1)
        # A body the model has a token for but that no card spawns (the Mother Witch's
        # VoodooHog) used to be dropped here, so the model never saw the pigs live
        # (owner, 2026-11-15; capture of 2026-11-13). The model reads the unit type,
        # not the card: the real engine's training states carry card_id -1 for every
        # unit. Keep the body with card -1; the readers of the card field
        # (seen-card memory, tactics) already skip negative cards.
        row = [0] * 28
        # kind 1 = building, as RoyaleSim sets it; the unit-type model reads it
        # as the "building" feature (it was always 0 live before 2026-10-10).
        # A building is the building card's own body: a Tombstone's Skeletons or a
        # Furnace's spirits are troops (training marks them 0; live marked them 1 from
        # the card that made them, until 2026-10-20).
        own_card = _unit_card(unit_type)
        kind = 1 if own_card >= 0 and catalogue[own_card][8] == "BUILDING" else 0
        if name == 'MusketeerTurret':
            kind = 1
        elif name.startswith('TombstoneHero_Monster') or name == 'TombstoneHeroSkeleton':
            kind = 0
        row[0], row[1], row[2], row[3], row[4] = addr, team, kind, rs_card, -1
        row[5], row[6], row[7], row[8] = x * sub, y * sub, hp, mx
        row[10] = bool(catalogue[rs_card][5]) if rs_card >= 0 else False
        row[21], row[27] = level, unit_type
        # Deploy time left: reader field 12 (ms, entity +0x15c, 2026-10-14);
        # RoyaleSim's deploy_ticks, which the imitation models were trained on.
        if len(u) > 11 and u[11] > 0:
            row[11] = (u[11] + 49) // 50
        # Current target: reader field 13 (entity address, 2026-10-14), the
        # same thing as RoyaleSim's target_uid since uids here are addresses.
        if len(u) > 12 and u[12]:
            row[15] = u[12]
        # Cues (reader fields 14-15, 2026-10-21): attack clock ms -> attack_phase,
        # active buffs "Name:ms,..." -> buffs, as the engine's state gives them.
        if len(u) > 14:
            row[16] = u[13]
            row[19] = [[n, int(m)] for n, _, m in (p.partition(":") for p in (u[14] or "").split(","))
                       if n and m.lstrip("-").isdigit()]
            has_cues[0] = True
        entities.append(row)
        if name in UNIT_ALIASES or 'Hero' in name or name == 'MusketeerTurret':
            uncertain.append(name)
    me = frame.get("me") or [my_side, 0, [], []]
    hand_idx = me[2] if len(me) > 2 else []
    hand = [deck_rs[i] for i in hand_idx if 0 <= i < len(deck_rs)]
    cyc = me[3] if len(me) > 3 else []
    players = [None, None]
    for team in (0, 1):
        players[team] = {"team": team, "tower_hp": tower_hp[team], "tower_max_hp": tower_max[team],
                         "elixir_milli": 0, "hand": [], "hand_costs": [], "deck": [],
                         "next_card": -1, "crowns": 0}
    t_me = teams[my_side]
    players[t_me].update(
        elixir_milli=int(me[1] / 10) if len(me) > 1 else 0,     # reader raw: 1e-4 elixir
        hand=hand, hand_costs=[catalogue[c][2] for c in hand], deck=list(deck_rs),
        next_card=deck_rs[cyc[0]] if cyc and 0 <= cyc[0] < len(deck_rs) else -1)
    return {"tick": frame["t"], "entities": entities, "players": players,
            "spells": [], "projectiles": [], "game_over": False,
            "unmodelled_forms": uncertain + (['unknown living units'] if unknown else []),
            "unknown_units":unknown, "spells_seen": spells_seen, "cues": has_cues[0]}


if __name__ == "__main__":
    sys.exit(main())
