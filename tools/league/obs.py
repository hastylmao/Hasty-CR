"""League observation: one function shared by simulator training and live play.

What it adds over tools/rs_rows.obs_row, and why:

* Per-unit velocity (own frame, over the last ~10 ticks). Live play cannot
  run the engine lookahead while a hero is on the board (the reset API cannot
  rebuild one), and with Hero Musketeer and Hero Ice Golem in the deck that is
  most of every match. So no lookahead at all, anywhere: the network sees how
  each unit is moving and the 26-tick command delay is in the simulator, so
  it learns to lead its own plays. Simulator and live see the same thing.
* No deploy-timer flag: memory cannot provide it, so it is always 0.
* Ability buttons: available / spent / cost / cooldown for two buttons.

The input order of units, the 48-token cap and the enemy/friendly
reservation are those of obs_row, so the imitation-trained weights read the
same layout.
"""
from __future__ import annotations

import os

import numpy as np

MAX_UNITS = 48
UF = 18                # obs_row's 7 + vx, vy + log(max hp) (obs_v 4) + has target, target is a building (obs_v 5)
                       # + 6 cue features (obs_v 6): stunned, slowed, raged, damage over time, attack clock, buffs
N_BUTTONS = 2
VEL_WINDOW = 10        # ticks
F = None               # royalesim.ENTITY_FIELDS index, set by setup()


N_PRED = 8
DECK_LIMIT = 5000
_COST = None           # catalogue index -> elixir cost
_DECKS = None          # (decks x cards) bool, ladder decks
_DECK_W = None         # their play counts


def setup(royalesim):
    """Field indexes, card costs and the ladder deck table (data/league/meta_decks.json)."""
    global F, _COST, _DECKS, _DECK_W
    import json
    from pathlib import Path
    F = {k: i for i, k in enumerate(royalesim.ENTITY_FIELDS)}
    b = royalesim.Battle(card_names=None, slot_of_k=[[0, 1, 2], [0, 1, 2]])
    cat = json.loads(b.catalogue_json())
    _COST = np.asarray([row[2] for row in cat], np.float32)
    ids = {row[0]: i for i, row in enumerate(cat)}
    path = Path(__file__).resolve().parents[2] / "data" / "league" / "meta_decks.json"
    meta = json.loads(path.read_text())[:DECK_LIMIT]
    _DECKS = np.zeros((len(meta), len(cat)), bool)
    for i, d in enumerate(meta):
        _DECKS[i, [ids[c] for c in d["cards"]]] = True
    _DECK_W = np.asarray([d["seen"] for d in meta], np.float64)
    return F


ELIXIR_TICKS = 56      # one elixir per 2.8 s at 1x


def elixir_rate(tick):
    """Elixir per tick by phase: 1x, 2x in the last minute, 3x in overtime (approximate)."""
    return (1 if tick < 2400 else 2 if tick < 3600 else 3) / ELIXIR_TICKS


def opp_elixir(plays, t0, tick):
    """The opponent's elixir, counted from what they visibly played since t0.

    Starts at 5, regenerates by phase, capped at 10, minus each card's cost
    when it is seen. Public information only; a play seen late is charged
    late, as it would be by a human counting."""
    e, t = 5.0, t0
    for card_tok, tp in plays:
        if tp < t0:
            continue
        if tp > tick:
            break
        e = min(10.0, e + _integral(t, tp))
        e = max(0.0, e - float(_COST[card_tok - 2]))
        t = tp
    return min(10.0, e + _integral(t, tick))


def _integral(a, b):
    if b <= a:
        return 0.0
    total, t = 0.0, a
    for edge in (2400, 3600, 10 ** 9):
        if t < edge:
            seg = min(b, edge) - t
            total += seg * elixir_rate(t)
            t = min(b, edge)
        if t >= b:
            break
    return total


_PRED_CACHE = {}


def predict_deck(seen_tokens):
    """Cached: the seen set changes a few times a match, and the uncached
    deck-table product cost 74% of an actor's time (profile 2026-10-14)."""
    key = tuple(sorted(seen_tokens))
    hit = _PRED_CACHE.get(key)
    if hit is None:
        if len(_PRED_CACHE) > 200_000:
            _PRED_CACHE.clear()
        hit = _PRED_CACHE[key] = _predict_deck(key)
    return hit[0].copy(), hit[1].copy()


