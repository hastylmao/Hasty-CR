"""Automated unit tests for Hog 2.6 defensive micro tactics and tower HP detection."""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import policy_shims
import tower_hp


class MockNumber:
    def __init__(self, number: float):
        self.number = number


class MockCard:
    def __init__(self, name: str, cost: int):
        self.name = name
        self.cost = cost


class MockUnit:
    def __init__(self, name: str, tile_x: float, tile_y: float):
        self.name = name
        self.position = SimpleNamespace(tile_x=tile_x, tile_y=tile_y)


class TestDefensiveMicro(unittest.TestCase):
    def setUp(self):
        policy_shims._defend_at = 0.0
        policy_shims._defend_size = 0
        policy_shims._defend_centre = (9.0, 20.0)
        policy_shims._hog_sent_at = 0.0
        policy_shims._hog_sent_lane = 4
        self.deck = [
            MockCard("blank", 0),
            MockCard("hog_rider", 4),
            MockCard("cannon", 3),
            MockCard("ice_golem", 2),
            MockCard("musketeer", 4),
        ]
        self.ready = [0, 1, 2, 3]
        self.numbers = SimpleNamespace(
            elixir=MockNumber(6.0),
            left_enemy_princess_hp=MockNumber(1.0),
            right_enemy_princess_hp=MockNumber(1.0),
            left_ally_princess_hp=MockNumber(1.0),
            right_ally_princess_hp=MockNumber(1.0),
        )

    def test_cross_lane_ice_golem_kite_left_threat(self):
        """When a heavy melee threat crosses the left bridge (x=4, y=18), Ice Golem should kite to right (10, 18)."""
        enemies = [
            MockUnit("pekka", tile_x=4.0, tile_y=13.0),
            MockUnit("mega_knight", tile_x=4.5, tile_y=12.0),
        ]
        state = SimpleNamespace(
            cards=self.deck,
            ready=self.ready,
            numbers=self.numbers,
            enemies=enemies,
            allies=[],
        )
        
        res = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)
        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        
        self.assertEqual(slot, 3)  # ice_golem is slot index 2 (+ 1 = 3)
        self.assertEqual((x, y), (10, 18))
        self.assertIn("kite_ice_golem", note)

    def test_cannon_pull_geometry_left_threat(self):
        """When Ice Golem is not in hand, Cannon should pull to optimal 4-3 spot (9, 20)."""
        deck = [
            MockCard("blank", 0),
            MockCard("hog_rider", 4),
            MockCard("cannon", 3),
            MockCard("skeletons", 1),
            MockCard("musketeer", 4),
        ]
        enemies = [
            MockUnit("pekka", tile_x=4.0, tile_y=13.0),
            MockUnit("valkyrie", tile_x=4.5, tile_y=12.0),
        ]
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=self.numbers,
            enemies=enemies,
            allies=[],
        )
        
        res = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)
        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        
        self.assertEqual(slot, 2)  # cannon is slot 1 (+ 1 = 2)
        self.assertEqual((x, y), (9, 20))
        self.assertIn("defend_cannon_pull", note)

    def test_skeletons_center_distraction(self):
        """When a single threat is deep and neither Ice Golem nor Cannon are available, Skeletons distract in center (9, 21)."""
        deck = [
            MockCard("blank", 0),
            MockCard("hog_rider", 4),
            MockCard("the_log", 2),
            MockCard("skeletons", 1),
            MockCard("musketeer", 4),
        ]
        enemies = [
            MockUnit("mini_pekka", tile_x=4.0, tile_y=10.0),  # y=21
        ]
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=self.numbers,
            enemies=enemies,
            allies=[],
        )
        
        res = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)
        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        
        self.assertEqual(slot, 3)  # skeletons is slot 2 (+ 1 = 3)
        self.assertEqual((x, y), (9, 21))
        self.assertIn("defend_skeletons_distract", note)

    def test_anti_leak_cycling(self):
        """When elixir reaches 9.5+ with no enemy threat and no Hog in hand, cycle a 1-elixir card at the back."""
        deck = [
            MockCard("blank", 0),
            MockCard("fireball", 4),
            MockCard("cannon", 3),
            MockCard("ice_spirit", 1),
            MockCard("musketeer", 4),
        ]
        numbers = SimpleNamespace(
            elixir=MockNumber(9.8),
            left_enemy_princess_hp=MockNumber(1.0),
            right_enemy_princess_hp=MockNumber(1.0),
            left_ally_princess_hp=MockNumber(1.0),
            right_ally_princess_hp=MockNumber(1.0),
        )
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=numbers,
            enemies=[],
            allies=[],
        )
        
        res = policy_shims.apply(state, slot=2, x=9, y=21, delay=0)
        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        
        self.assertEqual(slot, 3)  # ice_spirit is slot 2 (+ 1 = 3)
        self.assertIn("anti_leak_cycle", note)

    def test_tower_finisher_fireball(self):
        """When enemy tower drops below 0.18 HP and half is safe, Fireball should snipe it."""
        deck = [
            MockCard("blank", 0),
            MockCard("hog_rider", 4),
            MockCard("fireball", 4),
            MockCard("skeletons", 1),
            MockCard("musketeer", 4),
        ]
        numbers = SimpleNamespace(
            elixir=MockNumber(5.0),
            left_enemy_princess_hp=MockNumber(0.14),
            right_enemy_princess_hp=MockNumber(1.0),
            left_ally_princess_hp=MockNumber(1.0),
            right_ally_princess_hp=MockNumber(1.0),
        )
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=numbers,
            enemies=[],
            allies=[],
        )
        
        res = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)
        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        
        self.assertEqual(slot, 2)  # fireball slot (+ 1 = 2)
        self.assertEqual((x, y), (4, 7))  # Left enemy princess tower coordinates
        self.assertIn("finish_left", note)

    def test_repeated_defense_same_push_is_vetoed(self):
        """After answering a push, the next tick should not stack another defender into the same fight."""
        enemies = [
            MockUnit("pekka", tile_x=4.0, tile_y=11.0),
            MockUnit("valkyrie", tile_x=4.5, tile_y=11.5),
        ]
        state = SimpleNamespace(
            cards=self.deck,
            ready=self.ready,
            numbers=self.numbers,
            enemies=enemies,
            allies=[],
        )

        first = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)
        second = policy_shims.apply(state, slot=1, x=4, y=16, delay=0)

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_hog_spell_support_targets_lane_cluster(self):
        """A just-played Hog may get Fireball support only when defenders cluster in its lane."""
        policy_shims._hog_sent_at = policy_shims.time.monotonic()
        policy_shims._hog_sent_lane = 14
        deck = [
            MockCard("blank", 0),
            MockCard("fireball", 4),
            MockCard("the_log", 2),
            MockCard("ice_spirit", 1),
            MockCard("musketeer", 4),
        ]
        numbers = SimpleNamespace(
            elixir=MockNumber(5.0),
            left_enemy_princess_hp=MockNumber(1.0),
            right_enemy_princess_hp=MockNumber(1.0),
            left_ally_princess_hp=MockNumber(1.0),
            right_ally_princess_hp=MockNumber(1.0),
        )
        enemies = [
            MockUnit("goblins", tile_x=14.0, tile_y=17.0),
            MockUnit("spear_goblins", tile_x=15.0, tile_y=17.0),
        ]
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=numbers,
            enemies=enemies,
            allies=[],
        )

        res = policy_shims.apply(state, slot=4, x=9, y=25, delay=0)

        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        self.assertEqual(slot, 1)
        self.assertIn("support_fireball_hog_cluster", note)

    def test_safe_bad_spell_cycles_cheap_card(self):
        """When safe, a low-value spell proposal should cycle instead of being vetoed forever."""
        deck = [
            MockCard("blank", 0),
            MockCard("fireball", 4),
            MockCard("cannon", 3),
            MockCard("skeletons", 1),
            MockCard("musketeer", 4),
        ]
        numbers = SimpleNamespace(
            elixir=MockNumber(7.0),
            left_enemy_princess_hp=MockNumber(1.0),
            right_enemy_princess_hp=MockNumber(1.0),
            left_ally_princess_hp=MockNumber(1.0),
            right_ally_princess_hp=MockNumber(1.0),
        )
        state = SimpleNamespace(
            cards=deck,
            ready=self.ready,
            numbers=numbers,
            enemies=[],
            allies=[],
        )

        res = policy_shims.apply(state, slot=1, x=9, y=20, delay=0)

        self.assertIsNotNone(res)
        slot, x, y, delay, note = res
        self.assertEqual(slot, 3)
        self.assertIn("veto_fireball_cycle_skeletons", note)


if __name__ == "__main__":
    unittest.main()
