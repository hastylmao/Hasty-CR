"""Run the same scenario through two independently built engines.

Where two implementations of the same game disagree, at least one is wrong.
That finds bugs without a recording, a human, or anyone's permission - which
matters here because the recorded evidence took days to gather and covers one
scenario.

The other engine is Jason-XII/clash-royale-simulator, checked out under
_references/. It is a separate Python implementation with A* pathfinding, its
own card tables, and - the reason this file exists - an explicit
`resolve_collisions` step that this engine has no equivalent of. Ours steers
around obstacles; that one resolves overlaps. Three independent measurements
already point at our collision handling, and this is the cheapest way to see
what a different treatment of it produces on identical input.

**Nothing is copied from it.** That repository carries no licence, so its code
cannot go into this MIT-licensed project. It is imported and driven as a black
box, and only the numbers that come out are compared - which is ordinary use of
published software, not derivation from it.

Both engines start princess towers at 3052 hit points and lay the arena out on
the same 18x32 grid, so a tower-damage count means the same thing in each.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "_references" / "clash-royale-simulator" / "src" / "clasher_new"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRINCESS_HP = 3052
TICK = 0.05                      # both engines advance in 50ms steps


# --------------------------------------------------------------------- ours

def ours(blocker: str | None, delay_s: float, seconds: float = 30.0) -> int:
    """Tower hits a Hog lands, with an optional body block, in this engine."""
    from sim import arena
    from sim.engine import Battle
    from sim.entities import make_tower, make_unit
    from sim.gamedata import load_gamedata

    cards = load_gamedata(level=11)
    tower_args = (PRINCESS_HP, 109, 800, 7500)

    battle = Battle()
    right = battle.add(make_tower(0, -1, arena.ENEMY_PRINCESS["right"], *tower_args)).uid
    battle.add(make_tower(0, -1, arena.ENEMY_PRINCESS["left"], *tower_args))
    king = battle.add(make_tower(0, -1, arena.ENEMY_KING, *tower_args, king=True))
    king.target_only_buildings = True          # a king sleeps until provoked

    hog = battle.add(make_unit(0, cards["hog_rider"].unit, 1, arena.tile(14, 18)))
    dropped = blocker is None
    hits, before = 0, battle.entities[right].hitpoints

    for tick in range(int(seconds / TICK)):
        if not dropped and tick * TICK >= delay_s:
            dropped = True
            card = cards[blocker]
            for i in range(card.summon_number or 1):
                dx, dy = ((0, 0), (1, 0), (0, 1), (1, 1))[i % 4]
                battle.add(make_unit(0, card.unit, -1, arena.tile(14 + dx, 17 - dy)))
        battle.step()
        now = battle.entities[right].hitpoints
        if now < before:
            hits += 1
            before = now
        if not hog.alive:
            break
    return hits


# ---------------------------------------------------------------- reference

def reference(blocker: str | None, delay_s: float, seconds: float = 30.0) -> int | None:
    """The same scenario in the other engine, or None if it cannot be built."""
    if not REFERENCE.exists():
        return None
    if str(REFERENCE) not in sys.path:
        sys.path.insert(0, str(REFERENCE))
    # Their card loader opens gamedata.json by relative path, so it only
    # imports with its own directory as the working directory. Ours is already
    # imported by now and resolves from ROOT, so the swap is safe.
    import os
    previous = os.getcwd()
    os.chdir(REFERENCE)
    try:
        from battle import BattleState
        from core import Position
        from player import PlayerState
    except Exception as exc:
        os.chdir(previous)
        print(f"  reference engine unavailable: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return None

    # Their card keys carry no underscores; these are read from their own
    # gamedata rather than guessed.
    deck = ["HogRider", "Skeletons", "Knight", "Musketeer",
            "IceSpirits", "Firecracker", "Golem", "SkeletonKing"]
    left = PlayerState(0, list(deck), 10.0)
    right_player = PlayerState(1, list(deck), 10.0)
    state = BattleState(left, right_player)

    names = {"skeletons": "Skeletons", "musketeer": "Musketeer",
             "knight": "Knight"}

    # Their orientation is MIRRORED from ours. Player 0 owns the BLUE towers
    # at y=6.5 and attacks downward at player 1's RED towers at y=25.5, so its
    # own half is y < 16. Deploying at y=17.5, as this first did, is enemy
    # ground and the engine correctly refuses it.
    #
    # Their river band is y 15.0-16.0 and nothing deploys inside it, so the
    # nearest legal spot to the bridge is 14.5. Ours is placed at 18.5 to
    # match: both engines then walk exactly eleven tiles to the tower.
    quiet = io.StringIO()
    with contextlib.redirect_stdout(quiet):
        ok = state.deploy_card(0, "HogRider", Position(14.5, 14.5))
        if not ok:
            os.chdir(previous)
            return None
        dropped = blocker is None
        target = None
        best = 99.0
        for entity in state.entities.values():
            owner = getattr(entity, "player", getattr(entity, "player_id", None))
            if owner != 1 or getattr(entity, "name", "") == "KingTower":
                continue
            pos = getattr(entity, "position", None)
            if pos is None:
                continue
            gap = abs(getattr(pos, "x", 99.0) - 14.5)
            if gap < best:                 # the right princess tower
                best, target = gap, entity
        if target is None:
            os.chdir(previous)
            return None
        hits, before = 0, getattr(target, "hitpoints", getattr(target, "hp", 0))

        for tick in range(int(seconds / TICK)):
            if not dropped and tick * TICK >= delay_s:
                dropped = True
                # y>=18 is the nearest player 1 may legally deploy: the
                # river is 15-16 and there is a further buffer beyond it.
                # At 16.5 the call returns False and the "block" is a Hog
                # walking an empty lane - which read as a body block costing
                # nothing at all rather than as a failed setup.
                placed = state.deploy_card(1, names.get(blocker, "Skeletons"),
                                           Position(14.5, 18.0))
                if not placed:
                    os.chdir(previous)
                    raise RuntimeError("reference refused the blocker deploy")
            state.step(TICK)
            now = getattr(target, "hitpoints", getattr(target, "hp", 0))
            if now < before:
                hits += 1
                before = now
    os.chdir(previous)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blocker", default="skeletons")
    ap.add_argument("--delay", type=float, default=0.5)
    args = ap.parse_args()

    print("Same scenario, two engines. Recorded from a real match: "
          "7 hits unblocked, 2 blocked.\n")
    print(f"{'scenario':<26}{'ours':>8}{'reference':>12}")
    print("-" * 46)
    for label, blocker in ((f"hog alone", None),
                           (f"hog + {args.blocker}", args.blocker)):
        a = ours(blocker, args.delay)
        b = reference(blocker, args.delay)
        shown = "n/a" if b is None else str(b)
        print(f"{label:<26}{a:>8}{shown:>12}")
    print("\nA disagreement localises the defect; agreement means both share it "
          "or both are right.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
