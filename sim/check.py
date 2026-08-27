"""Predictions the simulator makes that a person can check in a real match.

The engine is tested against the game's own data files, which is necessary and
not sufficient. It was fully self-consistent and 25% wrong about movement speed
until someone placed one Ice Golem in a real game and looked. That single test
found five bugs.

So this prints a short list of situations with a concrete predicted number,
small enough to run through in a few matches. Where the sim and the game
disagree, the sim is wrong until proven otherwise.

    python -m sim.check
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts")):
    if path not in sys.path:
        sys.path.insert(0, path)

from sim.adapter import grid_to_point                    # noqa: E402
from sim.arena import MT, Point, TICK_MS, distance       # noqa: E402
from sim.engine import Battle                            # noqa: E402
from sim.entities import make_unit                       # noqa: E402
from sim.gamedata import load_characters, load_gamedata, to_snake_case  # noqa: E402
from sim.match import Match                              # noqa: E402
from sim.runner import DECK_26, resolve_deck             # noqa: E402
from sim.spells import load_spells                       # noqa: E402

ALL = load_gamedata(11)
CHARACTERS = load_characters(11)
SPELLS = load_spells(11)


def _lookup(character: str):
    key = to_snake_case(character)
    card = ALL.get(key)
    if card is not None and card.unit is not None:
        return card.unit
    return CHARACTERS.get(key)


def _duel(attacker: str, defender: str, gap_tiles: float):
    """One against one, both alone, no towers. Returns (winner, seconds)."""
    battle = Battle()
    battle.unit_lookup = _lookup
    a = battle.add(make_unit(0, ALL[attacker].unit, 1, Point(9 * MT, 20 * MT)))
    d = battle.add(make_unit(0, ALL[defender].unit, -1,
                             Point(9 * MT, int((20 + gap_tiles) * MT))))
    for entity in (a, d):
        entity.deploy_remaining_ms = 0
    seconds = 0.0
    while a.alive and d.alive and seconds < 90:
        battle.step()
        seconds += TICK_MS / 1000.0
    winner = attacker if a.alive else defender if d.alive else "neither"
    return winner, seconds, (a.hitpoints, d.hitpoints)


def _push(card: str, place=(3, 17), defender: str | None = None):
    """One card sent at an undefended tower. Returns damage to that tower."""
    cards = dict(resolve_deck(ALL, DECK_26))
    for name in (card, defender):
        if name and name not in cards and name in ALL:
            cards[name] = ALL[name]
    deck = list(DECK_26)
    match = Match(cards=cards, decks=(deck, deck), seed=3, spells=SPELLS)
    match.players[1].hand = [card] + deck[:3]
    match.players[1].elixir = 10_000
    tower = match.towers[-1]["left"]
    before = tower.hitpoints
    if not match.play_card(1, card, grid_to_point(*place, 1)):
        return None
    if defender:
        match.players[-1].hand = [defender] + deck[:3]
        match.players[-1].elixir = 10_000
        match.play_card(-1, defender, grid_to_point(3, 20, -1))
    unit = [e for e in match.battle.entities.values()
            if e.side > 0 and not e.is_tower]
    for _ in range(int(60_000 / TICK_MS)):
        match.step()
        if not any(e.alive for e in unit):
            break
    return before - tower.hitpoints


def main() -> int:
    print("Things the simulator predicts. Check them in a real match; where it")
    print("disagrees with the game, the simulator is the one that is wrong.\n")

    checks = []

    dealt = _push("hog_rider")
    hits = dealt / ALL["hog_rider"].unit.damage if dealt else 0
    checks.append(("A lone Hog Rider on an undefended princess tower",
                   f"gets {hits:.0f} hits in ({dealt} damage) before dying"))

    dealt = _push("ice_golem", place=(3, 20))
    checks.append(("A lone Ice Golem sent at a princess tower",
                   f"deals {dealt} - one swing plus its death blast"))

    winner, seconds, _ = _duel("musketeer", "cannon", 10)
    checks.append(("A Musketeer walking into a Cannon, nothing else around",
                   f"{winner} wins after {seconds:.1f}s, untouched"))

    winner, seconds, hp = _duel("prince", "musketeer", 6)
    checks.append(("A Prince charging a lone Musketeer from 6 tiles",
                   f"{winner} wins in {seconds:.1f}s"))

    battle = Battle()
    battle.unit_lookup = _lookup
    spirit = battle.add(make_unit(0, ALL["ice_spirits"].unit, 1, Point(9 * MT, 20 * MT)))
    knight = battle.add(make_unit(0, ALL["knight"].unit, -1, Point(9 * MT, 21 * MT)))
    for e in (spirit, knight):
        e.deploy_remaining_ms = 0
    frozen = 0
    for _ in range(int(4000 / TICK_MS)):
        battle.step()
        if knight.buffed(battle.now_ms):
            frozen += TICK_MS
    checks.append(("An Ice Spirit hitting a Knight",
                   f"freezes it for {frozen/1000:.1f}s and dies doing it"))

    log = SPELLS["the_log"]
    checks.append(("The Log rolled over a Hog Rider",
                   f"pushes it back {log.pushback_mt/MT:.1f} tiles and does "
                   f"{log.damage} damage (a Giant is not pushed at all)"))

    poison = SPELLS["poison"]
    total = poison.damage_per_second * poison.life_duration_ms // 1000
    checks.append(("A Poison on a stationary unit for its whole duration",
                   f"deals {total} over {poison.life_duration_ms/1000:.0f}s "
                   f"and slows it {abs(poison.area_speed_pct)}%"))

    spec = ALL["miner"].unit
    checks.append(("A Miner sent at the far tower",
                   f"tunnels for about 3s, untouchable, at "
                   f"{spec.burrow_speed_mt_per_sec/MT:.1f} tiles/sec"))

    # Tower damage, now derived from the published per-level tables rather
    # than read off a screenshot. Both towers share one damage curve, so the
    # old 119/137 split - which matched no level and looked like a
    # transcription error - simply is not there any more.
    from sim.match import (KING_DAMAGE, KING_HIT_MS, PRINCESS_DAMAGE,
                           PRINCESS_HIT_MS)
    checks.append(("One princess tower shot on any unit",
                   f"deals {PRINCESS_DAMAGE}, once every "
                   f"{PRINCESS_HIT_MS/1000:.1f}s after a 1s windup"))
    checks.append(("One king tower shot on any unit",
                   f"deals {KING_DAMAGE}, once every {KING_HIT_MS/1000:.1f}s"))
    checks.append(("A Dagger Duchess in place of a princess tower",
                   "fires every 0.5s instead of 0.8s - run "
                   "`python -m sim.towers` for every variant"))

    width = max(len(a) for a, _ in checks)
    for question, answer in checks:
        print(f"  {question:<{width}s}   ->  {answer}")
    print("\nDisagreements are worth more than anything else in this file.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