def _predict_deck(seen_tokens):
    """Likely unseen opponent cards from the ladder decks that contain every
    card seen so far (weighted by how often each deck is played). Falls back
    to the cards' overall frequency when no listed deck matches.
    -> (token ids [N_PRED], probabilities [N_PRED])."""
    seen = [t - 2 for t in seen_tokens if t >= 2]
    match = _DECKS[:, seen].all(1) if seen else np.ones(len(_DECKS), bool)
    w = _DECK_W * match
    if w.sum() <= 0:
        w = _DECK_W * (_DECKS[:, seen].sum(1) if seen else 1)
    prob = (w @ _DECKS) / max(w.sum(), 1e-9)
    prob[seen] = 0.0
    top = np.argsort(-prob)[:N_PRED]
    ids = np.where(prob[top] > 0, top + 2, 0).astype(np.int64)
    return ids, prob[top].astype(np.float32)


def own(x_mt, y_mt, team):
    """World millitiles -> the acting team's frame, bottom = high y."""
    return (x_mt, 32_000 - y_mt) if team == 0 else (18_000 - x_mt, y_mt)


class Tracker:
    """Unit positions over the last VEL_WINDOW ticks, in world millitiles.

    One per match (both teams read the same world positions). `update` is
    called once per observed tick with the state's entities.
    """

    def __init__(self):
        self.hist = {}

    def update(self, entities, tick, sub):
        alive = set()
        for e in entities:
            uid = e[F["uid"]]
            alive.add(uid)
            h = self.hist.setdefault(uid, [])
            h.append((tick, e[F["x"]] / sub, e[F["y"]] / sub))
            while len(h) > 2 and tick - h[1][0] >= VEL_WINDOW:
                h.pop(0)
        for uid in [u for u in self.hist if u not in alive]:
            del self.hist[uid]

    def velocity(self, uid, team):
        """Own-frame (vx, vy) in millitiles per tick / 100 (a Hog ~ 0.5)."""
        h = self.hist.get(uid)
        if not h or len(h) < 2 or h[-1][0] == h[0][0]:
            return 0.0, 0.0
        (t0, x0, y0), (t1, x1, y1) = h[0], h[-1]
        dx, dy = (x1 - x0) / (t1 - t0), (y1 - y0) / (t1 - t0)
        if team == 0:
            dy = -dy
        else:
            dx = -dx
        return dx / 100.0, dy / 100.0


TOWERS_OWN = os.environ.get("HASTY_TOWERS_OWN") == "1"


TOWER_HP_SCALE = 5000.0     # a level-16 princess has 4858 hit points


def towers_vec(players, team, obs_v=6):
    """[own king, own slot 1, own slot 2, enemy king, enemy slot 1, enemy slot 2] as
    hit point fractions.

    Slot 1 is the princess at world x < 9000. `own()` mirrors x for team 1, so slot 1
    is on the model's left for team 0 and on its right for team 1. Towers are not in
    the unit list and the model is trained on both teams, so nothing in its input says
    which of the two it is: it cannot tell which lane holds the weak or dead tower
    (found 2026-11-15 from a live game: pushing the 1787 hp tower beside a 230 hp one).
    HASTY_TOWERS_OWN=1 swaps slots 1 and 2 for team 1, so slot 1 is always the model's
    left. Experimental and off by default: rows and models made with it must not be
    mixed with ones made without it. UNVERIFIED that this is the cause of the dead-lane
    plays; the control is a retrain and the lane counts of `actor.py --eval-tower`.

    obs_v 7: always in the model's frame, followed by the same six towers' hit points
    / TOWER_HP_SCALE. A fraction cannot say whether a Fireball ends a tower: 5% of a
    level-11 princess is 153 hit points, of a level-16 one 243."""
    out, absolute = [], []
    for t in (team, 1 - team):
        hp, mx = players[t]["tower_hp"], players[t]["tower_max_hp"]
        v = [h / max(1, m) for h, m in zip(hp, mx)]
        a = [h / TOWER_HP_SCALE for h in hp]
        if (TOWERS_OWN or obs_v >= 7) and team == 1:
            v, a = [v[0], v[2], v[1]], [a[0], a[2], a[1]]
        out += v
        absolute += a
    return out + absolute if obs_v >= 7 else out


def abilities_vec(player):
    """Two buttons x (available, spent, cost / 10, cooldown / 200, present)."""
    v = np.zeros(N_BUTTONS * 5, np.float32)
    for k, row in enumerate((player.get("abilities") or [])[:N_BUTTONS]):
        avail, spent, cost = int(row[0]), int(row[1]), int(row[2])
        cd = int(row[4]) if len(row) > 4 else 0
        v[5 * k:5 * k + 5] = (avail, spent, cost / 10.0, max(0, cd) / 200.0, 1.0)
    return v


N_SPELLS = 6
SF = 5                  # own, x, y, dir x, dir y


