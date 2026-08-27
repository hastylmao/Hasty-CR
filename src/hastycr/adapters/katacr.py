from __future__ import annotations

import sys
import types
import os
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np


BAR_SIZE = (24, 8)
N_BAR_SIZE = BAR_SIZE[0] * BAR_SIZE[1]
ARENA_CHANNELS = 2 + 2 * N_BAR_SIZE

# These IDs come from the classifier config shipped with the published
# StARformer checkpoint.  They are not the global Clash Royale card IDs.
CARD_IDS = {
    "cannon": 0,
    "empty": 1,
    "blank": 1,
    "fireball": 2,
    "hog_rider": 3,
    "hog-rider": 3,
    "ice_golem": 4,
    "ice-golem": 4,
    "ice_spirit": 5,
    "ice-spirit": 5,
    "ice_spirit_evolution": 6,
    "ice-spirit-evolution": 6,
    "musketeer": 7,
    "skeletons": 8,
    "skeletons_evolution": 9,
    "skeletons-evolution": 9,
    "the_log": 10,
    "the-log": 10,
}

MODEL_DECK_NAMES = frozenset(
    {"cannon", "fireball", "hog_rider", "ice_golem", "ice_spirit",
     "musketeer", "skeletons", "the_log"}
)


def _patch_orbax_windows_urls() -> None:
    """Repair old Orbax/TensorStore OCDBT file URLs on native Windows."""
    if os.name != "nt":
        return
    from orbax.checkpoint import type_handlers

    original = type_handlers.get_tensorstore_spec
    if getattr(original, "_hastycr_windows_fix", False):
        return

    def fixed(*args, **kwargs):
        spec = original(*args, **kwargs)
        kvstore = spec.get("kvstore", {})
        base = kvstore.get("base")
        if isinstance(base, str) and base.startswith("file://"):
            path = base[len("file://"):].replace("\\", "/")
            # A drive letter requires three slashes: file:///C:/path.
            kvstore["base"] = "file:///" + path.lstrip("/")
        return spec

    fixed._hastycr_windows_fix = True
    type_handlers.get_tensorstore_spec = fixed

    # The public checkpoint records cuda:0 SingleDeviceSharding.  Native
    # Windows JAX is CPU-only, so remap that storage annotation to the local
    # CPU; it does not alter parameter values or model math.
    original_sharding = type_handlers._deserialize_sharding_from_json_string
    if not getattr(original_sharding, "_hastycr_cpu_fix", False):
        def fixed_sharding(value):
            try:
                return original_sharding(value)
            except ValueError as exc:
                if "SingleDeviceSharding" not in str(exc):
                    raise
                import jax
                return jax.sharding.SingleDeviceSharding(jax.devices("cpu")[0])

        fixed_sharding._hastycr_cpu_fix = True
        type_handlers._deserialize_sharding_from_json_string = fixed_sharding


def _normalise_unit(name: str) -> str:
    aliases = {
        "minipekka": "mini-pekka",
        "brawler": "goblin-brawler",
        "elixir-golem-large": "elixir-golem-big",
        "elixir-golem-medium": "elixir-golem-mid",
        "phoenix-large": "phoenix-big",
        "phoenix-small": "phoenix-small",
        "fire-cracker": "firecracker",
    }
    value = name.lower().replace("_", "-")
    return aliases.get(value, value)


def grid_to_mumu(x: int, y: int) -> tuple[int, int]:
    """Map KataCR's top-down 18x32 arena grid to MuMu's 1080x1920 pixels."""
    if not (0 <= x < 18 and 0 <= y < 32):
        raise ValueError(f"KataCR grid position out of bounds: {(x, y)}")
    return round(103.5 + 51.0 * x), round(171.9 + 41.4 * y)


def _place(arena: np.ndarray, mask: np.ndarray, x: int, y: int, cls: int, bel: int) -> None:
    """Place at the nearest free cell, matching KataCR's collision resolution intent."""
    x, y = int(np.clip(x, 0, 17)), int(np.clip(y, 0, 31))
    candidates = [(x, y)]
    for radius in range(1, 4):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue
                candidates.append((x + dx, y + dy))
    for cx, cy in candidates:
        if 0 <= cx < 18 and 0 <= cy < 32 and not mask[cy, cx]:
            arena[cy, cx, 0] = cls
            arena[cy, cx, 1] = bel
            mask[cy, cx] = True
            return


