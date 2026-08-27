"""Card knowledge: what a detected enemy unit actually is and how to answer it.

The full 97-unit table lives in `units.json` (generated separately and
web-verified, because model priors about Clash Royale stats are stale).  The
fallback below covers the units that decide most ladder games, so the policy
degrades rather than crashes if the table is missing or partly malformed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

_TABLE_PATH = Path(__file__).with_name("units.json")

# key: (cost, air, hits_air, ranged, building, win_con, tank, swarm, threat,
#       dies_to_log, dies_to_fireball, melee_kitable)
_FALLBACK_ROWS = {
    #                       cost  air   hair   rng   bld   win   tank  swarm thr  log   fb    kite
    "archer":              (3,  False, True,  True,  False, False, False, True,  3, True,  True,  False),
    "baby_dragon":         (4,  True,  True,  True,  False, False, False, False, 4, False, False, False),
    "balloon":             (5,  True,  False, False, False, True,  False, False, 9, False, False, False),
    "bandit":              (3,  False, False, False, False, False, False, False, 5, False, False, True),
    "barbarian":           (5,  False, False, False, False, False, False, True,  6, False, False, True),
    "bat":                 (2,  True,  True,  False, False, False, False, True,  2, False, True,  False),
    "battle_ram":          (4,  False, False, False, False, True,  False, False, 6, False, False, False),
    "bomber":              (2,  False, False, True,  False, False, False, False, 3, True,  True,  False),
    "bowler":              (5,  False, False, True,  False, False, True,  False, 5, False, False, True),
    "cannon":              (3,  False, False, True,  True,  False, False, False, 1, False, False, False),
    "dark_prince":         (4,  False, False, False, False, False, True,  False, 6, False, False, True),
    "dart_goblin":         (3,  False, True,  True,  False, False, False, False, 3, True,  True,  False),
    "electro_giant":       (7,  False, False, False, False, True,  True,  False, 8, False, False, False),
    "electro_spirit":      (1,  False, True,  True,  False, False, False, False, 1, True,  True,  False),
    "electro_wizard":      (4,  False, True,  True,  False, False, False, False, 4, True,  True,  False),
    "elite_barbarian":     (6,  False, False, False, False, False, False, True,  7, False, False, True),
    "elixir_collector":    (6,  False, False, False, True,  False, False, False, 0, False, True,  False),
    "executioner":         (5,  False, True,  True,  False, False, False, False, 4, False, False, False),
    "fire_spirit":         (1,  False, True,  True,  False, False, False, False, 1, True,  True,  False),
    "firecracker":         (3,  False, True,  True,  False, False, False, False, 3, True,  True,  False),
    "fisherman":           (3,  False, False, True,  False, False, False, False, 4, False, True,  True),
    "flying_machine":      (4,  True,  True,  True,  False, False, False, False, 3, False, True,  False),
    "giant":               (5,  False, False, False, False, True,  True,  False, 8, False, False, False),
    "giant_skeleton":      (6,  False, False, False, False, True,  True,  False, 7, False, False, True),
    "goblin":              (2,  False, False, False, False, False, False, True,  2, True,  True,  True),
    "goblin_barrel":       (3,  False, False, False, False, True,  False, True,  6, True,  True,  False),
    "goblin_cage":         (4,  False, False, False, True,  False, False, False, 2, False, False, False),
    "goblin_drill":        (4,  False, False, False, True,  True,  False, False, 6, False, False, False),
    "golden_knight":       (4,  False, False, False, False, False, True,  False, 6, False, False, True),
    "golem":               (8,  False, False, False, False, True,  True,  False, 9, False, False, False),
    "golemite":            (0,  False, False, False, False, False, False, True,  3, False, False, True),
    "guard":               (3,  False, False, False, False, False, False, True,  3, False, False, True),
    "hog":                 (0,  False, False, False, False, True,  False, False, 5, False, False, False),
    "hog_rider":           (4,  False, False, False, False, True,  False, False, 7, False, False, False),
    "hunter":              (4,  False, True,  True,  False, False, False, False, 4, False, True,  False),
    "ice_golem":           (2,  False, False, False, False, False, True,  False, 2, False, True,  True),
    "ice_spirit":          (1,  False, True,  False, False, False, False, False, 1, True,  True,  False),
    "ice_wizard":          (3,  False, True,  True,  False, False, False, False, 3, True,  True,  False),
    "inferno_dragon":      (4,  True,  True,  True,  False, False, False, False, 5, False, False, False),
    "inferno_tower":       (5,  False, True,  True,  True,  False, False, False, 2, False, False, False),
    "knight":              (3,  False, False, False, False, False, True,  False, 4, False, False, True),
    "lava_hound":          (7,  True,  False, False, False, True,  True,  False, 7, False, False, False),
    "lava_pup":            (0,  True,  True,  True,  False, False, False, True,  2, False, True,  False),
    "lumberjack":          (4,  False, False, False, False, False, False, False, 6, False, False, True),
    "magic_archer":        (4,  False, True,  True,  False, False, False, False, 4, True,  True,  False),
    "mega_knight":         (7,  False, False, False, False, False, True,  False, 9, False, False, True),
    "mega_minion":         (3,  True,  True,  False, False, False, False, False, 3, False, False, False),
    "mighty_miner":        (4,  False, False, False, False, False, True,  False, 6, False, False, True),
    "miner":               (3,  False, False, False, False, True,  False, False, 4, False, False, True),
    "minion":              (3,  True,  True,  True,  False, False, False, True,  3, False, True,  False),
    "minipekka":           (4,  False, False, False, False, False, False, False, 7, False, False, True),
    "monk":                (5,  False, True,  False, False, False, True,  False, 6, False, False, True),
    "mortar":              (4,  False, False, True,  True,  True,  False, False, 5, False, False, False),
    "mother_witch":        (4,  False, True,  True,  False, False, False, False, 3, True,  True,  False),
    "musketeer":           (4,  False, True,  True,  False, False, False, False, 4, False, True,  False),
    "night_witch":         (4,  False, False, False, False, False, False, False, 5, False, True,  True),
    "pekka":               (7,  False, False, False, False, False, True,  False, 9, False, False, True),
    "phoenix_large":       (4,  True,  True,  False, False, False, False, False, 4, False, False, False),
    "phoenix_small":       (0,  True,  True,  False, False, False, False, False, 2, False, True,  False),
    "prince":              (5,  False, False, False, False, False, True,  False, 8, False, False, True),
    "princess":            (3,  False, True,  True,  False, False, False, False, 3, True,  True,  False),
    "ram_rider":           (5,  False, False, False, False, True,  False, False, 7, False, False, False),
    "rascal_boy":          (5,  False, False, False, False, False, True,  False, 4, False, False, True),
    "rascal_girl":         (0,  False, True,  True,  False, False, False, True,  2, True,  True,  False),
    "royal_ghost":         (3,  False, False, False, False, False, False, False, 5, False, False, True),
    "royal_giant":         (6,  False, False, True,  False, True,  True,  False, 9, False, False, False),
    "royal_hog":           (5,  False, False, False, False, True,  False, True,  6, False, False, False),
    "royal_recruit":       (7,  False, False, False, False, False, False, True,  4, False, False, True),
    "skeleton":            (0,  False, False, False, False, False, False, True,  1, True,  True,  True),
    "skeleton_dragon":     (4,  True,  True,  True,  False, False, False, True,  3, False, True,  False),
    "skeleton_king":       (4,  False, False, False, False, False, True,  False, 7, False, False, True),
    "sparky":              (6,  False, False, True,  False, False, False, False, 9, False, False, True),
    "spear_goblin":        (2,  False, True,  True,  False, False, False, True,  2, True,  True,  False),
    "tesla":               (4,  False, True,  True,  True,  False, False, False, 2, False, False, False),
    "tombstone":           (3,  False, False, False, True,  False, False, False, 1, False, True,  False),
    "valkyrie":            (4,  False, False, False, False, False, True,  False, 5, False, False, True),
    "wall_breaker":        (2,  False, False, False, False, True,  False, True,  5, True,  True,  False),
    "witch":               (5,  False, True,  True,  False, False, False, False, 4, False, True,  False),
    "wizard":              (5,  False, True,  True,  False, False, False, False, 4, False, True,  False),
    "x_bow":               (6,  False, False, True,  True,  True,  False, False, 7, False, False, False),
    "zappy":               (4,  False, True,  False, False, False, False, False, 3, False, True,  True),
}

_FIELDS = (
    "cost", "air", "hits_air", "ranged", "building", "win_con", "tank",
    "swarm", "threat", "dies_to_log", "dies_to_fireball", "melee_kitable",
    # Attack range in tiles and deploy time in seconds, taken from the extracted
    # card data. `ranged` only ever said whether a unit shoots, never how far,
    # so the policy could not know a Cannon (5.5) loses to a Musketeer (6.0) -
    # which it did, live, repeatedly. Absent for units with no game data, and
    # None must be read as "unknown", never as "short".
    "range", "deploy_s",
    # Splash radius in tiles, 0.0 for single-target attackers. Recorded because
    # the book had no way to express that a Valkyrie or a Dark Prince hits an
    # area, which is the first thing you would want to know before answering one
    # with a swarm. Nothing reads it yet: the obvious rule - never surround a
    # splash attacker with Skeletons - was tested in the simulator and did not
    # hold up. Skeletons against a Dark Prince leaked no tower damage at all.
    # The data is here so the question can be asked properly; the answer is not
    # in yet, so no decision depends on it.
    "splash",
)

_DEFAULT = {
    "cost": 4, "air": False, "hits_air": False, "ranged": False,
    "building": False, "win_con": False, "tank": False, "swarm": False,
    "threat": 4, "dies_to_log": False, "dies_to_fireball": False,
    "melee_kitable": True, "range": None, "deploy_s": 1.0, "splash": 0.0,
}


def _fallback_table() -> Dict[str, Dict[str, Any]]:
    return {name: dict(zip(_FIELDS, row)) for name, row in _FALLBACK_ROWS.items()}


class UnitBook:
    """Lookup with a merge policy: generated table first, fallback fills gaps."""

    def __init__(self, path: Path | None = None):
        self.table = _fallback_table()
        self.source = "fallback"
        self.load(path or _TABLE_PATH)

    def load(self, path: Path) -> None:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        merged = 0
        for name, props in raw.items():
            if not isinstance(props, dict):
                continue
            entry = dict(_DEFAULT)
            entry.update(self.table.get(name, {}))
            for field in _FIELDS:
                if field in props:
                    entry[field] = props[field]
            self.table[name] = entry
            merged += 1
        if merged:
            self.source = f"{path.name}({merged})"

    def get(self, name: str) -> Dict[str, Any]:
        return self.table.get(str(name).lower().replace("-", "_"), _DEFAULT)

    # Convenience predicates used all over the policy.
    def is_air(self, name: str) -> bool:
        return bool(self.get(name)["air"])

    def hits_air(self, name: str) -> bool:
        """Can this card shoot air at all. `is_air` is what the unit *is*."""
        return bool(self.get(name)["hits_air"])

    def threat(self, name: str) -> int:
        return int(self.get(name)["threat"])

    def cost(self, name: str) -> int:
        return int(self.get(name)["cost"])

    def kitable(self, name: str) -> bool:
        props = self.get(name)
        if props["air"] or props["building"] or props.get("win_con", False):
            return False
        if name in ("ice_golem", "wall_breaker", "elixir_golem"):
            return False
        return True

    def dies_to(self, spell: str, name: str) -> bool:
        key = "dies_to_log" if spell == "the_log" else "dies_to_fireball"
        return bool(self.get(name)[key])


BOOK = UnitBook()
