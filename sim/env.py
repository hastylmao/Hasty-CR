"""A headless Gym-style environment, for training a policy rather than tuning one.

Everything else in `sim/` answers "is setting X better than setting Y" by
playing whole matches with the hand-written policy. This exposes the same engine
one decision at a time, so a learned policy can act in it.

    env = ClashEnv(seed=0)
    obs, info = env.reset()
    while not done:
        action = pick(obs, info["action_mask"])
        obs, reward, terminated, truncated, info = env.step(action)

Design notes worth knowing before training anything on it.

**The opponent is the hand-written brain, not a random agent.** A random
opponent is not a test: this policy beat one 25-0, which says nothing about the
policy. The vendored ClashAI simulator fell into exactly that trap - random
actions won 12 of its 20 matches.

**Actions are masked, not penalised.** The legal set changes every step (elixir,
what is in hand, which half a card may be placed in), and 2,305 actions with
maybe 40 legal is far too sparse to learn from rejection alone. `info` carries a
boolean mask; illegal actions are treated as no-ops and flagged in `info`.

**The reward is shaped by tower damage, not only by the result.** A match is
~900 decisions and one terminal signal, which is a hard credit assignment
problem. Tower fractions are dense, monotone, and exactly what the game scores,
so the shaping is the objective rather than a proxy for it.

**Elixir is symmetric and honest.** The opponent's elixir is *not* in the
observation, because it is not observable in the real game either - the live
bot has to infer it (see `brain/economy.py`). Training on an oracle the deployed
agent will not have is how a simulator policy stops transferring.
"""

from __future__ import annotations

import random

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim import arena as sim_arena          # noqa: E402
from sim.adapter import grid_to_point       # noqa: E402
from sim.match import Match                 # noqa: E402

GRID_W, GRID_H = 18, 32
TILES = GRID_W * GRID_H
NUM_SLOTS = 4
CARD_ACTIONS = 1 + NUM_SLOTS * TILES       # index 0 is "hold elixir"
# An ability targets the currently living friendly champion/hero by stable UID
# rank, so the policy gets a real button press without exposing an arbitrary
# internal UID as part of its fixed action tensor.
ABILITY_SLOTS = 16
ACTIONS = CARD_ACTIONS + ABILITY_SLOTS

DECIDE_EVERY_MS = 500
MAX_MS = 310_000

DECK_26 = ["cannon", "fireball", "hog_rider", "ice_golem",
           "ice_spirit", "musketeer", "skeletons", "the_log"]
SPELLS = {"fireball", "the_log"}

# Spatial planes. Kept small deliberately: one plane per card type would be 100+
# channels of almost entirely zeros, which costs memory and learns slower than
# a handful of planes that carry what the decision actually turns on.
PLANES = ("ally_units", "enemy_units", "ally_hp", "enemy_hp",
          "ally_air", "enemy_air", "ally_buildings", "enemy_buildings")
NUM_PLANES = len(PLANES)

# Scalars: elixir, elapsed, elixir multiplier, our two tower fractions and
# their two, hand one-hot (4 slots x 8 cards), next card one-hot (8).
LANES = ("left", "right")
RIVER_ROW = 16                 # our half is y >= 16 in the policy's grid
NUM_SCALARS = 3 + 2 * len(LANES) + NUM_SLOTS * len(DECK_26) + len(DECK_26)


# --------------------------------------------------------------- both seats
#
# A policy is written to play the bottom of the board, so the top player's view
# is the board mirrored: `grid_to_point` already flips a top placement through
# (17-x, 31-y), and these flip the observation the same way. One frame of
# reference, two seats - which is what lets the same network drive both sides
# in self-play without learning each orientation separately.


def ability_entities(match, side: int):
    """Living friendly units with an ability, in stable UID order."""
    if match is None:
        return []
    return sorted((entity for entity in match.battle.entities.values()
                   if entity.side == side and entity.alive and entity.ability_buff),
                  key=lambda entity: entity.uid)


