"""Instant-damage spells, from the client's own projectile definitions.

2.6 lives on Fireball and Log value, so treating spells as no-ops (spend the
elixir, change nothing) would bias every measurement in the simulator against
the deck it exists to study.

Two details from the data that are easy to miss and change play a lot:

* `CrownTowerDamagePercent` is a **reduction**. Fireball carries -75, so a
  tower takes 25% of its damage; Log carries -87, so 13%. Applying full damage
  to towers would make spell-chipping look far stronger than it is.
* The Log's area is an **ellipse**: `Radius = 1950` across but `RadiusY = 600`
  deep. It sweeps a wide, shallow band rather than a circle, which is exactly
  why it clears a line of troops but does not reach behind them.
"""

from __future__ import annotations

import math
import re
import json
import csv
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path
from typing import Dict, Optional

from . import arena
from .arena import Point, isqrt

GAMEDATA = Path(__file__).resolve().parents[1] / "tmp" / "gamedata" / "csv_logic"
VERIFIED_RULES = Path(__file__).resolve().parents[1] / "data" / "royaleapi" / "combat_rules.json"

# Card name -> (file stem, section to read). Kept explicit because the mapping
# from a playable card to its projectile is not derivable from the names.
SPELL_SOURCES = {
    "fireball": ("fireballspell", "PROJECTILE.FireballSpell"),
    "the_log": ("logprojectile", "PROJECTILE.LogProjectileRolling"),
    "log": ("logprojectile", "PROJECTILE.LogProjectileRolling"),
    # These two pointed at files that do not exist - arrowsspell.toml and
    # zapspell.toml - so they failed the `path.exists()` check and were skipped
    # in silence. The sim has been playing with two spells, not four. Arrows
    # live in arrows.toml under a projectile section; Zap is an area effect
    # object with no projectile at all, so it reads from [AEO.Zap].
    "arrows": ("arrows", "PROJECTILE.ArrowsSpell"),
    "zap": ("zap", "AEO.Zap"),
    "rage": ("ragebottle", "AEO.Rage"),
}


@dataclass(frozen=True)
class SpellSpec:
    name: str
    damage: int
    radius_mt: int
    radius_y_mt: int
    crown_tower_percent: int      # percent of damage towers take
    pushback_mt: int
    target_buff: str = ""         # Freeze, IceWizardSlowDown, ZapFreeze
    buff_time_ms: int = 0
    spawn_character: str = ""     # Goblin Barrel drops goblins, not damage
    spawn_count: int = 0
    life_duration_ms: int = 0     # lingering area effects: poison, tornado
    # A lingering effect keeps hurting what stands in it. Poison is 36 a second
    # every 1000ms for 8 seconds; Tornado 60 a second every 550ms for one. The
    # numbers live in a BUFF section beside the area, not in the area itself.
    damage_per_second: int = 0
    hit_frequency_ms: int = 0
    tower_damage_per_hit: int = 0
    building_damage_percent: int = 100
    area_speed_pct: int = 0
    area_hit_speed_pct: int = 0
    area_only_own_troops: bool = False
    area_buff_linger_ms: int = 0
    # Tornado's whole point. `AttractPercentage` on the buff is a pull speed as
    # a percentage of one tile per second - Tornado declares 360, and the
    # published behaviour is a drag of "up to 3.5 tiles per second", the
    # shortfall being a unit's own movement working against it. The engine had
    # no attraction of any kind, so the card was a second of weak damage and
    # never moved anything, which is not what anybody plays it for.
    attract_percentage: int = 0
    # Lightning is the one spell that comes down from above rather than being
    # thrown across the arena - it alone declares `ProjectileStartHeight` - and
    # it is also the one projectile-based spell Monk cannot reflect. See
    # `reflect_target`.
    falls_from_sky: bool = False
    # `DeflectBehaviour` on the projectile. "NoDeflect" means Monk cannot send
    # it back; "CheckOnlyTargetPosition" means he has to be near the aim point
    # itself rather than anywhere in the blast.
    deflect_behaviour: str = ""
    hits_air: bool = True
    hits_ground: bool = True
    ignore_buildings: bool = False
    # A Graveyard is a lingering spawner rather than a lingering wound: it puts
    # a skeleton down every so often for as long as it lasts.
    area_spawn_character: str = ""
    area_spawn_period_ms: int = 0
    # Goblin Curse: anything that dies while standing in it comes back on the
    # caster's side, where it fell. DeathSpawnIsEnemy in the data means enemy
    # of the cursed unit, which is to say ours.
    convert_character: str = ""
    convert_count: int = 0
    conversion_ignore_buildings: bool = False
    # Targeted area spells do not hit every unit in the circle. Lightning and
    # Vines select the highest current HP targets; Clone selects friendlies.
    target_limit: int = 0
    target_highest_hitpoints: bool = False
    only_own_troops: bool = False
    clone: bool = False
    grounds_air: bool = False
    # Some spells have source-verified mechanics absent from the shipped
    # files. Void's display file has labels only, so its per-wave values live
    # in the versioned RoyaleAPI combat-rule snapshot.
    waves: int = 0
    wave_interval_ms: int = 0
    damage_by_target_count: tuple[int, int, int] = (0, 0, 0)
    tower_damage_by_target_count: tuple[int, int, int] = (0, 0, 0)
    # Some client spell definitions describe one projectile in a volley rather
    # than the player-visible spell result.  An audited external rule can
    # therefore supply the exact Crown Tower damage instead of manufacturing a
    # multiplier from incomplete projectile metadata (Arrows is the case).
    tower_damage_override: int = 0
    # Lingering areas normally enter through the common candidate loop too.
    # Set false only where an audited source establishes that the raw AEO
    # Damage field is not an impact hit (Goblin Curse is damage-over-time).
    initial_damage: bool = True
    # Rage is represented as a disposable RageBottle building in the client,
    # but the player action resolves to its death area immediately.  This flag
    # lets Match route such a card through spell resolution without a name
    # special case.
    resolves_card_as_spell: bool = False
    # Timing and placement semantics used when a card is cast from Match.
    projectile_speed_mt_per_sec: int = 0
    travels_from_king: bool = False
    impact_delay_ms: int = 0
    spawn_deploy_time_ms: int = 0
    deploy_own_side_only: bool = False
    can_place_on_water: bool = True
    sequential_targets: bool = False
    volley_waves: int = 0
    volley_interval_ms: int = 0
    # (delay, raw x expression, raw y expression), extracted from the card's
    # action graph. Graveyard uses this instead of an invented periodic spawn.
    area_spawn_events: tuple[tuple[int, int, int], ...] = ()
    area_spawn_deploy_time_ms: int = 0
    rolling_range_mt: int = 0
    rolling_speed_mt_per_sec: int = 0
    rolling_captures_troops: bool = False
    rolling_release_slow_pct: int = 0
    rolling_release_slow_ms: int = 0
    pulse_events: tuple[tuple[int, int, int], ...] = ()
    secondary_spawn_character: str = ""
    secondary_spawn_count: int = 0
    secondary_spawn_mirror_x: bool = False

    def damage_to(self, entity) -> int:
        if getattr(entity, "is_tower", False):
            if self.tower_damage_override:
                return self.tower_damage_override
            return self.damage * self.crown_tower_percent // 100
        return self.damage


