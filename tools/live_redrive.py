"""Re-play recorded live battles in the extracted engine and compare them with
what the real game did, frame by frame.

Needs live_play logs made with --record-frames N: they hold every unit on the
board every N ticks ({"f": tick, "u": [[addr, side, x, y, level, hp, max_hp,
name, deploy_ms], ...]}), next to our plays ("landed") and the opponent's
("opp"). Each play is placed in the engine with the loader's `spawn` (free,
no hand) at the tick, position and level the reader saw, so the hand, elixir
and deck order cannot add errors. The engine then runs on its own and its
board is compared with the recording at every recorded frame.

Spells: the reader sees the spell object, not the aim point. The aim is taken
as the object's last recorded position (where it landed); unverified.

    py -3 tools/live_redrive.py reports/live_play/<log>.jsonl [--battle K] [--verbose]
"""
import argparse
import collections
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADLESS = ROOT / "vendor" / "re" / "headless"
sys.path.insert(0, str(HEADLESS))
import engine  # noqa: E402

TOWERS = ("KingTower", "PrincessTower")
RAWS = {}       # (battle index, tick) -> (full reader frame, our reader side), when recorded
HOOK = None     # audit_inputs.py: called with (battle, tick, engine state, recorded units) per frame
SKIP = ("Projectile", "Dummy", "_Bomb", "lightning", "Bottle", "_Spawn")   # not a played card's own unit
PRINCESS_HP = {3052: 11, 3204: 12, 3372: 13, 3540: 14, 3708: 15, 4858: 16}   # unverified beyond 11 and 16
KING_HP = {4392: 11, 7728: 16}


