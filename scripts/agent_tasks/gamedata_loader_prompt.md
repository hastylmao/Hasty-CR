Write a loader that turns Clash Royale's extracted client data into Python objects.

The data was decoded from the game's own APK and lives in:
  C:\Users\aksha\Downloads\HastyCR\tmp\gamedata\csv_logic\

Key inputs:
- `characters/*.toml`   one file per troop, e.g. `hogrider.toml`, `musketeer.toml`.
                        Format: a `[CHARACTER.HogRider]` header then `Key = value`
                        lines (ints, floats, `true`/`false`, or quoted strings).
- `buildings/*.toml`    same shape, `[BUILDING.X]` headers (if the directory exists).
- `spells.csv`, `projectiles.csv`, `characters.csv`  classic CSVs: row 0 is column
                        names, row 1 is column *types*, data starts at row 2.
- `rarities.csv`        contains `Name`, `RelativeLevel`, `TournamentLevelIndex`,
                        `PowerLevelMultiplier`.
- `spells_characters.csv` (if present) maps a playable card to the character it spawns,
                        with `Name`, `SummonCharacter`, `SummonNumber`, `ManaCost`,
                        `Rarity`, `DeployTime`.

Write exactly one file:
  C:\Users\aksha\Downloads\HastyCR\sim\gamedata.py

It must define exactly this API, and nothing else public:

```python
UNITS_PER_TILE = 1000          # the data's distance unit is millitiles
MS_PER_SECOND  = 1000

@dataclass(frozen=True)
class UnitSpec:
    name: str                  # lowercase key, e.g. "hog_rider"
    hitpoints: int             # at the level given to load_gamedata()
    damage: int
    hit_speed_ms: int          # HitSpeed
    load_time_ms: int          # LoadTime (windup before the first hit)
    range_mt: int              # Range, in millitiles
    sight_range_mt: int        # SightRange
    speed_mt_per_sec: int      # Speed (the data's Speed is already millitiles/sec)
    collision_radius_mt: int   # CollisionRadius
    mass: int
    deploy_time_ms: int        # DeployTime
    attacks_ground: bool
    attacks_air: bool
    flying: bool               # true when the unit itself is airborne
    target_only_buildings: bool
    splash_radius_mt: int      # 0 when single-target
    jump_enabled: bool
    jump_speed_mt_per_sec: int
    retarget_after_attack: bool
    spawn_number: int          # units produced per deployment, minimum 1
    raw: dict                  # every parsed key, unmodified, for later use

@dataclass(frozen=True)
class CardSpec:
    name: str                  # lowercase, e.g. "hog_rider"
    cost: int                  # elixir
    rarity: str
    unit: UnitSpec | None      # None for pure spells
    summon_number: int
    deploy_time_ms: int

def load_gamedata(level: int = 11, root: Path | None = None) -> dict[str, CardSpec]:
    """Return {card_name: CardSpec} with stats scaled to `level`."""

def scale_stat(base: int, rarity: str, level: int, rarities: dict) -> int:
    """Scale a level-1 base stat to `level` for that rarity."""
```

Level scaling, already verified against published tournament stats to within 1.3%:
- For every rarity, `RelativeLevel + TournamentLevelIndex == 10`, and level 11
  (tournament standard) means **10 upgrade steps** from the base value in the file.
- Each step multiplies by `PowerLevelMultiplier / 100` (110 -> x1.10) and rounds.
- So `level=11` applies 10 steps; `level=1` applies `10 - TournamentLevelIndex -
  RelativeLevel` ... in practice: steps = level - 1 + RelativeLevel, capped sensibly.
  Verify your formula reproduces roughly: hog_rider level 11 hitpoints ~1700,
  musketeer ~730, giant ~4020, pekka ~3810. **Print these four as a self-check.**

Requirements:
- Standard library only (`tomllib` is available on Python 3.12) plus `dataclasses`.
  If `tomllib` chokes on a file, fall back to a small regex parser - some of these
  files are not strictly valid TOML.
- Names: lowercase and snake_case. `HogRider` -> `hog_rider`, `MiniPekka` ->
  `minipekka` (keep it as one word), `TheLog` -> `the_log`.
- Never crash on a missing key. Missing numeric fields default to 0, booleans to False.
- Skip any unit whose name ends in `_ev1`, `_evo` or contains `rework` for now.
- Include a `if __name__ == "__main__":` block that loads the data, prints how many
  cards were built, and prints the four self-check numbers above.

Test it by running:
  C:\Users\aksha\Downloads\HastyCR\.venvs\buildabot\Scripts\python.exe sim\gamedata.py

It must run clean and print sensible numbers. Iterate until it does.

Do NOT create any other file. Do NOT modify anything under scripts/ or tmp/.
Do not start, stop, or touch any running bot process.

When finished print: GAMEDATA_LOADER_DONE <number of cards>