# Section kinds worth reading, in the order we prefer them. A spell is either a
# projectile that lands or an area effect that sits there.
_SECTION = re.compile(r"\[(PROJECTILE|AEO|SPELL_OTHER)\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)",
                      re.S)
# `Buff` and `TargetBuff` are the same idea under two names: Freeze names its
# buff with the first, an Ice Spirit's projectile with the second.
_FIELDS = ("Damage", "Radius", "RadiusY", "CrownTowerDamagePercent", "Pushback",
           "ProjectileRadius", "ProjectileRadiusY",
           "TargetBuff", "Buff", "BuffTime", "SpawnCharacter",
           "SpawnCharacterCount", "SpawnNumber", "LifeDuration", "HitFrequency",
           "DamagePerSecond", "Projectile", "HitBiggestTargets", "Clone",
           "OnlyOwnTroops", "OnlyEnemies", "HitsAir", "HitsGround",
           "AoeToAir", "AoeToGround", "IgnoreBuildings", "HitSpeed",
           "SpawnAreaEffectObject", "Speed", "SpawnCharacterDeployTime",
           "SpawnInitialDelay", "ProjectileRange",
           # Lightning alone declares this: it comes down from above rather
           # than across the arena, which is why Monk cannot reflect it.
           "ProjectileStartHeight",
           # Whether Monk can reflect this at all, and how. The client says it
           # outright, which beats inferring it.
           "DeflectBehaviour")


def _read_section(body: str) -> dict:
    out = {}
    for key in _FIELDS:
        # Anchored to the start of a line. Unanchored, a search for Radius
        # also matches ProjectileStartRadius and DeflectRadius, so Fireball
        # came out with a 0.7 tile blast instead of 2.5 and Rocket 1.0
        # instead of 2.0. Third time this exact bug has appeared tonight:
        # every key lookup in this codebase needs the anchor.
        found = re.search(r"^\s*" + key + r'\s*=\s*"?(-?\w+)"?', body, re.M)
        if found:
            out[key] = found.group(1)
    return out


_BUFF_SECTION = re.compile(r"\[BUFF\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)", re.S)


def _linked_buff(text: str, name: str) -> dict:
    """The BUFF section an area effect names.

    Poison's area holds only a radius and a duration; its damage per second and
    its slow are in [BUFF.Poison] beside it. Reading only the area made every
    lingering spell an inert circle.
    """
    if not name:
        return {}
    for match in _BUFF_SECTION.finditer(text):
        if match.group(1) != name:
            continue
        body = match.group(2)
        out = {}
        for key in ("DamagePerSecond", "HitFrequency", "CrownTowerDamagePercent",
                    "CrownTowerDamagePerHit", "BuildingDamagePercent",
                    "SpeedMultiplier", "HitSpeedMultiplier",
                    "AttractPercentage"):
            found = re.search(r"^\s*" + key + r"\s*=\s*(-?\d+)", body, re.M)
            if found:
                out[key] = int(found.group(1))
        return out
    return {}


def _conversion(text: str) -> dict:
    """Buff fields that turn a dying unit into one of ours.

    Goblin Curse is the only card that does this: DeathSpawn names what it
    leaves, DeathSpawnIsEnemy says it belongs to whoever cast the curse, and
    DeathSpawnSameLocation puts it exactly where the victim fell - which is why
    a curse landing on the enemy king tower can leave a goblin standing there.
    """
    for match in _BUFF_SECTION.finditer(text):
        body = match.group(2)
        spawn = re.search(r'^\s*DeathSpawn\s*=\s*"([A-Za-z0-9_]+)"', body, re.M)
        if not spawn or "DeathSpawnIsEnemy" not in body:
            continue
        count = re.search(r"^\s*DeathSpawnCount\s*=\s*(\d+)", body, re.M)
        return {"DeathSpawn": spawn.group(1),
                "DeathSpawnCount": count.group(1) if count else "1",
                "IgnoreBuildings": "IgnoreBuildings" in body}
    return {}


