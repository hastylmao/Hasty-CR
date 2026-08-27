"""HastyCR adapter for high-speed headless Clash Royale simulation via ClashAI.

Enables self-play RL training, benchmark rollout generation, and policy evaluation
at >2,000 steps per second without emulator or screen capture overhead.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

ROOT = Path(__file__).resolve().parents[3]
CLASHAI_SRC = ROOT / "vendor" / "ClashAI" / "icebow" / "src"

if str(CLASHAI_SRC) not in sys.path:
    sys.path.insert(0, str(CLASHAI_SRC))


class HeadlessSimAdapter:
    """Wrapper around ClashAI's vectorized C++/Python simulation environment."""

    def __init__(self, num_envs: int = 4, seed: int = 42):
        self.num_envs = num_envs
        self.seed = seed
        self._envs: List[Any] = []
        self._initialized = False
        self._init_environments()

    def _init_environments(self) -> None:
        try:
            from clashrl.config import Config
            from clashrl.sim.env import SimMatchEnv

            cfg = Config.load()
            for i in range(self.num_envs):
                env = SimMatchEnv(cfg, seed=self.seed + i)
                self._envs.append(env)
            self._initialized = True
        except Exception as e:
            self._init_error = str(e)
            self._initialized = False

    @property
    def is_available(self) -> bool:
        return self._initialized and len(self._envs) > 0

    def step(self, actions: List[Tuple[int, int, int]]) -> List[Dict[str, Any]]:
        """Step all active environments simultaneously."""
        results = []
        if not self._initialized:
            return results

        for env, action in zip(self._envs, actions):
            try:
                obs, reward, done, info = env.step(action)
                results.append({
                    "obs": obs,
                    "reward": reward,
                    "done": done,
                    "info": info
                })
            except Exception as e:
                results.append({
                    "error": str(e),
                    "done": True,
                    "reward": 0.0
                })
        return results

    def reset(self) -> List[Any]:
        """Reset all simulation environments to initial states."""
        if not self._initialized:
            return []
        return [env.reset() for env in self._envs]
