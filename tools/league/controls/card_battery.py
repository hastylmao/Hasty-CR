"""Every card, every form, alone against towers: what does the engine do with it?

    card_battery.py --out runs/league/battery/new.jsonl [--cards A,B] [--level 11]

For each card and each form (0 base, 1 evolution, 2 hero) one battle: the card is
played at the left bridge (a spell: on the enemy's left princess tower) and the
enemy towers' hit points are traced for 900 ticks. For a form with an ability button
a second battle presses it 40 ticks after the first tower hit.

One line per battle: units seen (name, max hp), tower hits (first tick, the usual
gap between hits, the usual damage), what the ability press changed. `flags` lists
what looks wrong without a reference: engine error, deploy refused, no unit, a form
that plays exactly like the base, a hit gap that is not the table's HitSpeed.
The table check reads HitSpeed from the decoded tables next to the engine image
(HASTY_TABLES, default vendor/re/target/build_160635007/decoded); it is a hint, a
unit with an attack sequence or a charge legitimately differs.

This finds cards the engine runs wrongly on its own (Hero Electro Wizard's hit every
10 ticks was one). It does not prove a card right: only a comparison with the real
game does that (redrive_diag.py against scraped replays).
"""
import argparse
import collections
import json
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/league"))
import realsim  # noqa: E402


class AnyHero(dict):
    """Every hero form may load here; the button cost only fills the ability row."""
    def __contains__(self, k):
        return True

    def __getitem__(self, k):
        return 2


realsim.HERO_COST = AnyHero()
# Fillers are spells cast into our own corner: they cycle the deck without putting a
# body on the board or touching a tower.
FILL = ["Fireball", "Arrows", "Zap", "Poison", "Log", "Earthquake", "Snowball", "Rocket"]
CORNER = (16500, 1500)
WAIT = 30            # ticks after a play before the hand is read: the play has left it by then


def table_hitspeeds():
    root = Path(os.environ.get("HASTY_TABLES", ROOT / "vendor/re/target/build_160635007/decoded"))
    out = {}
    for f in root.rglob("*.toml"):
        sec = None
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"\s*\[+(?:CHARACTER|EXT|BUILDING)\.([A-Za-z0-9_]+)\]+", line)
            if m:
                sec = m.group(1)
                continue
            if re.match(r"\s*\[", line):
                sec = None
                continue
            m = re.match(r"\s*HitSpeed\s*=\s*(\d+)", line)
            if m and sec:
                out.setdefault(sec, int(m.group(1)))
    return out


def _play(b, slot, x, y):
    b.eng._call("setelixir 0 10000")
    b.step([], 1)                      # so the wrapper's own elixir check sees the refill
    return b.step([(0, slot, x * realsim.SUB, y * realsim.SUB)], 1)[0][1]


def _cycle_back(b, cid):
    """Play fillers until `cid` is in hand again. Returns its slot or None."""
    for _ in range(8):
        hand = json.loads(b.state_json())["players"][0]["hand"]
        if cid in hand:
            return hand.index(cid)
        slot = next(i for i, c in enumerate(hand) if c != cid)
        _play(b, slot, *CORNER)
        b.step([], WAIT)
    return None


