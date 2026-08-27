"""Which fields does the client declare that the simulator never reads?

Written after Tornado. The engine had no attraction at all, so a meta staple
and an entire evolution silently did nothing, and no test failed because every
number *around* the missing mechanic was correct. Going card by card would
never have found it: the card list looked fine.

The failure has a shape, though. Somewhere in the shipped data a key is
declared, and nowhere in `sim/` is that key's name mentioned. That is
mechanical to check, so this checks it.

A hit is not a bug. Most unread keys are art, audio, or UI - `ScaledEffect`,
`PrefabAsset`, `IconSWF` - and some are engine internals that do not survive
into a headless simulation. What the list is for is reading down until
something is obviously a mechanic, the way `AttractPercentage` was.

Usage:
    python scripts/unread_fields.py            # mechanics-looking keys only
    python scripts/unread_fields.py --all      # everything unread
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tmp" / "gamedata" / "csv_logic"
SIM = ROOT / "sim"

KEY = re.compile(r"^\s*([A-Z][A-Za-z0-9_]*)\s*=", re.M)
SECTION = re.compile(r"^\s*\[+\s*([A-Z_]+)[.\]]", re.M)

# Presentation, not mechanics. Anything whose name says "how it looks" or
# "what it is called"; none of it survives into a headless simulation.
COSMETIC = re.compile(
    r"(Effect|Asset|Icon|SWF|Anim|Clip|Sound|Audio|Vfx|VFX|Sfx|Texture|Shader|"
    r"Prefab|Sprite|Model|Scale|Colou?r|Visual|Screen|Popover|Healthbar|"
    r"HealthBar|Export|File|TID|Name|Debug|Tutorial|Emote|Banner|Deck|Blueprint|"
    r"Shadow|Camera|Trail|Glow|Skin|UI|Hud|Offset[XYZ]$)")


# Keys looked at and deliberately left unread. Kept so a later run does not
# spend the same evening rediscovering them.
EXAMINED = {
    "IsBuilding":
        "Declared on 49 sections. The simulator infers building status from "
        "speed and card type instead, and the two agree on every one of them - "
        "checked in both directions. Reading the field would be tidier and "
        "would change nothing.",
    "DeployDelay":
        "300 or 400 on about forty-five characters, beside a DeployTime of "
        "1000 that the loader does read. Not a swarm stagger: Hog Rider and the "
        "Princess Tower declare it and deploy alone. It is a deploy-animation "
        "offset, and adding it as gameplay delay would slow half the roster "
        "against published deploy times.",
    "IgnoreBuff":
        "Buff immunities. Most are party-mode event buffs, but the pair that "
        "matters on ladder is VoodooCurse/GoblinCurse: Golem, Lava Hound, "
        "Battle Ram, Elixir Golem, Cannon Cart, Skeleton Balloon and "
        "Suspicious Bush are exempt from being converted, because what they "
        "leave when they die is their own. Unread, a cursed Golem left two "
        "Golemites AND a goblin. Implemented - see "
        "tests/test_curse_immunity.py.",
    "SubActionsDelay":
        "Genuinely unread, and mostly it costs nothing: almost every action "
        "group in the client is [0, 0] or a sub-tick 50ms. Twenty-five files "
        "do stage by a real interval, and most of that is animation and effect "
        "sequencing - the cards this project models were built from their "
        "declared values rather than by walking their graphs. The one place a "
        "delay had been transcribed by hand into the loader is Zap "
        "Evolution's two pulses, which are now checked against the graph by "
        "tests/test_transcribed_graphs.py, along with an assertion that no new "
        "staged group has appeared.",
    "SpawnRadius":
        "Scatter for where a spawner's units appear - 1500 for Dark Witch's "
        "bats, 650 for the spirits. `DeathSpawnRadius` is the one the loader "
        "reads and this is its live-spawn sibling. Left alone deliberately: it "
        "moves arrivals by under a tile and the separation pass reshuffles "
        "them anyway, and exact placement is explicitly out of scope.",
    "SpawnSpeedMultiplier":
        "Declared on twelve buffs and read by nothing, so a frozen Tombstone "
        "kept producing skeletons at its normal rate - Freeze on a defensive "
        "spawner bought only the attack pause. The client sets it to exactly "
        "the same number as HitSpeedMultiplier in every case (-100 for Stun "
        "and the freezes, 130-170 for the rages), so the field the simulator "
        "already carried was the right one and _tick_spawners simply never "
        "looked at it. See tests/test_spawner_buffs.py.",
    "DeflectBehaviour":
        "Declared on 33 projectiles and read by nothing, while Monk reflected "
        "everything. It says outright what he can catch and what happens: "
        "NoDeflect on 23 of them including Lightning, Princess and Electro "
        "Dragon; InvertDirection on the Logs, which roll back rather than "
        "being redirected; CheckOnlyTargetPosition on Arrows, which is why "
        "they need a closer landing. Monk's spell reflection had been built by "
        "inferring the set and was wrong about The Log. Reading the field beat "
        "reasoning about the data - see tests/test_monk_reflection.py.",
    "AttractPercentage":
        "What the sweep was written to find, and the reason it exists. Declared "
        "by Tornado (360), Evolved Valkyrie (300) and Wizard Hero (250) and "
        "read by nothing, so a meta staple and an entire evolution silently "
        "moved no one. Implemented - see tests/test_attraction.py.",
}


# Sections that describe how a unit or spell behaves in a battle. Everything
# else in csv_logic - game modes, rewards, leaderboards, shop offers, arena
# themes - declares hundreds of keys that could not possibly matter to a
# simulation, and drowns the list they would otherwise be read from.
GAMEPLAY = ("CHARACTER", "BUILDING", "BUFF", "AEO", "PROJECTILE", "ACTION",
            "SPELL", "EXT", "ABILITY", "TARGET_RESOLVER", "SHAPE",
            "AREA_EFFECT_OBJECT", "SPELL_EVOLVED", "CHARACTER_EVOLVED")


def declared() -> Counter:
    """Key names declared inside gameplay sections, with how often each appears.

    Scoped by section rather than by file: a single file happily mixes a
    character with the STATS block that describes how its card is drawn, and
    only one of those is a mechanic.
    """
    seen: Counter = Counter()
    for path in DATA.rglob("*.toml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        headings = list(SECTION.finditer(text))
        if not headings:
            continue
        for index, heading in enumerate(headings):
            if heading.group(1) not in GAMEPLAY:
                continue
            end = (headings[index + 1].start()
                   if index + 1 < len(headings) else len(text))
            seen.update(KEY.findall(text[heading.end():end]))
    return seen


def referenced() -> set[str]:
    """Every identifier the simulator mentions anywhere in its source."""
    words: set[str] = set()
    for path in SIM.rglob("*.py"):
        words.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*",
                                path.read_text(encoding="utf-8", errors="replace")))
    return words


def report(show_all: bool = False) -> list[tuple[str, int]]:
    known = referenced()
    rows = [(key, count) for key, count in declared().items()
            if key not in known and (show_all or not COSMETIC.search(key))]
    # Most-declared first: a key on fifty cards matters more than one on one.
    return sorted(rows, key=lambda row: (-row[1], row[0]))


def main() -> int:
    show_all = "--all" in sys.argv
    rows = report(show_all)
    print(f"{len(rows)} client keys the simulator never mentions"
          f"{'' if show_all else ' (cosmetics filtered out)'}\n")
    for key, count in rows:
        note = "   <- examined" if key in EXAMINED else ""
        print(f"  {count:5}  {key}{note}")
    print("\nA hit is a question, not a defect. Read down until one is "
          "obviously a mechanic.")
    print(f"{len(EXAMINED)} keys have already been looked at; EXAMINED in this "
          f"file records what came of each.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
