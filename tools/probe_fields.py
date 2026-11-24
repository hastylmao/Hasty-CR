"""Find new battle fields in an hcr_probe dump (scripts/gamestate/native/hcr_probe.c).

    py -3.12 tools/probe_fields.py reports/probe/training1.jsonl

Read-only analysis of raw entity records captured during a match:

* target pointer: an 8-byte-aligned offset whose value, across combat units,
  is often the address of ANOTHER live entity in the same frame (and 0 when
  the unit has nothing to hit);
* deploy timer: an int32 offset that, on units first seen, counts down from a
  positive value to 0 within ~2 s and then stays 0;
* candidate fields of our player record that change only rarely (ability
  charge / cooldown candidates), with the ticks they changed at.

Prints ranked candidates; nothing is assumed until checked against the
screen or the simulator.
"""
from __future__ import annotations

import collections
import json
import struct
import sys


def frames(path):
    for line in open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line.startswith("{\"t\":") or line.startswith("{\"t\":-1"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        yield d


def main(path):
    fr = list(frames(path))
    print(f"{len(fr)} battle frames, ticks {fr[0]['t']}..{fr[-1]['t']}")
    # ------------------------------------------------------------ target pointer
    hits = collections.Counter()
    seen_nonzero = collections.Counter()
    samples = 0
    for d in fr[::3]:
        addrs = {u[0] for u in d["u"]}
        for addr, hx, name in d["u"]:
            if not name or "Tower" in name or "Projectile" in name:
                continue
            b = bytes.fromhex(hx)
            samples += 1
            for off in range(0, len(b) - 7, 8):
                v = struct.unpack_from("<Q", b, off)[0]
                if v:
                    seen_nonzero[off] += 1
                if v in addrs and v != addr:
                    hits[off] += 1
    print("\ntarget-pointer candidates (offset: share of unit-samples pointing at another live entity)")
    for off, n in hits.most_common(8):
        print(f"  +0x{off:03x}: {n / max(1, samples):.2f}  (non-zero {seen_nonzero[off] / max(1, samples):.2f})")
    # ------------------------------------------------------------ deploy timer
    first = {}
    series = collections.defaultdict(list)          # addr -> [(tick, bytes)]
    for d in fr:
        for addr, hx, name in d["u"]:
            if addr not in first:
                first[addr] = (d["t"], name)
            if d["t"] - first[addr][0] <= 120:
                series[addr].append((d["t"], bytes.fromhex(hx)))
    score = collections.Counter()
    tested = 0
    for addr, s in series.items():
        name = first[addr][1]
        if not name or "Tower" in name or len(s) < 8:
            continue
        tested += 1
        for off in range(0, len(s[0][1]) - 3, 4):
            v = [struct.unpack_from("<i", b, off)[0] for _, b in s]
            if v[0] <= 0 or v[0] > 5000:
                continue
            down = all(a >= b for a, b in zip(v, v[1:]))
            reaches = v[-1] == 0 and 0 in v[:len(v) * 3 // 4 + 1]
            if down and reaches and len(set(v)) > 3:
                score[off] += 1
    print(f"\ndeploy-timer candidates (offset: share of {tested} new units counting down to 0)")
    for off, n in score.most_common(6):
        print(f"  +0x{off:03x}: {n / max(1, tested):.2f}")
    # ------------------------------------------------------------ player record
    prev, changes = None, collections.defaultdict(list)
    for d in fr:
        if not d.get("me"):
            continue
        b = bytes.fromhex(d["me"])
        if prev is not None:
            for off in range(0, len(b) - 3, 4):
                a, c = struct.unpack_from("<i", prev, off)[0], struct.unpack_from("<i", b, off)[0]
                if a != c:
                    changes[off].append((d["t"], a, c))
        prev = b
    rare = sorted(((off, ch) for off, ch in changes.items() if 1 <= len(ch) <= 12),
                  key=lambda x: x[0])
    print("\nplayer-record int32 fields that changed 1-12 times (ability / charge candidates)")
    for off, ch in rare:
        print(f"  +0x{off:03x}: " + ", ".join(f"t{t}:{a}->{c}" for t, a, c in ch[:6]))


if __name__ == "__main__":
    main(sys.argv[1])