def spells_vec(state, team, sub):
    """Spells in flight or on the ground (a Goblin Barrel, a Fireball, a
    Log, a Poison): card token, side, own-frame position and the unit
    direction of travel. RoyaleSim gives each spell's aim; live, the bridge
    supplies the same rows with the aim extrapolated from the reader's
    positions, so both see the same thing. Without this the model only
    learned "a Goblin Barrel was played" and guessed the lane.
    """
    ids = np.zeros(N_SPELLS, np.int64)
    feats = np.zeros((N_SPELLS, SF), np.float32)
    rows = state.get("spells") or []
    k = 0
    for row in rows:
        if k >= N_SPELLS:
            break
        t, card, x, y, ax, ay = row[0], row[1], row[3], row[4], row[5], row[6]
        if card is None or card < 0:
            continue
        ox, oy = own(x / sub, y / sub, team)
        tx, ty = own(ax / sub, ay / sub, team)
        dx, dy = tx - ox, ty - oy
        n = (dx * dx + dy * dy) ** 0.5
        if n > 1:
            dx, dy = dx / n, dy / n
        else:
            dx = dy = 0.0
        ids[k] = card + 2
        feats[k] = (1.0 if t == team else 0.0, ox / 18_000, oy / 32_000, dx, dy)
        k += 1
    return ids, feats


# Buff name -> cue category (engine / live reader buff rows: Freeze, ZapFreeze, Rage,
# Poison ...). Name keywords, unverified beyond the four measured 2026-10-21.
_CUE_KEYS = (("stun", ("freeze", "stun", "zap", "electro", "paraly")),
             ("slow", ("slow", "snow", "ice", "chill")),
             ("rage", ("rage", "berserk", "haste")),
             ("dot", ("poison", "burn", "fire", "quake", "vine", "toxic")))


def cue_feats(e, cues):
    """Six cue features of one unit: [stunned, slowed, raged, damage over time] as
    remaining seconds / 5 (capped at 1), the attack clock / 3 s (capped), and the
    number of buffs / 4. Zeros unless the state carries engine / live cues."""
    out = [0.0] * 6
    if not cues:
        return out
    buffs = e[F["buffs"]] or []
    for item in buffs:
        try:
            name, ms = item[0].lower(), max(0, int(item[1]))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        for k, (_, keys) in enumerate(_CUE_KEYS):
            if any(w in name for w in keys):
                out[k] = max(out[k], min(1.0, ms / 5000))
                break
    out[4] = min(1.0, max(0, int(e[F["attack_phase"]] or 0)) / 3000)
    out[5] = min(1.0, len(buffs) / 4)
    return out


