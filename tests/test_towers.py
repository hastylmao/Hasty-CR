"""Are the tower stats the ones the game publishes, and do tower troops exist?

`sim/match.py` carried four hardcoded numbers - princess 3346/119, king
5735/137 - read off a live account because the tower-level curve was not in the
shipped files. It is now published, and checked against it those values match
**no level at all**: Princess Tower hitpoints run ... 2968, 3262, 3584 ... so
3346 falls between levels 10 and 11, and the King's 5735 between 5592 and 6144.

The likeliest explanation is the account had a tower troop equipped. A tower
troop replaces the Princess Tower and is not a reskin - Dagger Duchess fires
every 500ms against 800ms, Cannoneer every 2200ms for far more damage - so a
simulator that only ever models the Princess Tower is wrong about every match
played with one of the others.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.towers import (DEFAULT_TOWER_LEVEL, TOWER_TROOPS,  # noqa: E402
                        king_tower, princess_tower, variants)

PUBLISHED = json.loads(
    (ROOT / "data" / "royaleapi" / "cards_stats_building.json")
    .read_text(encoding="utf-8"))


def _table(name: str, field: str):
    for row in PUBLISHED:
        if isinstance(row, dict) and row.get("name") == name and row.get(field):
            return row[field]
    raise AssertionError(f"no {field} for {name}")


@pytest.mark.parametrize("level", [1, 9, 11, 14])
def test_the_standard_towers_match_the_published_table(level):
    princess = princess_tower(level)
    king = king_tower(level)
    assert princess.hitpoints == _table("PrincessTower", "hitpoints_per_level")[level - 1]
    assert king.hitpoints == _table("KingTower", "hitpoints_per_level")[level - 1]


def test_the_old_hardcoded_values_match_no_level():
    """Why the constants were replaced, stated as a fact rather than a story."""
    table = _table("PrincessTower", "hitpoints_per_level")
    assert 3346 not in table, "3346 is a real level after all; revisit this"
    assert 3584 in table
    king = _table("KingTower", "hitpoints_per_level")
    assert 5735 not in king
    assert 6144 in king


def test_every_tower_troop_loads_with_its_own_mechanics():
    every = variants(DEFAULT_TOWER_LEVEL)
    assert set(every) == set(TOWER_TROOPS)
    for spec in every.values():
        assert spec.hitpoints > 0, spec.name
        assert spec.damage > 0, spec.name
        assert spec.hit_speed_ms > 0, spec.name
        assert spec.range_mt > 0, spec.name


def test_the_troops_are_actually_different_from_each_other():
    """A reskin would make this module pointless; they are not reskins."""
    every = variants(DEFAULT_TOWER_LEVEL)
    speeds = {spec.name: spec.hit_speed_ms for spec in every.values()}
    assert speeds["Dagger Duchess"] == 500
    assert speeds["Cannoneer"] == 2200
    assert speeds["Princess Tower"] == 800
    assert len(set(speeds.values())) >= 3, speeds


def test_royal_chef_reads_the_tower_and_not_the_cook():
    """`chef_tower.toml` has [CHARACTER.Chef] at 5 hitpoints and
    [BUILDING.ChefTower] at 1240. Taking the first match in the file gave
    Royal Chef five hitpoints."""
    chef = princess_tower(1, "chef_tower")
    assert chef.hitpoints == 1240, chef.hitpoints
    assert chef.hit_speed_ms == 1000
    assert chef.load_time_ms == 200


def test_a_troops_damage_comes_from_its_projectile():
    """Cannoneer's damage is on its projectile, not its tower block - the same
    shape that gave Cannon and Musketeer zero damage before the unit loader
    learned to follow `Projectile`."""
    cannoneer = princess_tower(1, "cannoneer")
    duchess = princess_tower(1, "dagger_duchess")
    assert cannoneer.damage == 125, cannoneer.damage
    assert duchess.damage == 42, duchess.damage


def test_towers_get_stronger_with_level():
    for troop in TOWER_TROOPS:
        low = princess_tower(9, troop)
        high = princess_tower(14, troop)
        assert high.hitpoints > low.hitpoints, troop
        assert high.damage >= low.damage, troop


def test_an_unknown_troop_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError):
        princess_tower(11, "not_a_tower_troop")


def test_match_uses_the_derived_values():
    from sim.match import KING_DAMAGE, KING_HP, PRINCESS_DAMAGE, PRINCESS_HP

    assert PRINCESS_HP == princess_tower(DEFAULT_TOWER_LEVEL).hitpoints
    assert PRINCESS_DAMAGE == princess_tower(DEFAULT_TOWER_LEVEL).damage
    assert KING_HP == king_tower(DEFAULT_TOWER_LEVEL).hitpoints
    assert KING_DAMAGE == king_tower(DEFAULT_TOWER_LEVEL).damage


def test_tower_hp_filter_rejects_impossible_rises_and_flicker_zeros():
    """Replays the readings that block 162 actually logged.

    `20260821_144145_m004.json` has ally-left reading 0.00 at 14s and 0.56 at
    19s: a destroyed tower reporting health again.  Across forty logged matches
    the raw reader did that 52 times and rose outright 107 times.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from tower_hp import TowerHpFilter

    f = TowerHpFilter(confirm_seconds=0.6, zero_confirm_seconds=2.5)

    # A single occluded frame must not destroy a healthy tower.
    assert f.update("ally_left", 1.00, 0.0) == 1.00
    assert f.update("ally_left", 0.00, 0.3) == 1.00
    assert f.update("ally_left", 1.00, 0.6) == 1.00

    # Nor may a run of them shorter than the zero-confirmation window.
    for i, t in enumerate((1.0, 1.4, 1.8)):
        assert f.update("ally_left", 0.00, t) == 1.00
    assert f.update("ally_left", 0.94, 2.2) == 1.00       # first drop, unproven

    # A real drop is accepted once it holds for the confirmation window.  The
    # median of the run is taken, so the first accepted value trails the newest
    # reading - deliberately, because over-reporting damage is the error that
    # made the bot walk away from a tower still standing.
    assert f.update("ally_left", 0.56, 3.0) == 0.94
    assert f.update("ally_left", 0.55, 3.4) == 0.94       # first drop, unproven
    assert f.update("ally_left", 0.56, 4.1) == 0.56       # confirmed

    # An impossible rise is never taken.
    assert f.update("ally_left", 0.93, 4.3) == 0.56
    assert f.update("ally_left", 1.00, 4.5) == 0.56

    # A genuine death holds for the whole window, and is then permanent.
    for t in (5.0, 6.0, 7.0, 8.0):
        f.update("ally_left", 0.00, t)
    assert f.update("ally_left", 0.00, 9.0) == 0.0
    assert f.update("ally_left", 0.62, 9.5) == 0.0

    # Sides and owners are tracked apart.
    assert f.update("enemy_right", 1.00, 9.5) == 1.00


