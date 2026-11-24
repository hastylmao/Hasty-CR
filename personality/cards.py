"""Card knowledge the detector needs: cost, kind, what counters what.

Costs are the game's published elixir costs. Names are normalized (lowercase,
letters only) so 'HogRider', 'hog_rider' and 'Hog Rider' are one key.
"""
from __future__ import annotations

import re


def norm(name: str) -> str:
    n = re.sub(r"[^a-z]", "", (name or "").lower())
    for suffix in ("spell", "ev", "evo"):
        if n.endswith(suffix) and len(n) > len(suffix) + 2:
            n = n[: -len(suffix)]
    return ALIASES.get(n, n)


ALIASES = {
    "thelog": "log", "icegolemite": "icegolem", "icespirits": "icespirit",
    "skeletonwarriors": "skeletons", "skeleton": "skeletons", "archer": "archers",
    "minion": "minions", "goblin": "goblins", "speargoblin": "speargoblins",
    "barbarian": "barbarians", "megaknightev": "megaknight", "zappies": "zappies",
    "goblinbarrel": "goblinbarrel", "royalrecruit": "royalrecruits",
}

COST = {
    "skeletons": 1, "icespirit": 1, "firespirit": 1, "electrospirit": 1, "healspirit": 1,
    "log": 2, "zap": 2, "snowball": 2, "giantsnowball": 2, "icegolem": 2, "speargoblins": 2,
    "goblins": 2, "bats": 2, "barbarianbarrel": 2, "rage": 2, "wallbreakers": 2, "bomber": 2,
    "cannon": 3, "knight": 3, "archers": 3, "minions": 3, "arrows": 3, "tornado": 3,
    "goblinbarrel": 3, "skeletonarmy": 3, "guards": 3, "miner": 3, "princess": 3,
    "icewizard": 3, "megaminion": 3, "dartgoblin": 3, "firecracker": 3, "earthquake": 3,
    "tombstone": 3, "goblingang": 3, "bandit": 3, "royalghost": 3, "skeletonbarrel": 3,
    "elixirgolem": 3, "battleram": 4, "eliteBarbarians".lower(): 6,
    "hogrider": 4, "musketeer": 4, "fireball": 4, "valkyrie": 4, "minipekka": 4,
    "poison": 4, "freeze": 4, "lumberjack": 4, "inferno dragon".replace(" ", ""): 4,
    "infernodragon": 4, "babydragon": 4, "electrowizard": 4, "magicarcher": 4,
    "mortar": 4, "furnace": 4, "goblincage": 4, "hunter": 4, "nightwitch": 4,
    "battlehealer": 4, "flyingmachine": 4, "zappies": 4, "ramrider": 5, "darkprince": 4,
    "prince": 5, "witch": 5, "wizard": 5, "balloon": 5, "barbarians": 5, "minionhorde": 5,
    "infernotower": 5, "bowler": 5, "executioner": 5, "graveyard": 5, "goblinhut": 5,
    "cannoncart": 5, "electrodragon": 5, "rocket": 6, "xbow": 6, "lightning": 6,
    "giant": 5, "royalgiant": 6, "sparky": 6, "elixircollector": 6, "royalrecruits": 7,
    "megaknight": 7, "lavahound": 7, "golem": 8, "pekka": 7, "electrogiant": 7,
    "goblingiant": 6, "threemusketeers": 9, "royalhogs": 5, "skeletondragons": 4,
    "goblindrill": 4, "monk": 5, "archerqueen": 5, "goldenknight": 4, "skeletonking": 4,
    "mightyminer": 4, "littleprince": 3, "goblinstein": 5, "bossbandit": 6,
    "megaminions": 3, "giantskeleton": 6, "bombtower": 4, "tesla": 4,
}
SPELLS = {"log", "zap", "snowball", "giantsnowball", "arrows", "tornado", "fireball",
          "poison", "freeze", "rocket", "lightning", "earthquake", "rage", "barbarianbarrel",
          "goblinbarrel", "graveyard", "royaldelivery", "void", "clone", "mirror"}
BUILDINGS = {"cannon", "tesla", "infernotower", "bombtower", "mortar", "xbow", "tombstone",
             "furnace", "goblincage", "goblinhut", "elixircollector", "barbarianhut", "goblindrill"}
WIN_CONDITIONS = {"hogrider", "giant", "royalgiant", "golem", "lavahound", "balloon",
                  "battleram", "ramrider", "goblingiant", "electrogiant", "megaknight",
                  "pekka", "xbow", "mortar", "graveyard", "goblinbarrel", "miner",
                  "royalhogs", "elixirgolem", "sparky", "goblindrill", "threemusketeers"}
# Decks the ladder collectively agrees are a war crime.
ANNOYING = {"megaknight", "xbow", "mortar", "goblinbarrel", "graveyard", "lavahound",
            "royalrecruits", "elixirgolem", "sparky", "threemusketeers", "goblindrill",
            "royalhogs", "electrogiant", "goblingiant", "princess"}
# Enemy card -> our cards that answer it. Spells near the unit count regardless.
COUNTERS = {
    "hogrider": {"cannon", "icegolem", "skeletons", "tesla", "minipekka", "infernotower"},
    "goblinbarrel": {"log", "zap", "arrows", "barbarianbarrel"},
    "skeletonarmy": {"log", "zap", "arrows", "valkyrie"},
    "minionhorde": {"arrows", "fireball", "icespirit"},
    "balloon": {"musketeer", "minions", "infernotower", "arrows"},
    "megaknight": {"minipekka", "pekka", "skeletons", "icegolem", "cannon", "musketeer"},
    "giant": {"cannon", "minipekka", "infernotower", "skeletons"},
    "golem": {"infernotower", "minipekka", "pekka"},
    "prince": {"skeletons", "icegolem", "cannon"},
    "darkprince": {"skeletons", "icegolem", "cannon"},
    "battleram": {"cannon", "skeletons", "icegolem", "log"},
    "princess": {"log", "zap", "arrows"},
    "goblingang": {"log", "zap", "arrows"},
    "wizard": {"fireball", "lightning"},
    "musketeer": {"fireball", "icegolem"},
}


def cost(name: str) -> int:
    return COST.get(norm(name), 4)


def is_spell(name: str) -> bool:
    return norm(name) in SPELLS


def is_building(name: str) -> bool:
    return norm(name) in BUILDINGS
