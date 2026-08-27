"""Present a simulated match in the exact shape the live policy expects.

`scripts/brain/policy.py` reads a BuildABot `State`: `state.cards[0..4]`,
`state.ready`, `state.numbers.*.number`, and `state.enemies` / `state.allies`
carrying `unit.name` and `position.tile_x/tile_y`. Reproducing that duck type
here means the policy that plays live runs unchanged against the simulator - no
second implementation to keep in sync, and anything learned in sim is directly
about the thing that actually plays.

The one conversion that matters: BuildABot reports tiles **bottom-up**, while
the simulator and the policy's own grid are top-down. `31 - y` appears exactly
once, here, for the same reason it appears exactly once in the live stack.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List

from . import arena
from .arena import MT, Point
from .match import MAX_ELIXIR, Match

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _unit_view(entity, side: int):
    """One detected unit, as the given side sees it.

    The policy always believes it is the bottom player. For the top player the
    whole board must therefore be mirrored on the way *in* as well as on the
    way out. Mirroring only the placements - which is what the first version
    did - left the top player reading the board upside-down: it defended the
    wrong half and every self-play match ended 20-0 to the bottom side, which
    looked like a strong policy and was really a broken viewpoint.
    """
    grid_x = entity.pos.x / MT
    grid_y = entity.pos.y / MT
    if side < 0:
        grid_x, grid_y = 17 - grid_x, 31 - grid_y
    return SimpleNamespace(
        unit=SimpleNamespace(name=entity.name),
        position=SimpleNamespace(tile_x=grid_x, tile_y=31 - grid_y),
    )


def build_state(match: Match, side: int, cards: dict):
    """A policy-facing view of the match from `side`'s perspective."""
    player = match.players[side]
    hand = list(player.hand)

    def card_view(name):
        spec = cards.get(name)
        return SimpleNamespace(name=name if spec else "blank",
                               cost=spec.cost if spec else 0)

    slots = [card_view(player.next_card or "blank")]
    for index in range(4):
        slots.append(card_view(hand[index]) if index < len(hand)
                     else SimpleNamespace(name="blank", cost=0))

    elixir = player.elixir / 1000.0
    ready = {i for i in range(4)
             if i < len(hand) and cards.get(hand[i]) and cards[hand[i]].cost <= elixir}

    ours = match.tower_fractions(side)
    theirs = match.tower_fractions(-side)
    if side < 0:
        # Mirroring x swaps which lane is "left".
        ours = {"left": ours["right"], "right": ours["left"]}
        theirs = {"left": theirs["right"], "right": theirs["left"]}

    enemies, allies = [], []
    for entity in match.battle.entities.values():
        if entity.is_tower or not entity.alive:
            continue
        (allies if entity.side == side else enemies).append(_unit_view(entity, side))

    numbers = SimpleNamespace(
        elixir=SimpleNamespace(number=elixir),
        left_ally_princess_hp=SimpleNamespace(number=ours["left"]),
        right_ally_princess_hp=SimpleNamespace(number=ours["right"]),
        left_enemy_princess_hp=SimpleNamespace(number=theirs["left"]),
        right_enemy_princess_hp=SimpleNamespace(number=theirs["right"]),
    )
    return SimpleNamespace(
        cards=slots, ready=ready, numbers=numbers,
        enemies=enemies, allies=allies,
        screen=SimpleNamespace(name="in_game"),
    )


def grid_to_point(x: int, y: int, side: int) -> Point:
    """Policy grid cell -> simulator position.

    The policy always reasons as the bottom player. For the top player the
    board is mirrored, so its placements are flipped rather than the policy
    being taught about sides.
    """
    if side > 0:
        return arena.tile(x, y)
    return arena.tile(17 - x, 31 - y)