def _spell_file(card: str, directory: Path):
    """Find the file holding a spell, by name rather than by a hand-written map.

    The old table listed five spells and pointed two of them at files that do
    not exist, which failed silently. Matching on the card's own name finds
    eighteen and cannot rot the same way.
    """
    explicit = SPELL_SOURCES.get(card)
    if explicit:
        path = directory / f"{explicit[0]}.toml"
        if path.exists():
            return path
    stem = card.replace("_", "")
    candidates = []
    for path in directory.glob("*.toml"):
        key = path.stem
        # Try the squashed name and the card's own name: Dark Magic is in
        # dark_magic.toml, so stripping underscores misses it entirely.
        if key in (stem, card, stem + "spell", card + "spell"):
            return path
        if key.startswith(stem) or key.startswith(card):
            candidates.append(path)
    if candidates:
        return candidates[0]

    # Nothing matched by filename. Some cards live in a file named after
    # something else - Goblin Curse's sections are in goblinmorphprojectile -
    # so fall back to whichever file declares a section with this card's name.
    wanted = card.replace("_", "").lower()
    for path in directory.glob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _SECTION.finditer(text):
            if match.group(2).replace("_", "").lower() == wanted:
                return path
    return None


def _parse_sections(path: Path) -> Dict[str, Dict[str, str]]:
    sections: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections[current] = {}
            continue
        match = re.match(r"(\w+)\s*=\s*(.+)", line)
        if match and current:
            sections[current][match.group(1)] = match.group(2).strip().strip('"')
    return sections


def _section_for(sections: Dict[str, Dict[str, str]], kind: str, name: str) -> dict:
    """Find a named section, preserving the client's spelling exactly."""
    wanted = f"{kind}.{name}".lower()
    for key, value in sections.items():
        if key.lower() == wanted:
            return value
    return {}


