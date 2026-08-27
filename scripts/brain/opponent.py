"""Learn the opponent's deck during the match and track their cycle.

Why this matters more than the elixir estimate
----------------------------------------------
The push planner's question is "can they answer this Hog right now". So far it
has been answered from an inferred elixir bar, which drifts and has repeatedly
read empty when it was not. But a Hog is not stopped by elixir, it is stopped by
a *specific card* - a Cannon, a Tesla, a Tornado, a swarm - and Clash Royale's
cycle makes card availability far more knowable than elixir.

Every deck is eight cards and a card returns only after four others are played.
So once we have seen a card, we know it cannot come back until they have played
four more. Counting their deploys is enough to say, with real confidence, that
their building is still four cards away.

What is knowable and what is not:

* their deck, after we have seen all eight cards - and 2.6 opponents at this
  level rarely surprise you twice,
* how many cards they have played since each one was last seen,
* therefore which cards *cannot* be in their hand right now.

Not knowable: which of the available four they actually hold, or anything they
played outside our detector's view. So the useful signal is one-directional -
"their answer is definitely not ready" is trustworthy, "they have it" is not -
and the planner should only lean on the confident direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .knowledge import BOOK

# Cards that actually stop a Hog Rider: buildings that pull it, and swarms or
# high-dps units that kill it before it lands its hits.
HOG_ANSWERS = frozenset({
    "cannon", "tesla", "inferno_tower", "bomb_tower", "goblin_cage",
    "tombstone", "furnace", "goblin_hut", "barbarian_hut", "elixir_collector",
    "skeletons", "skeleton_army", "goblin", "spear_goblin", "guard",
    "barbarian", "minipekka", "valkyrie", "knight", "bomber", "tornado",
    "electro_spirit", "ice_spirit", "bats", "bat", "minion", "mega_minion",
})

DECK_SIZE = 8
CYCLE_GAP = 4          # cards that must be played before one returns


@dataclass
class OpponentModel:
    deck: List[str] = field(default_factory=list)     # in order first seen
    last_play_index: Dict[str, int] = field(default_factory=dict)
    plays: int = 0
    last_seen_at: Dict[str, float] = field(default_factory=dict)

    def reset(self) -> None:
        self.deck.clear()
        self.last_play_index.clear()
        self.last_seen_at.clear()
        self.plays = 0

    # ------------------------------------------------------------- observing

    def observe(self, deploys: List[str], now: float) -> None:
        """Record cards the opponent has just deployed.

        `deploys` should be genuinely new deployments, not re-sightings - the
        elixir model already does that filtering and getting it wrong here would
        corrupt the cycle count in the same way it corrupted the elixir estimate.
        """
        for name in deploys:
            if BOOK.cost(name) <= 0:
                continue                       # spawned children are not cards
            if name not in self.deck and len(self.deck) < DECK_SIZE:
                self.deck.append(name)
            self.plays += 1
            self.last_play_index[name] = self.plays
            self.last_seen_at[name] = now

    # -------------------------------------------------------------- querying

    def plays_since(self, card: str) -> Optional[int]:
        index = self.last_play_index.get(card)
        return None if index is None else self.plays - index

    def definitely_unavailable(self, card: str) -> bool:
        """True when the cycle says this card cannot be in their hand.

        Only the confident direction: a card seen fewer than four deploys ago is
        still behind three others. The converse - that a card *is* available -
        is not claimed, because we cannot see which of their remaining four they
        hold.
        """
        since = self.plays_since(card)
        return since is not None and since < CYCLE_GAP

    def known_answers(self) -> List[str]:
        """Cards in their observed deck that would stop a Hog."""
        return [card for card in self.deck if card in HOG_ANSWERS]

    def answer_ready(self) -> bool:
        """Could any Hog answer we have seen be in their hand right now?

        Deliberately pessimistic while we are still learning the deck: before
        we have seen an answer at all, assume they have one. Claiming a free Hog
        because we have not seen their Cannon yet would be the same mistake as
        trusting the empty-elixir reading.
        """
        answers = self.known_answers()
        if not answers:
            return True
        return any(not self.definitely_unavailable(card) for card in answers)

    @property
    def deck_known(self) -> bool:
        return len(self.deck) >= DECK_SIZE

    def summary(self) -> str:
        if not self.deck:
            return "opponent unknown"
        answers = self.known_answers()
        blocked = [c for c in answers if self.definitely_unavailable(c)]
        return (f"deck {len(self.deck)}/8 plays={self.plays} "
                f"answers={len(answers)} blocked={len(blocked)}")
