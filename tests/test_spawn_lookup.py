"""Does resolving a spawned character ever come back with the wrong unit?

`Battle` resolves a spawn by client name - `Golemite`, `BalloonBomb`,
`RamRider` - through `Match`'s lookup. That lookup tried the card table first,
after snake-casing the name, which is right for most spawns and catastrophic
for one shape: a companion whose name snake-cases onto a card name resolves to
that card's *own* unit.

`RamRider` became `ram_rider`, which is the Ram Rider card, whose unit is the
Ram - and the Ram declares `RamRider` as its attachment. `Battle.add` builds
the attachment and calls itself, so the Ram spawned a Ram spawned a Ram until
the stack ran out. It killed about one random-deck match in fifteen and never
appeared in a fixed-deck test, because Hog 2.6 contains no attachment cards.

The exact client identifier is now tried first, which is unambiguous by
construction: the character table is keyed by exactly that name.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.adapter import grid_to_point                           # noqa: E402
from sim.arena import TICK_MS                                   # noqa: E402
from sim.gamedata import load_characters, load_gamedata         # noqa: E402
from sim.match import Match                                     # noqa: E402
from sim.spells import load_spells                              # noqa: E402

CARDS = load_gamedata(level=11)
SPELLS = load_spells(level=11)
CHARACTERS = load_characters(11)

# Every character the client says carries a companion, and what it carries.
ATTACHMENTS = {name: str(getattr(spec, "attached_character", "") or "")
               for name, spec in CHARACTERS.items()
               if str(getattr(spec, "attached_character", "") or "")}


def _match(deck):
    return Match(cards=CARDS, decks=(deck, list(deck)), seed=1, spells=SPELLS)


def test_there_are_attachment_cards_to_test():
    assert ATTACHMENTS, "no character declares an attachment any more"


@pytest.mark.parametrize("carrier", sorted(ATTACHMENTS))
def test_an_attachment_never_resolves_back_to_its_carrier(carrier):
    """The cycle, stated directly rather than as a stack overflow.

    A companion must not resolve to a unit that declares that same companion,
    because that is precisely the loop `Battle.add` walks.
    """
    match = _match(["knight", "archers", "fireball", "musketeer",
                    "cannon", "skeletons", "zap", "giant"])
    companion_name = ATTACHMENTS[carrier]
    resolved = match.battle.unit_lookup(companion_name)
    assert resolved is not None, companion_name
    onward = str(getattr(resolved, "attached_character", "") or "")
    assert onward != companion_name, (carrier, companion_name, onward)


def test_a_carrier_card_deploys_with_its_companion_and_does_not_recurse():
    deck = ["goblin_giant", "knight", "archers", "fireball",
            "cannon", "skeletons", "zap", "giant"]
    match = _match(deck)
    for _ in range(40):
        match.step()
    # The hand is four of eight and shuffled, so waiting for the card to cycle
    # in would make the test depend on the shuffle. Put it in hand instead;
    # what is under test is the spawn, not the draw.
    player = match.players[1]
    if "goblin_giant" not in player.hand:
        player.hand[0] = "goblin_giant"
    player.elixir = 10_000
    assert match.play_card(1, "goblin_giant", grid_to_point(9, 22, 1))
    for _ in range(int(3 * 1000 / TICK_MS)):
        match.step()

    names = {entity.name for entity in match.battle.entities.values()
             if entity.alive and not entity.is_tower}
    assert "goblin_giant" in names, names
    # The companion is present, and exactly once rather than a stack of them.
    companions = [entity for entity in match.battle.entities.values()
                  if entity.alive and entity.name == "spear_goblin_giant"]
    assert len(companions) == 1, len(companions)
    assert not match.missing_spawns, match.missing_spawns
