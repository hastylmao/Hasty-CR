"""Play simulated matches, optionally driven by the live bot's own policy.

The point of the adapter is that `scripts/brain/policy.py` runs here unchanged,
so this measures the thing that actually plays rather than a reimplementation
of it. Two uses:

    python -m sim.runner --matches 20            benchmark and win rate
    python -m sim.runner --matches 1 --trace     watch one match unfold

The opponent is deliberately simple for now. Its only job is to be a punching
bag good enough to expose obvious policy failures; calibrating a realistic
opponent comes after the mechanics themselves are measured against the client.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim import arena  # noqa: E402
from sim.adapter import build_state, grid_to_point  # noqa: E402
from sim.arena import TICK_MS, Point  # noqa: E402
from sim.gamedata import load_gamedata  # noqa: E402
from sim.match import Match  # noqa: E402

DECK_26 = ["cannon", "fireball", "hog_rider", "ice_golem",
           "ice_spirit", "musketeer", "skeletons", "the_log"]

# The client names a card after the thing it summons, which does not always
# match the name players (or our policy) use. Resolved here rather than in the
# loader, so the loader stays a faithful reading of the data.
CARD_ALIASES = {
    "ice_golem": ("ice_golemite", "icegolem"),
    "ice_spirit": ("ice_spirits", "icespirit"),
    "the_log": ("log",),
    "skeletons": ("skeleton_warriors",),
}


def resolve_deck(cards: dict, deck: List[str]) -> dict:
    """Map our card names onto whatever the game data calls them."""
    resolved = {}
    for name in deck:
        if name in cards:
            resolved[name] = cards[name]
            continue
        for alias in CARD_ALIASES.get(name, ()):
            if alias in cards:
                # Re-key under our name so the policy sees what it expects.
                spec = cards[alias]
                resolved[name] = type(spec)(**{**spec.__dict__, "name": name})
                break
    return resolved

DECIDE_EVERY_MS = 500          # roughly the live bot's decision rate


class BrainPolicy:
    """The live bot's policy, playing in the simulator."""

    def __init__(self, cards: Dict[str, object], side: int, config_path=None):
        from brain.policy import Brain
        # A config path per side is what makes an A/B possible: a variant plays
        # the current baseline, and the win rate is the answer.
        self.brain = Brain(config_path=config_path, use_advisor=False, learn=False)
        self.cards = cards
        self.side = side
        self.plays: Dict[str, int] = {}

    def reset(self) -> None:
        self.brain.reset()

    def act(self, match: Match) -> Optional[tuple]:
        state = build_state(match, self.side, self.cards)
        now = match.elapsed_ms / 1000.0
        decision = self.brain.decide(state, now, now)
        if decision is None:
            return None
        point = grid_to_point(decision.x, decision.y, self.side)
        if not match.play_card(self.side, decision.card, point):
            return None
        self.brain.confirm(decision, now)
        self.plays[decision.card] = self.plays.get(decision.card, 0) + 1
        return decision.card, decision.x, decision.y, decision.tag


class SimpleOpponent:
    """Uses legal cards and engaged champion abilities for broad smoke tests."""

    def __init__(self, cards: Dict[str, object], side: int, seed: int = 0):
        self.cards = cards
        self.side = side
        self.rng = random.Random(seed)
        self.plays: Dict[str, int] = {}
        self.abilities: Dict[str, int] = {}

    def reset(self) -> None:
        pass

    def act(self, match: Match) -> Optional[tuple]:
        # Champion abilities are separate paid actions, not a passive property
        # of the troop. The generic policy exists to exercise arbitrary public
        # decks, so leaving this button untouched made Golden Knight, Monk and
        # every hero look like a broken ordinary troop in the viewer. Limit it
        # to a champion already fighting, which is the same conservative
        # trigger the compatibility auto-ability path uses.
        eligible = [entity for entity in match.battle.entities.values()
                    if entity.side == self.side and entity.alive
                    and entity.target_uid is not None
                    and match.can_activate_ability(self.side, entity.uid)]
        if eligible:
            entity = min(eligible, key=lambda item: item.uid)
            if match.activate_ability(self.side, entity.uid):
                self.abilities[entity.name] = self.abilities.get(entity.name, 0) + 1
                return "ability", -1, -1, entity.name

        player = match.players[self.side]
        options = [c for c in player.hand
                   if self.cards.get(c) and player.elixir >= self.cards[c].cost * 1000]
        if not options or self.rng.random() < 0.55:
            return None
        card = self.rng.choice(options)
        grid_x = self.rng.choice([3, 4, 9, 13, 14])
        grid_y = self.rng.choice([17, 19, 22, 25])
        if not match.play_card(self.side, card, grid_to_point(grid_x, grid_y, self.side)):
            return None
        self.plays[card] = self.plays.get(card, 0) + 1
        return card, grid_x, grid_y, "opponent"


