"""Let a trained policy drive the top seat, so both sides get better.

The reason this exists, stated plainly: **a fixed opponent cannot punish
passivity, so training against one says nothing about whether the win condition
is needed.**

That is not a theory. Training against `ScriptedOpponent` drifted to a policy
that took *zero* crowns in sixty evaluation matches, never played Hog Rider at
all, and still won a third of them - by chipping with Log and Ice Spirit and
taking the overtime tiebreak. Against a script that attacks on a timer and
defends with a heuristic, "never commit to anything" is a survivable plan. It
is not survivable against an opponent who notices you are not attacking and
walks a tank down the lane, because the tiebreak stops being reachable.

So the opponent has to learn too. `PolicyOpponent` wraps a checkpoint behind
the same `.reset()` / `.act(match)` interface `ScriptedOpponent` already uses,
and `sim.env.observe`/`legal_mask` hand it the board from the top seat mirrored
into the bottom frame - the same frame `grid_to_point` already flips placements
through. One network, either colour, no orientation to learn twice.

**A league, not a mirror.** Pure self-play against the newest checkpoint is a
known way to go in circles: two policies chase each other's current weakness
and forget how to beat anything else. `League` samples an opponent per episode
from past checkpoints plus the scripted meta decks, so the agent keeps having
to beat the decks it will actually meet as well as its own history.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from sim.adapter import grid_to_point
from sim.env import (ABILITY_SLOTS, ACTIONS, CARD_ACTIONS, GRID_W, NUM_SLOTS,
                     TILES, ability_entities, legal_mask, observe)


def decode_for(action: int):
    """Action index -> ("ability", rank) or (slot, x, y). Mirrors env.decode."""
    action = int(action)
    if action <= 0:
        return None
    if action >= CARD_ACTIONS:
        rank = action - CARD_ACTIONS
        return ("ability", rank) if rank < ABILITY_SLOTS else None
    index = action - 1
    slot, cell = divmod(index, TILES)
    y, x = divmod(cell, GRID_W)
    return slot, x, y


class PolicyOpponent:
    """Drives one seat with a network, greedily or by sampling.

    `temperature` is why this is worth having over a frozen greedy copy. A
    deterministic opponent is one opponent; the agent overfits to its exact
    line and the record stops meaning anything. Sampling keeps the pool of
    behaviours wide enough that beating it is beating a deck, not a script.
    """

    def __init__(self, network, cards: Dict[str, object], side: int = -1,
                 device=None, seed: int = 0, temperature: float = 1.0,
                 greedy: bool = False):
        import torch
        self.network = network
        self.cards = cards
        self.side = side
        self.device = device or torch.device("cpu")
        self.rng = random.Random(seed)
        self.temperature = temperature
        self.greedy = greedy
        self.plays: Dict[str, int] = {}
        self.name = "self"

    def reset(self) -> None:
        self.plays = {}

    def act(self, match) -> Optional[tuple]:
        import torch
        if match is None or match.finished:
            return None
        mask = legal_mask(match, self.cards, self.side)
        if not mask[1:].any():
            return None                      # nothing affordable; hold
        obs = observe(match, self.side)
        with torch.no_grad():
            planes = torch.from_numpy(obs["planes"]).unsqueeze(0).to(self.device)
            scalars = torch.from_numpy(obs["scalars"]).unsqueeze(0).to(self.device)
            logits, _ = self.network(planes, scalars)
            logits = logits[0].float()
            logits[~torch.from_numpy(mask).to(logits.device)] = float("-inf")
            if self.greedy:
                action = int(torch.argmax(logits).item())
            else:
                scaled = logits / max(1e-3, self.temperature)
                probs = torch.softmax(scaled, dim=-1)
                action = int(torch.multinomial(probs, 1).item())

        decoded = decode_for(action)
        if decoded is None:
            return None
        if decoded[0] == "ability":
            entities = ability_entities(match, self.side)
            rank = decoded[1]
            if rank < len(entities):
                match.activate_ability(self.side, entities[rank].uid)
            return None
        slot, x, y = decoded
        hand = match.players[self.side].hand
        if slot >= len(hand):
            return None
        card = hand[slot]
        if match.play_card(self.side, card, grid_to_point(x, y, self.side)):
            self.plays[card] = self.plays.get(card, 0) + 1
            return (card, x, y)
        return None


class League:
    """The pool of opponents an episode can be drawn from.

    Holds frozen snapshots of past selves. `scripted_share` is the fraction of
    episodes still played against the meta deck pool - kept deliberately
    non-zero, because a league that only plays itself converges on a private
    metagame and loses to an ordinary ladder deck.
    """

    def __init__(self, capacity: int = 8, scripted_share: float = 0.4,
                 seed: int = 0):
        self.capacity = capacity
        self.scripted_share = scripted_share
        self.rng = random.Random(seed)
        self.snapshots: List[dict] = []
        self.labels: List[str] = []

    def add(self, state_dict, label: str) -> None:
        """Store a CPU copy, so the pool never aliases the live weights."""
        frozen = {k: v.detach().to("cpu").clone() for k, v in state_dict.items()}
        self.snapshots.append(frozen)
        self.labels.append(label)
        if len(self.snapshots) > self.capacity:
            # Drop the oldest, but never the very first: the earliest snapshot
            # is the only one guaranteed not to share the current policy's
            # blind spots, and it is what stops the league drifting as a whole.
            self.snapshots.pop(1)
            self.labels.pop(1)

    def sample(self) -> Optional[tuple]:
        """(state_dict, label), or None meaning 'use the scripted pool'."""
        if not self.snapshots or self.rng.random() < self.scripted_share:
            return None
        index = self.rng.randrange(len(self.snapshots))
        return self.snapshots[index], self.labels[index]

    def __len__(self) -> int:
        return len(self.snapshots)