def battles(path):
    """Split a log into battles: (frames, plays) per battle that has frames."""
    cur_f, cur_p, out = [], [], []
    for line in open(path, encoding="utf-8", errors="ignore"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "f" in d:
            if cur_f and d["f"] < cur_f[-1][0] - 100:          # a new battle started
                out.append((cur_f, cur_p))
                cur_f, cur_p = [], []
            cur_f.append((d["f"], d["u"]))
            if "raw" in d:                                      # full reader frame (audit_inputs.py)
                RAWS[(len(out), d["f"])] = (d["raw"], d.get("side"))
        elif "card" in d and "tile" in d and "t" in d:      # our tap (lands ~26 ticks later)
            cur_p.append(("us", d["t"], d["card"]))
        elif "opp" in d:
            cur_p.append(("opp", d["t"], d["opp"]))
        elif "result" in d and cur_f:
            out.append((cur_f, cur_p))
            cur_f, cur_p = [], []
    if cur_f:
        out.append((cur_f, cur_p))
    return out


def tower_levels(frames):
    lv = [16, 16]
    for _, units in frames[:3]:
        for addr, side, x, y, level, hp, mx, name, *_ in units:
            if name == "KingTower" and side in (0, 1):
                lv[side] = KING_HP.get(mx, lv[side])
            elif name == "PrincessTower" and side in (0, 1):
                lv[side] = PRINCESS_HP.get(mx, lv[side])
    return lv


def find_spawns(frames):
    """Every unit seen for the first time: (tick, side, name, x, y, level, addr)."""
    seen, out = {}, []
    for t, units in frames:
        for addr, side, x, y, level, hp, mx, name, *_ in units:
            # addresses are reused after an object is freed: a known address with a
            # new name is a new unit
            if seen.get(addr) == name:
                continue
            seen[addr] = name
            if name in TOWERS or side not in (0, 1):
                continue
            out.append((t, side, name, x, y, level, addr))
    return out


def last_pos(frames, addr, name, t0):
    p = None
    for t, units in frames:
        if t < t0:
            continue
        hit = [u for u in units if u[0] == addr]
        if not hit or hit[0][7] != name:
            if p is not None:
                break
            continue
        p = (hit[0][2], hit[0][3])
    return p


_forms = {}


def form_id(eng, card, form):
    """Form spell global id: evolution = table 13 row '<card>_EV1', hero = table
    203 row '<card>_hero' (the ids the engine's hand cards carry)."""
    if not form:
        return None
    key = (card, form)
    if key not in _forms:
        name, table = (f"{card}_EV1", 13) if form == 1 else (f"{card}_hero", 203)
        rows = [r for r in eng._call("findrow " + name)["rows"] if r[0] == table]
        _forms[key] = table * 1000000 + rows[0][1] if rows else None
    return _forms[key]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--battle", type=int, default=-1)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--lag", type=int, default=-3, help="place each play this many ticks after it was first seen")
    ap.add_argument("--dump", type=int, nargs=2, default=None, help="print both boards between two ticks")
    a = ap.parse_args()
    ids = json.load(open(HEADLESS / "engine_cards.json"))
    eng = engine.RealEngine()
    eng._call("setrow 72 6 0x60 256")
    tmpl = json.load(open(HEADLESS / "battle_golem.json"))
    summary = collections.defaultdict(list)
    track = collections.defaultdict(list)     # unit name -> (age ticks, position gap, hp gap)
    for bi, (frames, plays) in enumerate(battles(a.log)):
        if a.battle >= 0 and bi != a.battle:
            continue
        lv = tower_levels(frames)
        j = json.loads(json.dumps(tmpl))
        for s in (0, 1):
            j["battle"]["hbd"][s]["kt"] = lv[s]
            for sc in j["battle"][f"deck{s}"].get("sc", []):
                sc["l"] = lv[s] - 1          # princess level comes from the support card
        (HEADLESS / "live_redrive_tmp.json").write_text(json.dumps(j))
        eng.new_battle("live_redrive_tmp.json")
        # Plays: a play event, then the new units of that side within 6 ticks.
        spawns = find_spawns(frames)
        used, placed, unmatched = set(), [], []
        # Our side: the side whose units appear just after our taps.
        votes = collections.Counter(s[1] for who, t, _ in plays if who == "us"
                                    for s in spawns if 15 <= s[0] - t <= 45)
        mine = votes.most_common(1)[0][0] if votes else 1
        levels = collections.defaultdict(list)
        for sp in spawns:
            if sp[5]:
                levels[sp[1]].append(sp[5])
        side_level = {k: sorted(v)[len(v) // 2] for k, v in levels.items()}
        # Two passes: plays whose units carry the card's name first, then the rest by time.
        todo = list(plays)
        for strict in (True, False):
            rest = []
            for who, t, card in todo:
                side = mine if who == "us" else 1 - mine
                lo, hi = (t + 10, t + (150 if strict else 60)) if who == "us" else (t - 6, t + 6)
                key = card.lower().replace(" ", "")[:5]
                cand = [s for s in spawns if s[6] not in used and s[1] == side and lo <= s[0] <= hi
                        and (not any(k in s[2] for k in SKIP) or (strict and key in s[2].lower()))
                        and (not strict or key in s[2].lower())]
                if not cand:
                    rest.append((who, t, card))
                    continue
                first = min(cand, key=lambda s: abs(s[0] - (t + 26 if who == "us" else t)))
                group = [s for s in cand if s[0] == first[0]]
                for s in group:
                    used.add(s[6])
                name = first[2]
                # Where the player aimed: a flying spell (Fireball...) or a tunnelling
                # unit (Goblin Drill, Miner) is first seen at the king and ends at the
                # aim point; a rolling log starts at it; the rest are seen where placed.
                flying = any(k in name for k in ("Spell", "Dig")) or name.startswith("Miner")
                roll = [s for s in spawns if s[1] == side and "Rolling" in s[2] and first[0] <= s[0] <= first[0] + 30]
                if "Projectile" in name and roll:
                    # a thrown log (Barbarian Barrel...): it lands where the rolling log appears
                    x, y = roll[0][3], roll[0][4]
                elif flying:
                    x, y = last_pos(frames, first[6], first[2], first[0])
                else:
                    x = sum(s[3] for s in group) // len(group)
                    y = sum(s[4] for s in group) // len(group)
                form = 1 if "_ev" in name.lower() else 2 if name.endswith("Hero") or "Hero_" in name else 0
                level = first[5] if 0 < first[5] <= 15 else side_level.get(side, 11)
                placed.append((first[0], side, card, x, y, level, form))
            todo = rest
        unmatched += todo
        if a.verbose:
            print(f"battle {bi}: towers {lv}, our side {mine}, {len(placed)} plays placed, unmatched {unmatched[:8]}")
            for pl in sorted(placed):
                print("   placed", pl)
        placed.sort()
        rec = {t: u for t, u in frames}
        pi = 0
        first_diff, diffs = None, []
        pairs, born = {}, {}
        for t, units in frames:
            while pi < len(placed) and placed[pi][0] + a.lag <= t:
                pt, side, card, x, y, level, form = placed[pi]
                pi += 1
                os_ = ids.get(card)
                if os_ is None:
                    unmatched.append(("nocard", pt, card))
                    continue
                if eng.t < pt + a.lag:
                    eng.step(pt + a.lag - eng.t)
                lvl = max(0, min(15, level or 10))      # the reader gives the level index (level - 1)
                sel = {"os": os_, "pd": lvl << 10}
                fs = form_id(eng, card, form)
                if fs:
                    sel["pd"] |= form | (form << 19)
                    sel["fs"] = fs
                before = {o[6] for o in eng.state()["objects"]}
                eng._call("spawn " + json.dumps({"ct": 153, "c": {"t": eng.t, "t2": eng.t, "idHi": 0,
                                                                  "idLo": side + 1, "px": x, "py": y, "sid": 0,
                                                                  "sel": sel}}))
                if a.verbose:
                    eng.step(1)
                    new = sorted({o[0] for o in eng.state()["objects"] if o[6] not in before})
                    print(f"   spawn t {pt} side {side} {card} form {form} at ({x},{y}) -> {new}")
            if eng.t < t:
                eng.step(t - eng.t)
            s = eng.state()
            if HOOK is not None:
                HOOK(bi, t, s, units)
            if s["flags"][0]:
                break
            # Pair each real unit with an engine unit of the same name and side
            # (nearest, unpaired) and log their position and hitpoint gaps.
            emap = {o[6]: o for o in s["objects"] if o[4] > 0}
            for u in units:
                if u[7] in TOWERS or u[5] <= 0 or "Projectile" in u[7]:
                    continue
                key = (u[0], u[7])
                g = pairs.get(key)
                if g is None:
                    taken = set(pairs.values())
                    cand = [o for o in emap.values() if o[0] == u[7] and o[1] == u[1] and o[6] not in taken]
                    if not cand:
                        continue
                    o = min(cand, key=lambda o: (o[2] - u[2]) ** 2 + (o[3] - u[3]) ** 2)
                    pairs[key] = g = o[6]
                    born[key] = t
                o = emap.get(g)
                if o is None:
                    continue
                age = t - born[key]
                d = math.hypot(o[2] - u[2], o[3] - u[3])
                track[u[7]].append((age, d, u[5] - o[4]))
            if a.dump and a.dump[0] <= t <= a.dump[1]:
                ru = sorted((u[7], u[1], u[2] // 100, u[3] // 100, u[5]) for u in units
                            if u[5] > 0 and not any(k in u[7] for k in ("Projectile",)))
                eu = sorted((o[0], o[1], o[2] // 100, o[3] // 100, o[4]) for o in s["objects"]
                            if o[4] > 0 and "Projectile" not in o[0])
                print(f"--- t {t}")
                print(f"  real   {ru}")
                print(f"  engine {eu}")
            real_t = sorted((u[7], u[1], u[5]) for u in units if u[7] in TOWERS and u[5] > 0)
            eng_t = sorted((o[0], o[1], o[4]) for o in s["objects"] if o[0] in TOWERS and o[4] > 0)
            if [r[:2] for r in real_t] != [e[:2] for e in eng_t] or any(
                    abs(r[2] - e[2]) > 150 for r, e in zip(real_t, eng_t)):
                diffs.append((t, real_t, eng_t))
                if first_diff is None:
                    first_diff = t
            # per-unit-type hitpoints, both sides
            rc = collections.Counter((u[7], u[1]) for u in units if u[7] not in TOWERS and u[5] > 0)
            ec = collections.Counter((o[0], o[1]) for o in s["objects"] if o[0] not in TOWERS and o[4] > 0)
            for k in set(rc) | set(ec):
                if rc[k] != ec[k]:
                    summary[k].append(rc[k] - ec[k])
        print(f"battle {bi}: towers lv {lv}, plays {len(placed)} placed / {len(unmatched)} unmatched, "
              f"first tower divergence at tick {first_diff}")
        if diffs and a.verbose:
            for t, r, e in diffs[:3]:
                print(f"   t {t}: real {r}\n          engine {e}")
    print()
    print("Per unit type, real vs engine twin (first 60 ticks of each unit's life):")
    print(f"  {'unit':28s} {'samples':>7s} {'pos gap tiles mean / max':>26s} {'hp gap mean':>12s}")
    rows = []
    for name, v in track.items():
        early = [x for x in v if x[0] <= 60]
        if len(early) >= 3:
            rows.append((sum(x[1] for x in early) / len(early), name, early))
    for m, name, early in sorted(rows, reverse=True)[:30]:
        print(f"  {name:28s} {len(early):7d} {m / 1000:12.2f} / {max(x[1] for x in early) / 1000:5.2f}"
              f" {sum(x[2] for x in early) / len(early):12.0f}")
    print("\nUnit count differences (real minus engine), summed over frames, largest first:")
    for k, v in sorted(summary.items(), key=lambda kv: -sum(abs(x) for x in kv[1]))[:25]:
        print(f"  {k[0]:28s} side {k[1]}: frames {len(v):4d}, mean {sum(v) / len(v):+.2f}")
    eng.close()


if __name__ == "__main__":
    main()
