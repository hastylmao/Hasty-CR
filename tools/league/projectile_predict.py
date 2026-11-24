"""Predict where and when a flying Goblin Barrel (or Rocket) lands, from reader frames
(2026-11-24).

Measured on 138 recorded live barrels (reports/live_play/2026111*.jsonl, "raw" frames):
the reader sees GoblinBarrelSpell for ~50 ticks (2.5 s, min 30) before the goblins appear;
raw unit field 7 is the target x exactly; the barrel flies in a straight line, so the line
through its first two sightings at x = target x gives the landing y. Landing error after two
sightings: median 13 game units (0.013 tile), p90 631.

    pp = ProjectilePredictor()
    for frame in frames:                     # reader raw frames: {"t": tick, "u": [...]}
        for p in pp.update(frame):           # new predictions, once per flying object
            print(p)  # dict(name, side, x, y, land_tick, seen_tick)

Rocket is included as UNVERIFIED (same field layout assumed: 19 sightings, 50-tick flight).
"""

FLYING = {"GoblinBarrelSpell": "GoblinBarrel", "RocketSpell": "Rocket"}


class ProjectilePredictor:
    def __init__(self):
        self.track = {}       # address -> [(t, x, y, target_x, side)]
        self.done = set()

    def update(self, frame):
        t = frame["t"]
        out = []
        alive = set()
        for u in frame.get("u", []):
            if len(u) <= 10 or u[10] not in FLYING:
                continue
            addr, side, x, y, tx = u[0], u[3], u[4], u[5], u[7]
            alive.add(addr)
            pts = self.track.setdefault(addr, [])
            if not pts or pts[-1][0] != t:
                pts.append((t, x, y, tx, side))
            if addr in self.done or len(pts) < 2:
                continue
            (t0, x0, y0, tx0, s), (t1, x1, y1, _, _) = pts[0], pts[-1]
            if x1 == x0 or t1 == t0:
                continue
            ly = y0 + (y1 - y0) * (tx0 - x0) / (x1 - x0)
            vy = (y1 - y0) / (t1 - t0)
            land = t1 + (ly - y1) / vy if vy else None
            if land is None or land < t1:
                continue
            self.done.add(addr)
            out.append(dict(name=FLYING[u[10]], side=s, x=int(tx0), y=int(ly), land_tick=int(round(land)),
                            seen_tick=t0))
        for a in [a for a in self.track if a not in alive]:
            del self.track[a]
            self.done.discard(a)
        return out
