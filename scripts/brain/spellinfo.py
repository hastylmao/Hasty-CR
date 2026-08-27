"""What a spell actually does to a tower, from the client's own numbers.

`CrownTowerDamagePercent` in the extracted client data is a **reduction**, and
it is severe: Fireball carries -75 and Log carries -87, so a tower takes 25%
and 13% of their damage respectively. Measured at tournament level against the
3346-hitpoint princess towers this account plays with:

    fireball   700 damage -> 175 to a tower =  5.23% of it
    the_log    275 damage ->  35 to a tower =  1.05% of it

Two things follow, and the bot was getting both wrong.

*The finisher was mis-set.* `fireball_finish_hp` has been 0.068 and then 0.15,
so the bot spent its Fireball on towers at 15% - which it cannot kill, leaving
them alive at about 10%. A guaranteed finish needs the tower at or under 5.2%.

*Chip is asymmetric.* A Fireball at the tower is 5.2% for four elixir, which is
worth having in double elixir and decisive in a close game. A Log at the tower
is 1.05% for two - a quarter of the damage per elixir, and it throws away the
deck's only answer to a ground swarm. So the bot should chip with Fireball and
never with Log, and until now it had no notion of either.
"""

from __future__ import annotations

# Fraction of one princess tower a spell removes, at tournament level.
# Derived from the extracted client data, not recalled - see the module note.
TOWER_FRACTION = {
    "fireball": 0.052,
    "the_log": 0.010,
}

# Which spells are worth throwing at a tower purely for chip damage.
CHIP_SPELLS = ("fireball",)


def tower_fraction(card: str) -> float:
    return TOWER_FRACTION.get(card, 0.0)


def can_finish(card: str, tower_hp: float, inbound: float = 0.0) -> bool:
    """Whether this spell finishes a tower sitting at `tower_hp`.

    `inbound` is damage already on its way - a Hog mid-swing, say - expressed
    as a fraction of a tower. Counting it is what lets the bot finish at 8% when
    the Hog will cover the difference, instead of either wasting the spell or
    missing the kill.
    """
    return tower_hp > 0.0 and tower_hp <= tower_fraction(card) + inbound


def worth_chipping(card: str, elixir: float, cost: int, multiplier: float,
                   spare_elixir: float = 7.0) -> bool:
    """Chip only with elixir to spare, and mostly when it is cheap to have.

    Deliberately conservative: the Fireball is also the answer to a support
    cluster, so spending it on a tower is only right when there is nothing to
    answer and the bar is nearly full - or when elixir is flowing at double or
    triple rate and holding it costs nothing.
    """
    if card not in CHIP_SPELLS:
        return False
    if elixir - cost < 0:
        return False
    if multiplier >= 2.0:
        return elixir >= spare_elixir - 1.0
    return elixir >= spare_elixir
