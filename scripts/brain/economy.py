"""Estimate the opponent's elixir.

The bot used to attack whenever *it* could afford a Hog, which is why the Hog
kept walking into a full-elixir opponent and dying to whatever they felt like
playing. 2.6 does the opposite: it sends the Hog when the opponent is short,
because a Hog they cannot answer is the entire win condition.

Nothing reports enemy elixir, so it is inferred:

* both players start at 5 and cap at 10,
* elixir regenerates every 2.8s, halving to 1.4s at 2:00 and about 0.9s at 4:00
  (verified by search, not recalled - the phase boundaries in particular were
  wrong in an earlier version of this file's config),
* every enemy unit that appears for the first time cost them its card's elixir.

The estimate drifts - spells are never seen as units, and a card played out of
our detector's view is missed - so it is deliberately conservative: unseen
spending is not guessed at, and the value is clamped into range every tick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List

START_ELIXIR = 5.0
MAX_ELIXIR = 10.0
SINGLE_SECONDS = 2.8
DOUBLE_SECONDS = 1.4
TRIPLE_SECONDS = 0.9

# Two units of the same card landing together are one purchase, not two.
# This has to cover more than the spawn animation: the unit tracker loses and
# re-acquires a unit repeatedly during a fight, and each re-acquisition looks
# like a first sighting. Charging for those pinned the estimate at 0.0 for a
# whole match, so every moment looked like a punish window.
#
# A fixed window alone does not close that hole: `tracker.STALE_SECONDS` is 2.5,
# so a unit the detector loses for three seconds mid-fight comes back as a fresh
# track, and anything living longer than this window is billed again every time.
# `observe_spawns` therefore also refreshes the timer for every name *currently
# visible*, so a unit that never actually left the arena can never be re-billed
# however long the fight runs. See `visible=` below.
SPAWN_DEDUPE_SECONDS = 6.0

# A card is *deployed* on their side of the arena or at the bridge. Anything
# appearing for the first time deep in our half is a unit we lost track of, not
# a purchase. (Miner and Goblin Drill genuinely do this; missing those two costs
# far less than billing every re-acquisition.)
MAX_DEPLOY_Y = 17.0


@dataclass
class EnemyEconomy:
    elixir: float = START_ELIXIR
    updated_at: float = 0.0
    spent: float = 0.0
    last_spawn: Dict[str, float] = field(default_factory=dict)
    charges: List[tuple[float, float]] = field(default_factory=list)  # (cost, at)
    started: bool = False

    def reset(self, now: float) -> None:
        self.elixir = START_ELIXIR
        self.updated_at = now
        self.spent = 0.0
        self.last_spawn.clear()
        self.charges.clear()
        self.started = True

    def regen_seconds(self, multiplier: float) -> float:
        if multiplier >= 3.0:
            return TRIPLE_SECONDS
        if multiplier >= 2.0:
            return DOUBLE_SECONDS
        return SINGLE_SECONDS

    def tick(self, now: float, multiplier: float) -> None:
        if not self.started:
            self.reset(now)
            return
        elapsed = max(0.0, now - self.updated_at)
        self.updated_at = now
        self.elixir = min(MAX_ELIXIR, self.elixir + elapsed / self.regen_seconds(multiplier))

    def observe_spawns(self, spawns: List[tuple[str, int, float]], now: float,
                       visible: Iterable[str] | None = None) -> float:
        """Charge the opponent for cards deployed for the first time.

        `spawns` is (unit_name, card_cost, grid_y) for tracks on their first
        sighting. `visible` is every enemy unit name on the field this frame,
        whether newly sighted or not; those names have their dedupe timer
        refreshed so a unit that is merely re-acquired is never billed as a
        second copy. Returns the elixir deducted, for logging.

        Passing `visible` makes the estimate *under*-count rather than over-count
        (a genuine second Musketeer played while the first is still alive is
        free), which is the direction this module already chooses deliberately:
        reading their bar as fuller than it is makes the bot cautious about
        sending the Hog, while reading it as empty made every moment look like a
        punish window.
        """
        deducted = 0.0
        for name, cost, y in spawns:
            if cost <= 0:
                continue  # spawned children (skeletons from a Tombstone, golemites)
            if y > MAX_DEPLOY_Y:
                continue  # re-acquired mid-fight in our half, not a new card
            if now - self.last_spawn.get(name, -99.0) < SPAWN_DEDUPE_SECONDS:
                continue  # same card, multiple units, or a flickering track
            self.last_spawn[name] = now
            self.elixir = max(0.0, self.elixir - cost)
            self.spent += cost
            self.charges.append((float(cost), now))
            deducted += cost
        # After charging, so a card deployed this frame is still billed once.
        for name in visible or ():
            self.last_spawn[name] = now
        del self.charges[:-40]
        return deducted

    def recent_spend(self, now: float, window: float = 5.0) -> float:
        """Elixir we *saw* them commit in the last `window` seconds.

        This is the honest punish signal. The running `elixir` estimate drifts
        low - every unit name is charged separately and a re-deploy after the
        dedupe window charges again - so "their bar is empty" was true almost
        all the time and the bot read every moment as a punish window, sending
        the Hog alone over and over. A directly observed recent commitment does
        not accumulate that error.
        """
        return sum(cost for cost, at in self.charges if now - at <= window)

    @property
    def is_low(self) -> bool:
        """Low enough that they cannot answer a Hog with a real defence."""
        return self.elixir < 4.0

    @property
    def is_committed(self) -> bool:
        """They have just emptied their bar into something."""
        return self.elixir < 2.5
