"""Read-only probe: what does the client hold about the opponent? (2026-11-20)

The owner believes the Clash Royale client exposes the opponent's deck and hand
(paid hacks show them). In the first friendly (2026-10) the opponent's hand vector
(+0x210/+0x21C) read as -1. This compares both player records field by field,
during a live battle, a few times, to find where the opponent's deck, hand,
cycle and elixir are, if anywhere.

Small reads only: two 0x400-byte player records, plus up to 64 bytes behind each
pointer-like field. No heap scan (bulk heap reads made the game exit, 2026-10).
Usage: start a battle on instance 3, then
  .venvs\\royalegym\\Scripts\\python.exe scripts\\gamestate\\opp_probe.py
Output: reports/opp_probe/<time>.json and a printed summary.
"""
from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "gamestate"), str(ROOT / "scripts")]
from memread import GameMemory  # noqa: E402

REC = 0x400


def i32s(b):
    return list(struct.unpack(f"<{len(b) // 4}i", b[:len(b) // 4 * 4]))


def looks_ptr(v):
    return 0x10000 < v < 0x7FFFFFFFFFFF and v % 4 == 0


def sample(g, b):
    ps = g.u64(b + 0xA8)
    out = {"tick": struct.unpack("<i", g.read(b + 0x60, 4))[0], "players": []}
    for k in range(2):
        p = g.u64(ps + 0xE0 + 8 * k)
        raw = g.read(p, REC)
        if len(raw) < REC:
            continue
        rec = {"addr": hex(p), "side": struct.unpack_from("<i", raw, 0x78)[0],
               "elixir_raw": struct.unpack_from("<i", raw, 0x2F8)[0],
               "played_total": struct.unpack_from("<i", raw, 0x318)[0],
               "played_ids": list(struct.unpack_from("<8i", raw, 0x288)),
               "ints": i32s(raw), "behind": {}}
        # Vector-like fields: pointer + small count somewhere after it.
        for off in range(0, REC - 8, 8):
            v = struct.unpack_from("<Q", raw, off)[0]
            if looks_ptr(v):
                rec["behind"][hex(off)] = i32s(g.read(v, 64))
        out["players"].append(rec)
    return out


def main():
    g = GameMemory()
    print("waiting for a battle...")
    while not g.battle():
        time.sleep(2)
    samples = []
    for n in range(8):
        b = g.battle()
        if not b:
            break
        samples.append(sample(g, b))
        print(f"sample {n}: tick {samples[-1]['tick']}")
        time.sleep(6)
    d = ROOT / "reports" / "opp_probe"
    d.mkdir(parents=True, exist_ok=True)
    path = d / time.strftime("%Y%m%d_%H%M%S.json")
    path.write_text(json.dumps(samples))
    for s in samples[-1:]:
        for r in s["players"]:
            print(f"side {r['side']}: elixir_raw {r['elixir_raw']} played {r['played_total']} {r['played_ids']}")
            h = r["behind"].get("0x210")
            print("   +0x210 hand vec:", h[:8] if h else None, " +0x220 cycle vec:", (r["behind"].get("0x220") or [None])[:8])
    print("saved", path)


if __name__ == "__main__":
    main()