def run(b, names, card, form, level, press, pre=0):
    """`pre`: plays of the card in the other lane before the traced one (an evolution
    is the card's 2nd or 3rd play). Only the left princess and the king are traced,
    and only bodies in the left half are listed."""
    cid = names[card]
    d = [cid] + [names[n] for n in FILL if n != card][:7]
    b.reset(seed=3, decks=[d, d], shuffle=0, forms=[[form] + [0] * 7, [0] * 8],
            levels=[[level] * 8, [level] * 8], tower_levels=[level, level])
    b.step([], 100)
    kind = b.cat[cid][8]
    pre_codes = []
    for _ in range(pre):
        slot = _cycle_back(b, cid)
        pre_codes.append(_play(b, slot, *(CORNER if kind == "SPELL" else (14500, 10500))))
        b.step([], WAIT)
    slot = _cycle_back(b, cid)
    x, y = {"SPELL": (3500, 25500), "BUILDING": (3500, 12500)}.get(kind, (3500, 14500))
    t0 = b.eng.t
    code = _play(b, slot, x, y)
    if code != 0:
        # Not legal there (the Log, Royal Delivery, Royal Recruits ...): our side, mid-lane.
        x, y = 3500, 10500
        code = _play(b, _cycle_back(b, cid), x, y)
    if code != 0:
        # Still refused (Royal Recruits take the whole width): the first tile the engine allows.
        slot = _cycle_back(b, cid)
        for ty in range(10, 0, -1):
            for tx in (8, 9, 5, 12, 3, 14):
                if code != 0 and b.check_deploy(0, slot, (tx * 1000 + 500) * realsim.SUB, (ty * 1000 + 500) * realsim.SUB) == 0:
                    x, y = tx * 1000 + 500, ty * 1000 + 500
                    code = _play(b, slot, x, y)
    trace, last, units, own_peak, pressed_at, abil_seen = [], None, {}, 0, None, False
    for _ in range(900):
        cmds = []
        if press and pressed_at is None and trace and b.eng.t >= trace[0][0] + 40:
            cmds, pressed_at = [(0, 4, 0, 0)], b.eng.t
        b.step(cmds, 1)
        s = json.loads(b.state_json())
        mine = [o for o in b.s["objects"] if o[1] == 0 and o[0] not in ("KingTower", "PrincessTower") and (o[2] < 9000 or x >= 8000)]
        own_peak = max(own_peak, len(mine))
        for o in mine:
            units[o[0]] = max(units.get(o[0], 0), o[5])
        abil_seen = abil_seen or any(r[0] for r in s["players"][0].get("abilities") or [])
        hp = s["players"][1]["tower_hp"][:2]
        if last is not None and hp != last:
            trace.append((b.eng.t - t0, sum(a - c for a, c in zip(last, hp))))
        last = hp
    gaps = [t2 - t1 for (t1, _), (t2, _) in zip(trace, trace[1:])]
    return {"card": card, "form": form, "kind": kind, "press": bool(press), "pre": pre, "pre_codes": pre_codes, "deploy_code": code, "at": [x, y],
            "units": sorted(units.items()), "own_peak": own_peak, "hits": len(trace),
            "first_hit": trace[0][0] if trace else None,
            "gap": statistics.median(gaps) if gaps else None,
            "gaps": dict(collections.Counter(gaps).most_common(4)),
            "dmg": statistics.median([d_ for _, d_ in trace]) if trace else None,
            "dmg_total": sum(d_ for _, d_ in trace), "tower_hp_end": last,
            "ability_button": abil_seen, "pressed_at": pressed_at}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cards", default="")
    ap.add_argument("--level", type=int, default=11)
    ap.add_argument("--forms", default="0,1,2")
    a = ap.parse_args()
    hs = table_hitspeeds()
    b = realsim.RealBattle()
    names = {r[0]: i for i, r in enumerate(b.cat)}
    cards = [c for c in a.cards.split(",") if c] or [r[0] for r in b.cat]
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = {}
    with out.open("w") as f:
        for card in cards:
            for form in [int(x) for x in a.forms.split(",")]:
                for press in (0, 1):
                    if press and not (rec.get("ability_button") and "error" not in rec):
                        continue
                    try:
                        rec = run(b, names, card, form, a.level, press)
                        # An evolution is the 2nd or 3rd play of the card: repeat with
                        # earlier plays until the board shows something the base did not.
                        for pre in (1, 2):
                            if form != 1 or press or card not in base or (rec["units"], rec["hits"], rec["gap"], rec["dmg"]) != base[card]:
                                break
                            rec = run(b, names, card, form, a.level, press, pre)
                    except Exception as e:                      # engine fault, refused form ...
                        rec = {"card": card, "form": form, "press": bool(press), "error": f"{type(e).__name__}: {e}"[:300]}
                        try:
                            b = realsim.RealBattle()
                        except Exception as e2:
                            rec["error"] += f" | restart: {e2}"[:200]
                    flags = []
                    if "error" in rec:
                        flags.append("error")
                    else:
                        if rec["deploy_code"] != 0:
                            flags.append("deploy_refused")
                        if rec["kind"] != "SPELL" and not rec["units"]:
                            flags.append("no_unit")
                        if rec["kind"] == "SPELL" and rec["hits"] == 0:
                            flags.append("spell_no_tower_damage")
                        sig = (rec["units"], rec["hits"], rec["gap"], rec["dmg"])
                        if form == 0 and not press:
                            base[card] = sig
                        elif not press and base.get(card) == sig:
                            flags.append("same_as_base")
                        if press and rec["pressed_at"] is None:
                            flags.append("press_never_sent")
                        for name, _ in rec["units"]:
                            want = hs.get(name)
                            if want and rec["gap"] and rec["own_peak"] == 1 and abs(rec["gap"] * 50 - want) > 100:
                                flags.append(f"gap {rec['gap'] * 50} ms, table HitSpeed {want}")
                    rec["flags"] = flags
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    print(card, form, "press" if press else "", flags, file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