def observe(match, side: int = 1) -> dict:
    """The board as `side` sees it, always oriented as the bottom player."""
    planes = np.zeros((NUM_PLANES, GRID_H, GRID_W), dtype=np.float32)
    if match is None:
        return {"planes": planes, "scalars": np.zeros(NUM_SCALARS, dtype=np.float32)}
    for entity in match.battle.entities.values():
        if not getattr(entity, "alive", True):
            continue
        if getattr(entity, "is_tower", False):
            continue
        x, y = sim_arena.to_tiles(entity.pos)
        # Bin in the bottom frame first, then mirror the *cell*. Mirroring
        # the coordinate instead lets rounding disagree: a unit sitting on an
        # exact half tile rounds to even in both frames, so 16.5 and 14.5 both
        # round down and the two seats see it one cell apart. That asymmetry
        # would quietly favour one side of every self-play game.
        grid_x = int(np.clip(round(x), 0, GRID_W - 1))
        grid_y = int(np.clip(round(31 - y), 0, GRID_H - 1))
        if side < 0:
            grid_x, grid_y = (GRID_W - 1) - grid_x, (GRID_H - 1) - grid_y
        ours = (getattr(entity, "side", 1) > 0) == (side > 0)
        base = 0 if ours else 1
        planes[base, grid_y, grid_x] += 1.0
        planes[2 + base, grid_y, grid_x] += float(
            getattr(entity, "hitpoints", 0)) / 1000.0
        if getattr(entity, "flying", False):
            planes[4 + base, grid_y, grid_x] += 1.0
        if getattr(entity, "is_building", False):
            planes[6 + base, grid_y, grid_x] += 1.0

    scalars = np.zeros(NUM_SCALARS, dtype=np.float32)
    player = match.players[side]
    scalars[0] = player.elixir / 10_000.0
    scalars[1] = min(1.0, match.elapsed_ms / 180_000.0)
    # Elixir regen expressed as a multiplier (1x, 2x, 3x) rather than a
    # period, so the scale matches how the game talks about it.
    scalars[2] = 2800.0 / max(1, match.regen_ms()) / 3.0
    ours = match.tower_fractions(side)
    theirs = match.tower_fractions(-side)
    base = 3
    for index, key in enumerate(LANES):
        scalars[base + index] = ours.get(key, 0.0)
        scalars[base + len(LANES) + index] = theirs.get(key, 0.0)
    base += 2 * len(LANES)
    for slot, card in enumerate(player.hand[:NUM_SLOTS]):
        if card in DECK_26:
            scalars[base + slot * len(DECK_26) + DECK_26.index(card)] = 1.0
    nxt = player.next_card
    if nxt in DECK_26:
        scalars[base + NUM_SLOTS * len(DECK_26) + DECK_26.index(nxt)] = 1.0
    return {"planes": planes, "scalars": scalars}


# Which cells a card may go in, by (side, which enemy towers are down, spell).
# The answer depends only on geometry, and it was being recomputed from
# scratch every step: 4 slots x 32 rows x 18 columns of `grid_to_point` plus
# `deploy_area_ok`, in Python, twice per step once the opponent also learned.
# There are eight distinct answers in a whole run.
_PLACEMENT_CACHE: Dict[tuple, np.ndarray] = {}


def _placeable(side: int, enemy_down: tuple, spell: bool) -> np.ndarray:
    key = (side, enemy_down, spell)
    cached = _PLACEMENT_CACHE.get(key)
    if cached is not None:
        return cached
    grid = np.zeros((GRID_H, GRID_W), dtype=bool)
    for y in range(GRID_H):
        # Deliberately *not* short-circuiting the enemy half for troops here.
        # It reads like a free optimisation - troops go on your own side - but
        # it is only true while both princess towers stand. Taking one opens a
        # strip in front of it, which is how a crown snowballs into the next
        # one, and `deploy_area_ok` has always implemented that. Skipping those
        # rows meant the rule was unreachable from the action space: the agent
        # could take a tower and gain none of the ground it should have won.
        for x in range(GRID_W):
            point = grid_to_point(x, y, side)
            grid[y, x] = (sim_arena.in_arena(point) if spell
                          else sim_arena.deploy_area_ok(point, side,
                                                        list(enemy_down)))
    _PLACEMENT_CACHE[key] = grid
    return grid


def legal_mask(match, cards, side: int = 1) -> np.ndarray:
    """Which actions `side` may take right now. Index 0 (hold) always is."""
    mask = np.zeros(ACTIONS, dtype=bool)
    mask[0] = True
    if match is None or match.finished:
        return mask
    player = match.players[side]
    enemy_down = [key for key, value in match.tower_fractions(-side).items()
                  if value <= 0.0 and key in ("left", "right")]
    for slot, card in enumerate(player.hand[:NUM_SLOTS]):
        spec = cards.get(card)
        cost = getattr(spec, "cost", 0) * 1000 if spec else 0
        if player.elixir < cost:
            continue
        grid = _placeable(side, tuple(enemy_down), card in SPELLS)
        base = 1 + slot * TILES
        mask[base:base + TILES] = grid.reshape(-1)
    for rank, entity in enumerate(ability_entities(match, side)[:ABILITY_SLOTS]):
        if match.can_activate_ability(side, entity.uid):
            mask[CARD_ACTIONS + rank] = True
    return mask


