"""Two reported oddities, checked against the engine rather than argued about.

1. A card appearing to be played again a second or two after it was played.
   The deck is eight cards and the hand is four, so the same card cannot come
   back until four others have gone down. This walks a real match and reports
   the actual gap, in seconds and in plays, between repeats of a card.

2. A troop deployed at the back of one lane walking at a building in the other
   lane, across the river. `Battle._acquire_target` gates what a unit can
   *see* by its sight range, but the building pull that gives a
   building-targeter its destination is not gated at all - so any building
   anywhere outranks the lane it was sent down.

Run it with no arguments; it prints what it found and exits non-zero if either
check fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim import arena                                            # noqa: E402
from sim.arena import MT, Point                                  # noqa: E402
from sim.entities import make_unit                               # noqa: E402
from sim.gamedata import load_gamedata                           # noqa: E402
from sim.match import Match                                      # noqa: E402
from sim.runner import DECK_26, resolve_deck                     # noqa: E402
from sim.spells import load_spells                               # noqa: E402


def check_cycle(matches: int = 3) -> bool:
    """Play greedily and record when each card comes back around."""
    from sim.runner import BrainPolicy

    cards = resolve_deck(load_gamedata(level=11), DECK_26)
    spells = load_spells(level=11)
    worst_gap_s = None
    worst_plays = None
    offenders = []

    for seed in range(1, matches + 1):
        match = Match(cards=cards, decks=(list(DECK_26), list(DECK_26)),
                      seed=seed, spells=spells)
        ours, theirs = BrainPolicy(cards, 1), BrainPolicy(cards, -1)
        played: list[tuple[int, str]] = []
        last_seen: dict[str, tuple[int, int]] = {}
        while not match.finished and match.elapsed_ms < 180_000:
            for side, brain in ((1, ours), (-1, theirs)):
                hand_before = list(match.players[side].hand)
                move = brain.act(match)          # plays the card itself
                if move is None or side != 1:
                    continue
                card = move[0]
                if card not in hand_before:
                    offenders.append((seed, card, 0.0, 0))
                    print(f"  ILLEGAL: {card} played from hand {hand_before}")
                index = len(played)
                played.append((match.elapsed_ms, card))
                if card in last_seen:
                    was_ms, was_index = last_seen[card]
                    gap_s = (match.elapsed_ms - was_ms) / 1000.0
                    gap_plays = index - was_index
                    if worst_gap_s is None or gap_s < worst_gap_s:
                        worst_gap_s, worst_plays = gap_s, gap_plays
                    if gap_plays < 4:
                        offenders.append((seed, card, gap_s, gap_plays))
                last_seen[card] = (match.elapsed_ms, index)
            match.step()

    print(f"cycle: {matches} matches, closest repeat of any card "
          f"{worst_gap_s:.1f}s apart and {worst_plays} plays apart")
    if offenders:
        for seed, card, gap_s, gap_plays in offenders[:5]:
            print(f"  ILLEGAL seed {seed}: {card} repeated after "
                  f"{gap_plays} plays ({gap_s:.1f}s)")
        return False
    print("  hand and cycle are enforced: no card returned in under 4 plays")
    return True


def check_lane_pull() -> bool:
    """A Hog sent down the right lane, with a Cannon parked on the far left."""
    cards = load_gamedata(level=11)
    spells = load_spells(level=11)
    match = Match(cards=resolve_deck(cards, DECK_26),
                  decks=(list(DECK_26), list(DECK_26)), seed=1, spells=spells)
    battle = match.battle

    hog = battle.add(make_unit(9001, cards["hog_rider"].unit, 1,
                               arena.tile(14, 26)))
    hog.deploy_remaining_ms = 0
    cannon = battle.add(make_unit(9002, cards["cannon"].unit, -1,
                                  arena.tile(3, 13)))
    cannon.deploy_remaining_ms = 0

    sight = hog.sight_range_mt / MT
    gap = ((hog.pos.x - cannon.pos.x) ** 2
           + (hog.pos.y - cannon.pos.y) ** 2) ** 0.5 / MT
    print(f"lane pull: hog at tile (14,26) sight {sight:.1f} tiles; "
          f"enemy cannon at (3,13) is {gap:.1f} tiles away")

    start_x = hog.pos.x
    for _ in range(120):                  # six seconds
        battle.step()
    drift = (hog.pos.x - start_x) / MT
    chasing = hog.target_uid == cannon.uid or hog.walk_target_uid == cannon.uid

    print(f"  after 6s the hog has moved {drift:+.1f} tiles across "
          f"(target={'cannon' if chasing else 'not the cannon'})")
    if chasing or drift < -1.0:
        print("  WRONG: a building 16 tiles away and in the other lane should "
              "not out-pull the lane the hog was sent down")
        return False
    print("  hog stays in its lane")
    return True


def main() -> int:
    ok = check_cycle()
    print()
    ok = check_lane_pull() and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
