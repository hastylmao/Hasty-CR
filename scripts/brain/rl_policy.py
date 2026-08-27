"""Drive the live bot with a checkpoint trained in the simulator.

`scripts/cr_bot.py` says, at the top of the file, "No learned checkpoint in the
hot path" - the runner has always been the hand-written `Brain`. That was the
right call when the learned thing was a StARformer that cost too much per
frame, but it left the RL work with nowhere to go: a policy could get as good
as it liked in the simulator and never touch a real match.

This is the bridge. It exposes the one method the runner calls -
`decide(state, elapsed, now, frame=None) -> Candidate | None` - so swapping it
in is a one-line change and everything downstream (tap timing, hand tracking,
match filtering) is untouched.

**Why the coordinates line up.** The simulator's action grid and the live grid
are the same convention, checked rather than assumed: both are 18x32 with the
river at row 16, our half at y >= 16, enemy princess towers at y=7 and ours at
y=24. So a decoded action `(slot, x, y)` is already a live grid cell and needs
no transform. The *observation* is the one that flips - `sim.env.observe` bins
a unit at tile y into plane row 31-y - and that flip is applied here too.
`tests/test_rl_policy.py` asserts both, because a silent mirror is the single
most expensive bug this project has hit.

**What is approximated, honestly.** The simulator observes each unit's current
hit points; live vision does not measure HP, so a detected unit contributes its
card's full HP. A half-dead Musketeer therefore looks healthy to the policy.
That is a real gap, not a rounding detail, and it is the first thing to suspect
if live behaviour diverges from simulated behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.env import (ACTIONS, CARD_ACTIONS, DECK_26, GRID_H, GRID_W,
                     NUM_PLANES, NUM_SCALARS, NUM_SLOTS, SPELLS, TILES,
                     _placeable)

_CARDS = None
# Detected unit names are not always the card key. A Skeletons card puts three
# entities called `skeleton` on the board, Archers puts two `archer`, and the
# card table is keyed by the card. Looking a unit up by its own name silently
# returns nothing, and nothing means zero hit points and "not a building" -
# which is how a Cannon came out looking like a troop.
_UNIT_TO_CARD = {
    "skeleton": "skeletons", "archer": "archers", "goblin": "goblins",
    "spear_goblin": "spear_goblins", "minion": "minions", "barbarian": "barbarians",
    "royal_recruit": "royal_recruits", "royal_hog": "royal_hogs",
    "bat": "bats", "elite_barbarian": "elite_barbarians",
    "three_musketeer": "three_musketeers", "guard": "guards",
}


def _cards():
    """The card table, resolved exactly the way `ClashEnv` resolves it.

    Not `load_gamedata` directly: the loader does not key everything under the
    name this project plays it as - `ice_golem` is simply absent from it, and
    `resolve_deck` is what maps our names onto the client's. Using the raw
    table here meant Ice Golem had no cost, fell back to a default of four
    elixir, and was masked out as unaffordable at two.
    """
    global _CARDS
    if _CARDS is None:
        from sim.gamedata import load_gamedata
        from sim.meta_decks import deck_pool
        from sim.runner import resolve_deck
        all_cards = load_gamedata(11)
        wanted = set(DECK_26)
        try:
            for _name, _style, deck in deck_pool(all_cards):
                wanted |= set(deck)
        except (RuntimeError, OSError):
            pass                      # no pool synced; our own deck is enough
        _CARDS = resolve_deck(all_cards, sorted(wanted))
    return _CARDS


def card_cost(card: str) -> float:
    """Elixir cost, or 99 for something we cannot price and must not play."""
    spec = _cards().get(card)
    cost = getattr(spec, "cost", None) if spec else None
    return float(cost) if cost else 99.0


def _unit_traits(name: str):
    """(max_hp, flying, is_building) for a detected unit name."""
    spec = _cards().get(_UNIT_TO_CARD.get(name, name))
    unit = getattr(spec, "unit", None) if spec else None
    if unit is None:
        return 0.0, False, False
    # `is_building` is derived, not declared - `sim.entities.make_unit` reads
    # it as "cannot move, or the client declares it in spells_buildings.csv".
    # Reading a field of that name off the spec gets None for every building.
    building = (getattr(unit, "speed_mt_per_sec", 1) == 0
                or bool(getattr(unit, "from_building_card", False)))
    return (float(getattr(unit, "hitpoints", 0) or 0),
            bool(getattr(unit, "flying", False)), building)


def ally_cells_with_names(state):
    """Our units as (cell, name), which `Observation.allies` throws away.

    `obs.allies` is a list of bare cells - the hand-written policy only ever
    needed to know where our units are. The network was trained with four
    planes per side (count, hit points, air, building), so feeding it nameless
    allies would zero three of its four ally planes: a train/serve mismatch
    that does not crash and does quietly change every decision. `state` still
    has the names, so they are recovered here rather than lost.
    """
    from brain import arena as live_arena
    out = []
    for ally in getattr(state, "allies", ()) or ():
        cell = live_arena.to_grid(ally.position.tile_x, ally.position.tile_y)
        out.append((cell, str(ally.unit.name)))
    return out


def observation_from_live(obs, allies=None) -> dict:
    """A live `brain.policy.Observation` in the simulator's own frame.

    `obs.tracks` are the enemies. `allies` is an optional list of
    `(cell, name)` from `ally_cells_with_names`; without it our own units fall
    back to `obs.allies`, which carries positions but no identity.
    """
    planes = np.zeros((NUM_PLANES, GRID_H, GRID_W), dtype=np.float32)

    def place(cell_x: float, cell_y: float, base: int, name: Optional[str]):
        # Same flip `sim.env.observe` applies: tile y -> plane row 31-y.
        col = int(np.clip(round(cell_x), 0, GRID_W - 1))
        row = int(np.clip(round(31 - cell_y), 0, GRID_H - 1))
        planes[base, row, col] += 1.0
        hp, flying, building = _unit_traits(name) if name else (0.0, False, False)
        planes[2 + base, row, col] += hp / 1000.0
        if flying:
            planes[4 + base, row, col] += 1.0
        if building:
            planes[6 + base, row, col] += 1.0

    if allies is not None:
        for cell, name in allies:
            place(cell.x, cell.y, 0, name)
    else:
        for cell in obs.allies:
            place(cell.x, cell.y, 0, None)
    for track in obs.tracks:
        place(track.cell.x, track.cell.y, 1, str(track.name))

    scalars = np.zeros(NUM_SCALARS, dtype=np.float32)
    scalars[0] = float(obs.elixir) / 10.0
    scalars[1] = min(1.0, float(obs.elapsed) / 180.0)
    # The simulator stores 2800 / regen_ms / 3; live carries the multiplier
    # directly, and those are the same number.
    scalars[2] = float(obs.multiplier) / 3.0
    base = 3
    for index, lane in enumerate(("left", "right")):
        scalars[base + index] = float(obs.ally_hp.get(lane, 1.0))
        scalars[base + 2 + index] = float(obs.enemy_hp.get(lane, 1.0))
    base += 4
    for card, slot in obs.hand.items():
        if card in DECK_26 and 0 <= slot < NUM_SLOTS:
            scalars[base + slot * len(DECK_26) + DECK_26.index(card)] = 1.0
    return {"planes": planes, "scalars": scalars}


def mask_from_live(obs) -> np.ndarray:
    """Legal actions live: what is in hand, affordable, and placeable."""
    mask = np.zeros(ACTIONS, dtype=bool)
    mask[0] = True
    enemy_down = tuple(sorted(lane for lane in ("left", "right")
                              if float(obs.enemy_hp.get(lane, 1.0)) <= 0.0))
    for card, slot in obs.hand.items():
        if not (0 <= slot < NUM_SLOTS):
            continue
        # Millielixir, matching the simulator: comparing 3.999 against 4.0 in
        # floats and 3999 against 4000 in integers must give the same answer.
        if round(float(obs.elixir) * 1000) < round(card_cost(card) * 1000):
            continue
        grid = _placeable(1, enemy_down, card in SPELLS)
        start = 1 + slot * TILES
        mask[start:start + TILES] = grid.reshape(-1)
    return mask


class RLBrain:
    """A trained checkpoint behind the `Brain.decide` interface.

    `temperature` of 0 is greedy, and greedy is the right default live:
    sampling is exploration, and there is nothing to explore on ladder.
    """

    def __init__(self, checkpoint: Path, temperature: float = 0.0,
                 device: str = "cpu", min_confidence: float = 0.0):
        import torch
        from sim.train_ppo import build_network
        self.torch = torch
        self.device = torch.device(device)
        blob = torch.load(Path(checkpoint), map_location=self.device,
                          weights_only=False)
        self.network = build_network(NUM_PLANES, NUM_SCALARS, ACTIONS)
        self.network.load_state_dict(blob["state_dict"])
        self.network.to(self.device).eval()
        self.step_trained = int(blob.get("step", 0))
        self.temperature = temperature
        self.checkpoint_name = Path(checkpoint).name
        self.min_confidence = min_confidence
        self.last_obs = None
        self.holds = 0
        # Built here rather than on the first decision. `cr_bot` calls
        # `brain.reset()` the moment it sees a battle, before it ever asks for
        # a decision, and a lazily-built observer made that throw
        # `AttributeError` on every frame - the bot sat in a live match doing
        # nothing at all while the log filled with the same line.
        self._observer = self._build_observer()

    @staticmethod
    def _build_observer():
        from brain.policy import Brain
        # Perception only, and explicitly no advisor: this reuses the
        # hand-written brain's tracking, hand smoothing and elixir model, and
        # none of its judgement.
        return Brain(learn=False, use_advisor=False)

    # ------------------------------------------------------------- interface
    #
    # `cr_bot` drives whichever brain it is given through one interface, so a
    # learned policy has to answer the whole of it and not only `decide`.
    # Everything that is bookkeeping rather than judgement is delegated to the
    # observer, which already does it correctly: hand tracking has to be told
    # what was played or the next observation is wrong, and the elixir model
    # has to be told or it thinks we are richer than we are.

    def reset(self) -> None:
        """New match: clear perception state and the play counters."""
        self._observer.reset()
        self.last_obs = None
        self.holds = 0

    def confirm(self, candidate, obs_now=None) -> None:
        """A card was actually tapped. The observer needs to know."""
        self._observer.confirm(candidate, obs_now)

    @property
    def committed_elixir(self) -> float:
        return self._observer.committed_elixir

    @property
    def plays(self) -> int:
        return self._observer.plays

    @property
    def play_counts(self):
        return self._observer.play_counts

    @property
    def hand_tracker(self):
        return self._observer.hand_tracker

    @property
    def classifier_overrides(self) -> int:
        return self._observer.classifier_overrides

    @property
    def advice_used(self) -> int:
        return self._observer.advice_used

    @property
    def book(self):
        return self._observer.book        # None: learn=False

    # There is no advisor in this path and there is not going to be one. The
    # attribute exists so the match record can say so rather than crash.
    advisor = None

    def summary(self) -> str:
        # A string, because that is what the match record stores and what
        # `Brain.summary` returns; returning a dict here wrote a different
        # shape into every match json depending on which brain played.
        return (f"{self._observer.summary()} brain=rl "
                f"ckpt={self.checkpoint_name} step={self.step_trained} "
                f"holds={self.holds}")

    # The runner reloads config between matches; nothing to reload here.
    def reload_config(self) -> None:
        pass

    def decide(self, state, elapsed: float, now: Optional[float] = None,
               frame=None):
        from brain.policy import Candidate
        obs = self._observer.observe(state, elapsed, now, frame)
        self.last_obs = obs

        view = observation_from_live(obs, ally_cells_with_names(state))
        mask = mask_from_live(obs)
        if not mask[1:].any():
            self.holds += 1
            return None

        torch = self.torch
        with torch.no_grad():
            p = torch.from_numpy(view["planes"]).unsqueeze(0).to(self.device)
            s = torch.from_numpy(view["scalars"]).unsqueeze(0).to(self.device)
            logits, _ = self.network(p, s)
            logits = logits[0].float()
            logits[~torch.from_numpy(mask).to(logits.device)] = float("-inf")
            probs = torch.softmax(logits, dim=-1)
            if self.temperature <= 0:
                action = int(torch.argmax(logits).item())
            else:
                action = int(torch.multinomial(
                    torch.softmax(logits / self.temperature, dim=-1), 1).item())
            confidence = float(probs[action].item())

        if action == 0 or confidence < self.min_confidence:
            self.holds += 1
            return None
        if action >= CARD_ACTIONS:
            self.holds += 1          # abilities: no live activation path yet
            return None

        index = action - 1
        slot, cell = divmod(index, TILES)
        y, x = divmod(cell, GRID_W)
        card = next((name for name, held in obs.hand.items() if held == slot), None)
        if card is None:
            self.holds += 1
            return None
        return Candidate(card=card, slot=slot, x=int(x), y=int(y),
                         tag=f"rl_p{confidence:.2f}", weight_key="rl",
                         features={"confidence": confidence}, score=confidence)