def test_tower_hp_filter_replays_a_logged_trace_monotonically():
    import json
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    from tower_hp import TowerHpFilter

    traces = sorted((root / "tmp" / "live" / "matches").glob("*_m*.json"))
    if not traces:
        return  # no live record on this machine
    checked = 0
    for path in traces[-10:]:
        record = json.loads(path.read_text())
        f = TowerHpFilter()
        seen = {}
        for second, summary in record.get("hp_trace", []):
            ally, enemy = summary.split("-")
            raw = ally.split("/") + enemy.split("/")
            for key, value in zip(
                    ("ally_left", "ally_right", "enemy_left", "enemy_right"), raw):
                out = f.update(key, float(value), float(second))
                assert out <= seen.get(key, 1.0) + 1e-9, (path.name, key, out)
                seen[key] = out
                checked += 1
    assert checked > 0


def test_tower_hp_filter_will_not_kill_a_tower_it_never_saw_damaged():
    """A bar that reads healthy and then reads zero for ever is a broken reader.

    Measured on the live record: in three of the last sixty matches *both*
    enemy princess bars read zero within five seconds of the start and stayed
    there for the rest of the match - up to 213 seconds - because the enemy
    colour mask misses some arena skins outright and returns 0.0 for a tower at
    full health.  The old "a destroyed tower stays destroyed" rule then made
    that permanent for the whole match.

    It is not a cosmetic error.  Two crowns per affected match are invented in
    the block report, which is the run's headline metric; experience.py is paid
    a phantom tower-damage reward for whatever happened to be played at the
    time; and the policy drops the tower from its target list, so the finisher
    and the lane choice aim at a tower that is really untouched.

    Nothing in the game takes a princess tower from full to zero in one blow -
    the Rocket is the hardest-hitting spell there is and tops out near 2.2k
    against a tower on roughly 3.0-3.6k - and the bars are sampled several
    times a second, so a real death is always read on the way down.  A tower
    may therefore only die from a reading that already knows it was hurt.
    """
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from tower_hp import TowerHpFilter

    # The observed failure: zero from the first frame, for ever.
    f = TowerHpFilter()
    for t in range(0, 60):
        assert f.update("enemy_left", 0.00, float(t)) == 1.00

    # And it must still recognise the tower when the reader comes back, rather
    # than having latched anything in the meantime.
    assert f.update("enemy_left", 0.62, 60.4) == 1.00     # first drop, unproven
    assert f.update("enemy_left", 0.62, 61.2) == 0.62     # confirmed

    # A damaged tower may still be finished - a Rocket does exactly this - so
    # the guard must not become a rule that towers never die.
    for t in (62.0, 63.0, 64.0, 65.0):
        f.update("enemy_left", 0.00, t)
    assert f.update("enemy_left", 0.00, 66.0) == 0.0
    assert f.update("enemy_left", 0.55, 66.5) == 0.0      # and stays dead

    # A healthy tower blinking out mid-match is occlusion, not a death, however
    # long it holds: the reader never saw it take a scratch.
    g = TowerHpFilter()
    assert g.update("ally_right", 1.00, 0.0) == 1.00
    for t in range(1, 40):
        assert g.update("ally_right", 0.00, float(t)) == 1.00