def build(state, team, mem, tick, tracker, unit_types, sub, obs_v=6):
    """Model input for `team` from a RoyaleSim-shaped state.

    obs_v 7 (2026-11-15): live crown towers are unit tokens too, first in the list,
    with their position in the model's frame, hit point fraction and size, so the
    model sees where each tower stands next to the units around it; and `towers` is
    the 12-value vector of towers_vec. Rows of different obs_v must not be mixed.

    `unit_types`: entity unit_type index -> model unit token (the vocabulary
    map; 0 = padding). `mem`: {"seen": {team: set(card+2)}, "last": {team:
    [(card+2, tick)]}} of what each side has visibly played.
    """
    ents = [e for e in state["entities"] if e[F["tower_slot"]] < 0 and e[F["hp"]] > 0]
    king = next((e for e in state["entities"]
                 if e[F["team"]] == team and e[F["tower_slot"]] == 0), None)
    kx, ky = ((king[F["x"]], king[F["y"]]) if king is not None
              else (9000 * sub, (3000 if team == 0 else 29000) * sub))
    ents.sort(key=lambda e: (e[F["x"]] - kx) ** 2 + (e[F["y"]] - ky) ** 2)
    if len(ents) > MAX_UNITS:
        enemy = [e for e in ents if e[F["team"]] != team][:24]
        friendly = [e for e in ents if e[F["team"]] == team][:12]
        reserved = {e[F["uid"]] for e in enemy + friendly}
        kept = enemy + friendly + [e for e in ents if e[F["uid"]] not in reserved][:MAX_UNITS - len(reserved)]
        kept_ids = {e[F["uid"]] for e in kept}
        ents = [e for e in ents if e[F["uid"]] in kept_ids]
    if obs_v >= 7:
        tw = [e for e in state["entities"] if e[F["tower_slot"]] >= 0 and e[F["hp"]] > 0]
        tw.sort(key=lambda e: (e[F["team"]] != team, e[F["tower_slot"]]))
        ents = tw + ents[:MAX_UNITS - len(tw)]
    ids = np.zeros(MAX_UNITS, np.int64)
    feats = np.zeros((MAX_UNITS, UF), np.float32)
    # What each unit is attacking (live: reader target pointer, 2026-10-14).
    # A building or tower target is what kiting is about: a Hog locked on our
    # Cannon, a Giant walking to the tower.
    structure = {e[F["uid"]] for e in state["entities"]
                 if e[F["tower_slot"]] >= 0 or e[F["kind"]] == 1}
    alive = {e[F["uid"]] for e in state["entities"] if e[F["hp"]] > 0}
    for k, e in enumerate(ents[:MAX_UNITS]):
        ut = e[F["unit_type"]]
        tok = unit_types[ut] if 0 <= ut < len(unit_types) else 0
        if tok == 0:
            continue
        ox, oy = own(e[F["x"]] / sub, e[F["y"]] / sub, team)
        vx, vy = tracker.velocity(e[F["uid"]], team)
        ids[k] = tok
        feats[k] = (1.0 if e[F["team"]] == team else 0.0, ox / 18_000, oy / 32_000,
                    e[F["hp"]] / max(1, e[F["max_hp"]]), 1.0 if e[F["flying"]] else 0.0,
                    1.0 if e[F["kind"]] == 1 or e[F["tower_slot"]] >= 0 else 0.0,
                    # Still deploying (live: reader deploy timer, 2026-10-14).
                    1.0 if e[F["deploy_ticks"]] > 0 else 0.0, vx, vy,
                    # Absolute size: the hp fraction alone cannot tell a level-14
                    # Knight from a level-16 one, or a Golem from a Skeleton at 50%.
                    float(np.log1p(max(0, e[F["max_hp"]]))) / 10.0,
                    1.0 if e[F["target_uid"]] in alive else 0.0,
                    1.0 if e[F["target_uid"]] in structure else 0.0,
                    *cue_feats(e, state.get("cues")))
    p = state["players"][team]
    hand = [c + 2 for c in p["hand"][:4]] + [0] * (4 - len(p["hand"][:4]))
    opp = 1 - team
    seen = sorted(mem["seen"][opp])[:8]
    last = mem["last"][opp][-4:]
    t_ms = tick * 50
    pred_ids, pred_p = predict_deck(seen)
    sp_ids, sp_feats = spells_vec(state, team, sub)
    oe = opp_elixir(mem["last"][opp], mem.get("t0", 0), tick)
    return {
        "unit_ids": ids, "unit_feats": feats,
        "towers": np.asarray(towers_vec(state["players"], team, obs_v), np.float32),
        "scalars": np.asarray([p["elixir_milli"] / 10_000, min(1.0, t_ms / 300_000),
                               1.0 if t_ms >= 120_000 else 0.0,
                               1.0 if t_ms >= 180_000 else 0.0, oe / 10.0], np.float32),
        "hand": np.asarray(hand, np.int64),
        "next": np.int64((p["next_card"] + 2) if p.get("next_card", -1) >= 0 else 0),
        "opp_seen": np.asarray(seen + [0] * (8 - len(seen)), np.int64),
        "opp_last": np.asarray([c for c, _ in last] + [0] * (4 - len(last)), np.int64),
        "opp_last_age": np.asarray([min(1.0, (tick - t) / 400) for _, t in last]
                                   + [1.0] * (4 - len(last)), np.float32),
        "abil": abilities_vec(p),
        "pred": pred_ids, "pred_p": pred_p,
        "spell_ids": sp_ids, "spell_feats": sp_feats,
    }


KEYS = ("unit_ids", "unit_feats", "towers", "scalars", "hand", "next", "opp_seen",
        "opp_last", "opp_last_age", "abil", "pred", "pred_p", "spell_ids", "spell_feats")


def trim(batch):
    """Drop unit slots that are padding in every row of a batch.

    Units are packed from slot 0 (nearest first), so the batch only needs as
    many slots as its fullest board. Padding is masked out anyway; trimming
    it saves the transformer the work (typical boards hold 10-20 of 48).
    Works on dicts of numpy arrays or torch tensors."""
    ids = batch["unit_ids"]
    nz = (ids != 0)
    n = int(nz.any(0).nonzero()[0].max()) + 1 if hasattr(nz, "nonzero") and not hasattr(nz, "device") and nz.any() else None
    if n is None:
        if hasattr(nz, "device"):
            cols = nz.any(0).nonzero()
            n = int(cols.max()) + 1 if len(cols) else 1
        else:
            n = 1
    out = dict(batch)
    out["unit_ids"] = ids[:, :n]
    out["unit_feats"] = batch["unit_feats"][:, :n]
    return out