@dataclass
class RewardWeights:
    """What the agent is actually optimising.

    Tower damage dominates because it is what the game scores, and it is
    symmetric: dealing and taking a tower fraction are worth the same, so the
    shaping cannot make the policy structurally attack-happy or turtle-happy.

    `elixir_traded` is the term that docstring said to add if it were ever
    added: net milli-elixir of enemy bodies destroyed minus our own lost, per
    step, in whole elixir. It defaults to zero, so nothing changes unless a run
    asks for it.

    It exists because tower damage cannot see most of the game. Kiting a
    Musketeer with an Ice Golem, pulling a tank to the centre so both Princess
    Towers work on it, answering a five-elixir push with two - none of those
    move a tower's hitpoints at all, and all of them are why one player beats
    another. Scored on elixir they are exactly what they are: +4, +6, +3.

    It is still a prior about how to play, which is why it is off by default
    and named rather than folded into the tower weight.
    """
    tower_damage_dealt: float = 10.0
    tower_damage_taken: float = -10.0
    crown_for: float = 3.0
    crown_against: float = -3.0
    win: float = 10.0
    loss: float = -10.0
    draw: float = 0.0
    elixir_traded: float = 0.0
    illegal_action: float = -0.01
    step_cost: float = 0.0


@dataclass
class EpisodeStats:
    steps: int = 0
    plays: int = 0
    illegal: int = 0
    cards: Dict[str, int] = field(default_factory=dict)

    @property
    def hog_share(self) -> float:
        return self.cards.get("hog_rider", 0) / self.plays if self.plays else 0.0


