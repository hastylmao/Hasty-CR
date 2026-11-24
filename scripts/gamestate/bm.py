"""Public-memory BM events and a single, priority-ordered ADB input worker.

Coordinates were inspected on instance 3 at 1080x1920. Tray readiness (100 ms)
and outside-tap dismissal still need active-battle validation. No vision runs.
"""
from collections import deque
import random
import threading
import time

TRAY = (105, 1640)
DISMISS = (1040, 150)  # outside tray, away from cards and deployable ground
SLOTS = [(x, y) for y in (1275, 1440) for x in (280, 470, 660, 850)]


class BMController:
    def __init__(self, cooldown=4.0, seed=None):
        self.cooldown = cooldown
        self.rng = random.Random(seed)
        self.reset()

    def reset(self):
        self.towers = {}
        self.threats = {}
        self.missing = {}
        self.last_tick = None
        self.last_sent = time.monotonic()
        self.event = None

    def observe(self, frame, side):
        now = time.monotonic()
        tick = frame['t']
        if self.last_tick is not None and tick <= self.last_tick:
            return
        self.last_tick = tick
        units = frame.get('u', [])
        towers = {u[0]: u[8] for u in units
                  if len(u) > 10 and u[10] in {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower','ChefTowerKing'} and u[3] != side}
        if any(hp < self.towers.get(uid, hp) for uid, hp in towers.items()):
            self.event = ('tower_damage', now)
        self.towers = towers
        own_towers = [u for u in units if len(u) > 10 and u[10] in {'KingTower','PrincessTower','Cannoneer','DaggerDuchess','ChefTower','ChefTowerKing'} and u[3] == side]
        if not own_towers:
            return
        low = own_towers[0][5] < 16000
        alive = {u[0] for u in units if u[8] > 0}
        for u in units:
            if (len(u) > 10 and u[3] != side and u[8] > 0
                    and u[9] > 0 and not any(s in u[10] for s in ('Tower', 'Projectile', 'Container'))
                    and u[10] and ((u[5] < 16000) if low else (u[5] > 16000))):
                self.threats[u[0]] = u[9]
        defeated = 0
        for uid in list(self.threats):
            if uid in alive:
                self.missing.pop(uid, None)
                continue
            self.missing.setdefault(uid, tick)
            if tick - self.missing[uid] >= 4:  # 200 ms confirmation
                defeated += self.threats.pop(uid)
                self.missing.pop(uid, None)
        if defeated >= 500:
            self.event = ('defence_kill', now)

    def proposal(self):
        now = time.monotonic()
        if now - self.last_sent < self.cooldown:
            return None
        reason = self.event[0] if self.event and now - self.event[1] < 3 else None
        if reason is None and now - self.last_sent < 7:
            return None
        # Pig = row 2, column 2 (index 5). Never index 0 (thumbs-up).
        slot = 5 if self.rng.random() < .5 else self.rng.choice((1, 2, 3, 4, 6, 7))
        return slot, reason or 'periodic'

    def accepted(self):
        self.last_sent = time.monotonic()
        self.event = None


class PriorityInput:
    """Inference never waits for emotes. Card jobs preempt tray readiness wait."""
    def __init__(self, tapper):
        self.tapper = tapper
        self.cv = threading.Condition()
        self.cards = deque()
        self.emote = None
        self.active = False
        self.generation = 0
        self.closed = False
        self.results = deque()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def tap_pair(self, a, b):
        with self.cv:
            self.cards.append((a, b, time.monotonic()))
            self.emote = None
            self.cv.notify_all()

    def tap(self, a):
        """One tap (an ability button), queued with card priority."""
        self.tap_pair(a, None)

    def battle(self, active):
        with self.cv:
            self.active = active
            self.generation += 1
            self.emote = None
            self.cards.clear()
            self.cv.notify_all()

    def offer(self, slot, reason):
        with self.cv:
            if not self.active or self.cards or self.emote is not None:
                return False
            self.emote = (slot, reason, time.monotonic(), self.generation)
            self.cv.notify_all()
            return True

    def drain(self):
        with self.cv:
            items = list(self.results)
            self.results.clear()
            return items

    def _run(self):
        while True:
            with self.cv:
                self.cv.wait_for(lambda: self.closed or self.cards or self.emote)
                if self.closed:
                    return
                card = self.cards.popleft() if self.cards else None
                emote = None if card else self.emote
                if emote:
                    self.emote = None
            start = time.monotonic()
            try:
                if card:
                    if card[1] is None:
                        self.tapper.tap(card[0])
                    else:
                        self.tapper.tap_pair(card[0], card[1])
                    result = {'input': 'card', 'queue_ms': round((start-card[2])*1000)}
                else:
                    slot, reason, queued, generation = emote
                    with self.cv:
                        if self.cards or not self.active or generation != self.generation or start-queued > .5:
                            continue
                    self.tapper.tap(TRAY)
                    with self.cv:
                        interrupted = self.cv.wait_for(
                            lambda: self.cards or self.closed or not self.active or generation != self.generation,
                            timeout=.1)
                    if not interrupted:
                        self.tapper.tap(SLOTS[slot])
                    # Always dismiss, including when a card arrives during opening.
                    self.tapper.tap(DISMISS)
                    result = {'emote_slot': slot+1, 'reason': reason,
                              'attempted': not interrupted}
                result['input_ms'] = round((time.monotonic()-start)*1000)
            except Exception as exc:
                result = {'input_error': str(exc)}
                with self.cv:
                    self.closed = True
                    self.cards.clear()
                    self.emote = None
            with self.cv:
                self.results.append(result)

    def close(self):
        with self.cv:
            self.closed = True
            self.cards.clear()
            self.emote = None
            self.cv.notify_all()
        self.thread.join(timeout=2)
        self.tapper.close()
