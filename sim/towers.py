"""Tower stats, including the tower troops that replace a Princess Tower.

`sim/match.py` carried four hardcoded numbers - princess 3346/119, king
5735/137 - with an honest comment saying they were read off a live account
because the tower-level curve was not in the shipped files. It is now: the
published `cards_stats_building` tables give hitpoints at every level for both
towers, and the tower projectiles give damage at every level.

Checked against those tables, the hardcoded values match **no level at all**.
Princess Tower hitpoints run ... 2968, 3262, 3584 ... and 3346 sits between
levels 10 and 11; the King's 5735 sits between 5592 and 6144. Most likely the
account had a tower troop equipped, which is the other half of this module.

A tower troop replaces the Princess Tower and is not a reskin:

    Princess Tower   1400 hitpoints, hits every 800ms
    Dagger Duchess   1270 hitpoints, hits every 500ms
    Cannoneer        1200 hitpoints, hits every 2200ms, 1400ms load
    Royal Chef       1240 hitpoints, hits every 1000ms

A simulator that always models the Princess Tower is wrong about every match
played with one of the others - Dagger Duchess alone fires 60% faster.

Base stats come from the client files, which are the authority on mechanics.
Per-level hitpoints come from the published tables where they exist, because
the client does not ship the tower level curve.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "data" / "royaleapi" / "cards_stats_building.json"
PROJECTILES = ROOT / "data" / "royaleapi" / "cards_stats_projectile.json"

# client file -> the name a player would use
TOWER_TROOPS = {
    "princesstower": "Princess Tower",
    "dagger_duchess": "Dagger Duchess",
    "cannoneer": "Cannoneer",
    "chef_tower": "Royal Chef",
}

DEFAULT_TOWER_LEVEL = 11


@dataclass(frozen=True)
class TowerSpec:
    """One tower, at one level."""

    key: str
    name: str
    hitpoints: int
    damage: int
    hit_speed_ms: int
    load_time_ms: int
    range_mt: int
    source: str


_SECTION = re.compile(r"^\[([A-Z_]+)\.([A-Za-z0-9_]+)\]", re.M)


def _tower_section(text: str) -> str:
    """The block describing the tower itself, not a companion or a projectile.

    `chef_tower.toml` holds `[CHARACTER.Chef]` with 5 hitpoints - the cook
    standing on it - and `[BUILDING.ChefTower]` with 1240, which is the tower.
    Taking the first match in the file gave Royal Chef five hitpoints. A
    BUILDING block is preferred, then a CHARACTER one, and only then the whole
    file.
    """
    blocks = list(_SECTION.finditer(text))
    for kind in ("BUILDING", "CHARACTER"):
        for index, match in enumerate(blocks):
            if match.group(1) != kind:
                continue
            end = (blocks[index + 1].start() if index + 1 < len(blocks)
                   else len(text))
            body = text[match.end():end]
            if re.search(r"^\s*Hitpoints\s*=\s*\d+", body, re.M):
                return body
    return text


def _client_field(path: Path, key: str) -> Optional[int]:
    """`key` from the tower's own section of a client TOML file.

    Anchored, because this codebase's recurring bug is an unanchored lookup
    where a longer key swallows a shorter one.
    """
    if not path.exists():
        return None
    body = _tower_section(path.read_text(encoding="utf-8", errors="replace"))
    found = re.search(rf"^\s*{key}\s*=\s*(\d+)", body, re.M)
    return int(found.group(1)) if found else None


def _projectile_field(path: Path, key: str) -> Optional[int]:
    """`key` from the projectile the tower section declares it fires."""
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    named = re.search(r'^\s*Projectile\s*=\s*"([A-Za-z0-9_]+)"',
                      _tower_section(text), re.M)
    if not named:
        return None
    block = re.search(
        rf"^\[PROJECTILE\.{re.escape(named.group(1))}\](.*?)(?=\n\[|\Z)",
        text, re.M | re.S)
    if not block:
        return None
    found = re.search(rf"^\s*{key}\s*=\s*(\d+)", block.group(1), re.M)
    return int(found.group(1)) if found else None


def _published_table(name: str, field: str) -> Optional[list]:
    if not PUBLISHED.exists():
        return None
    for row in json.loads(PUBLISHED.read_text(encoding="utf-8")):
        if isinstance(row, dict) and row.get("name") == name and row.get(field):
            return row[field]
    return None


def _projectile_damage(name: str, level: int) -> Optional[int]:
    if not PROJECTILES.exists():
        return None
    for row in json.loads(PROJECTILES.read_text(encoding="utf-8")):
        if isinstance(row, dict) and row.get("name") == name:
            table = row.get("damage_per_level")
            if table and 0 <= level - 1 < len(table):
                return int(table[level - 1])
    return None


def _scaled(base: int, table: Optional[list], level: int) -> int:
    """The published value at `level` if there is a table, else the base."""
    if table and 0 <= level - 1 < len(table):
        return int(table[level - 1])
    return int(base)


def princess_tower(level: int = DEFAULT_TOWER_LEVEL,
                   troop: str = "princesstower",
                   gamedata_root: Optional[Path] = None) -> TowerSpec:
    """The defending tower in a lane, which may be a tower troop."""
    if troop not in TOWER_TROOPS:
        raise ValueError(f"unknown tower troop {troop!r}; "
                         f"expected one of {sorted(TOWER_TROOPS)}")
    from .gamedata import GAMEDATA_ROOT

    root = Path(gamedata_root or GAMEDATA_ROOT) / "characters"
    path = root / f"{troop}.toml"

    hitpoints_base = _client_field(path, "Hitpoints") or 1400
    hit_speed = _client_field(path, "HitSpeed") or 800
    load_time = _client_field(path, "LoadTime")
    reach = _client_field(path, "Range") or 7500
    # A tower's damage lives on the projectile it fires, not on the tower
    # block - the same shape that gave Cannon and Musketeer zero damage until
    # the unit loader learned to follow `Projectile`.
    damage_base = _client_field(path, "Damage") or _projectile_field(path, "Damage") or 50

    # Only the standard tower has a published per-level curve. A tower troop
    # is carried along that same curve from its own base, holding the ratio
    # constant - the identical rule `gamedata.carry_verified` uses for a value
    # verified at one level. Returning the level-1 base instead would make
    # every tower troop about a third of a Princess Tower, which is a worse
    # error than an extrapolation along the curve its own class uses.
    tower_table = _published_table("PrincessTower", "hitpoints_per_level")
    if troop == "princesstower":
        hitpoints = _scaled(hitpoints_base, tower_table, level)
        damage = _projectile_damage("TowerPrincessProjectile", level)
    else:
        hitpoints = hitpoints_base
        if tower_table and 0 <= level - 1 < len(tower_table) and tower_table[0]:
            hitpoints = round(hitpoints_base * tower_table[level - 1]
                              / tower_table[0])
        damage = None
        published = _projectile_damage("TowerPrincessProjectile", level)
        base_at_one = _projectile_damage("TowerPrincessProjectile", 1)
        if published and base_at_one:
            damage = round(damage_base * published / base_at_one)

    return TowerSpec(
        key=troop,
        name=TOWER_TROOPS[troop],
        hitpoints=int(hitpoints),
        damage=int(damage if damage is not None else damage_base),
        hit_speed_ms=int(hit_speed),
        # princesstower.toml gives LoadTime 1000; a missing value means the
        # tower fires immediately, which handed every tower a free first shot
        # when it was assumed rather than read.
        load_time_ms=int(load_time if load_time is not None else 1000),
        range_mt=int(reach),
        source=str(path),
    )


def king_tower(level: int = DEFAULT_TOWER_LEVEL,
               gamedata_root: Optional[Path] = None) -> TowerSpec:
    from .gamedata import GAMEDATA_ROOT

    root = Path(gamedata_root or GAMEDATA_ROOT) / "characters"
    path = root / "king_tower.toml"
    return TowerSpec(
        key="king_tower",
        name="King Tower",
        hitpoints=_scaled(_client_field(path, "Hitpoints") or 2400,
                          _published_table("KingTower", "hitpoints_per_level"),
                          level),
        damage=int(_projectile_damage("KingProjectile", level)
                   or _client_field(path, "Damage") or 50),
        hit_speed_ms=int(_client_field(path, "HitSpeed") or 1000),
        load_time_ms=int(_client_field(path, "LoadTime") or 500),
        range_mt=int(_client_field(path, "Range") or 7000),
        source=str(path),
    )


def variants(level: int = DEFAULT_TOWER_LEVEL) -> Dict[str, TowerSpec]:
    return {key: princess_tower(level, key) for key in TOWER_TROOPS}


def main() -> int:
    print(f"tower stats at level {DEFAULT_TOWER_LEVEL}\n")
    king = king_tower()
    print(f"  {'tower':16s} {'hp':>6s} {'dmg':>5s} {'hit':>6s} {'load':>6s} {'range':>6s}")
    print(f"  {king.name:16s} {king.hitpoints:6d} {king.damage:5d} "
          f"{king.hit_speed_ms:6d} {king.load_time_ms:6d} {king.range_mt:6d}")
    for spec in variants().values():
        print(f"  {spec.name:16s} {spec.hitpoints:6d} {spec.damage:5d} "
              f"{spec.hit_speed_ms:6d} {spec.load_time_ms:6d} {spec.range_mt:6d}")
    print("\nA tower troop replaces the Princess Tower. Only the standard tower "
          "has a\npublished per-level curve; the others show their client base, "
          "which is what is known.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