def build_structured_state(state: Any, unit2idx: dict[str, int]) -> dict[str, np.ndarray]:
    """Translate a ClashRoyaleBuildABot State into KataCR's observation schema."""
    arena = np.zeros((32, 18, ARENA_CHANNELS), dtype=np.int32)
    mask = np.zeros((32, 18), dtype=np.bool_)

    # BuildABot uses a bottom-up tile y; KataCR uses top-down y.
    for side, detections in ((-1, state.allies), (1, state.enemies)):
        for detection in detections:
            name = _normalise_unit(detection.unit.name)
            cls = unit2idx.get(name)
            if cls is None:
                continue
            _place(
                arena,
                mask,
                int(detection.position.tile_x),
                31 - int(detection.position.tile_y),
                cls,
                side,
            )

    # BuildABot's unit detector omits towers.  Fixed tower tokens provide the
    # positional context seen during policy training; masks follow live HP bars.
    tower_specs = (
        ("enemy_king_hp", "king-tower", 9, 3, 1),
        ("left_enemy_princess_hp", "queen-tower", 4, 7, 1),
        ("right_enemy_princess_hp", "queen-tower", 14, 7, 1),
        ("left_ally_princess_hp", "queen-tower", 4, 24, -1),
        ("right_ally_princess_hp", "queen-tower", 14, 24, -1),
        ("ally_king_hp", "king-tower", 9, 28, -1),
    )
    numbers = state.numbers
    for attr, name, x, y, bel in tower_specs:
        hp = getattr(getattr(numbers, attr, None), "number", 1)
        if hp > 0.10 and name in unit2idx:
            _place(arena, mask, x, y, unit2idx[name], bel)

    cards = np.array(
        [CARD_IDS.get(card.name, CARD_IDS["empty"]) for card in state.cards],
        dtype=np.int32,
    )
    if cards.shape != (5,):
        raise ValueError(f"Expected [next, hand1..4], got {cards.shape}")
    elixir = int(np.clip(round(state.numbers.elixir.number), 0, 10))
    return {"arena": arena, "arena_mask": mask, "cards": cards,
            "elixir": np.array(elixir, dtype=np.int32)}


class KataPolicy:
    """Model-only KataCR StARformer runner with a causal 50-step history."""

    def __init__(self, kata_root: Path, checkpoint_dir: Path, epoch: int = 3):
        self.kata_root = Path(kata_root).resolve()
        self.checkpoint_dir = Path(checkpoint_dir).resolve()
        sys.path.insert(0, str(self.kata_root))

        # starformer imports BAR constants from the heavyweight training dataset.
        # A tiny module shim avoids pulling Torch/OpenCV/SciPy into inference.
        dataset_name = "katacr.policy.offline.dataset"
        if dataset_name not in sys.modules:
            shim = types.ModuleType(dataset_name)
            shim.BAR_SIZE = BAR_SIZE
            shim.BAR_RGB = False
            sys.modules[dataset_name] = shim

        import jax
        _patch_orbax_windows_urls()
        from katacr.constants.label_list import unit2idx
        from katacr.policy.offline.starformer import StARConfig, StARformer, TrainConfig
        from katacr.utils.ckpt_manager import CheckpointManager

        loaded = CheckpointManager(str(self.checkpoint_dir)).restore(epoch)
        self.cfg = loaded["config"]
        self.model = StARformer(StARConfig(**self.cfg))
        self.model.create_fns()
        train_cfg = TrainConfig(**self.cfg)
        base_state = self.model.get_state(train_cfg, train=False)
        self.state = base_state.replace(
            params=loaded["variables"]["params"], tx=None, opt_state=None
        )
        self.rng = jax.random.PRNGKey(42)
        self.unit2idx = unit2idx
        self.n_step = int(self.model.cfg.n_step)
        self.reset()

    def reset(self) -> None:
        self.obs = {key: deque(maxlen=getattr(self, "n_step", 50))
                    for key in ("arena", "arena_mask", "cards", "elixir")}
        self.actions = {key: deque(maxlen=getattr(self, "n_step", 50))
                        for key in ("select", "pos")}
        self.rtg = deque(maxlen=getattr(self, "n_step", 50))
        self.timestep = deque(maxlen=getattr(self, "n_step", 50))
        self.previous_action = (0, 0, -1)

    def _pad(self, values: deque, dtype=None) -> np.ndarray:
        stacked = np.stack(values)
        shape = (self.n_step,) + stacked.shape[1:]
        out = np.zeros(shape, dtype=dtype or stacked.dtype)
        out[: len(stacked)] = stacked
        return out[None, ...]

    def predict(self, state: Any, elapsed_seconds: int, rtg: float = 3.0) -> tuple[int, int, int, int]:
        import jax

        obs = build_structured_state(state, self.unit2idx)
        select, x, y = self.previous_action
        max_time = int(self.model.cfg.max_timestep)
        timestamp = np.array(min(max(elapsed_seconds, 0), max_time), np.int32)
        # The published policy was trained at 5 FPS. Full ADB capture plus the
        # BuildABot detector runs near 1 FPS, so repeat the latest structured
        # observation to keep the 50-token context near its trained 10-second
        # horizon instead of stretching it across roughly 50 seconds.
        for repeat_idx in range(5):
            for key, value in obs.items():
                self.obs[key].append(value)
            action_select = select if repeat_idx == 0 else 0
            action_pos = (y, x) if repeat_idx == 0 else (-1, 0)
            self.actions["select"].append(np.array(action_select, np.int32))
            self.actions["pos"].append(np.array(action_pos, np.int32))
            self.rtg.append(np.array(rtg, np.float32))
            self.timestep.append(timestamp)
        step_len = len(self.timestep)
        self.rng, use_rng = jax.random.split(self.rng)
        action, *_ = self.model.predict(
            self.state,
            {key: self._pad(values) for key, values in self.obs.items()},
            {key: self._pad(values) for key, values in self.actions.items()},
            self._pad(self.rtg),
            self._pad(self.timestep),
            step_len,
            use_rng,
            True,
        )
        slot, px, py, delay = map(int, np.asarray(jax.device_get(action))[0])
        # The next observation must contain the action that was actually sent,
        # not merely the model's candidate.  Call record_action after both taps.
        self.previous_action = (0, 0, -1)
        return slot, px, py, delay

    def record_action(self, slot: int, x: int, y: int) -> None:
        self.previous_action = (int(slot), int(x), int(y))
