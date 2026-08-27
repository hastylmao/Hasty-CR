"""A scripted opponent that plays a real deck with a plausible plan.

`SimpleOpponent` plays a random affordable card at a random spot, which is why
it loses about 99.7% of the time. That makes it useless as a measuring stick:
beating it says nothing. The alternative in use has been self-play, and a
mirror has the opposite problem - it defends exactly as well as we attack and
never punishes passivity, so nothing in the simulator prices tempo. That gap is
how a change that froze the bot live came recommended by the simulator.

This sits between the two. It is not strong and is not meant to be. It defends
what is actually coming, spends elixir at a rate its deck's style implies, and
reacts after a human-sized delay rather than on the tick the threat appears.
The design is taken from vegetableleaf/ClashAI's ScriptedBot; the code is our
own because the engines differ.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from .adapter import grid_to_point
from .arena import MT, RIVER_Y

# How much elixir a style banks before committing to an attack. Beatdown sits
# on a full bar and commits behind a tank; cycle spends as soon as it can.
COMMIT_ELIXIR = {"cycle": 5, "control": 7, "beatdown": 9}
# Seconds between noticing a threat and answering it. Instant reactions are the
# main reason a scripted opponent feels inhuman, and they make the opponent a
# harder defensive test than any real player.
REACTION_SECONDS = {"cycle": 0.6, "control": 0.9, "beatdown": 1.1}


class ScriptedOpponent:
    """Pilots one deck with deck-agnostic heuristics set by its style."""

    def __init__(self, cards: Dict[str, object], side: int, deck: List[str],
                 style: str = "cycle", seed: int = 0):
        self.cards = cards
        self.side = side
        self.deck = deck
        self.style = style
        self.rng = random.Random(seed)
        self.plays: Dict[str, int] = {}
        self.threat_since: Optional[int] = None
        self.last_play_ms = -9999
        self._reaction = REACTION_SECONDS.get(style, 0.8)

    def reset(self) -> None:
        self.threat_since = None
        self.last_play_ms = -9999
        base = REACTION_SECONDS.get(self.style, 0.8)
        self._reaction = base * self.rng.uniform(0.6, 1.6)

    # ------------------------------------------------------------------ helpers

    def _affordable(self, match) -> List[str]:
        player = match.players[self.side]
        return [c for c in player.hand
                if self.cards.get(c) and player.elixir >= self.cards[c].cost * 1000]

    def _threats(self, match) -> List:
        """Enemy units on our half of the board, nearest to our tower first."""
        out = []
        for entity in match.battle.entities.values():
            if not entity.alive or entity.is_tower or entity.side == self.side:
                continue
            on_our_half = (entity.pos.y > RIVER_Y) if self.side > 0 else (entity.pos.y < RIVER_Y)
            if on_our_half:
                out.append(entity)
        # nearest to our king first: that is what has to be answered
        out.sort(key=lambda e: -e.pos.y if self.side > 0 else e.pos.y)
        return out

    def _cheapest(self, options: List[str]) -> str:
        return self._weighted(options, prefer_cheap=True)

    def _biggest(self, options: List[str]) -> str:
        return self._weighted(options, prefer_cheap=False)

    def _weighted(self, options: List[str], prefer_cheap: bool) -> str:
        """Lean towards the cheap or the expensive end without always taking it.

        Strict min/max made this opponent perfectly predictable: the same hand
        in the same situation produced the same card every single time, so an
        agent training against it learns one script rather than a matchup. The
        user watched it drop an Inferno at the bridge four times running.

        Weights are the cost ranked within the affordable options, so the
        preferred end is still much likelier - this is meant to be a plausible
        opponent, not a random one.
        """
        if len(options) == 1:
            return options[0]
        ranked = sorted(options, key=lambda c: self.cards[c].cost,
                        reverse=not prefer_cheap)
        # 8, 4, 2, 1 ... so the intended pick wins about half the time.
        weights = [max(1, 2 ** (len(ranked) - index - 1))
                   for index in range(len(ranked))]
        return self.rng.choices(ranked, weights=weights, k=1)[0]

    def _jitter(self, value: int, spread: int, low: int, high: int) -> int:
        """Move a placement a tile or two so it is not always the same square."""
        return min(high, max(low, value + self.rng.randint(-spread, spread)))

    def _play(self, match, card: str, x: int, y: int, tag: str):
        if not match.play_card(self.side, card, grid_to_point(x, y, self.side)):
            return None
        self.plays[card] = self.plays.get(card, 0) + 1
        self.last_play_ms = match.elapsed_ms
        return card, x, y, tag

    # --------------------------------------------------------------------- act

    def act(self, match) -> Optional[tuple]:
        options = self._affordable(match)
        if not options:
            return None

        threats = self._threats(match)
        if threats:
            if self.threat_since is None:
                self.threat_since = match.elapsed_ms
            waited = (match.elapsed_ms - self.threat_since) / 1000.0
            # Jittered so the answer does not land on the same frame every time.
            if waited >= self._reaction:
                return self._defend(match, options, threats[0])
            return None

        self.threat_since = None
        return self._attack(match, options)

    def _defend(self, match, options: List[str], threat) -> Optional[tuple]:
        """Answer the deepest threat, placed between it and our tower.

        Deliberately crude: it does not know matchups. What matters is that
        elixir goes on defence when defence is needed, so our own attacks meet
        something rather than walking into an empty half.
        """
        # our own frame: y grows towards our king, so sit a little in front
        tiles_y = threat.pos.y // MT if self.side > 0 else (31 - threat.pos.y // MT)
        tiles_x = threat.pos.x // MT if self.side > 0 else (17 - threat.pos.x // MT)
        spot_y = self._jitter(int(tiles_y) - 1, 1, 18, 28)
        spot_x = self._jitter(int(tiles_x), 2, 1, 16)
        card = self._cheapest(options)
        return self._play(match, card, spot_x, spot_y, f"defend_{self.style}")

    def _attack(self, match, options: List[str]) -> Optional[tuple]:
        player = match.players[self.side]
        need = COMMIT_ELIXIR.get(self.style, 6) * 1000
        if player.elixir < need:
            return None
        # Don't dribble cards out one per tick.
        if match.elapsed_ms - self.last_play_ms < 1200:
            return None

        lane = self._jitter(self.rng.choice([3, 14]), 2, 1, 16)
        if self.style == "beatdown":
            # Commit behind the king and let it walk, which is the whole point
            # of banking elixir for a tank.
            card = self._biggest(options)
            return self._play(match, card, lane, self._jitter(27, 1, 24, 29),
                              "push_beatdown")
        card = self._biggest(options) if self.style == "control" else self._cheapest(options)
        return self._play(match, card, lane, self._jitter(17, 2, 15, 22),
                          f"push_{self.style}")