def _verified_rules() -> dict:
    """Rules deliberately sourced outside the client data, never guessed."""
    if not VERIFIED_RULES.exists():
        return {}
    try:
        data = json.loads(VERIFIED_RULES.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data.get("rules", {}) if isinstance(data, dict) else {}


def _scale_verified(value: int, rule: dict, level: int) -> int:
    """Move a published level-specific value to the requested card level.

    Combat-rule overrides are recorded at the level stated by their source
    (normally tournament level 11). Mirror requests the same spell one level
    higher, so returning the level-11 override unchanged made mirrored spells
    pay more without becoming stronger.
    """
    result = int(value)
    source_level = int(rule.get("level", level) or level)
    if level > source_level:
        for _ in range(level - source_level):
            result = round(result * 110 / 100)
    elif level < source_level:
        for _ in range(source_level - level):
            result = round(result * 100 / 110)
    return result


def _tier_values(rule: dict, field: str, level: int) -> tuple[int, int, int]:
    values = rule.get(field, {})
    try:
        return tuple(_scale_verified(int(values[key]), rule, level)
                     for key in ("one", "two_to_four", "five_or_more"))
    except (KeyError, TypeError, ValueError):
        return (0, 0, 0)


def _power_multipliers(root: Path) -> dict[str, list[int]]:
    """Read the client's rarity growth rule for spell combat numbers.

    Spell projectile files store the same level-one bases as character files.
    Leaving them unscaled made Fireball, Zap, Goblin Curse, and Arrows much
    weaker than the level-11 troops they are meant to interact with.
    """
    path = root / "rarities.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = csv.reader(handle)
        try:
            headers = next(rows)
            next(rows)  # the client's type row
        except StopIteration:
            return {}
        result: dict[str, list[int]] = {}
        current = ""
        for row in rows:
            values = dict(zip(headers, row))
            name = values.get("Name")
            if name:
                current = name
                result[current] = []
            if current and values.get("PowerLevelMultiplier"):
                try:
                    result[current].append(int(values["PowerLevelMultiplier"]))
                except ValueError:
                    pass
        return result


def _scale_spell_stat(value: int, rarity: str, level: int,
                      multipliers: dict[str, list[int]]) -> int:
    """Scale a level-one spell value using the exact client rarity rule."""
    steps = max(0, level - 1)
    if steps == 0:
        return int(value)
    cumulative = multipliers.get(rarity, ())
    if steps <= len(cumulative):
        return round(int(value) * cumulative[steps - 1] / 100)
    result = (round(int(value) * cumulative[-1] / 100)
              if cumulative else int(value))
    for _ in range(max(0, steps - len(cumulative))):
        result = round(result * 110 / 100)
    return result


# Spells whose spawning is described by named ACTION entries the loader does
# not parse. The Graveyard's file lists 8 distinct Spawn_Skeleton actions over
# a 9 second life, so a skeleton about every 1100ms. That period is read off
# the action count rather than measured, and is recorded here as an inference
# rather than buried in the loader.
_AREA_SPAWN = {
    "graveyard": ("Skeleton", 0),
}

# Exact Graveyard_rework action list shipped by the client. The June 2026
# balance removed the thirteenth Skeleton; the current graph contains these
# twelve delays and locations, each with a 500 ms deploy.
_GRAVEYARD_EVENTS = (
    (2200, -3500, 0), (2700, -2500, 2500), (3300, 0, -3500),
    (3800, 3500, 0), (4400, 2500, -2500), (4900, -3500, 0),
    (5500, 0, -3500), (6000, -2500, -2500), (6500, 3500, 0),
    (7100, 0, 3500), (7600, 2500, 2500), (8200, -2500, 2500),
)

_REPORTED_MISSING = False

# Rows present in the extracted client data but absent from the public-card
# catalogue/actionable game mode. They are test/event artefacts, not playable
# cards. Never turn a missing file for one of these into a guessed spell.
QUARANTINED_INTERNAL_SPELLS = frozenset({
    "tri_wizards", "goblin_party_rocket", "warm_spell",
})


def load_spells(level: int = 11, root: Path | None = None,
                scale=None) -> Dict[str, SpellSpec]:
    """Every spell the data describes, found by name rather than a fixed table.

    `scale` is the same level-scaling function the card loader uses; passing it
    in keeps one implementation of the rule rather than two that can drift.
    """
    directory = Path(root or GAMEDATA) / "characters"
    data_root = Path(root or GAMEDATA)
    out: Dict[str, SpellSpec] = {}
    missing: list = []
    verified_rules = _verified_rules()

    from .gamedata import load_gamedata
    cards = load_gamedata(level=level, root=data_root)
    spell_cards = [name for name, card in cards.items()
                   if ((card.unit is None and card.form != "Evolution")
                       or name == "rage"
                       or verified_rules.get(name, {}).get("resolves_card_as_spell"))
                   and name not in QUARANTINED_INTERNAL_SPELLS]
    multipliers = _power_multipliers(data_root)

    for card in spell_cards:
        # Mirror carries no stats because it is a rule, not a card: Match
        # resolves it to whatever that player last played. Reporting it as a
        # missing spell would be reporting work that is already done.
        if card == "mirror":
            continue
        if card == "barb_log_hero":
            continue
        path = _spell_file(card, directory)
        if path is None:
            missing.append(f"{card}: no data file")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            missing.append(f"{card}: unreadable {path.name}")
            continue

        sections = _parse_sections(path)

        best = None
        preferred = SPELL_SOURCES.get(card)
        if preferred and "." in preferred[1]:
            kind, section_name = preferred[1].split(".", 1)
            preferred_fields = _section_for(sections, kind, section_name)
            if preferred_fields:
                best = dict(preferred_fields)
        for match in _SECTION.finditer(text):
            fields = _read_section(match.group(3))
            if not fields:
                continue
            # A lingering area effect - Poison, Tornado, Graveyard - carries no
            # damage of its own: the damage lives in a BUFF section beside it,
            # and the AEO only holds a radius and a duration. Judging sections
            # on damage alone dropped every one of them.
            if not any(k in fields for k in ("Damage", "SpawnCharacter",
                                            "TargetBuff", "Buff",
                                            "DamagePerSecond", "LifeDuration")):
                continue
            if best is None or (not preferred and len(fields) > len(best)):
                best = fields
        rule = verified_rules.get(card, {})
        if best is None and not rule:
            missing.append(f"{card}: no usable section in {path.name}")
            continue
        if best is None:
            # Void's file is intentionally stats-display-only. The source
            # registry supplies its combat definition and names the source.
            best = {"Radius": str(rule.get("radius_mt", 0))}

        # An AEO can name a projectile whose damage/buff lives in a separate
        # section. Lightning was previously resolved from just one side of the
        # link: either a damage value with no radius or a radius with no damage.
        projectile_name = str(best.get("Projectile", "") or "")
        if projectile_name:
            projectile = _section_for(sections, "PROJECTILE", projectile_name)
            if projectile:
                best = {**projectile, **best}

        def num(key: str, default: int = 0) -> int:
            try:
                return int(float(best.get(key, default)))
            except (TypeError, ValueError):
                return default

        def flag(key: str, default: bool = False) -> bool:
            value = best.get(key)
            if value is None:
                return default
            return str(value).strip().lower() == "true"

        linked = _linked_buff(text, str(best.get("Buff") or best.get("TargetBuff") or ""))
        # Vines is an action graph rather than a simple AEO. Its selected
        # targets receive Vines_Trap_Snare_Base; EXT sections only choose art.
        if card == "vines":
            linked = _linked_buff(text, "Vines_Trap_Snare_Base")
        _convert = _conversion(text)
        # A curse's real damage is on its damage buff, not on the area, and it
        # is small: 14 a second, where the area's own Damage field is a
        # one-off. The card is the conversion, not the chip.
        if not linked.get("DamagePerSecond"):
            # The tick damage may sit in a buff named after the card rather
            # than one the area points at - Goblin Curse keeps its 14 a second
            # in GoblinCurseDamage, which nothing references by name.
            wanted = card.replace("_", "").lower()
            for other in _BUFF_SECTION.finditer(text):
                if not other.group(1).replace("_", "").lower().startswith(wanted):
                    continue
                found = re.search(r"^\s*DamagePerSecond\s*=\s*(\d+)",
                                  other.group(2), re.M)
                if found:
                    linked = dict(linked)
                    linked["DamagePerSecond"] = int(found.group(1))
                    for key in ("HitFrequency", "CrownTowerDamagePerHit",
                                "BuildingDamagePercent", "SpeedMultiplier",
                                "HitSpeedMultiplier"):
                        # Anchored: an unanchored lookup lets a longer key
                        # swallow a shorter one, and SpeedMultiplier sits
                        # inside HitSpeedMultiplier. Archer Queen's buff reads
                        # +280 that way, against a real -25.
                        extra = re.search(r"^\s*" + key + r"\s*=\s*(-?\d+)",
                                          other.group(2), re.M)
                        if extra:
                            linked[key] = int(extra.group(1))
                    break
        damage = num("Damage")
        # A lingering spell's tower reduction lives on its buff, not its area.
        if not best.get("CrownTowerDamagePercent") and "CrownTowerDamagePercent" in linked:
            best["CrownTowerDamagePercent"] = str(linked["CrownTowerDamagePercent"])
        card_rarity = cards[card].rarity
        if damage:
            damage = (scale(damage, card_rarity, level) if scale is not None
                      else _scale_spell_stat(damage, card_rarity, level, multipliers))
        damage_per_second = int(linked.get("DamagePerSecond", 0) or 0)
        if damage_per_second:
            damage_per_second = (
                scale(damage_per_second, card_rarity, level) if scale is not None
                else _scale_spell_stat(damage_per_second, card_rarity, level, multipliers))
        if "damage_per_second_override" in rule:
            damage_per_second = _scale_verified(
                int(rule["damage_per_second_override"]), rule, level)
        tower_damage_per_hit = int(linked.get("CrownTowerDamagePerHit", 0) or 0)
        if tower_damage_per_hit:
            tower_damage_per_hit = (
                scale(tower_damage_per_hit, card_rarity, level) if scale is not None
                else _scale_spell_stat(tower_damage_per_hit, card_rarity, level,
                                       multipliers))
        # The Log states its width as ProjectileRadius rather than Radius,
        # so anchoring the lookup correctly then found nothing at all for it.
        radius = num("Radius") or num("ProjectileRadius")
        # A negative CrownTowerDamagePercent is a reduction: the Log's -87
        # means a tower takes 13%. A spell with no entry hits towers in full.
        crown = best.get("CrownTowerDamagePercent")
        crown_pct = 100 + int(crown) if crown is not None else 100

        # Do not silently treat a projectile's own radius/damage as the
        # player-visible card.  `combat_rules.json` records the source and
        # version for the few cards whose complete result is not in the
        # shipped section (currently Arrows and Void).
        if "damage_override" in rule:
            damage = _scale_verified(int(rule["damage_override"]), rule, level)
        raw_radius_y = num("RadiusY") or num("ProjectileRadiusY") or radius
        radius = int(rule.get("radius_mt", radius) or 0)
        # An audited circular-radius override applies on both axes unless the
        # rule expressly supplies an ellipse.  Otherwise retain a raw Y axis
        # (The Log is 1.95 x 0.60 tiles, not a circle).
        if "radius_y_mt" in rule:
            radius_y = int(rule["radius_y_mt"] or radius)
        elif "radius_mt" in rule:
            radius_y = radius
        else:
            radius_y = raw_radius_y

        target_buff = str(rule.get("target_buff",
                                   best.get("TargetBuff") or best.get("Buff") or ""))
        only_own_troops = bool(rule.get(
            "only_own_troops", flag("OnlyOwnTroops")))
        has_target_flags = any(key in best for key in
                               ("HitsAir", "HitsGround", "AoeToAir", "AoeToGround"))
        hits_air = bool(rule.get(
            "hits_air", flag("HitsAir", flag("AoeToAir", not has_target_flags))))
        hits_ground = bool(rule.get(
            "hits_ground", flag("HitsGround", flag("AoeToGround", not has_target_flags))))

        out[card] = SpellSpec(
            name=card,
            damage=damage,
            radius_mt=radius,
            radius_y_mt=radius_y,
            crown_tower_percent=max(0, crown_pct),
            pushback_mt=num("Pushback"),
            target_buff=target_buff,
            buff_time_ms=int(rule.get("buff_time_ms", num("BuffTime")) or 0),
            spawn_character=str(best.get("SpawnCharacter", "") or ""),
            # A blank count beside a named spawn means one, same as deaths.
            spawn_count=(num("SpawnCharacterCount") or num("SpawnNumber")
                         or (1 if best.get("SpawnCharacter") else 0)),
            life_duration_ms=int(rule.get("life_duration_ms", num("LifeDuration")) or 0),
            damage_per_second=damage_per_second,
            hit_frequency_ms=int(rule.get(
                "hit_frequency_ms", linked.get("HitFrequency", 0)
                or num("HitSpeed")) or 0),
            tower_damage_per_hit=(
                _scale_verified(int(rule["tower_damage_per_hit_override"]), rule, level)
                if "tower_damage_per_hit_override" in rule else tower_damage_per_hit),
            building_damage_percent=int(linked.get("BuildingDamagePercent", 100) or 100),
            area_speed_pct=int(rule.get("area_speed_pct",
                                        linked.get("SpeedMultiplier", 0)) or 0),
            area_hit_speed_pct=int(rule.get("area_hit_speed_pct",
                                            linked.get("HitSpeedMultiplier", 0)) or 0),
            area_only_own_troops=bool(rule.get("area_only_own_troops", False)),
            attract_percentage=int(rule.get(
                "attract_percentage", linked.get("AttractPercentage", 0)) or 0),
            falls_from_sky=bool(num("ProjectileStartHeight")),
            deflect_behaviour=str(best.get("DeflectBehaviour", "") or ""),
            area_buff_linger_ms=int(rule.get("area_buff_linger_ms", 0) or 0),
            hits_air=hits_air,
            hits_ground=hits_ground,
            ignore_buildings=bool(rule.get("ignore_buildings",
                                             flag("IgnoreBuildings"))),
            area_spawn_character=_AREA_SPAWN.get(card, ("", 0))[0],
            area_spawn_period_ms=_AREA_SPAWN.get(card, ("", 0))[1],
            convert_character=_convert.get("DeathSpawn", ""),
            convert_count=int(_convert.get("DeathSpawnCount", 0) or 0),
            conversion_ignore_buildings=bool(_convert.get("IgnoreBuildings", False)),
            target_limit=3 if card in {"lightning", "vines"} else 0,
            target_highest_hitpoints=card in {"lightning", "vines"},
            only_own_troops=only_own_troops,
            clone=str(best.get("Clone", "")).lower() == "true",
            grounds_air=card == "vines",
            waves=int(rule.get("waves", 0) or 0),
            wave_interval_ms=int(rule.get("wave_interval_ms", 0) or 0),
            damage_by_target_count=_tier_values(rule, "damage_by_target_count", level),
            tower_damage_by_target_count=_tier_values(
                rule, "tower_damage_by_target_count", level),
            tower_damage_override=(
                _scale_verified(int(rule["tower_damage_override"]), rule, level)
                if "tower_damage_override" in rule else 0),
            initial_damage=bool(rule.get("initial_damage", True)),
            resolves_card_as_spell=bool(rule.get("resolves_card_as_spell", False)),
            projectile_speed_mt_per_sec=num("Speed") * 1000 // 60,
            travels_from_king=bool(rule.get("travels_from_king", False)),
            impact_delay_ms=int(rule.get("impact_delay_ms", 0) or 0),
            spawn_deploy_time_ms=int(rule.get(
                "spawn_deploy_time_ms", num("SpawnCharacterDeployTime")) or 0),
            deploy_own_side_only=bool(rule.get("deploy_own_side_only", False)),
            can_place_on_water=bool(rule.get("can_place_on_water", True)),
            sequential_targets=bool(rule.get("sequential_targets",
                                                card == "lightning")),
            volley_waves=int(rule.get("volley_waves", 0) or 0),
            volley_interval_ms=int(rule.get("volley_interval_ms", 0) or 0),
            area_spawn_events=_GRAVEYARD_EVENTS if card == "graveyard" else (),
            area_spawn_deploy_time_ms=500 if card == "graveyard" else 0,
            rolling_range_mt=(num("ProjectileRange")
                              if card in {"log", "the_log", "barb_log"} else 0),
        )

    # `the_log` is what the deck calls it; the data files say `log`.
    if "log" in out and "the_log" not in out:
        out["the_log"] = out["log"]
    # RoyaleAPI's player-visible key is Void while the game client calls it
    # dark_magic. Expose both at the boundary so callers never need to guess.
    if "dark_magic" in out and "void" not in out:
        out["void"] = out["dark_magic"]
    # Hero Barbarian Barrel uses the ordinary first barrel projectile, but its
    # terminal spawn is the linked Hero Barbarian rather than a plain one.
    # The SPELL_HERO source contains only that link; all trajectory/damage
    # fields inherit from BarbLog's projectile chain.
    if "barb_log" in out and "barb_log_hero" in cards:
        out["barb_log_hero"] = replace(
            out["barb_log"], name="barb_log_hero",
            spawn_character="BarbLogBarbarianHero")
    # Zap Evolution's current client graph is two pulses: the normal 2.5-tile
    # Zap immediately and another full-damage 3.0-tile Zap after 1.45s.
    if "zap" in out and "zap_ev1" in cards:
        out["zap_ev1"] = replace(
            out["zap"], name="zap_ev1",
            pulse_events=((0, 2500, 100), (1450, 3000, 100)))
    # The real barrel retains its normal Goblins; a second barrel lands at the
    # horizontally mirrored point and contains the client character
    # GoblinDummy. Its current 66 damage is versioned in combat_rules.json.
    if "goblin_barrel" in out and "goblin_barrel_ev1" in cards:
        out["goblin_barrel_ev1"] = replace(
            out["goblin_barrel"], name="goblin_barrel_ev1",
            secondary_spawn_character="GoblinDummy",
            secondary_spawn_count=3,
            secondary_spawn_mirror_x=True)
    # Giant Snowball Evolution's action graph supplies the whole procedure:
    # after the ordinary projectile lands it rolls 4 tiles at Speed=300,
    # captures troops in a 2.5-tile radius, and leaves them slowed by 35% for
    # 3 seconds when released. August 2026 reduced the range from 4.5 to 4.
    if "snowball" in out and "snowball_ev1" in cards:
        out["snowball_ev1"] = replace(
            out["snowball"], name="snowball_ev1", pushback_mt=0,
            target_buff="snowball_spell_ev1_hit", buff_time_ms=3000,
            rolling_range_mt=4000, rolling_speed_mt_per_sec=5000,
            rolling_captures_troops=True,
            rolling_release_slow_pct=-35,
            rolling_release_slow_ms=3000)
    # Say it once per process. It is worth saying - a silently missing spell is
    # what let arrows and zap go unloaded for months - but not on every call.
    global _REPORTED_MISSING
    if missing and not _REPORTED_MISSING:
        _REPORTED_MISSING = True
        print("spells not loaded: " + "; ".join(missing))
    return out


def apply_spell(battle, spec: SpellSpec, at: Point, side: int) -> int:
    """Resolve a spell where it lands. Returns damage dealt.

    A spell is not only damage. A Goblin Barrel is three goblins and no damage
    at all, Freeze and Snowball hand out a buff, and the Log shoves. Treating
    every spell as a damage number made the ones that are not - most of them -
    do nothing at all.
    """
    dealt = 0

    if spec.pulse_events:
        for delay_ms, radius_mt, damage_pct in spec.pulse_events:
            battle.spell_pulse_events.append([
                battle.now_ms + delay_ms, spec, at, side,
                radius_mt, damage_pct])
        return dealt

    if (spec.rolling_range_mt > 0
            and (spec.rolling_speed_mt_per_sec > 0
                 or spec.projectile_speed_mt_per_sec > 0)):
        battle.rolling_spells.append([
            spec, at, side, 0, set(), set(),
        ])
        return dealt

    if spec.volley_waves > 0:
        battle.areas.append([spec, at, side,
                             battle.now_ms + (spec.volley_waves + 1)
                             * max(1, spec.volley_interval_ms),
                             battle.now_ms, None, spec.volley_waves])
        return dealt

    if spec.area_spawn_events:
        for delay_ms, dx, dy in spec.area_spawn_events:
            battle.spell_spawn_events.append([
                battle.now_ms + delay_ms, spec, at, side, dx, dy])
        return dealt

    if spec.sequential_targets and spec.target_limit > 0:
        # Lightning chooses one currently-highest-HP target per bolt. It may
        # therefore hit a unit spawned by an earlier bolt (Battle Ram, Cage),
        # while never striking the same entity twice.
        battle.areas.append([spec, at, side,
                             battle.now_ms + spec.life_duration_ms,
                             battle.now_ms, set()])
        return dealt

    if spec.waves and spec.damage_by_target_count != (0, 0, 0):
        # Void counts the targets at every wave; adding a unit to the field
        # before a later wave changes that wave's tier. Store the complete
        # source-verified rule in the normal area scheduler rather than baking
        # special damage into a one-off hit.
        battle.areas.append([spec, at, side,
                             battle.now_ms + spec.waves * spec.wave_interval_ms,
                             battle.now_ms, None, spec.waves])
        return dealt

    # Clone is a separate action from ordinary AOE damage: it duplicates every
    # friendly troop in its circle at one hitpoint. Buildings are explicitly
    # ignored by the client data. Copying the entity retains the card's real
    # mechanics while resetting transient combat state.
    if spec.clone:
        from dataclasses import replace
        originals = []
        for entity in list(battle.entities.values()):
            if (entity.side != side or not entity.alive or entity.is_building
                    or entity.is_tower or getattr(entity, "is_clone", False)):
                continue
            if arena.distance(entity.pos, at) <= spec.radius_mt + entity.collision_radius_mt:
                originals.append(entity)
        for entity in originals:
            clone = replace(entity, uid=0, hitpoints=1, shield_hitpoints=1,
                            target_uid=None, windup_remaining_ms=0,
                            attack_cooldown_ms=0, dashing=False,
                            deploy_remaining_ms=0, is_clone=True)
            battle.add(clone)

    # A spell that lingers is registered with the battle and keeps working;
    # only its first tick happens now.
    if spec.life_duration_ms > 0 and (spec.damage_per_second
                                      or spec.area_speed_pct
                                      or spec.area_hit_speed_pct
                                      or spec.area_spawn_character):
        # The final slot is the target set captured when the area first ticks.
        # Vines does not retarget a fourth troop after one of its original
        # targets dies; ordinary lingering circles leave this empty.
        battle.areas.append([spec, at, side,
                             battle.now_ms + spec.life_duration_ms,
                             battle.now_ms, None])

    # Spells that put units on the board rather than damage on them.
    def spawn_group(character: str, count: int, centre: Point) -> None:
        if not character or count <= 0 or not battle.unit_lookup:
            return
        unit_spec = battle.unit_lookup(character)
        if unit_spec is not None:
            from .entities import make_unit
            for index in range(count):
                angle = 6.28318 * index / max(1, count)
                offset_x = int(500 * math.cos(angle))
                offset_y = int(500 * math.sin(angle))
                pos = arena.clamp_to_arena(Point(
                    centre.x + offset_x, centre.y + offset_y))
                spawned = make_unit(0, unit_spec, side, pos, battle.now_ms)
                if spec.spawn_deploy_time_ms > 0:
                    spawned.deploy_remaining_ms = spec.spawn_deploy_time_ms
                battle.add(spawned)

    # Spells that put units on the board rather than damage on them.
    spawn_group(spec.spawn_character, spec.spawn_count, at)
    if spec.secondary_spawn_character and spec.secondary_spawn_count > 0:
        secondary_at = (Point(arena.WIDTH - at.x, at.y)
                        if spec.secondary_spawn_mirror_x else at)
        spawn_group(spec.secondary_spawn_character,
                    spec.secondary_spawn_count, secondary_at)

    candidates = []
    for entity in list(battle.entities.values()):
        if not entity.alive or entity.untargetable:
            continue
        if spec.only_own_troops:
            if entity.side != side or entity.is_building:
                continue
        elif entity.side == side:
            continue
        if entity.flying and not spec.hits_air:
            continue
        if not entity.flying and not spec.hits_ground:
            continue
        if entity.is_building and spec.ignore_buildings:
            continue
        dx = abs(entity.pos.x - at.x)
        dy = abs(entity.pos.y - at.y)
        rx = spec.radius_mt + entity.collision_radius_mt
        ry = spec.radius_y_mt + entity.collision_radius_mt
        if rx <= 0 or ry <= 0:
            continue
        # Ellipse test, so the Log's wide shallow band is not treated as a disc.
        if (dx * dx) * (ry * ry) + (dy * dy) * (rx * rx) > (rx * rx) * (ry * ry):
            continue
        candidates.append(entity)

    if spec.target_highest_hitpoints:
        candidates.sort(key=lambda e: (-e.hitpoints, e.uid))
    if spec.target_limit:
        candidates = candidates[:spec.target_limit]

    for entity in candidates:
        if spec.initial_damage:
            dealt += entity.take_damage(spec.damage_to(entity))

        # Freeze, Snowball and Lightning hand out a buff where they land, the
        # same timed percentages a unit's attack applies.
        if spec.target_buff and spec.buff_time_ms > 0:
            from .gamedata import load_buffs
            speed_pct, hit_pct, _heal = load_buffs().get(spec.target_buff, (0, 0, 0))
            if speed_pct or hit_pct:
                entity.buff_until_ms = max(entity.buff_until_ms,
                                           battle.now_ms + spec.buff_time_ms)
                entity.buff_speed_pct = speed_pct
                entity.buff_hit_speed_pct = hit_pct
                if hit_pct <= -100:
                    # Zap/Lightning interrupt Inferno-family ramp damage.
                    entity.ramp_target_uid = None
                    entity.ramp_started_ms = 0

        # The Log rolls things backwards, which is most of why it is played:
        # 700 millitiles, away from where it landed, and never buildings or
        # the 21 heavies that carry IgnorePushback. This was parsed and then
        # ignored, so the Log was pure damage and a Hog it pushed off the
        # bridge kept walking.
        if (spec.pushback_mt > 0 and entity.alive
                and not entity.is_building and not entity.ignore_pushback):
            ox, oy = entity.pos.x - at.x, entity.pos.y - at.y
            span = arena.isqrt(ox * ox + oy * oy) or 1
            entity.pos = arena.clamp_to_arena(Point(
                entity.pos.x + ox * spec.pushback_mt // span,
                entity.pos.y + oy * spec.pushback_mt // span))
    return dealt


def reflect_target(battle, spec: SpellSpec, at: Point, side: int):
    """Where a spell goes when a meditating Monk catches it, or None.

    The client says which spells he can catch and what happens to each, in
    `DeflectBehaviour` on the projectile, and it beats every inference:

        NoDeflect                 Lightning, Royal Delivery - untouchable
        InvertDirection           the Logs - they roll back the way they came
        (anything else)           Fireball, Rocket, Arrows, Snowball, Goblin
                                  Barrel - sent at the caster's own tower
        CheckOnlyTargetPosition   Arrows - he has to be near the aim point
                                  itself, not merely inside the blast

    Reflection changes whose spell it is either way, which the caller does. For
    a rolling spell that is the whole effect: roll direction is derived from
    the owning side, so flipping it reverses the Log exactly as the client's
    `InvertDirection` describes, and the returned point is unchanged.

    For everything else the destination is the caster's nearest own crown
    tower - a Monk defending on the right sends it to their right tower -
    falling back to the other if it is down, and to the king if both are.

    Spells ignored Monk entirely before this. A Fireball onto a meditating Monk
    hit him for full and the caster kept their tower, when the real card turns
    it into a Fireball on their own tower.

      https://clashroyale.fandom.com/wiki/Monk
    """
    behaviour = spec.deflect_behaviour
    if spec.projectile_speed_mt_per_sec <= 0 or "NoDeflect" in behaviour:
        return None
    # Arrows are checked against the aim point alone; everything else counts
    # its blast, so a Fireball skimming him is still caught.
    reach = 0 if "CheckOnlyTargetPosition" in behaviour else spec.radius_mt
    monk = next((entity for entity in battle.entities.values()
                 if entity.alive and entity.side != side
                 and entity.deflect_radius_mt > 0
                 and entity.deflect_from_ms <= battle.now_ms
                     < entity.deflect_until_ms
                 and arena.distance(entity.pos, at)
                     <= entity.deflect_radius_mt + reach), None)
    if monk is None:
        return None
    if "InvertDirection" in behaviour:
        return at
    theirs = [entity for entity in battle.entities.values()
              if entity.alive and entity.is_tower and entity.side == side]
    princesses = [e for e in theirs if e.name != "king_tower"]
    if princesses:
        princesses.sort(key=lambda e: (arena.distance(monk.pos, e.pos), e.uid))
        return princesses[0].pos
    king = next((e for e in theirs if e.name == "king_tower"), None)
    return king.pos if king is not None else None


def cast_spell(battle, spec: SpellSpec, at: Point, side: int,
               origin: Point | None = None) -> int:
    """Cast now and resolve at the client/source-backed impact time.

    The target point stays fixed while units move, making prediction a real
    policy concern. `apply_spell` remains the landing primitive for isolated
    mechanic tests and delayed resolution.
    """
    bounced = reflect_target(battle, spec, at, side)
    if bounced is not None:
        # Reflection changes whose spell it is, not just where it lands. Moving
        # only the impact point sent a Fireball to the caster's own tower and
        # still had it hurt the Monk's side, so it did nothing at all.
        at, side = bounced, -side
    delay = max(0, spec.impact_delay_ms)
    if (spec.travels_from_king and spec.projectile_speed_mt_per_sec > 0
            and origin is not None):
        travel = arena.distance(origin, at) * 1000 // spec.projectile_speed_mt_per_sec
        delay = max(delay, travel)
    if delay <= 0:
        dealt = apply_spell(battle, spec, at, side)
        battle.resolved_spell_damage[side] = (
            battle.resolved_spell_damage.get(side, 0) + dealt)
        return dealt
    battle.spell_impacts.append([battle.now_ms + delay, spec, at, side])
    return 0
