"""Does elixir arrive at the rate the real game pays it?

Every decision the policy makes is an affordability decision, so the income
rate is the single number that sets the tempo of the whole environment. It has
been wrong before: 5% of all elixir income was being truncated away by integer
division, which is small enough to look like nothing and large enough to change
which cycle a Hog deck can sustain.

Rates are asserted against the published figures rather than against the
constant in the code, because a test that reads the same constant the code
reads cannot disagree with it.

Measuring this needs care. The bar caps at ten, so a player who never spends
stops gaining and the naive measurement reports the cap rather than the rate;
these tests drain the bar every tick.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.gamedata import load_gamedata                          # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.runner import DECK_26, resolve_deck                    # noqa: E402
from sim.spells import load_spells                              # noqa: E402

FULL = load_gamedata(level=11)
CARDS = resolve_deck(FULL, DECK_26)
SPELLS = load_spells(level=11)

# Published seconds per elixir, by phase.
SINGLE, DOUBLE, TRIPLE = 2.8, 1.4, 0.933


def _seconds_per_elixir(start_ms: int, window_ms: int = 40_000) -> float:
    match = Match(cards=CARDS, decks=(DECK_26, list(DECK_26)), seed=1,
                  spells=SPELLS)
    while match.elapsed_ms < start_ms:
        match.step()
        match.players[1].elixir = 0
    gained = 0
    started = match.elapsed_ms
    while match.elapsed_ms < start_ms + window_ms:
        before = match.players[1].elixir
        match.step()
        after = match.players[1].elixir
        if after > before:
            gained += after - before
        match.players[1].elixir = 0
    assert gained, "no elixir arrived at all"
    return ((match.elapsed_ms - started) / 1000.0) / (gained / 1000.0)


@pytest.mark.parametrize("phase_start,expected,label", [
    (5_000, SINGLE, "single"),
    (125_000, DOUBLE, "double"),
    (245_000, TRIPLE, "triple"),
])
def test_income_matches_the_published_rate(phase_start, expected, label):
    measured = _seconds_per_elixir(phase_start)
    assert measured == pytest.approx(expected, abs=0.005), (label, measured)


def test_double_is_exactly_twice_single_and_triple_three_times():
    """The phases are one rate divided, so rounding must not drift them apart."""
    single = _seconds_per_elixir(5_000)
    assert _seconds_per_elixir(125_000) == pytest.approx(single / 2, abs=0.005)
    assert _seconds_per_elixir(245_000) == pytest.approx(single / 3, abs=0.005)


def test_income_is_not_silently_truncated():
    """The historical bug, stated as the thing it cost.

    Integer division threw away a slice of every tick's income. Over a full
    single-elixir minute that is a whole card, so it is asserted as a total
    rather than as a rate where it would round away.
    """
    match = Match(cards=CARDS, decks=(DECK_26, list(DECK_26)), seed=1,
                  spells=SPELLS)
    gained = 0
    while match.elapsed_ms < 60_000:
        before = match.players[1].elixir
        match.step()
        after = match.players[1].elixir
        if after > before:
            gained += after - before
        match.players[1].elixir = 0
    # 60 seconds at 2.8s each is 21.43 elixir; a 5% loss would show as ~20.3.
    assert gained / 1000.0 == pytest.approx(60 / SINGLE, abs=0.1), gained