class ClashEnv:
    """One agent on the bottom side; the hand-written brain on the top."""

    metadata = {"render_modes": []}

    def __init__(self, seed: int = 0, level: int = 11, opponent: str = "brain",
                 decide_every_ms: int = DECIDE_EVERY_MS, max_ms: int = MAX_MS,
                 rewards: Optional[RewardWeights] = None,
                 opponent_config: Optional[Path] = None):
        from sim.gamedata import load_gamedata
        from sim.runner import BrainPolicy, SimpleOpponent, resolve_deck
        from sim.spells import load_spells

        self._spells = load_spells(level=level)
        self._brain_policy = BrainPolicy
        self._simple_opponent = SimpleOpponent
        self._opponent_kind = opponent
        self._opponent_config = opponent_config

        # `meta` draws a different real ladder deck every episode. The card
        # table has to carry every card in the pool, not just our eight, or the
        # opponent's deck resolves to nothing and it stands there.
        all_cards = load_gamedata(level=level)
        self._deck_pool = []
        if opponent == "meta":
            from sim.meta_decks import deck_pool
            self._deck_pool = deck_pool(all_cards)
            if not self._deck_pool:
                raise RuntimeError(
                    "opponent='meta' needs a deck pool; run "
                    "scripts/sync_meta_decks.py")
        wanted = set(DECK_26)
        for _name, _style, deck in self._deck_pool:
            wanted |= set(deck)
        self._cards = resolve_deck(all_cards, sorted(wanted))

        self.seed = seed
        self.decide_every_ms = decide_every_ms
        self.max_ms = max_ms
        # `or` here calls bool() on whatever is passed, which raises on a
        # numpy array - and a caller with a local named `rewards` holding
        # the per-step reward buffer is an easy mistake to make.
        self.rewards = RewardWeights() if rewards is None else rewards

        self.match: Optional[Match] = None
        self.opponent = None
        self._policy_opponent = None
        self.opponent_deck_name = ""
        self.opponent_deck_style = ""
        self.stats = EpisodeStats()
        self._turn = 0
        self._last_towers: Tuple[float, float] = (1.0, 1.0)
        self._last_elixir: Tuple[int, int] = (0, 0)
        self._episodes = 0

    # ------------------------------------------------------------- spaces

    def set_policy_opponent(self, opponent) -> None:
        """Swap in a learned opponent for the next episode, or None to revert.

        Set between episodes rather than mid-match: changing who is playing the
        top seat half way through a game makes the episode unattributable.
        """
        self._policy_opponent = opponent

    def set_opponent_kind(self, kind: str) -> None:
        """Choose which scripted opponent the next episode faces.

        Training against a single opponent produces a policy that beats that
        opponent and nothing else. Measured here on 60 held-out games: a run
        trained 50% against the rule engine reached 93.3% against it while
        falling to 76.7% against meta decks, from a starting point of 41.7%
        and 86.7%. The reverse arrangement had already failed the same way in
        the other direction - 82.5% against meta decks and 16.7% against the
        rule engine.

        So the diet has to contain both, and which one an episode uses is a
        per-episode choice rather than a property of the environment.

        `meta` requires the deck pool, which is only loaded when the
        environment was constructed with it; asking for it otherwise is a
        silent no-op rather than an error, because a worker that raises
        mid-run takes the whole rollout down.
        """
        if kind == "meta" and not self._deck_pool:
            return
        if kind in ("brain", "meta", "simple", "mirror"):
            self._opponent_kind = kind

    @property
    def observation_shape(self) -> Dict[str, tuple]:
        return {"planes": (NUM_PLANES, GRID_H, GRID_W), "scalars": (NUM_SCALARS,)}

    @property
    def action_count(self) -> int:
        return ACTIONS

    @staticmethod
    def decode(action: int) -> Optional[Tuple[int, int, int] | Tuple[str, int]]:
        """Card action -> ``(slot, x, y)``, ability -> ``('ability', rank)``."""
        if action <= 0:
            return None
        if action >= CARD_ACTIONS:
            return ("ability", action - CARD_ACTIONS)
        index = action - 1
        slot, cell = divmod(index, TILES)
        y, x = divmod(cell, GRID_W)
        return slot, x, y

    @staticmethod
    def encode(slot: int, x: int, y: int) -> int:
        return 1 + slot * TILES + y * GRID_W + x

    @staticmethod
    def encode_ability(rank: int) -> int:
        return CARD_ACTIONS + rank

    def _ability_entities(self):
        return ability_entities(self.match, 1)

    # -------------------------------------------------------------- reset

    def reset(self, seed: Optional[int] = None) -> Tuple[dict, dict]:
        if seed is not None:
            self.seed = seed
        else:
            self.seed += 1
        self._episodes += 1

        opponent_deck = DECK_26
        if self._opponent_kind == "meta" and self._policy_opponent is None:
            # Seeded by the episode seed, so a run is reproducible and two
            # workers on different seeds see different decks.
            picker = random.Random(self.seed)
            name, style, opponent_deck = picker.choice(self._deck_pool)
            self.opponent_deck_name = name
            self.opponent_deck_style = style
        self.match = Match(cards=self._cards, decks=(DECK_26, opponent_deck),
                           seed=self.seed, spells=self._spells)
        if self._policy_opponent is not None:
            # A learned opponent keeps its own deck fixed to ours: it is a past
            # version of this policy, and it reads a 2.6 hand one-hot.
            self.opponent = self._policy_opponent
            self.opponent_deck_name = getattr(self.opponent, "name", "self")
            self.opponent_deck_style = "self"
        elif self._opponent_kind == "brain":
            self.opponent = self._brain_policy(self._cards, side=-1,
                                               config_path=self._opponent_config)
        elif self._opponent_kind == "meta":
            from sim.opponents import ScriptedOpponent
            self.opponent = ScriptedOpponent(
                self._cards, side=-1, deck=list(opponent_deck),
                style=self.opponent_deck_style, seed=self.seed + 1)
        elif self._opponent_kind == "mirror":
            # Our own deck, piloted by the deck-agnostic heuristics rather than
            # by the rule engine or a past self. It exists so a mirror-trained
            # policy meets more than two ways of playing 2.6: the style sets
            # reaction time (0.6s cycling, 1.1s beatdown) and how much elixir
            # is banked before committing, and `reset` jitters the reaction by
            # 0.6-1.6x on top. A human playing hog cycle is not the rule
            # engine and is not a past self, and a policy that has only ever
            # seen those two will have learned their timings specifically.
            from sim.opponents import ScriptedOpponent
            style = random.Random(self.seed).choice(
                ["cycle", "cycle", "control", "beatdown"])
            self.opponent_deck_name = f"mirror_{style}"
            self.opponent_deck_style = style
            self.opponent = ScriptedOpponent(
                self._cards, side=-1, deck=list(DECK_26),
                style=style, seed=self.seed + 1)
        else:
            self.opponent = self._simple_opponent(self._cards, side=-1,
                                                  seed=self.seed + 1)
        self.opponent.reset()
        self.stats = EpisodeStats()
        self._turn = 0
        self._last_towers = self._tower_totals()
        self._last_elixir = (0, 0)
        return self._observe(), self._info()

    # --------------------------------------------------------------- step

    def step(self, action: int) -> Tuple[dict, float, bool, bool, dict]:
        assert self.match is not None, "call reset() first"
        match = self.match
        reward = self.rewards.step_cost
        illegal = False

        decoded = self.decode(int(action))
        if decoded is not None:
            if decoded[0] == "ability":
                rank = decoded[1]
                entities = self._ability_entities()
                illegal = (rank >= len(entities)
                           or not match.activate_ability(1, entities[rank].uid))
            else:
                slot, x, y = decoded
                hand = match.players[1].hand
                if slot >= len(hand):
                    illegal = True
                else:
                    card = hand[slot]
                    point = grid_to_point(x, y, 1)
                    if not match.play_card(1, card, point):
                        illegal = True
                    else:
                        self.stats.plays += 1
                        self.stats.cards[card] = self.stats.cards.get(card, 0) + 1
        if illegal:
            reward += self.rewards.illegal_action
            self.stats.illegal += 1

        # The opponent acts on the same tick, and who resolves first alternates.
        # Letting one side always go first hands it every contested tile, which
        # showed up in self-play as a 115-72 record - three sigma from even.
        self._turn += 1
        if self._turn % 2 == 0 and self.opponent is not None:
            self.opponent.act(match)

        target = match.elapsed_ms + self.decide_every_ms
        while not match.finished and match.elapsed_ms < target:
            match.step()

        if self._turn % 2 == 1 and self.opponent is not None:
            self.opponent.act(match)

        reward += self._shaping_reward()
        self.stats.steps += 1

        terminated = bool(match.finished)
        truncated = (not terminated) and match.elapsed_ms >= self.max_ms
        if terminated or truncated:
            reward += self._terminal_reward()
        return self._observe(), reward, terminated, truncated, self._info()

    # ------------------------------------------------------------ rewards

    def _tower_totals(self) -> Tuple[float, float]:
        ours = sum(self.match.tower_fractions(1).values())
        theirs = sum(self.match.tower_fractions(-1).values())
        return ours, theirs

    def _shaping_reward(self) -> float:
        ours, theirs = self._tower_totals()
        was_ours, was_theirs = self._last_towers
        self._last_towers = (ours, theirs)
        dealt = max(0.0, was_theirs - theirs)
        taken = max(0.0, was_ours - ours)
        reward = (dealt * self.rewards.tower_damage_dealt
                  + taken * self.rewards.tower_damage_taken)
        if self.rewards.elixir_traded:
            reward += self._elixir_trade() * self.rewards.elixir_traded
        return reward

    def _elixir_trade(self) -> float:
        """Net elixir destroyed since the last step, in whole elixir.

        Symmetric on purpose: killing four elixir of theirs and losing four of
        ours nets nothing, so this pays for *trades* rather than for kills. A
        term that only counted their losses would reward throwing bodies at
        anything.
        """
        destroyed = self.match.battle.elixir_destroyed
        ours = destroyed.get(1, 0)
        theirs = destroyed.get(-1, 0)
        was_ours, was_theirs = self._last_elixir
        self._last_elixir = (ours, theirs)
        return ((ours - was_ours) - (theirs - was_theirs)) / 1000.0

    def _terminal_reward(self) -> float:
        match = self.match
        mine = match.crowns_for(1)
        theirs = match.crowns_for(-1)
        reward = (mine * self.rewards.crown_for
                  + theirs * self.rewards.crown_against)
        if match.result == "bottom":
            reward += self.rewards.win
        elif match.result == "top":
            reward += self.rewards.loss
        else:
            reward += self.rewards.draw
        return reward

    # -------------------------------------------------------- observation

    def _observe(self) -> dict:
        return observe(self.match, 1)

    def action_mask(self) -> np.ndarray:
        """Which actions are legal right now. Index 0 (hold) always is."""
        return legal_mask(self.match, self._cards, 1)

    def _info(self) -> dict:
        return {
            "action_mask": self.action_mask(),
            "elapsed_s": (self.match.elapsed_ms / 1000.0) if self.match else 0.0,
            "crowns": ((self.match.crowns_for(1), self.match.crowns_for(-1))
                       if self.match else (0, 0)),
            "result": self.match.result if self.match else None,
            "stats": self.stats,
        }

    def close(self) -> None:
        self.match = None
        self.opponent = None
