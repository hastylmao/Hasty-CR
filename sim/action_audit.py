"""Inventory unresolved *semantic* client action graphs.

The old report counted every ACTION/AEO/BUFF node and placed one node in
multiple buckets. A single hero could therefore add fifty "missing mechanics"
even when most nodes were animation or UI helpers. This report counts one
source file once and excludes source-backed, scenario-tested handlers.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp" / "gamedata" / "csv_logic" / "characters"
ACTION = re.compile(r"^\[(ACTION|AEO|BUFF)\.([^]]+)\]", re.M)

SUPPORTED_FILES = {
    "angry_barbarian_evo.toml", "baby_dragon_ev1.toml", "berserker_hero.toml",
    "blowdart_goblin_evo.toml",
    "cannon_cart.toml", "cannon_ev1.toml", "clone.toml",
    "electro_dragon_ev1.toml",
    "furnace_ev1.toml", "ghost_ev1.toml", "goblin_cage_ev1.toml",
    "goblin_demolisher.toml",
    "globalclone.toml", "goblin_giant_ev1.toml", "goblinstein.toml",
    "golden_knight.toml", "hunter_ev1.toml", "ice_golemite_hero.toml",
    "inferno_dragon_ev1.toml", "mega_knight_ev1.toml",
    "mini_pekka_hero.toml", "knight_hero.toml", "giant_hero.toml",
    "bowler_hero.toml", "dark_prince_hero.toml", "barb_log_hero.toml",
    "barb_log_hero_spell.toml", "valkyrie_hero.toml",
    "goblins_hero.toml", "tombstone_hero.toml",
    "ronin.toml", "boss_bandit.toml",
    "king_tower.toml",
    "minion_horde_ev1.toml", "musketeer_hero.toml", "royal_hog_ev1.toml",
    "musketeer_ev1.toml", "pekka_ev1.toml", "rage_barbarian_evo.toml",
    "ram_rider.toml",
    "skeleton_army_ev1.toml", "skeleton_balloon_ev1.toml",
    "snowball_ev1.toml", "vines.toml",
    "witch_ev1.toml",
    # `ActionOnDeflector`: deflecting her shot costs the deflector 25, which
    # the reflection path now applies. Her one action node is implemented.
    "firecracker.toml",
}

# Scenario/NPC graphs absent from the synced public RoyaleAPI card catalogue.
# They are not legal standard-battle actions and therefore do not block the RL
# card simulator. Keep this separate from SUPPORTED_FILES: excluded is not the
# same claim as implemented.
OUT_OF_SCOPE_FILES = {"goblin_queen.toml"}

# These files are not an undifferentiated implementation queue. Their
# deterministic/source-complete portions are implemented, but the remaining
# procedures depend on collision or trajectory behavior that the shipped
# numbers do not define. Keep the exact probe requirement beside the filename
# so a future pass cannot silently replace it with a plausible guess.
# Firecracker left this table on 2026-08-20. Its gate was "five-way non-homing
# fan collision", and non-homing collision turned out not to be an open
# question: the published projectile data sets `check_collisions` false and a
# shot that has left an attacker connects with what it was fired at. The card
# deals its damage correctly now, so there was nothing left to calibrate.
CALIBRATION_GATED_FILES = {
    # Not a collision question. The damage is declared on an ACTION -
    # `ActionExecutionerEvoProjectile` with Damage 70 and StrongDamage 94 -
    # and nothing reads it, so the card currently deals nothing at all. What
    # is needed is the ping-pong controller that swaps between the normal and
    # strong projectile on distance, not a measurement.
    # The card deals its declared 70 now - the loader follows a projectile's
    # OnStartingAction into the controller that holds it. What is still open is
    # the ping-pong itself: the axe swaps between Strong and Normal projectile
    # data on `get_ping_pong_projectile_distance` crossing 2000 and 3000, so it
    # hits for StrongDamage 94 near the thrower on the way out and on the way
    # back, and 70 in between. That needs the axe's travel modelled, not a
    # constant.
    # The axe returns now, and hits on both legs - which is what the card is,
    # and what its own screen states as "70 x2". What remains is only where
    # the strong band ends: the client declares a hysteresis, strong below
    # 2000 outbound and below 3000 inbound, and this uses the single 2500
    # `StrongDamageRange` the card screen displays.
    "axeman_ev1.toml": (
        "strong-band hysteresis: 2000 outbound against 3000 inbound, "
        "modelled as the displayed 2500"),
    # Implemented. `ActionGoblinDrillEvoRelocate` declares the thresholds
    # (66 and 33 percent), the a second underground, and the goblins left
    # behind - two, then one. The destination is the only part the file does
    # not state, and the published behaviour does: same spot, unless it is
    # hugging a crown tower, in which case a quarter turn around it. What is
    # left is how close "hugging" is, named as `Battle.DRILL_TOWER_REACH_MT`.
    "goblin_drill_ev1.toml": (
        "how near a crown tower counts as beside it, deciding whether the "
        "resurface is in place or a quarter turn around"),
    # The ice arrow is implemented: every third attack drops the declared
    # three-tile, 5500ms `IceWizardSlowDown` field. The one number the client
    # does not carry is the cadence - `Princess_EV1_reload_frequency` is an
    # empty VARIABLE - and the published "every 3, starting with the first" is
    # recorded in combat_rules.json with its source.
    #
    # What is left is where the arrow's field lands when the shot is leading a
    # moving target: it is placed on the target rather than at the point the
    # arrow actually reaches.
    "princess_ev1.toml": (
        "ice-arrow field placement against a moving target: placed on the "
        "target rather than where the arrow lands"),
    # Implemented. The "accelerated payload trajectory" is a declared formula -
    # the speed ramps +2 every 150ms and is overridden to
    # `logX10000(max(5, rampup - 1)) / 80` - and integrating it gives the dive
    # time. Target selection, the fallback landing and the landing burst are
    # all read from the file.
    #
    # The one open question is which logarithm `logX10000` means. Natural log
    # puts him down in 0.9-1.5s across the range, matching the published
    # "after a 1-second delay"; base ten would take 1.5-2.7s. It moves when he
    # lands, never where.
    "balloon_hero.toml": (
        "which logarithm logX10000 denotes, deciding the dive time within "
        "about a second"),
    # Narrowed by reading the file. The ability is fully declared: 100ms of
    # invisibility, a decoy `EliteArcherHero_Dummy` left where he stood for
    # 7000ms, and a triple shot for the same 7000ms - Damage 19,
    # `ProjectileCount = 2` beside the normal arrow, 1500 apart. None of that
    # needs measuring; it needs writing, and it is currently the reason the
    # ability is offered and then refused. Only the pierce ordering along the
    # line is genuinely a calibration question.
    # Implemented: the decoy, its declared seven-second life, and the three
    # arrows abreast. What remains is ordering along each line - arrows are
    # resolved by distance rather than swept, the same treatment the ordinary
    # pierce already gets.
    "elite_archer_hero.toml": (
        "hit ordering along each of the three lines, resolved by distance "
        "rather than swept"),
    # Target acquisition and arrival are implemented: the client declares
    # `ActionWarpCharacter` Speed 1500 with a resolver picking the lowest max
    # hitpoints, furthest first, towers excluded, and the loader had simply
    # never parsed TARGET_RESOLVER sections. What is left is the flight shape -
    # `Acceleration = 400` describes a curve, and the engine arrives after
    # distance/speed. That changes when it lands, not where.
    "mega_minion_hero.toml": (
        "warp flight curve: Acceleration 400 is unmodelled, arrival is "
        "distance/Speed"),
    # Both halves are implemented. Projectile reflection back at the attacker
    # already was; spell reflection is now, onto the caster's nearest own crown
    # tower, for the projectile-based spells only - which the data itself
    # distinguishes, and which matches the published list once Lightning is
    # excluded by its declared `ProjectileStartHeight`.
    #
    # What is left is the arrival path: a reflected spell is placed on the
    # tower rather than flown back along a trajectory, so its travel time is
    # the spell's own rather than the return leg's.
    "monk.toml": (
        "reflected spell travel time: the return leg is placed, not flown"),
    # The attraction is implemented. `AttractPercentage` was declared on the
    # buff all along - 250 here, 300 on Evolved Valkyrie, 360 on Tornado - and
    # the engine had no pull of any kind, so a meta staple was a second of weak
    # damage that moved nothing. What remains is the flight: the ability form
    # rises to FlyingHeight 3500 over `TransitionDuration`, and the simulator
    # swaps forms without modelling the climb.
    "wizard_hero.toml": (
        "ground-to-air climb: the form swap is modelled, the 3500-height "
        "transition arc is not"),
}


def report() -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for path in DATA.rglob("*.toml"):
        if path.name in SUPPORTED_FILES or path.name in OUT_OF_SCOPE_FILES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        nodes = ACTION.findall(text)
        if not nodes:
            continue
        if path.name in CALIBRATION_GATED_FILES:
            found["calibration-gated source graphs"].append(
                f"{path.name} ({len(nodes)} nodes): "
                f"{CALIBRATION_GATED_FILES[path.name]}")
            continue
        folded = " ".join(name.lower() for _kind, name in nodes)
        filename = path.name.lower()
        if "_ev1" in filename or "_evo" in filename or "_ev" in folded:
            category = "unresolved evolution source graphs"
        elif ("hero" in filename or any(
                word in folded for word in (
                    "ability", "guardian", "resurrect", "teleport", "deflect"))):
            category = "unresolved champion / hero source graphs"
        elif any(word in folded for word in (
                "transform", "clone", "attract", "chain", "ramp", "snare")):
            category = "unresolved special source graphs"
        else:
            continue
        found[category].append(f"{path.name} ({len(nodes)} nodes)")
    return {category: sorted(set(entries)) for category, entries in found.items()}


def main() -> int:
    total = 0
    for category, entries in report().items():
        total += len(entries)
        print(f"{category}: {len(entries)}")
        for entry in entries:
            print(f"  {entry}")
    print(f"\nSemantic source files still requiring implementation or probe: {total}")
    print("Visual/UI sub-actions are intentionally not counted as mechanics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
