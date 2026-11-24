import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from gamestate.bm import BMController, PriorityInput, TRAY, DISMISS


def unit(uid, side, hp, name, y=24000, mx=1000):
    return [uid, 0, 0, side, 9000, y, 0, 11, hp, mx, name]


def test_pig_is_favoured_and_thumbs_up_never_chosen():
    bm = BMController(seed=7)
    slots = []
    for _ in range(1000):
        bm.last_sent = 0
        slots.append(bm.proposal()[0])
    assert 0 not in slots
    assert 450 < slots.count(5) < 550


def test_tower_damage_and_confirmed_defence_from_memory():
    bm = BMController()
    own = unit(1, 1, 4000, 'KingTower', mx=4000)
    enemy = unit(2, 0, 4000, 'PrincessTower', y=3000, mx=4000)
    threat = unit(3, 0, 700, 'HogRider')
    bm.observe({'t': 1, 'u': [own, enemy, threat]}, 1)
    enemy[8] = 3900
    bm.observe({'t': 2, 'u': [own, enemy, threat]}, 1)
    assert bm.event[0] == 'tower_damage'
    bm.event = None
    bm.observe({'t': 3, 'u': [own, enemy]}, 1)
    assert bm.event is None
    bm.observe({'t': 7, 'u': [own, enemy]}, 1)
    assert bm.event[0] == 'defence_kill'


def test_card_preempts_emote_before_selection_and_tray_is_dismissed():
    opened, done = threading.Event(), threading.Event()
    calls = []
    class FakeTapper:
        def tap(self, xy):
            calls.append(xy)
            if xy == TRAY:
                opened.set()
        def tap_pair(self, a, b):
            calls.append((a, b))
            done.set()
        def close(self):
            pass
    worker = PriorityInput(FakeTapper())
    try:
        worker.battle(True)
        assert worker.offer(5, 'tower_damage')
        assert opened.wait(1)
        worker.tap_pair((10, 20), (30, 40))
        assert done.wait(1)
        assert calls == [TRAY, DISMISS, ((10, 20), (30, 40))]
    finally:
        worker.close()


def test_no_emotes_outside_battle_or_during_cooldown():
    bm = BMController()
    assert bm.proposal() is None
    class FakeTapper:
        def close(self):
            pass
    worker = PriorityInput(FakeTapper())
    try:
        assert not worker.offer(5, 'periodic')
    finally:
        worker.close()
