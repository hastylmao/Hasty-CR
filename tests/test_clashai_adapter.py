import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hastycr.adapters.clashai_sim import HeadlessSimAdapter


class ClashAIAdapterTests(unittest.TestCase):
    def test_simulator_adapter_lifecycle(self):
        adapter = HeadlessSimAdapter(num_envs=2, seed=42)
        self.assertTrue(adapter.is_available)
        states = adapter.reset()
        self.assertEqual(len(states), 2)


if __name__ == "__main__":
    unittest.main()