def play_match(cards, seed: int, trace: bool = False, max_ms: int = 310_000,
               spells: Optional[dict] = None, opponent: str = "brain",
               bottom_config=None, top_config=None):
    top_deck = list(DECK_26)
    scripted = None
    if opponent == "scripted":
        # A real archetype rather than our own deck mirrored back at us. The
        # card pool has to carry the opponent's cards too, so it is widened
        # here rather than at every call site.
        from .gamedata import load_gamedata
        from .meta_decks import deck_pool
        pool = deck_pool(load_gamedata(level=11))
        if pool:
            name, style, top_deck = pool[seed % len(pool)]
            cards = dict(cards)
            for card in top_deck:
                if card not in cards:
                    cards[card] = load_gamedata(level=11)[card]
            scripted = (name, style)

    match = Match(cards=cards, decks=(DECK_26, top_deck), seed=seed,
                  spells=spells or {})
    bottom = BrainPolicy(cards, side=1, config_path=bottom_config)
    # Self-play by default. A random opponent is not a test: the policy beat
    # one 25-0, which says nothing about the policy and everything about the
    # opponent - the same trap the vendored ClashAI simulator fell into, where
    # random actions won 12 of 20 matches.
    if scripted is not None:
        from .opponents import ScriptedOpponent
        top = ScriptedOpponent(cards, side=-1, deck=top_deck,
                               style=scripted[1], seed=seed + 1)
    elif opponent == "brain":
        top = BrainPolicy(cards, side=-1, config_path=top_config)
    else:
        top = SimpleOpponent(cards, side=-1, seed=seed + 1)
    bottom.reset()
    top.reset()

    next_decision = 0
    turn = 0
    while not match.finished and match.elapsed_ms < max_ms:
        match.step()
        if match.elapsed_ms >= next_decision:
            next_decision = match.elapsed_ms + DECIDE_EVERY_MS
            turn += 1
            # Alternate who decides first. Letting the bottom player always go
            # first hands it every contested tile and every timing tie, which
            # showed up as a 115-72 record in self-play - three sigma from even
            # on 200 matches, so a real edge rather than noise.
            order = (bottom, top) if turn % 2 else (top, bottom)
            for policy in order:
                played = policy.act(match)
                if played and trace and policy is bottom:
                    print(f"  {match.elapsed_ms/1000:6.1f}s  {played[0]:11s} "
                          f"({played[1]:2d},{played[2]:2d})  {played[3]}")
    return match, bottom, top


def main() -> int:
    parser = argparse.ArgumentParser(description="Run simulated matches")
    parser.add_argument("--matches", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--level", type=int, default=11)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--opponent", choices=["brain", "simple", "scripted"],
                        default="brain")
    args = parser.parse_args()

    from sim.gamedata import scale_stat
    from sim.spells import load_spells

    cards = resolve_deck(load_gamedata(level=args.level), DECK_26)
    missing = [c for c in DECK_26 if c not in cards]
    if missing:
        print(f"deck cards missing from the game data: {missing}")
        return 1
    spells = load_spells(
        level=args.level,
        scale=lambda base, rarity, level: scale_stat(base, rarity, level, {}),
    )

    wins = losses = draws = 0
    crowns_for = crowns_against = 0
    plays: Dict[str, int] = {}
    started = time.monotonic()
    total_ticks = 0

    for index in range(args.matches):
        match, bottom, _ = play_match(cards, seed=args.seed + index,
                                      trace=args.trace, spells=spells,
                                      opponent=args.opponent)
        total_ticks += match.elapsed_ms // TICK_MS
        crowns_for += match.crowns_for(1)
        crowns_against += match.crowns_for(-1)
        if match.result == "bottom":
            wins += 1
        elif match.result == "top":
            losses += 1
        else:
            draws += 1
        for card, count in bottom.plays.items():
            plays[card] = plays.get(card, 0) + count
        if args.trace:
            print(f"match {index + 1}: {match.summary()}")

    elapsed = time.monotonic() - started
    total = sum(plays.values()) or 1
    print(f"\n{args.matches} matches in {elapsed:.1f}s "
          f"({args.matches / max(elapsed, 1e-6):.1f} matches/s, "
          f"{total_ticks / max(elapsed, 1e-6):,.0f} ticks/s)")
    print(f"record {wins}W {losses}L {draws}D   crowns {crowns_for}-{crowns_against}")
    print("card mix: " + "  ".join(
        f"{c} {100 * n / total:.0f}%" for c, n in
        sorted(plays.items(), key=lambda kv: -kv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
