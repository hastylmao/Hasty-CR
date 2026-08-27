import csv
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
import sys

UNITS_PER_TILE = 1000
MS_PER_SECOND = 1000
COMBAT_RULES_PATH = Path(__file__).resolve().parents[1] / "data" / "royaleapi" / "combat_rules.json"
_COMBAT_RULES_CACHE: dict | None = None


def combat_rule(name: str) -> dict:
    """Return an explicitly versioned external rule, never model memory."""
    global _COMBAT_RULES_CACHE
    try:
        if _COMBAT_RULES_CACHE is None:
            payload = json.loads(COMBAT_RULES_PATH.read_text(encoding="utf-8"))
            _COMBAT_RULES_CACHE = payload.get("rules", {}) if isinstance(payload, dict) else {}
        rule = _COMBAT_RULES_CACHE.get(name, {})
        return rule if isinstance(rule, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

@dataclass(frozen=True)
class UnitSpec:
    name: str                  # lowercase key, e.g. hog_rider
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
    target_only_troops: bool
    splash_radius_mt: int      # 0 when single-target
    jump_enabled: bool
    jump_speed_mt_per_sec: int
    retarget_after_attack: bool
    attack_self_pushback_mt: int
    spawn_number: int          # units produced per deployment, minimum 1
    # Charge: a Prince walks a way, then moves at ChargeSpeedMultiplier and its
    # next hit deals DamageSpecial before the charge resets. ChargeRange is in
    # hundredths of a tile, unlike Range which is in millitiles - inferred, not
    # documented: the file holds 250 for the Prince and 300 for the Dark Prince,
    # and the game's own patch notes put the Prince's charge at 2.5 tiles.
    # A ranged attack is a projectile that flies, not damage that teleports.
    # Speed is in the same tiles-per-minute unit as movement, so the tower's
    # 600 is 10 tiles a second and a shot across its 7.5 tile range takes most
    # of a second to land. 0 means melee, or a projectile with no speed given.
    projectile_speed_mt_per_sec: int
    # Projectile steering is an explicit client field.  A missing `Homing`
    # entry is deliberately *not* treated as true: the combat layer must not
    # silently turn a positional shot into a target-following one.
    projectile_homing: bool
    charge_range_mt: int       # 0 when the unit does not charge
    charge_speed_multiplier: int   # percent, 200 = double speed
    damage_special: int        # charge-hit damage, 0 when it has none
    shield_hitpoints: int      # absorbed before hitpoints, 0 when none
    initial_shield_pct: int    # source OnStartingAction can override 100
    # What happens when it dies. A Golem is not a big Knight: it leaves two
    # Golemites and a blast, and a defence that ignores that is measuring the
    # wrong card. Names here are the data's own PascalCase character names.
    death_damage: int          # 0 when it does not explode
    death_damage_radius_mt: int
    death_damage_pushback_mt: int
    death_spawn_character: str  # "" when it leaves nothing
    death_spawn_count: int
    death_spawn_radius_mt: int
    death_spawn_at_source: bool
    death_spawn_deploy_ms: int
    death_spawn_offsets: tuple[tuple[int, int], ...]
    # Buildings and a few troops produce units on a timer.
    spawn_character: str
    spawn_count: int
    spawn_pause_ms: int        # gap between waves, 0 when not a spawner
    spawn_start_ms: int        # delay before the first wave
    spawn_forward_mt: int
    spawn_deploy_ms: int
    hot_spawn_character: str
    hot_spawn_interval_ms: int
    hot_spawn_first_delay_ms: int
    hot_spawn_side_mt: int
    hot_spawn_behind_mt: int
    hot_spawn_deploy_ms: int
    hot_spawn_stop_moving_ms: int
    hot_spawn_normal_resume_ms: int
    threshold_spawn_hp_pct: int
    threshold_spawn_character: str
    threshold_spawn_interval_ms: int
    threshold_spawn_behind_mt: int
    # A buff this unit's attack applies to what it hits. Freeze is
    # SpeedMultiplier -100 and HitSpeedMultiplier -100 for BuffTime; an Ice
    # Wizard's chill is -30 on both. Percentages, so -100 means stopped.
    target_buff: str
    buff_time_ms: int
    # Several electric cards carry their stun directly on the character
    # instead of the projectile.  MultipleTargets is also character data
    # (Electro Wizard: two), so retain both rather than treating them as one
    # card-specific exception.
    multiple_targets: int
    all_targets_hit: bool
    variable_damage2: int
    variable_damage3: int
    variable_damage_time1_ms: int
    variable_damage_time2_ms: int
    persistent_ramp_damages: tuple[int, ...]
    persistent_ramp_thresholds: tuple[int, ...]
    persistent_ramp_decay_ms: int
    spawn_area_damage: int
    spawn_area_tower_damage: int
    spawn_area_radius_mt: int
    spawn_area_buff: str
    spawn_area_buff_ms: int
    chained_hit_count: int
    chained_hit_radius_mt: int
    chain_unlimited: bool
    chain_full_damage_hits: int
    chain_reduced_damage: int
    chain_reduced_speed_mt_per_sec: int
    chain_repeat_memory: int
    special_min_range_mt: int
    special_range_mt: int
    special_load_time_ms: int
    pull_projectile_speed_mt_per_sec: int
    pull_target_speed_mt_per_sec: int
    pull_self_speed_mt_per_sec: int
    pull_margin_mt: int
    pull_speed_pct: int
    pull_buff_ms: int
    projectile_radius_mt: int
    projectile_range_mt: int
    pierces: bool
    attached_character: str
    transform_at_hp_pct: int
    transform_character: str
    # A Kamikaze unit dies on its own attack - an Ice Spirit is one hit and
    # gone. Without it the spirit survived and re-froze its victim for as long
    # as it lived, which turned a 1.1 second freeze into a permanent one.
    # Heavies shrug off the Log. 21 units carry IgnorePushback - Giant,
    # P.E.K.K.A., Golem, Prince - and knocking them back would make the Log a
    # far better defensive card than it is.
    # Tunnelling speed, in the same tiles-per-minute unit as movement. A Miner
    # is 650 and a Goblin Drill 300. Non-zero means the unit travels to where
    # it was placed underground, and cannot be hit on the way.
    # Dash: a Bandit closes from between DashMinRange and DashMaxRange, cannot
    # be hit on the way, and lands DashDamage rather than a normal hit. It is
    # charge's cousin - the difference is that it crosses the gap itself.
    # Royal Ghost vanishes when it has not attacked for a while and reappears
    # to swing. Invisible units cannot be picked as a target at all, which is
    # the whole card - a spell aimed at one hits nothing.
    # Champion abilities. Each is an ordinary buff with a cast time and an
    # elixir price, so the effect needs no special case - only the trigger.
    ability_buff: str
    ability_buff_ms: int
    ability_cast_ms: int
    ability_cost: int
    ability_dash_range_mt: int
    ability_dash_count: int
    ability_dash_landing_ms: int
    ability_shield_pct: int
    ability_spawn_character: str
    ability_action_delay_ms: int
    ability_pushback_damage: int
    ability_pushback_radius_mt: int
    ability_pushback_strength_mt: int
    ability_appear_behind_mt: int
    ability_area_damage: int
    ability_area_radius_mt: int
    ability_area_pulse_times_ms: tuple[int, ...]
    ability_area_slow_pct: int
    ability_area_duration_ms: int
    ability_area_slow_linger_ms: int
    ability_deploy_character: str
    ability_deploy_forward_mt: int
    ability_deploy_delay_ms: int
    ability_deploy_damage: int
    ability_deploy_radius_mt: int
    ability_deploy_pushback_mt: int
    ability_lane_switch: bool
    ability_lane_switch_delay_ms: int
    ability_bomb_damage: int
    ability_bomb_radius_mt: int
    ability_bomb_pushback_mt: int
    ability_link_target: str
    ability_link_duration_ms: int
    ability_link_interval_ms: int
    ability_link_width_mt: int
    ability_link_damage: int
    ability_link_tower_damage: int
    link_receiver_on_death: bool
    cannot_target_towers: bool
    ability_damage_pct: int
    ability_tower_damage_pct: int
    ability_unkillable: bool
    ability_duration_includes_cast: bool
    ability_cast_locks_actions: bool
    tower_damage_pct: int
    invisible_after_ms: int
    # Evolution passives are declared on the character and its named buff.
    # Keep the resolved numeric effects on the spec so level-scaled healing
    # does not have to be reconstructed by the combat engine.
    idle_damage_reduction_pct: int
    buff_after_hits_count: int
    buff_after_hits_time_ms: int
    buff_after_hits_speed_pct: int
    buff_after_hits_hit_speed_pct: int
    buff_after_hits_heal_per_second: int
    buff_after_hits_overheal_pct: int
    buff_after_hits_spawn_character: str
    buff_after_hits_spawn_count: int
    buff_after_hits_spawn_interval_ms: int
    group_max_size: int
    kill_heal_thresholds: tuple[int, ...]
    kill_heal_amounts: tuple[int, ...]
    kill_heal_overheal_pct: int
    death_area_damage: int
    death_area_radius_mt: int
    death_area_duration_ms: int
    death_area_hit_frequency_ms: int
    death_area_speed_pct: int
    death_area_hit_speed_pct: int
    death_area_buff_linger_ms: int
    death_area_tower_damage: int
    owned_spawn_death_heal: int
    owned_spawn_death_heal_count: int
    owned_spawn_death_heal_overheal_pct: int
    spawn_after_first_character: str
    spawn_after_first_pause_ms: int
    attack_area_damage: int
    attack_area_radius_mt: int
    attack_area_pushback_mt: int
    shield_lost_charge_range_mt: int
    shield_lost_area_damage: int
    shield_lost_area_radius_mt: int
    shield_lost_area_pushback_mt: int
    on_damage_invulnerable_ms: int
    on_damage_speed_pct: int
    on_damage_hit_speed_pct: int
    on_damage_invisible: bool
    starting_side_summons: tuple[str, str]
    starting_side_summon_distance_mt: int
    starting_side_summon_damage: int
    starting_side_summon_radius_mt: int
    starting_side_summon_damage_delay_ms: int
    far_attack_min_range_mt: int
    far_attack_damage: int
    projectile_area_damage: int
    projectile_area_radius_mt: int
    projectile_area_delay_ms: int
    projectile_area_buff: str
    projectile_area_buff_ms: int
    projectile_area_hits_ground: bool
    projectile_area_hits_air: bool
    # Evolved Dart Goblin's projectile attaches a target-bound poison
    # controller.  The controller's thresholds and pulse geometry are
    # explicit in blowdart_goblin_evo.toml; current level-11 damage values are
    # versioned in combat_rules.json so a stale client snapshot cannot silently
    # override a published balance change.
    target_poison_damage_tiers: tuple[int, ...]
    target_poison_stack_thresholds: tuple[int, ...]
    target_poison_radius_mt: int
    target_poison_first_tick_ms: int
    target_poison_interval_ms: int
    target_poison_tower_pct: int
    target_poison_tower_duration_ms: int
    sniper_ammo: int
    sniper_min_range_mt: int
    sniper_max_range_mt: int
    sniper_side_clip_mt: int
    sniper_damage: int
    sniper_projectile_speed_mt_per_sec: int
    group_death_spawn_character: str
    group_required_guard_character: str
    group_death_kill_character: str
    permanent_invulnerable: bool
    always_invisible: bool
    periodic_ranged_damage: int
    periodic_ranged_min_mt: int
    periodic_ranged_max_mt: int
    periodic_ranged_cooldown_ms: int
    periodic_ranged_projectile_speed_mt_per_sec: int
    periodic_ranged_trail_interval_ms: int
    periodic_ranged_trail_delay_ms: int
    periodic_ranged_area_radius_mt: int
    periodic_ranged_area_duration_ms: int
    periodic_ranged_area_speed_pct: int
    container_drop_hp_pct: int
    container_drop_damage: int
    container_drop_radius_mt: int
    container_drop_pushback_mt: int
    container_drop_delay_ms: int
    container_drop_spawn_character: str
    container_drop_spawn_count: int
    container_drop_spawn_radius_mt: int
    container_drop_spawn_deploy_ms: int
    container_drop_threshold_offset: tuple[int, int]
    container_drop_death_offset: tuple[int, int]
    deploy_barrage_x_mt: tuple[int, ...]
    deploy_barrage_forward_mt: tuple[int, ...]
    deploy_barrage_delays_ms: tuple[int, ...]
    deploy_barrage_damage: int
    deploy_barrage_tower_damage: int
    deploy_barrage_radius_mt: int
    deploy_barrage_pushback_mt: int
    capture_radius_mt: int
    capture_damage: int
    capture_hit_frequency_ms: int
    capture_drag_delay_ms: int
    capture_drag_time_ms: int
    capture_cooldown_ms: int
    quest_interval_ms: int
    quest_hit_advance_ms: int
    quest_start_delay_ms: int
    quest_max_stacks: int
    ability_level_adjustments: tuple[int, ...]
    ability_level_hitpoints: tuple[int, ...]
    ability_level_damages: tuple[int, ...]
    ability_missing_hp_heal_pct: int
    ability_taunt_radius_mt: int
    ability_taunt_area_ms: int
    ability_taunt_duration_ms: int
    ability_hurl_radius_mt: int
    ability_hurl_distance_mt: int
    ability_hurl_delay_ms: int
    ability_hurl_flight_ms: int
    ability_hurl_stun_ms: int
    ability_hurl_damage: int
    ability_hurl_damage_radius_mt: int
    ability_siege_range_mt: int
    ability_siege_duration_ms: int
    ability_siege_lock_ms: int
    ability_siege_damage: int
    ability_siege_tower_damage: int
    ability_siege_radius_mt: int
    ability_siege_projectile_speed_mt_per_sec: int
    ability_siege_hit_speed_ms: int
    ability_split_character: str
    ability_split_mount: str
    ability_split_warp_mt: int
    ability_split_warp_ms: int
    ability_split_spawn_damage_delay_ms: int
    ability_split_spawn_damage: int
    ability_split_spawn_tower_damage: int
    ability_split_spawn_radius_mt: int
    ability_split_spawn_pushback_mt: int
    ability_reroll_range_mt: int
    ability_reroll_duration_ms: int
    ability_reroll_start_delay_ms: int
    ability_reroll_damage: int
    ability_reroll_tower_damage: int
    ability_reroll_radius_mt: int
    ability_reroll_radius_y_mt: int
    ability_reroll_heal_missing_pct: int
    ability_spin_seek_radius_mt: int
    ability_spin_pending_speed_mt_per_sec: int
    ability_spin_speed_mt_per_sec: int
    ability_spin_duration_ms: int
    ability_spin_interval_ms: int
    ability_spin_damage: int
    ability_spin_tower_damage: int
    ability_spin_radius_mt: int
    ability_spin_damage_reduction_pct: int
    last_group_death_spawn_character: str
    ability_window_ms: int
    ability_reinforcement_character: str
    ability_reinforcement_damage: int
    ability_reinforcement_offsets: tuple[tuple[int, int, int], ...]
    ability_self_destruct_delay_ms: int
    always_untargetable: bool
    ability_transform_character: str
    ability_destroy_group_character: str
    ability_post_source_death_window_ms: int
    ability_transform_lock_ms: int
    parry_cooldown_ms: int
    parry_damage_pct: int
    parry_stun_ms: int
    parry_stun_delay_ms: int
    parry_damage_delay_ms: int
    ability_warp_backward_mt: int
    ability_warp_delay_ms: int
    ability_invisible_ms: int
    ability_max_charges: int
    ability_cooldown_ms: int
    ability_buff_delay_ms: int
    deflect_radius_mt: int
    ability_temporary_character: str
    ability_temporary_transition_ms: int
    ability_temporary_duration_ms: int
    ground_on_damage_hp_pct: int
    ground_on_attack: bool
    ground_transition_ms: int
    ground_character: str
    ground_landing_damage: int
    ground_landing_radius_mt: int
    control_range_mt: int
    control_initial_cooldown_ms: int
    control_cooldown_ms: int
    control_cast_ms: int
    control_projectile_speed_mt_per_sec: int
    control_buff: str
    control_duration_ms: int
    control_grounds_air: bool
    wind_width_mt: int
    wind_height_mt: int
    wind_forward_offset_mt: int
    wind_duration_ms: int
    wind_after_death_ms: int
    wind_ally_speed_pct: int
    wind_enemy_speed_pct: int
    wind_buff_linger_ms: int
    uppercut_every_hits: int
    uppercut_push_mt: int
    uppercut_flight_ms: int
    uppercut_root_ms: int
    # Electro Giant answers whatever hits it: everything within
    # ReflectedAttackRadius takes ReflectedAttackDamage and a stun.
    reflect_damage: int
    reflect_radius_mt: int
    reflect_buff: str
    reflect_buff_ms: int
    dash_min_range_mt: int
    dash_max_range_mt: int
    dash_damage: int
    dash_cooldown_ms: int
    dash_pushback_mt: int
    dash_radius_mt: int
    burrow_speed_mt_per_sec: int
    ignore_pushback: bool
    kamikaze: bool
    lifetime_ms: int           # 0 when it does not expire on its own
    raw: dict                  # every parsed key, unmodified, for later use
    # Set when the card was declared in `spells_buildings.csv`. Being a
    # building was otherwise inferred from Speed == 0, which is true of most
    # buildings and not all of them; the client's own file organisation says
    # so directly, and agrees with the public snapshot's card type.
    from_building_card: bool = False
    # `ActionWarpCharacter`: a warp onto a resolved target rather than the
    # fixed retreat Boss Bandit uses.
    ability_warp_to_target_speed: int = 0
    ability_warp_to_target_strategy: str = ""
    # Evolved Valkyrie: each swing spawns a half-second tornado that drags what
    # is near her toward her. See `load_buff_attractions`.
    attack_area_attract_percentage: int = 0
    attack_area_duration_ms: int = 0
    # Wizard Hero: the ability projectile spawns a mini tornado beside its
    # damage area. See `_action_spawned_attractor`.
    projectile_area_attract_percentage: int = 0
    projectile_area_attract_radius_mt: int = 0
    projectile_area_attract_duration_ms: int = 0
    # Skeleton King's summon. Six skeletons at no souls, sixteen at ten, one
    # every 250ms in a ring around him. See `load_ability_details`.
    ability_summon_character: str = ""
    ability_summon_base_count: int = 0
    ability_summon_max_count: int = 0
    ability_summon_interval_ms: int = 0
    ability_summon_initial_delay_ms: int = 0
    ability_summon_deploy_ms: int = 0
    ability_summon_min_radius_mt: int = 0
    ability_summon_max_radius_mt: int = 0
    # Evolved Executioner's boomerang axe. See `_pingpong_controller`.
    pingpong_range_mt: int = 0
    pingpong_radius_mt: int = 0
    pingpong_damage: int = 0
    pingpong_strong_damage: int = 0
    pingpong_strong_range_mt: int = 0
    pingpong_pushback_mt: int = 0
    # Evolved Goblin Drill's relocation. See `_drill_relocate`.
    hide_hp_thresholds: tuple[int, ...] = ()
    hide_time_ms: int = 0
    hide_goblin_counts: tuple[int, ...] = ()
    hide_spawn_character: str = ""
    hide_spawn_offset_mt: int = 0
    hide_reappear_damage: int = 0
    hide_reappear_radius_mt: int = 0
    hide_reappear_pushback_mt: int = 0
    # An emergence area can be barred from crown towers. Goblin Drill's is:
    # `CrownTowerDamagePercent = -100`, so 100 + (-100) = 0 percent.
    spawn_area_tower_percent: int = 100
    # Elite Archer Hero's seven seconds of triple shot: two more arrows beside
    # the ordinary one, 1500 apart, each its own piercing line.
    ability_shot_window_ms: int = 0
    ability_extra_projectiles: int = 0
    ability_extra_projectile_spacing_mt: int = 0
    ability_shot_damage: int = 0
    ability_shot_range_mt: int = 0
    # Evolved Princess's ice arrow. See `_special_attack_area`.
    special_attack_every: int = 0
    special_attack_radius_mt: int = 0
    special_area_duration_ms: int = 0
    special_area_hit_frequency_ms: int = 0
    special_area_buff: str = ""
    special_area_buff_ms: int = 0
    # Balloon Hero's Coffin Cadets. See `_paratrooper_drop`.
    ability_drop_character: str = ""
    ability_drop_radius_mt: int = 0
    ability_drop_deploy_ms: int = 0
    ability_drop_height_mt: int = 0
    # `DeflectBehaviour` on the shot. "NoDeflect" means a meditating Monk
    # cannot send it back at the shooter - twenty-three projectiles say so and
    # the engine reflected every one of them.
    projectile_deflect_behaviour: str = ""
    # What deflecting this shot costs the deflector. Firecracker declares
    # `ActionOnDeflector`, an `ActionDealDamage` of 25 aimed at whoever sent
    # the shot back - so catching her fireworks is not free.
    projectile_deflector_damage: int = 0
    # Buffs this unit is declared immune to. The ones that matter on ladder
    # are `GoblinCurse` and `VoodooCurse`: everything with its own death spawn
    # - Golem, Lava Hound, Goblin Giant, Battle Ram, Elixir Golem, Cannon
    # Cart - is exempt from being converted, because what it leaves behind is
    # its own. The rest are party-mode event buffs.
    ignored_buffs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CardSpec:
    name: str                  # lowercase, e.g. hog_rider
    cost: int                  # elixir
    rarity: str
    unit: UnitSpec | None      # None for pure spells
    summon_number: int
    # How far apart a multi-unit card spawns its members, from the card row -
    # Skeletons and Barbarians are both 700. This lives on the spell, not on
    # the character, which is why it was never read.
    summon_radius_mt: int
    summon_deploy_delay_ms: int
    deploy_time_ms: int
    # Normal, HeroForm, or another client-declared card form.  This is kept
    # separate from rarity so an RL deck cannot accidentally identify a hero
    # as its ordinary base card.
    form: str = ""
    evolution_cycles: int = 0
    secondary_unit: UnitSpec | None = None
    secondary_summon_number: int = 0
    secondary_summon_deploy_delay_ms: int = 0
    secondary_offset_toward_centre_mt: int = 0
    additional_summons: tuple[tuple[UnitSpec, int, int], ...] = ()


def _merge_character_overlay(base: dict, overlay: dict) -> dict:
    """Apply the client's EXT/evolution override operators to a character."""
    resolved = dict(base)
    for key, value in overlay.items():
        if key == "Base":
            continue
        if (isinstance(value, list) and len(value) == 2
                and isinstance(value[0], str) and value[0] in {"%", "="}):
            if value[0] == "%":
                try:
                    resolved[key] = round(int(resolved.get(key, 0) or 0)
                                          * int(value[1]) / 100)
                except (TypeError, ValueError):
                    resolved[key] = value[1]
            else:
                resolved[key] = value[1]
        else:
            resolved[key] = value
    return resolved

def scale_stat(base: int, rarity: str, level: int, rarities: dict) -> int:
    """Scale a level-1 base stat to `level` for that rarity.

    The number of upgrade steps is the level *above the rarity's own starting
    level*, not above one. Every rarity shares the identical multiplier
    sequence - 110, 121, 133, 146, 160 and so on - and differs only in
    `RelativeLevel`: Common starts at 1, Rare at 3, Epic at 6, Legendary at 9,
    Champion at 11. A Legendary at level 11 is two upgrades along, not ten.

    Taking `level - 1` for everything gave every non-Common card the Common
    level-11 multiplier of 2.56. Prince Buff came out at 3686 against a
    published 2304, Super Hog Rider at 3584 against 1694 - the higher the
    rarity, the further out. Common cards were unaffected, which is why it
    survived: the deck this project is built around is mostly Common and Rare.
    """
    steps = level - 1
    if steps <= 0:
        return int(base)
    data = rarities.get(rarity, {})
    cumulative = data.get('PowerLevelMultipliers', ())
    if steps <= len(cumulative):
        return round(int(base) * cumulative[steps - 1] / 100)
    # Future levels beyond the shipped table retain the final 10% step.
    val = round(int(base) * cumulative[-1] / 100) if cumulative else int(base)
    for _ in range(max(0, steps - len(cumulative))):
        val = round(val * data.get('PowerLevelMultiplier', 110) / 100)
    return int(val)

def carry_verified(override, base: int, rarity: str, level: int,
                   rarities: dict, verified_level) -> int:
    """A value verified at one level, expressed at another.

    `combat_rules.json` records numbers a person went and checked - balance
    changes read off Supercell's blog - and each is stamped with the level it
    was seen at. Applying such a value only at that exact level leaves every
    other level falling back to raw scaling, silently and wrongly: Mirror
    resolves cards one level up, so a mirrored Evolved Witch used to come out
    at 922 hitpoints against the 1451 she is verified at, weaker for being
    played higher.

    Carrying it is done with the client's own curve rather than an invented
    one. The override is a measurement of the same card the shipped data
    describes, so its ratio to `scale_stat` at the verified level is held
    constant across levels. That introduces no new claim about the game: at
    the verified level the value is returned exactly, and elsewhere it moves
    the way every other stat on that card moves.

    This is not a substitute for verifying the value at the level you care
    about. It is what to do until someone does.
    """
    value = int(override)
    if verified_level is None or int(verified_level) == level:
        return value
    anchor = scale_stat(base, rarity, int(verified_level), rarities)
    if anchor <= 0:
        return value
    here = scale_stat(base, rarity, level, rarities)
    return max(1, round(here * value / anchor))


def verified_or_scaled(external: dict, key: str, base, rarity: str, level: int,
                       rarities: dict) -> int:
    """A verified override for `key` if there is one, otherwise raw scaling.

    Collapses the shape that used to be repeated at every override site, where
    the level test was written out by hand and gated the value to the single
    level it was verified at. Repeating a condition seven times is how six of
    them stay right and one drifts.
    """
    override = external.get(key)
    if override is None:
        return scale_stat(int(base or 0), rarity, level, rarities)
    return carry_verified(override, int(base or 0), rarity, level, rarities,
                          external.get('level'))


def _action_damage(raw: dict, action_name, depth: int = 0) -> int:
    """Damage declared on an action, following one action group into its parts.

    The client can hang a projectile's damage off the action it starts instead
    of the projectile row: Evolved Executioner's axe is Damage 0 pointing at an
    `ActionExecutionerEvoProjectile` controller that holds the real 70. Reading
    only the projectile made the card inert.

    Depth-limited because action graphs reference each other freely and a cycle
    here would hang the loader rather than fail it.
    """
    if not action_name or depth > 2:
        return 0
    actions = raw.get('_ACTION_DATA', {})
    action = actions.get(str(action_name), {})
    if not isinstance(action, dict):
        return 0
    try:
        found = int(action.get('Damage', 0) or 0)
    except (TypeError, ValueError):
        found = 0
    if found:
        return found
    sub = action.get('SubActions', [])
    if isinstance(sub, str):
        sub = [sub]
    if isinstance(sub, list):
        for child in sub:
            found = _action_damage(raw, child, depth + 1)
            if found:
                return found
    return 0


def _paratrooper_drop(raw: dict) -> dict:
    """A character dropped onto a resolved target by an ability.

    Balloon Hero's Coffin Cadets: an `ActionSpawn` of `ProjectileType` whose
    projectile carries `SpawnCharacter = "SkeletonTrooper"`, aimed by a
    resolver that takes the closest non-flying, non-tower target inside a
    6500 circle and breaks ties on highest current hitpoints.

    The action audit listed this as needing calibration for a "logX10000
    accelerated payload trajectory". The trajectory is a declared formula -
    the speed ramps by +2 every 150ms and is overridden to
    `logX10000(max(5, rampup - 1)) / 80` - and the only genuinely open question
    is which logarithm `logX10000` means. That decides when the trooper lands,
    not where, and the ability was doing nothing whatsoever meanwhile.
    """
    actions = raw.get('_ACTION_DATA', {})
    projectiles = {**raw.get('_PROJECTILE_DATA', {}), **raw.get('_EXT_DATA', {})}
    resolvers = raw.get('_RESOLVER_DATA', {})
    shapes = raw.get('_SHAPE_DATA', {})
    for action in actions.values():
        if not isinstance(action, dict):
            continue
        if (str(action.get('ClassType', '')) != 'ActionSpawn'
                or str(action.get('SpawnType', '')) != 'ProjectileType'):
            continue
        projectile = projectiles.get(str(action.get('SpawnData', '') or ''), {})
        if not isinstance(projectile, dict) or not projectile.get('SpawnCharacter'):
            continue
        radius = 0
        for resolver in resolvers.values():
            if not isinstance(resolver, dict):
                continue
            shape = shapes.get(str(resolver.get('Shape', '') or ''), {})
            if isinstance(shape, dict) and shape.get('Radius'):
                radius = int(shape['Radius'])
                break
        return {
            'character': str(projectile['SpawnCharacter']),
            'radius': radius,
            'deploy': int(projectile.get('SpawnCharacterDeployTime', 0) or 0),
            # He dives from under the balloon, so even a landing directly
            # below is a fall rather than an appearance.
            'height': int(action.get('StartPositionZOffset', 0) or 0),
        }
    return {}


def _special_attack_area(raw: dict) -> dict:
    """The lingering field a periodic special attack leaves behind.

    Evolved Princess fires an ice arrow every third shot: attack sequence index
    1 carries `Princess_EV1_FreezeProjectile`, whose `SpawnAreaEffectObject` is
    a three-tile slow field lasting 5500ms. The simulator fired her ordinary
    arrow every time, so the evolution was a Princess with a slightly larger
    splash on paper and no slow at all.

    Her death freeze is a different area and was already modelled; this is only
    the one the arrow leaves.
    """
    sequence = raw.get('AttackSequenceList') or ()
    if len(sequence) < 2 or not isinstance(sequence[1], dict):
        return {}
    special = sequence[1]
    tables = {**raw.get('_PROJECTILE_DATA', {}), **raw.get('_EXT_DATA', {})}
    projectile = tables.get(
        str(special.get('CustomFirstProjectile')
            or special.get('Projectile') or ''), {})
    if not isinstance(projectile, dict):
        return {}
    areas = {**raw.get('_AEO_DATA', {}), **raw.get('_EXT_DATA', {})}
    area = areas.get(str(projectile.get('SpawnAreaEffectObject', '') or ''), {})
    if not isinstance(area, dict) or not area:
        return {}
    # An EXT area inherits from the AEO it names, overriding a field or two.
    base = areas.get(str(area.get('Base', '') or '').split('.')[-1], {})
    merged = {**(base if isinstance(base, dict) else {}), **area}
    merged['_radius'] = int(projectile.get('Radius', 0)
                            or merged.get('Radius', 0) or 0)
    return merged


def _parallel_projectiles(raw: dict) -> dict:
    """Extra arrows fired beside the ordinary one, and what they carry.

    Elite Archer Hero's ability does not declare this on its own graph. It sets
    his attack sequence to index 1, whose projectile is
    `..._Power_Shot_Projectile_Middle`, and *that* projectile's
    `OnStartingAction` is the `ActionCreateParallelProjectiles` making two more
    1500 apart. Following the ability alone finds nothing, which is why his
    ability was offered and then refused for having no declared effect.
    """
    actions = raw.get('_ACTION_DATA', {})
    # Both tables: a hero's projectiles are declared as EXT overlays chaining
    # EXT -> EXT -> PROJECTILE, so none of them appear in `_PROJECTILE_DATA`
    # at all and looking only there finds nothing.
    projectiles = {**raw.get('_PROJECTILE_DATA', {}), **raw.get('_EXT_DATA', {})}
    # Scanning the card's own projectile tables rather than walking its attack
    # sequence: the sequence lives on the CHARACTER row and does not survive
    # the EXT overlay that defines the hero, so following it finds nothing.
    # Exactly one card in the client declares parallel projectiles, so a scan
    # cannot pick up somebody else's.
    for projectile in projectiles.values():
        if not isinstance(projectile, dict):
            continue
        action = actions.get(str(projectile.get('OnStartingAction', '') or ''), {})
        if (isinstance(action, dict) and str(action.get('ClassType', ''))
                == 'ActionCreateParallelProjectiles'):
            carried = projectiles.get(
                str(action.get('ProjectileType', '') or ''), {})
            return {
                'count': int(action.get('ProjectileCount', 0) or 0),
                'spacing': int(action.get('ProjectileDistance', 0) or 0),
                'damage': int(carried.get('Damage', 0) or 0),
                'range': int(carried.get('ProjectileRange', 0) or 0),
            }
    return {}


def _action_lifetime(raw: dict) -> int:
    """A lifetime declared as an action rather than a `LifeTime` field.

    Elite Archer Hero's decoy is killed by its own graph - an `ActionInterval`
    counting 7000ms into an `ActionKill` - and nothing read it, so the decoy
    stood on the board forever. A permanent decoy is a different and much
    better card than a seven-second one.
    """
    actions = raw.get('_ACTION_DATA', {})
    start = str(raw.get('OnStartingAction', '') or '')
    if not start:
        return 0
    seen: set[str] = set()

    def walk(name: str, depth: int = 0) -> int:
        if not name or name in seen or depth > 3:
            return 0
        seen.add(name)
        action = actions.get(name, {})
        if not isinstance(action, dict):
            return 0
        target = str(action.get('ActionToExecute', '') or '')
        if (str(action.get('ClassType', '')) == 'ActionInterval' and target
                and str(actions.get(target, {}).get('ClassType', '')) == 'ActionKill'):
            return int(action.get('Interval', 0) or 0)
        subs = action.get('SubActions', [])
        if isinstance(subs, str):
            subs = [subs]
        for child in subs if isinstance(subs, list) else ():
            found = walk(str(child), depth + 1)
            if found:
                return found
        return 0

    return walk(start)


def _drill_relocate(raw: dict) -> dict:
    """The Evolved Goblin Drill's hide-and-resurface controller.

    `ActionGoblinDrillEvoRelocate` declares the whole evolution: it goes under
    at `HideHpThresholds` of 66 and 33 percent, stays down for `HideTime`, and
    leaves goblins behind on the way - two the first time, one the second, from
    the two `HideActions` groups. `FirstAppearAction` is the damage burst it
    comes back up with.

    Where it comes back is the one thing the file does not say, only
    `UseDistanceBasedPositioning = true`. The published behaviour fills that
    in: it resurfaces in the same spot unless it was placed next to a Crown
    Tower, in which case it comes up ninety degrees around that tower.
    """
    for action in raw.get('_ACTION_DATA', {}).values():
        if (isinstance(action, dict)
                and str(action.get('ClassType', '')) == 'ActionGoblinDrillEvoRelocate'):
            return action
    return {}


def _drill_hide_goblins(raw: dict, action: dict) -> tuple:
    """How many goblins each hide leaves behind, in threshold order."""
    actions = raw.get('_ACTION_DATA', {})
    counts = []
    groups = action.get('HideActions', [])
    if isinstance(groups, str):
        groups = [groups]
    for name in groups:
        group = actions.get(str(name), {})
        subs = group.get('SubActions', []) if isinstance(group, dict) else []
        if isinstance(subs, str):
            subs = [subs]
        counts.append(sum(
            1 for sub in subs
            if str(actions.get(str(sub), {}).get('ClassType', '')) == 'ActionSpawnToLocation'))
    return tuple(counts)


def _pingpong_controller(raw: dict) -> dict:
    """The controller for a boomerang projectile, if the card throws one.

    Evolved Executioner is the only card that does. His axe flies out to
    `ProjectileRange` and comes back, hitting everything in its radius on both
    legs - which is why his card screen shows his damage as "70 x2" through
    `OverrideIntValue2 = 2` and `Unit = "INTEGER_TIMES_X"`.

    The simulator threw the axe at whatever he was targeting, dealt damage
    once, and stopped there. Anything standing behind that target took nothing,
    and nothing was ever hit twice - so a card whose whole job is clearing a
    line was a single-target 70.
    """
    for action in raw.get('_ACTION_DATA', {}).values():
        if (isinstance(action, dict)
                and str(action.get('ClassType', '')) == 'ActionExecutionerEvoProjectile'):
            return action
    return {}


def _action_spawned_area(raw: dict, action_name, depth: int = 0) -> dict:
    """The area effect an action spawns, following one action group into its parts.

    A projectile usually names its area outright with `SpawnAreaEffectObject`,
    and the loader read only that field. Wizard Hero's ability projectile
    declares nothing of the sort - it points `OnTargetReachedAction` at an
    action group whose two `ActionSpawn` children spawn the tornado and the
    17-damage area beside it. The area existed in the file and the card landed
    a bare hit.

    Prefers an area that declares damage, because a card can spawn several and
    only one of them is the one this single field can carry. Depth-limited for
    the same reason `_action_damage` is: action graphs reference each other
    freely and a cycle here would hang the loader.
    """
    if not action_name or depth > 2:
        return {}
    actions = raw.get('_ACTION_DATA', {})
    areas = raw.get('_AEO_DATA', {})
    action = actions.get(str(action_name), {})
    if not isinstance(action, dict):
        return {}
    found: dict = {}
    if (str(action.get('ClassType', '')) == 'ActionSpawn'
            and str(action.get('SpawnType', '')) == 'AreaEffectType'):
        area = areas.get(str(action.get('SpawnData', '') or ''), {})
        if isinstance(area, dict) and area:
            if int(area.get('Damage', 0) or 0) > 0:
                return area
            found = area
    sub = action.get('SubActions', [])
    if isinstance(sub, str):
        sub = [sub]
    if isinstance(sub, list):
        for child in sub:
            area = _action_spawned_area(raw, child, depth + 1)
            if area:
                if int(area.get('Damage', 0) or 0) > 0:
                    return area
                found = found or area
    return found


def _attract_percentage(raw: dict, buff_name: str) -> int:
    """`AttractPercentage` for a buff, wherever the client happens to keep it.

    Tornado's and Evolved Valkyrie's live in the shared buff tables; Wizard
    Hero declares `[BUFF.WizardHero_MiniTornadoBuff]` inside its own file, so
    the global loader alone would miss it and the card would look like it had
    no pull at all.
    """
    if not buff_name:
        return 0
    local = raw.get('_BUFF_DATA', {}).get(buff_name, {})
    if isinstance(local, dict) and local.get('AttractPercentage') is not None:
        return int(local['AttractPercentage'])
    return load_buff_attractions().get(buff_name, 0)


def _action_spawned_attractor(raw: dict, action_name, depth: int = 0) -> dict:
    """The *attracting* area an action spawns, beside whichever one carries damage.

    Wizard Hero's ability projectile spawns two areas from one action group:
    `WizardHero_DamageAEO`, which `_action_spawned_area` returns, and
    `WizardHero_MiniTornadoAEO`, whose buff declares `AttractPercentage = 250`.
    A single area field can only carry one of them, so the pull is looked up
    separately rather than by dropping the damage.
    """
    if not action_name or depth > 2:
        return {}
    actions = raw.get('_ACTION_DATA', {})
    areas = raw.get('_AEO_DATA', {})
    action = actions.get(str(action_name), {})
    if not isinstance(action, dict):
        return {}
    if (str(action.get('ClassType', '')) == 'ActionSpawn'
            and str(action.get('SpawnType', '')) == 'AreaEffectType'):
        area = areas.get(str(action.get('SpawnData', '') or ''), {})
        if isinstance(area, dict) and _attract_percentage(
                raw, str(area.get('Buff', '') or '')):
            return area
    sub = action.get('SubActions', [])
    if isinstance(sub, str):
        sub = [sub]
    if isinstance(sub, list):
        for child in sub:
            area = _action_spawned_attractor(raw, child, depth + 1)
            if area:
                return area
    return {}


def _warp_to_target(raw: dict) -> tuple:
    """Speed and target strategy for an `ActionWarpCharacter`, if the card has one.

    Read from the client's own tables rather than recorded by hand. The action
    audit listed this as "accelerating warp path, arrival contact and target
    acquisition", as though it needed measuring, and every number was already
    in the file: Mega Minion Hero declares Speed 1500 and a resolver that picks
    the lowest max hitpoints, furthest first, with towers excluded.
    """
    actions = raw.get('_ACTION_DATA', {})
    resolvers = raw.get('_RESOLVER_DATA', {})
    for action in actions.values():
        if not isinstance(action, dict):
            continue
        if action.get('ClassType') != 'ActionWarpCharacter':
            continue
        try:
            speed = int(action.get('Speed', 0) or 0)
        except (TypeError, ValueError):
            speed = 0
        resolver = resolvers.get(str(action.get('TargetResolver', '') or ''), {})
        strategies = resolver.get('StrategyList', []) if isinstance(resolver, dict) else []
        if isinstance(strategies, str):
            strategies = [strategies]
        return speed, ",".join(str(s) for s in strategies)
    return 0, ""


def to_snake_case(name: str) -> str:
    n = name.lower()
    if n == "minipekka": return "minipekka"
    if n == "thelog": return "the_log"
    s = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s).lower()

def parse_toml_fallback(text: str) -> dict:
    data = {}
    current_section = data
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'): continue
        if line.startswith('[') and line.endswith(']'):
            sec = line[1:-1]
            parts = sec.split('.')
            current = data
            for p in parts:
                if p not in current:
                    current[p] = {}
                current = current[p]
            current_section = current
        elif '=' in line:
            k, v = line.split('=', 1)
            k = k.strip()
            v = v.strip()
            if v == 'true': v = True
            elif v == 'false': v = False
            elif v.isdigit(): v = int(v)
            elif v.startswith('-') and v[1:].isdigit(): v = int(v)
            elif v.startswith('"') and v.endswith('"'): v = v[1:-1]
            elif v.startswith('[') and v.endswith(']'):
                try:
                    import json
                    v = json.loads(v)
                except: pass
            else:
                try: v = float(v)
                except: pass
            current_section[k] = v
    return data

def parse_toml_file(path: Path) -> dict:
    text = path.read_text(encoding='utf-8', errors='replace')
    try:
        import tomllib
        return tomllib.loads(text)
    except Exception:
        return parse_toml_fallback(text)

def _projectile_field(raw: dict, proj_name, key: str, default):
    """Read a field from the unit's projectile section.

    An Ice Spirit carries no freeze of its own: the freeze is on
    IceSpiritsProjectile as TargetBuff and BuffTime, which is why looking only
    at the character never found it.
    """
    if not proj_name:
        return default
    local = raw.get('_PROJECTILE_DATA', {}).get(proj_name, {})
    value = local.get(key, default)
    return value if value not in (None, '') else default


def build_unit_spec(name: str, raw: dict, level: int, card_rarity: str, rarities_dict: dict, proj_dict: dict) -> UnitSpec:
    snake_name = to_snake_case(name)
    
    hp_base = int(raw.get('Hitpoints', 0))
    dmg_base = int(raw.get('Damage', 0))
    if dmg_base == 0:
        sequence = raw.get('AttackSequenceList', [])
        if isinstance(sequence, list) and sequence and isinstance(sequence[0], dict):
            dmg_base = int(sequence[0].get('Damage', 0) or 0)

    # A ranged unit carries no Damage of its own: it fires a projectile, and
    # the damage lives in the `[PROJECTILE.X]` section its `Projectile` field
    # names. Reading only the character section gave Cannon and Musketeer
    # **zero damage**, so in simulation a Cannon could not kill a Hog Rider and
    # a Musketeer could not shoot anything.
    # Follow the declared chain until a damage figure turns up, rather than
    # stopping at `Projectile`. Two shapes broke that:
    #
    #   Princess names `Projectile = PrincessProjectileDeco`, which is the
    #   decorative arrow and carries no Damage at all; the real shot is
    #   `CustomFirstProjectile = PrincessProjectile`, Damage 66.
    #
    #   Firecracker's projectile carries no Damage either - it declares
    #   `SpawnProjectile = FirecrackerExplosion`, and the damage is on that.
    #
    # Both came out as zero-damage cards: a Princess that fired and hurt
    # nothing. Each hop below is a field the client itself declares, so this
    # follows the data rather than guessing where a number ought to live.
    if dmg_base == 0:
        projectiles = raw.get('_PROJECTILE_DATA', {})
        seen = set()
        queue = [raw.get('Projectile'), raw.get('CustomFirstProjectile')]
        # An attack sequence can name the real projectile while the top level
        # names a decorative one or blanks it out. Evolved Princess sets
        # `CustomFirstProjectile = ""` at the top and declares
        # `Princess_EV1_Projectile` inside its AttackSequenceList, so reading
        # only the top level left the card firing a decoration for no damage.
        sequence_entries = raw.get('AttackSequenceList', [])
        if isinstance(sequence_entries, list):
            for entry in sequence_entries:
                if not isinstance(entry, dict):
                    continue
                queue.append(entry.get('CustomFirstProjectile'))
                queue.append(entry.get('Projectile'))
        while queue and dmg_base == 0:
            key = queue.pop(0)
            if not key or key in seen:
                continue
            seen.add(key)
            local = projectiles.get(key, {})
            try:
                dmg_base = int(local.get('Damage', 0) or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{name} projectile {key} has non-scalar Damage "
                    f"{local.get('Damage')!r}") from exc
            if dmg_base == 0:
                queue.append(local.get('SpawnProjectile'))
                # A projectile can carry its damage on the action it starts
                # rather than on itself. Evolved Executioner's axe declares
                # Damage 0 and points `OnStartingAction` at an action group
                # whose controller holds Damage 70 / StrongDamage 94, so the
                # card threw an axe that hurt nothing at all. Super Archer's
                # charge arrow is the same shape with no Damage field of its
                # own anywhere on the projectile.
                dmg_base = _action_damage(raw, local.get('OnStartingAction'))

    proj_name = raw.get('Projectile')
    projectile_data = raw.get('_PROJECTILE_DATA', {}).get(proj_name, {}) if proj_name else {}
    projectile_area_name = str(projectile_data.get('SpawnAreaEffectObject', '') or '')
    projectile_area = raw.get('_AEO_DATA', {}).get(projectile_area_name, {})
    if not projectile_area:
        # Not every projectile names its area directly; some declare an action
        # that spawns it. See `_action_spawned_area`.
        projectile_area = _action_spawned_area(
            raw, projectile_data.get('OnTargetReachedAction'))
    projectile_attract_area = _action_spawned_attractor(
        raw, projectile_data.get('OnTargetReachedAction'))
    special_proj_name = raw.get('ProjectileSpecial')
    external = combat_rule(snake_name)
    hp = scale_stat(hp_base, card_rarity, level, rarities_dict)
    dmg = scale_stat(dmg_base, card_rarity, level, rarities_dict)
    if external.get('damage_override') is not None:
        dmg = carry_verified(external['damage_override'], dmg_base, card_rarity,
                             level, rarities_dict, external.get('level'))
    if external.get('hitpoints_override') is not None:
        hp = carry_verified(external['hitpoints_override'], hp_base, card_rarity,
                            level, rarities_dict, external.get('level'))

    splash = int(raw.get('AreaDamageRadius', 0))
    if not splash and proj_name:
        local_proj = raw.get('_PROJECTILE_DATA', {}).get(proj_name, {})
        splash = int(local_proj.get('Radius', 0)) or int(local_proj.get('AreaDamageRadius', 0))
        if not splash:
            splash = proj_dict.get(proj_name, 0)
            
    proj_speed = 0
    if proj_name:
        local_proj = raw.get('_PROJECTILE_DATA', {}).get(proj_name, {})
        proj_speed = int(local_proj.get('Speed', 0) or 0) * 1000 // 60

    is_flying = int(raw.get('FlyingHeight', 0)) > 0 or bool(raw.get('Flying', False))
    ability_name = str(raw.get('Ability', '') or '')
    ability_details = load_ability_details().get(ability_name, {})
    initial_shield_pct = 100
    start_action = str(raw.get('OnStartingAction', '') or '')
    actions = raw.get('_ACTION_DATA', {})
    seen_actions: set[str] = set()
    def find_start_shield(action_name: str) -> int | None:
        if action_name in seen_actions:
            return None
        seen_actions.add(action_name)
        action = actions.get(action_name, {}) if isinstance(actions, dict) else {}
        if not isinstance(action, dict):
            return None
        if action.get('ClassType') == 'ActionSetShield':
            return int(action.get('ShieldPercent', 0) or 0)
        children = action.get('SubActions', [])
        if isinstance(children, str):
            children = [children]
        for child in children:
            result = find_start_shield(str(child))
            if result is not None:
                return result
        return None
    if start_action:
        found_start_shield = find_start_shield(start_action)
        if found_start_shield is not None:
            initial_shield_pct = found_start_shield

    after_hits = raw.get('BuffAfterHitsCount', [])
    after_times = raw.get('BuffAfterHitsTime', [])
    after_names = raw.get('BuffAfterHits', [])
    if not isinstance(after_hits, list):
        after_hits = [after_hits]
    if not isinstance(after_times, list):
        after_times = [after_times]
    if not isinstance(after_names, list):
        after_names = [after_names]
    after_name = str(after_names[0] if after_names else '')
    after_speed, after_hit_speed, after_heal = load_buffs().get(
        after_name, (0, 0, 0))
    after_spawn = load_buff_spawns().get(after_name, ("", 0, 0))
    idle_buff = str(raw.get('BuffWhenNotAttacking', '') or '')
    death_area = raw.get('_AEO_DATA', {}).get(
        str(raw.get('DeathAreaEffect', '') or ''), {})
    death_damage_area = raw.get('_EXT_DATA', {}).get(
        str(death_area.get('SpawnAreaEffectObject', '') or ''), {})
    death_area_buff = str(death_area.get('Buff', '') or '')
    death_speed, death_hit_speed, _ = load_buffs().get(
        death_area_buff, (0, 0, 0))
    attack_action = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('OnAttackAction', '') or ''), {})
    attack_area = raw.get('_AEO_DATA', {}).get(
        str(attack_action.get('SpawnData', '') or ''), {})
    wind_area = raw.get('_AEO_DATA', {}).get(
        str(attack_action.get('Aeo', '') or ''), {})
    wind_shape = raw.get('_SHAPE_DATA', {}).get(
        str(wind_area.get('Shape', '') or ''), {})
    wind_hit_action = raw.get('_ACTION_DATA', {}).get(
        str(wind_area.get('OnHitAction', '') or ''), {})
    wind_enemy_action = raw.get('_ACTION_DATA', {}).get(
        str(wind_hit_action.get('IsEnemyAction', '') or ''), {})
    wind_friend_action = raw.get('_ACTION_DATA', {}).get(
        str(wind_hit_action.get('IsSameTeamAction', '') or ''), {})
    wind_enemy_buff = raw.get('_BUFF_DATA', {}).get(
        str(wind_enemy_action.get('SpawnData', '') or ''), {})
    wind_friend_buff = raw.get('_BUFF_DATA', {}).get(
        str(wind_friend_action.get('SpawnData', '') or ''), {})
    shield_action = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('ShieldLostAction', '') or ''), {})
    shield_charge_buff = str(shield_action.get('SpawnData', '') or '')
    shield_area_action = shield_action
    shield_children = shield_action.get('SubActions', [])
    if isinstance(shield_children, str):
        shield_children = [shield_children]
    if shield_children:
        shield_area_action = raw.get('_ACTION_DATA', {}).get(
            str(shield_children[0]), {})
    shield_lost_area = raw.get('_AEO_DATA', {}).get(
        str(shield_area_action.get('SpawnData', '') or ''), {})
    damage_action = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('OnDamageTakenAction', '') or ''), {})
    damage_children = damage_action.get('SubActions', [])
    if isinstance(damage_children, str):
        damage_children = [damage_children]
    damage_buff_action = {}
    for child_name in damage_children:
        candidate = raw.get('_ACTION_DATA', {}).get(str(child_name), {})
        if candidate.get('SpawnType') == 'BuffType':
            damage_buff_action = candidate
            break
    damage_buff = raw.get('_BUFF_DATA', {}).get(
        str(damage_buff_action.get('SpawnData', '') or ''), {})
    starting_action = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('OnStartingAction', '') or ''), {})
    threshold_spawn_interval = {}
    threshold_spawn_action = {}
    if starting_action.get('ClassType') == 'ActionRunActionAtHealth':
        threshold_children = starting_action.get('Actions', [])
        if isinstance(threshold_children, str):
            threshold_children = [threshold_children]
        for child_name in threshold_children:
            candidate = raw.get('_ACTION_DATA', {}).get(str(child_name), {})
            if candidate.get('ClassType') == 'ActionInterval':
                threshold_spawn_interval = candidate
                threshold_spawn_action = raw.get('_ACTION_DATA', {}).get(
                    str(candidate.get('ActionToExecute', '') or ''), {})
                break
    starting_children = starting_action.get('SubActions', [])
    if isinstance(starting_children, str):
        starting_children = [starting_children]
    side_summon_action = {}
    for child_name in starting_children:
        candidate = raw.get('_ACTION_DATA', {}).get(str(child_name), {})
        if candidate.get('ClassType') == 'ActionGhostEvoAction':
            side_summon_action = candidate
            break
    side_spawn_action = raw.get('_ACTION_DATA', {}).get(
        str(side_summon_action.get('SummonActionData', '') or ''), {})
    side_damage_area = raw.get('_AEO_DATA', {}).get(
        str(side_summon_action.get('DamageAEO', '') or ''), {})
    attack_select = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('OnStartingAttackAction', '') or ''), {})
    far_range_match = re.search(
        r'target_in_range\((\d+)\)', str(attack_select.get('Condition', '')))
    second_projectile = raw.get('_PROJECTILE_DATA', {}).get(
        str(raw.get('Projectile2', '') or ''), {})
    killed_action = raw.get('_ACTION_DATA', {}).get(
        str(raw.get('OnKilledAction', '') or ''), {})
    killed_spawn_character = (str(killed_action.get('SpawnData', '') or '')
                              if killed_action.get('SpawnType') == 'CharacterType'
                              else '')
    killed_next = killed_action.get('NextAction', {})
    killed_projectile_name = (str(killed_next.get('SpawnData', '') or '')
                              if isinstance(killed_next, dict)
                              and killed_next.get('SpawnType') == 'ProjectileType'
                              else '')
    killed_projectile_name = (killed_projectile_name
                              or str(raw.get('DeathSpawnProjectile', '') or ''))
    killed_projectile = raw.get('_PROJECTILE_DATA', {}).get(
        killed_projectile_name, {})
    ground_group = {}
    if starting_action.get('ClassType') == 'ActionRunActionAtHealth':
        ground_actions = starting_action.get('Actions', [])
        if isinstance(ground_actions, str):
            ground_actions = [ground_actions]
        for action_name in ground_actions:
            candidate = actions.get(str(action_name), {})
            if candidate.get('ClassType') == 'ActionGroup':
                ground_group = candidate
                break
    on_attack_ground = actions.get(str(raw.get('OnAttackAction', '') or ''), {})
    if not ground_group and on_attack_ground.get('ClassType') == 'ActionGroup':
        ground_group = on_attack_ground
    ground_air_action = {}
    for child_name in (ground_group.get('SubActions', [])
                       if isinstance(ground_group.get('SubActions', []), list)
                       else [ground_group.get('SubActions', '')]):
        candidate = actions.get(str(child_name), {})
        if candidate.get('ClassType') == 'ActionAirToGround':
            ground_air_action = candidate
            break
    landed_group = actions.get(str(ground_air_action.get('ActionOnGround', '') or ''), {})
    ground_change_action = {}
    ground_area_action = {}
    landed_children = landed_group.get('SubActions', [])
    if isinstance(landed_children, str):
        landed_children = [landed_children]
    for child_name in landed_children:
        candidate = actions.get(str(child_name), {})
        if candidate.get('ClassType') == 'ActionChangeGameObjectData':
            ground_change_action = candidate
        elif (candidate.get('ClassType') == 'ActionSpawn'
              and candidate.get('SpawnType') == 'AreaEffectType'):
            ground_area_action = candidate
    ground_landing_area = raw.get('_AEO_DATA', {}).get(
        str(ground_area_action.get('SpawnData', '') or ''), {})
    control_action = (starting_action
                      if starting_action.get('ClassType') == 'ActionHunterNetAttack'
                      else {})
    control_projectile = raw.get('_PROJECTILE_DATA', {}).get(
        str(control_action.get('Projectile', '') or ''), {})
    control_hit = actions.get(
        str(control_projectile.get('OnHitTargetAction', '') or ''), {})
    control_select = {}
    control_air_action = {}
    control_hit_children = control_hit.get('SubActions', [])
    if isinstance(control_hit_children, str):
        control_hit_children = [control_hit_children]
    for child_name in control_hit_children:
        candidate = actions.get(str(child_name), {})
        if candidate.get('ClassType') == 'ActionSelect':
            control_select = candidate
        elif candidate.get('ClassType') == 'ActionAirToGround':
            control_air_action = candidate
    control_spawn = {}
    control_choices = control_select.get('SubActions', [])
    if isinstance(control_choices, str):
        control_choices = [control_choices]
    if control_choices:
        control_spawn = actions.get(str(control_choices[0]), {})
    uppercut_action = {}
    uppercut_target_group = {}
    uppercut_flight_action = {}
    uppercut_root_action = {}
    attack_children = attack_action.get('SubActions', [])
    if isinstance(attack_children, str):
        attack_children = [attack_children]
    for child_name in attack_children:
        candidate = actions.get(str(child_name), {})
        if candidate.get('ClassType') == 'ActionMegaKnightUppercut':
            uppercut_action = candidate
            break
    if uppercut_action:
        uppercut_target_group = actions.get(
            str(uppercut_action.get('ActionOnTargets', '') or ''), {})
        uppercut_children = uppercut_target_group.get('SubActions', [])
        if isinstance(uppercut_children, str):
            uppercut_children = [uppercut_children]
        for child_name in uppercut_children:
            candidate = actions.get(str(child_name), {})
            if candidate.get('ClassType') == 'ActionKnockback':
                uppercut_flight_action = candidate
            elif candidate.get('ClassType') == 'ActionWithDuration':
                uppercut_root_action = candidate
    chain_action = {}
    sequence_list = raw.get('AttackSequenceList', [])
    if isinstance(sequence_list, dict):
        sequence_list = [sequence_list]
    persistent_sequence_damages = tuple(
        scale_stat(int(row.get('Damage', 0) or 0), card_rarity,
                   level, rarities_dict)
        for row in sequence_list if isinstance(row, dict) and row.get('Damage'))
    if sequence_list:
        sequence_root = actions.get(
            str(sequence_list[0].get('DoAttackAction', '') or ''), {})
        sequence_children = sequence_root.get('SubActions', [])
        if isinstance(sequence_children, str):
            sequence_children = [sequence_children]
        for child_name in sequence_children:
            candidate = actions.get(str(child_name), {})
            if candidate.get('ClassType') == 'ActionChainProjectileAttack':
                chain_action = candidate
                break
    chain_projectiles = chain_action.get('Projectiles', [])
    if isinstance(chain_projectiles, str):
        chain_projectiles = [chain_projectiles]
    reduced_chain_projectile = (raw.get('_PROJECTILE_DATA', {}).get(
        str(chain_projectiles[-1]), {}) if chain_projectiles else {})
    
    return UnitSpec(
        name=snake_name,
        hitpoints=hp,
        damage=dmg,
        hit_speed_ms=int(raw.get('HitSpeed', 0)),
        load_time_ms=int(raw.get('LoadTime', 0)),
        range_mt=int(raw.get('Range', 0)),
        sight_range_mt=int(raw.get('SightRange', 0)),
        speed_mt_per_sec=int(raw.get('Speed', 0)),
        collision_radius_mt=int(raw.get('CollisionRadius', 0)),
        mass=int(raw.get('Mass', 0)),
        deploy_time_ms=int(raw.get('DeployTime', 0)),
        attacks_ground=bool(raw.get('AttacksGround', False)),
        attacks_air=bool(raw.get('AttacksAir', False)),
        flying=is_flying,
        target_only_buildings=bool(raw.get('TargetOnlyBuildings', False)),
        target_only_troops=bool(raw.get('TargetOnlyTroops', False)),
        splash_radius_mt=splash,
        jump_enabled=bool(raw.get('JumpEnabled', False)),
        jump_speed_mt_per_sec=int(raw.get('JumpSpeed', 0)),
        retarget_after_attack=bool(raw.get('RetargetAfterAttack', False)),
        attack_self_pushback_mt=int(raw.get('AttackPushBack', 0) or 0),
        spawn_number=max(1, int(raw.get('SpawnNumber', 0))),
        projectile_speed_mt_per_sec=proj_speed,
        projectile_homing=bool(_projectile_field(raw, proj_name, 'Homing', False)),
        projectile_deflect_behaviour=str(
            _projectile_field(raw, proj_name, 'DeflectBehaviour', '') or ''),
        # A single immunity is written as a bare string rather than a list,
        # and iterating that yields characters.
        ignored_buffs=tuple(
            str(name) for name in (
                [raw['IgnoreBuff']] if isinstance(raw.get('IgnoreBuff'), str)
                else (raw.get('IgnoreBuff') or ()))
            if isinstance(name, str)),
        projectile_deflector_damage=scale_stat(
            int(raw.get('_ACTION_DATA', {}).get(
                str(_projectile_field(raw, proj_name, 'ActionOnDeflector', '') or ''),
                {}).get('BaseDamageAmount', 0) or 0),
            card_rarity, level, rarities_dict),
        pingpong_range_mt=(
            int(_projectile_field(raw, proj_name, 'ProjectileRange', 0) or 0)
            if _projectile_field(raw, proj_name, 'PingpongVisualTime', 0) else 0),
        pingpong_radius_mt=int(
            _projectile_field(raw, proj_name, 'ProjectileRadius', 0)
            or _projectile_field(raw, proj_name, 'Radius', 0) or 0),
        # The evolution hangs its damage on a controller; the base card keeps
        # it on the projectile, where the unit's own damage already found it.
        # Both throw the same boomerang and both were single-hitting.
        pingpong_damage=(scale_stat(
            int(_pingpong_controller(raw).get('Damage', 0) or 0),
            card_rarity, level, rarities_dict)
            or dmg),
        pingpong_strong_damage=scale_stat(
            int(_pingpong_controller(raw).get('StrongDamage', 0) or 0),
            card_rarity, level, rarities_dict),
        pingpong_strong_range_mt=int(
            _pingpong_controller(raw).get('StrongDamageRange', 0) or 0),
        pingpong_pushback_mt=int(
            _pingpong_controller(raw).get('FirstStrongHitPushback', 0) or 0),
        hide_hp_thresholds=tuple(
            int(v) for v in _drill_relocate(raw).get('HideHpThresholds', ()) or ()),
        hide_time_ms=int(_drill_relocate(raw).get('HideTime', 0) or 0),
        hide_goblin_counts=_drill_hide_goblins(raw, _drill_relocate(raw)),
        hide_spawn_character=('Goblin' if _drill_relocate(raw) else ''),
        hide_spawn_offset_mt=(1000 if _drill_relocate(raw) else 0),
        hide_reappear_damage=scale_stat(
            int(raw.get('_AEO_DATA', {}).get('GoblinDrillDamage', {}).get(
                'Damage', 0) or 0) if _drill_relocate(raw) else 0,
            card_rarity, level, rarities_dict),
        hide_reappear_radius_mt=int(
            raw.get('_AEO_DATA', {}).get('GoblinDrillDamage', {}).get('Radius', 0) or 0
            if _drill_relocate(raw) else 0),
        hide_reappear_pushback_mt=int(
            raw.get('_AEO_DATA', {}).get('GoblinDrillDamage', {}).get('Pushback', 0) or 0
            if _drill_relocate(raw) else 0),
        death_damage=scale_stat(int(killed_projectile.get(
                                      'Damage', raw.get('DeathDamage', 0)) or 0),
                                card_rarity, level, rarities_dict),
        death_damage_radius_mt=int(killed_projectile.get(
            'Radius', raw.get('DeathDamageRadius', 0)) or 0),
        death_damage_pushback_mt=int(killed_projectile.get('Pushback', 0) or 0),
        death_spawn_character=str(external.get(
            'death_spawn_character_override',
            killed_spawn_character or raw.get('DeathSpawnCharacter', '')) or ''),
        # A Balloon names BalloonBomb but leaves the count blank, so a card
        # that clearly drops something would drop nothing. One is the sane
        # reading of "names a spawn, gives no number".
        death_spawn_count=(int(external['death_spawn_count_override'])
                           if external.get('death_spawn_count_override') is not None
                           else (1 if killed_spawn_character else
                                 (int(raw.get('DeathSpawnCount', 0) or 0)
                                  or (1 if raw.get('DeathSpawnCharacter') else 0)))),
        death_spawn_radius_mt=int(raw.get('DeathSpawnRadius', 0) or 0),
        death_spawn_at_source=bool(external.get('death_spawn_at_source', False)),
        death_spawn_deploy_ms=int(
            external.get('death_spawn_deploy_ms', 0) or 0),
        death_spawn_offsets=tuple(
            (int(row[0]), int(row[1]))
            for row in external.get('death_spawn_offsets', ())),
        spawn_character=str(external.get(
            'spawn_character_override', raw.get('SpawnCharacter', '')) or ''),
        spawn_count=int(external.get(
            'spawn_count_override', raw.get('SpawnNumber', 0)) or 0),
        spawn_pause_ms=int(external.get(
            'spawn_pause_override_ms', raw.get('SpawnPauseTime', 0)) or 0),
        spawn_start_ms=int(external.get(
            'spawn_start_override_ms', raw.get('SpawnStartTime', 0)) or 0),
        spawn_forward_mt=int(external.get('spawn_forward_mt', 0) or 0),
        spawn_deploy_ms=int(external.get('spawn_deploy_ms', 0) or 0),
        hot_spawn_character=str(external.get('hot_spawn_character', '') or ''),
        hot_spawn_interval_ms=int(
            external.get('hot_spawn_interval_ms', 0) or 0),
        hot_spawn_first_delay_ms=int(
            external.get('hot_spawn_first_delay_ms', 0) or 0),
        hot_spawn_side_mt=int(external.get('hot_spawn_side_mt', 0) or 0),
        hot_spawn_behind_mt=int(external.get('hot_spawn_behind_mt', 0) or 0),
        hot_spawn_deploy_ms=int(external.get('hot_spawn_deploy_ms', 0) or 0),
        hot_spawn_stop_moving_ms=int(
            external.get('hot_spawn_stop_moving_ms', 0) or 0),
        hot_spawn_normal_resume_ms=int(
            external.get('hot_spawn_normal_resume_ms', 0) or 0),
        threshold_spawn_hp_pct=int((starting_action.get('HealthPercentages') or [0])[0]
                                   if isinstance(starting_action.get('HealthPercentages'), list)
                                   else starting_action.get('HealthPercentages', 0) or 0),
        threshold_spawn_character=(str(threshold_spawn_action.get('SpawnData', '') or '')
                                   if threshold_spawn_action.get('SpawnType') == 'CharacterType'
                                   else ''),
        threshold_spawn_interval_ms=int(threshold_spawn_interval.get('Interval', 0) or 0),
        threshold_spawn_behind_mt=int(external.get('threshold_spawn_behind_mt', 0) or 0),
        target_buff=str(raw.get('BuffOnDamage') or
                        _projectile_field(raw, proj_name, 'TargetBuff', '')),
        buff_time_ms=int(raw.get('BuffOnDamageTime') or
                         _projectile_field(raw, proj_name, 'BuffTime', 0) or 0),
        multiple_targets=max(1, int(raw.get('MultipleTargets', 1) or 1)),
        all_targets_hit=bool(raw.get('AllTargetsHit', False)),
        variable_damage2=verified_or_scaled(
            external, 'variable_damage2_override',
            raw.get('VariableDamage2', 0), card_rarity, level, rarities_dict),
        variable_damage3=verified_or_scaled(
            external, 'variable_damage3_override',
            raw.get('VariableDamage3', 0), card_rarity, level, rarities_dict),
        variable_damage_time1_ms=int(raw.get('VariableDamageTime1', 0) or 0),
        variable_damage_time2_ms=int(raw.get('VariableDamageTime2', 0) or 0),
        persistent_ramp_damages=(persistent_sequence_damages
                                 if external.get('persistent_ramp_thresholds')
                                 else ()),
        persistent_ramp_thresholds=tuple(
            int(value) for value in external.get('persistent_ramp_thresholds', ())),
        persistent_ramp_decay_ms=int(external.get('persistent_ramp_decay_ms', 0) or 0),
        spawn_area_damage=(int(external['spawn_area_damage_override'])
                           if external.get('spawn_area_damage_override') is not None
                           else scale_stat(int(raw.get('_SPAWN_AREA_DATA', {}).get(
                               'Damage', 0) or 0), card_rarity, level,
                               rarities_dict)),
        spawn_area_tower_damage=int(
            external.get('spawn_area_tower_damage_override', 0) or 0),
        spawn_area_radius_mt=int(external.get(
            'spawn_area_radius_override_mt',
            raw.get('_SPAWN_AREA_DATA', {}).get('Radius', 0)) or 0),
        spawn_area_tower_percent=100 + int(
            raw.get('_SPAWN_AREA_DATA', {}).get('CrownTowerDamagePercent', 0) or 0),
        spawn_area_buff=str(raw.get('_SPAWN_AREA_DATA', {}).get('Buff', '') or ''),
        spawn_area_buff_ms=int(raw.get('_SPAWN_AREA_DATA', {}).get('BuffTime', 0) or 0),
        chained_hit_count=max(1, int(_projectile_field(raw, proj_name,
                                                       'ChainedHitCount', 1) or 1)),
        chained_hit_radius_mt=int(_projectile_field(raw, proj_name,
                                                    'ChainedHitRadius', 0) or 0),
        chain_unlimited=bool(chain_action and int(chain_action.get('MaxChainLength', 0) or 0) < 0),
        chain_full_damage_hits=max(0, len(chain_projectiles) - 1),
        chain_reduced_damage=scale_stat(
            int(reduced_chain_projectile.get('Damage', 0) or 0),
            card_rarity, level, rarities_dict),
        chain_reduced_speed_mt_per_sec=(
            int(reduced_chain_projectile.get('Speed', 0) or 0) * 1000 // 60),
        chain_repeat_memory=int(chain_action.get(
            'MaximumTargetsToRememberForRepeatChecks', 0) or 0),
        special_min_range_mt=int(raw.get('SpecialMinRange', 0) or 0),
        special_range_mt=int(raw.get('SpecialRange', 0) or 0),
        special_load_time_ms=int(raw.get('SpecialLoadTime', 0) or 0),
        pull_projectile_speed_mt_per_sec=(int(_projectile_field(raw, special_proj_name,
                                                                  'Speed', 0) or 0)
                                          * 1000 // 60),
        pull_target_speed_mt_per_sec=(int(_projectile_field(raw, special_proj_name,
                                                              'DragBackSpeed', 0) or 0)
                                      * 1000 // 60),
        pull_self_speed_mt_per_sec=(int(_projectile_field(raw, special_proj_name,
                                                            'DragSelfSpeed', 0) or 0)
                                    * 1000 // 60),
        pull_margin_mt=int(_projectile_field(raw, special_proj_name,
                                              'DragMargin', 0) or 0),
        pull_speed_pct=int(external.get('pull_speed_pct', 0) or 0),
        pull_buff_ms=int(external.get('pull_buff_ms', 0) or 0),
        projectile_radius_mt=int(_projectile_field(raw, proj_name,
                                                    'ProjectileRadius',
                                                    _projectile_field(raw, proj_name, 'Radius', 0)) or 0),
        projectile_range_mt=int(_projectile_field(raw, proj_name,
                                                   'ProjectileRange', 0) or 0),
        pierces=bool(external.get('pierces', False)),
        attached_character=(str(raw.get('SpawnCharacter', '') or '')
                            if bool(raw.get('SpawnAttach', False)) else ''),
        transform_at_hp_pct=int(raw.get('_TRANSFORM_DATA', {}).get('HealthPercent', 0) or 0),
        transform_character=str(raw.get('_TRANSFORM_DATA', {}).get('Character', '') or ''),
        ability_buff=str(ability_details.get('Buff', ability_name) or ''),
        ability_buff_ms=int(ability_details.get('BuffTime',
                           load_abilities().get(ability_name, (0, 0, 0))[0]) or 0),
        ability_cast_ms=load_abilities().get(ability_name, (0, 0, 0))[1],
        ability_cost=load_abilities().get(ability_name, (0, 0, 0))[2],
        ability_dash_range_mt=int(ability_details.get('DashRange', 0) or 0),
        # A declared dash with no count is one jump, not zero. Golden Knight
        # chains his and says how many; Super Hog Rider Terry's ability is a
        # single leap declaring only `DashRange`, and a count of zero made the
        # scheduler refuse an ability the gate had already offered.
        ability_dash_count=(int(raw.get('DashCount', 0) or 0)
                            or (1 if int(ability_details.get('DashRange', 0) or 0)
                                else 0)),
        ability_dash_landing_ms=int(raw.get('DashLandingTime', 0) or 0),
        ability_shield_pct=int(ability_details.get('ShieldPercent', 0) or 0),
        ability_spawn_character=str(ability_details.get('SpawnCharacter', '') or ''),
        ability_summon_character=str(
            ability_details.get('SummonCharacter', '') or ''),
        ability_summon_base_count=int(
            ability_details.get('SummonBaseCount', 0) or 0),
        ability_summon_max_count=int(
            ability_details.get('SummonMaxCount', 0) or 0),
        ability_summon_interval_ms=int(
            ability_details.get('SummonIntervalMs', 0) or 0),
        ability_summon_initial_delay_ms=int(
            ability_details.get('SummonInitialDelayMs', 0) or 0),
        ability_summon_deploy_ms=int(
            ability_details.get('SummonDeployMs', 0) or 0),
        ability_summon_min_radius_mt=int(
            ability_details.get('SummonMinRadius', 0) or 0),
        ability_summon_max_radius_mt=int(
            ability_details.get('SummonMaxRadius', 0) or 0),
        ability_action_delay_ms=int(external.get(
            'ability_action_delay_ms', ability_details.get(
                'TriggerDelay', ability_details.get('ActionDelay', 0))) or 0),
        ability_pushback_damage=scale_stat(int(ability_details.get('PushBackDamage', 0) or 0), card_rarity, level, rarities_dict),
        ability_pushback_radius_mt=int(ability_details.get('PushBackRadius', 0) or 0),
        ability_pushback_strength_mt=int(ability_details.get('PushBackStrength', 0) or 0),
        ability_appear_behind_mt=int(ability_details.get('AppearBehindAtDistance', 0) or 0),
        ability_area_damage=int(external.get('ability_area_damage', 0) or 0),
        ability_area_radius_mt=int(external.get('ability_area_radius_mt', 0) or 0),
        ability_area_pulse_times_ms=tuple(
            int(value) for value in external.get('ability_area_pulse_times_ms', ())),
        ability_area_slow_pct=int(external.get('ability_area_slow_pct', 0) or 0),
        ability_area_duration_ms=int(external.get('ability_area_duration_ms', 0) or 0),
        ability_area_slow_linger_ms=int(
            external.get('ability_area_slow_linger_ms', 0) or 0),
        # A verified override wins; otherwise take what the ability declares.
        # Musketeer Hero's turret was recorded by hand before the loader could
        # follow `ActionSpawnToLocation`, and that recording stays authoritative
        # rather than being silently replaced by a second reading of the graph.
        ability_deploy_character=str(
            external.get('ability_deploy_character')
            or (ability_details.get('DeployCharacter', '')
                # Dark Prince Hero's `ActionSpawnToLocation` puts down his
                # mount, which the split path already places. Reading it here
                # too would leave two of them standing.
                if ability_details.get('DeployCharacter')
                   != external.get('ability_split_mount') else '')
            or ''),
        ability_deploy_forward_mt=int(
            external.get('ability_deploy_forward_mt')
            if external.get('ability_deploy_character')
            else ability_details.get('DeployForward', 0) or 0),
        ability_deploy_delay_ms=int(
            external.get('ability_deploy_delay_ms', 0) or 0),
        ability_shot_window_ms=(
            int(ability_details.get('ShotWindow', 0) or 0)
            if _parallel_projectiles(raw) else 0),
        ability_extra_projectiles=int(
            _parallel_projectiles(raw).get('count', 0) or 0),
        ability_extra_projectile_spacing_mt=int(
            _parallel_projectiles(raw).get('spacing', 0) or 0),
        ability_shot_damage=scale_stat(
            int(_parallel_projectiles(raw).get('damage', 0) or 0),
            card_rarity, level, rarities_dict),
        ability_shot_range_mt=int(
            _parallel_projectiles(raw).get('range', 0) or 0),
        # The cadence is published, not shipped: the client declares
        # `Princess_EV1_reload_frequency` as a VARIABLE and never gives it a
        # value. Everything else here is read from the file.
        special_attack_every=int(external.get('special_attack_every', 0) or 0),
        special_attack_radius_mt=int(
            _special_attack_area(raw).get('_radius', 0) or 0),
        special_area_duration_ms=int(
            _special_attack_area(raw).get('LifeDuration', 0) or 0),
        special_area_hit_frequency_ms=int(
            _special_attack_area(raw).get('HitSpeed', 0) or 0),
        special_area_buff=str(
            _special_attack_area(raw).get('Buff', '') or ''),
        special_area_buff_ms=int(
            _special_attack_area(raw).get('BuffTime', 0) or 0),
        ability_drop_character=str(
            _paratrooper_drop(raw).get('character', '') or ''),
        ability_drop_radius_mt=int(
            _paratrooper_drop(raw).get('radius', 0) or 0),
        ability_drop_deploy_ms=int(
            _paratrooper_drop(raw).get('deploy', 0) or 0),
        ability_drop_height_mt=int(
            _paratrooper_drop(raw).get('height', 0) or 0),
        ability_deploy_damage=int(
            external.get('ability_deploy_damage', 0) or 0),
        ability_deploy_radius_mt=int(
            external.get('ability_deploy_radius_mt', 0) or 0),
        ability_deploy_pushback_mt=int(
            external.get('ability_deploy_pushback_mt', 0) or 0),
        ability_lane_switch=bool(external.get('ability_lane_switch', False)),
        ability_lane_switch_delay_ms=int(
            external.get('ability_lane_switch_delay_ms', 0) or 0),
        ability_bomb_damage=int(external.get('ability_bomb_damage', 0) or 0),
        ability_bomb_radius_mt=int(
            external.get('ability_bomb_radius_mt', 0) or 0),
        ability_bomb_pushback_mt=int(
            external.get('ability_bomb_pushback_mt', 0) or 0),
        ability_link_target=str(external.get('ability_link_target', '') or ''),
        ability_link_duration_ms=int(
            external.get('ability_link_duration_ms', 0) or 0),
        ability_link_interval_ms=int(
            external.get('ability_link_interval_ms', 0) or 0),
        ability_link_width_mt=int(
            external.get('ability_link_width_mt', 0) or 0),
        ability_link_damage=int(external.get('ability_link_damage', 0) or 0),
        ability_link_tower_damage=int(
            external.get('ability_link_tower_damage', 0) or 0),
        link_receiver_on_death=bool(
            external.get('link_receiver_on_death', False)),
        cannot_target_towers=bool(external.get('cannot_target_towers', False)),
        ability_damage_pct=int(external.get('ability_damage_pct', 0) or 0),
        ability_tower_damage_pct=int(
            external.get('ability_tower_damage_pct', 0) or 0),
        ability_unkillable=bool(external.get('ability_unkillable', False)),
        ability_duration_includes_cast=bool(
            external.get('ability_duration_includes_cast', False)),
        ability_cast_locks_actions=bool(
            external.get('ability_cast_locks_actions', False)),
        tower_damage_pct=int(external.get('tower_damage_pct', 100) or 100),
        invisible_after_ms=(int(raw.get('BuffWhenNotAttackingTime', 0) or 0)
                            if str(raw.get('BuffWhenNotAttacking', '')) == 'Invisibility'
                            else 0),
        idle_damage_reduction_pct=(load_buff_damage_reductions().get(idle_buff, 0)
                                   if idle_buff != 'Invisibility' else 0),
        buff_after_hits_count=int(after_hits[0] if after_hits else 0),
        buff_after_hits_time_ms=int(after_times[0] if after_times else 0),
        buff_after_hits_speed_pct=after_speed,
        buff_after_hits_hit_speed_pct=after_hit_speed,
        buff_after_hits_heal_per_second=scale_stat(
            after_heal, card_rarity, level, rarities_dict),
        buff_after_hits_overheal_pct=load_buff_overheal_percentages().get(
            after_name, 100),
        buff_after_hits_spawn_character=after_spawn[0],
        buff_after_hits_spawn_count=after_spawn[1],
        buff_after_hits_spawn_interval_ms=after_spawn[2],
        group_max_size=int(raw.get('GroupMaxSize', 0) or 0),
        kill_heal_thresholds=tuple(int(value) for value in
                                   external.get('kill_heal_thresholds', ())),
        kill_heal_amounts=tuple(int(value) for value in
                                external.get('kill_heal_amounts', ())),
        kill_heal_overheal_pct=int(external.get('kill_heal_overheal_pct', 100) or 100),
        death_area_damage=(int(external['death_area_damage_override'])
                           if external.get('death_area_damage_override') is not None
                           else scale_stat(
                               int(death_damage_area.get('Damage', 0) or 0),
                               str(death_damage_area.get(
                                   'Rarity', card_rarity) or card_rarity),
                               level, rarities_dict)),
        death_area_radius_mt=int(external.get(
            'death_area_radius_override_mt', death_area.get('Radius', 0)) or 0),
        death_area_duration_ms=int(external.get(
            'death_area_duration_override_ms', death_area.get('LifeDuration', 0)) or 0),
        death_area_hit_frequency_ms=int(external.get(
            'death_area_hit_frequency_override_ms', death_area.get('HitSpeed', 0)) or 0),
        death_area_speed_pct=int(external.get(
            'death_area_speed_override_pct', death_speed) or 0),
        death_area_hit_speed_pct=int(external.get(
            'death_area_hit_speed_override_pct', death_hit_speed) or 0),
        death_area_buff_linger_ms=int(external.get(
            'death_area_buff_linger_override_ms', death_area.get('BuffTime', 0)) or 0),
        death_area_tower_damage=int(
            external.get('death_area_tower_damage', 0) or 0),
        owned_spawn_death_heal=int(external.get('owned_spawn_death_heal', 0) or 0),
        owned_spawn_death_heal_count=int(external.get('owned_spawn_death_heal_count', 0) or 0),
        owned_spawn_death_heal_overheal_pct=int(
            external.get('owned_spawn_death_heal_overheal_pct', 100) or 100),
        spawn_after_first_character=str(external.get('spawn_after_first_character', '') or ''),
        spawn_after_first_pause_ms=int(external.get('spawn_after_first_pause_ms', 0) or 0),
        attack_area_damage=scale_stat(
            int(attack_area.get('Damage', 0) or 0),
            str(attack_area.get('Rarity', card_rarity) or card_rarity),
            level, rarities_dict),
        attack_area_radius_mt=int(attack_area.get('Radius', 0) or 0),
        attack_area_pushback_mt=int(attack_area.get('Pushback', 0) or 0),
        attack_area_attract_percentage=load_buff_attractions().get(
            str(attack_area.get('Buff', '') or ''), 0),
        attack_area_duration_ms=int(attack_area.get('LifeDuration', 0) or 0),
        shield_lost_charge_range_mt=(load_buff_charge_ranges().get(
            shield_charge_buff, 0) * 10),
        shield_lost_area_damage=verified_or_scaled(
            external, 'shield_lost_damage_override',
            shield_lost_area.get('Damage', 0), card_rarity, level, rarities_dict),
        shield_lost_area_radius_mt=int(shield_lost_area.get('Radius', 0) or 0),
        shield_lost_area_pushback_mt=int(shield_lost_area.get('Pushback', 0) or 0),
        on_damage_invulnerable_ms=(int(damage_buff_action.get('SpawnTime', 0) or 0)
                                  if 'NO_DAMAGE' in str(damage_buff.get('GameTagsToSet', ''))
                                  else 0),
        on_damage_speed_pct=int(damage_buff.get('SpeedMultiplier', 0) or 0),
        on_damage_hit_speed_pct=int(damage_buff.get('HitSpeedMultiplier', 0) or 0),
        on_damage_invisible=bool(damage_buff.get('Invisible', False)),
        starting_side_summons=(
            str(side_spawn_action.get('LeftSummonType', '') or ''),
            str(side_spawn_action.get('RightSummonType', '') or '')),
        starting_side_summon_distance_mt=int(
            side_summon_action.get('SummonDistance', 0) or 0),
        starting_side_summon_damage=scale_stat(
            int(side_damage_area.get('Damage', 0) or 0), card_rarity,
            level, rarities_dict),
        starting_side_summon_radius_mt=int(side_damage_area.get('Radius', 0) or 0),
        starting_side_summon_damage_delay_ms=int(
            side_summon_action.get('DamageAEOSpawnDelay', 0) or 0),
        far_attack_min_range_mt=(int(far_range_match.group(1))
                                 if far_range_match else 0),
        far_attack_damage=verified_or_scaled(
            external, 'far_attack_damage_override',
            second_projectile.get('Damage', 0), card_rarity, level, rarities_dict),
        projectile_area_damage=verified_or_scaled(
            external, 'projectile_area_damage_override',
            projectile_area.get('Damage', 0), card_rarity, level, rarities_dict),
        projectile_area_radius_mt=int(external.get(
            'projectile_area_radius_override_mt',
            projectile_area.get('Radius', 0)) or 0),
        projectile_area_delay_ms=int(external.get(
            'projectile_area_delay_override_ms',
            projectile_area.get('HitSpeed', 0)) or 0),
        projectile_area_attract_percentage=_attract_percentage(
            raw, str(projectile_attract_area.get('Buff', '') or '')),
        projectile_area_attract_radius_mt=int(
            projectile_attract_area.get('Radius', 0) or 0),
        projectile_area_attract_duration_ms=int(
            projectile_attract_area.get('LifeDuration', 0) or 0),
        projectile_area_buff=str(projectile_area.get('Buff', '') or ''),
        projectile_area_buff_ms=int(projectile_area.get('BuffTime', 0) or 0),
        projectile_area_hits_ground=bool(external.get(
            'projectile_area_hits_ground_override',
            projectile_area.get('HitsGround', False))),
        projectile_area_hits_air=bool(external.get(
            'projectile_area_hits_air_override',
            projectile_area.get('HitsAir', False))),
        target_poison_damage_tiers=tuple(
            int(value) for value in external.get('target_poison_damage_tiers', ())),
        target_poison_stack_thresholds=tuple(
            int(value) for value in external.get(
                'target_poison_stack_thresholds', ())),
        target_poison_radius_mt=int(
            external.get('target_poison_radius_mt', 0) or 0),
        target_poison_first_tick_ms=int(
            external.get('target_poison_first_tick_ms', 0) or 0),
        target_poison_interval_ms=int(
            external.get('target_poison_interval_ms', 0) or 0),
        target_poison_tower_pct=int(
            external.get('target_poison_tower_pct', 0) or 0),
        target_poison_tower_duration_ms=int(
            external.get('target_poison_tower_duration_ms', 0) or 0),
        sniper_ammo=int(external.get('sniper_ammo', 0) or 0),
        sniper_min_range_mt=int(external.get('sniper_min_range_mt', 0) or 0),
        sniper_max_range_mt=int(external.get('sniper_max_range_mt', 0) or 0),
        sniper_side_clip_mt=int(external.get('sniper_side_clip_mt', 0) or 0),
        sniper_damage=int(external.get('sniper_damage', 0) or 0),
        sniper_projectile_speed_mt_per_sec=int(
            external.get('sniper_projectile_speed_mt_per_sec', 0) or 0),
        group_death_spawn_character=str(
            external.get('group_death_spawn_character', '') or ''),
        group_required_guard_character=str(
            external.get('group_required_guard_character', '') or ''),
        group_death_kill_character=str(
            external.get('group_death_kill_character', '') or ''),
        permanent_invulnerable=bool(
            external.get('permanent_invulnerable', False)),
        always_invisible=bool(external.get('always_invisible', False)),
        periodic_ranged_damage=int(
            external.get('periodic_ranged_damage', 0) or 0),
        periodic_ranged_min_mt=int(
            external.get('periodic_ranged_min_mt', 0) or 0),
        periodic_ranged_max_mt=int(
            external.get('periodic_ranged_max_mt', 0) or 0),
        periodic_ranged_cooldown_ms=int(
            external.get('periodic_ranged_cooldown_ms', 0) or 0),
        periodic_ranged_projectile_speed_mt_per_sec=int(
            external.get('periodic_ranged_projectile_speed_mt_per_sec', 0) or 0),
        periodic_ranged_trail_interval_ms=int(
            external.get('periodic_ranged_trail_interval_ms', 0) or 0),
        periodic_ranged_trail_delay_ms=int(
            external.get('periodic_ranged_trail_delay_ms', 0) or 0),
        periodic_ranged_area_radius_mt=int(
            external.get('periodic_ranged_area_radius_mt', 0) or 0),
        periodic_ranged_area_duration_ms=int(
            external.get('periodic_ranged_area_duration_ms', 0) or 0),
        periodic_ranged_area_speed_pct=int(
            external.get('periodic_ranged_area_speed_pct', 0) or 0),
        container_drop_hp_pct=int(external.get('container_drop_hp_pct', 0) or 0),
        container_drop_damage=int(external.get('container_drop_damage', 0) or 0),
        container_drop_radius_mt=int(
            external.get('container_drop_radius_mt', 0) or 0),
        container_drop_pushback_mt=int(
            external.get('container_drop_pushback_mt', 0) or 0),
        container_drop_delay_ms=int(
            external.get('container_drop_delay_ms', 0) or 0),
        container_drop_spawn_character=str(
            external.get('container_drop_spawn_character', '') or ''),
        container_drop_spawn_count=int(
            external.get('container_drop_spawn_count', 0) or 0),
        container_drop_spawn_radius_mt=int(
            external.get('container_drop_spawn_radius_mt', 0) or 0),
        container_drop_spawn_deploy_ms=int(
            external.get('container_drop_spawn_deploy_ms', 0) or 0),
        container_drop_threshold_offset=tuple(
            int(value) for value in external.get(
                'container_drop_threshold_offset', (0, 0))),
        container_drop_death_offset=tuple(
            int(value) for value in external.get(
                'container_drop_death_offset', (0, 0))),
        deploy_barrage_x_mt=tuple(
            int(value) for value in external.get('deploy_barrage_x_mt', ())),
        deploy_barrage_forward_mt=tuple(
            int(value) for value in external.get(
                'deploy_barrage_forward_mt', ())),
        deploy_barrage_delays_ms=tuple(
            int(value) for value in external.get(
                'deploy_barrage_delays_ms', ())),
        deploy_barrage_damage=int(
            external.get('deploy_barrage_damage', 0) or 0),
        deploy_barrage_tower_damage=int(
            external.get('deploy_barrage_tower_damage', 0) or 0),
        deploy_barrage_radius_mt=int(
            external.get('deploy_barrage_radius_mt', 0) or 0),
        deploy_barrage_pushback_mt=int(
            external.get('deploy_barrage_pushback_mt', 0) or 0),
        capture_radius_mt=int(external.get('capture_radius_mt', 0) or 0),
        capture_damage=int(external.get('capture_damage', 0) or 0),
        capture_hit_frequency_ms=int(
            external.get('capture_hit_frequency_ms', 0) or 0),
        capture_drag_delay_ms=int(
            external.get('capture_drag_delay_ms', 0) or 0),
        capture_drag_time_ms=int(external.get('capture_drag_time_ms', 0) or 0),
        capture_cooldown_ms=int(external.get('capture_cooldown_ms', 0) or 0),
        quest_interval_ms=int(external.get('quest_interval_ms', 0) or 0),
        quest_hit_advance_ms=int(external.get('quest_hit_advance_ms', 0) or 0),
        quest_start_delay_ms=int(external.get('quest_start_delay_ms', 0) or 0),
        quest_max_stacks=int(external.get('quest_max_stacks', 0) or 0),
        ability_level_adjustments=tuple(
            int(value) for value in external.get('ability_level_adjustments', ())),
        ability_level_hitpoints=tuple(
            scale_stat(int(raw.get('Hitpoints', 0) or 0), card_rarity,
                       level + int(adjustment), rarities_dict)
            for adjustment in external.get('ability_level_adjustments', ())),
        ability_level_damages=tuple(
            scale_stat(int(raw.get('Damage', 0) or 0), card_rarity,
                       level + int(adjustment), rarities_dict)
            for adjustment in external.get('ability_level_adjustments', ())),
        ability_missing_hp_heal_pct=int(
            external.get('ability_missing_hp_heal_pct', 0) or 0),
        ability_taunt_radius_mt=int(
            external.get('ability_taunt_radius_mt', 0) or 0),
        ability_taunt_area_ms=int(external.get('ability_taunt_area_ms', 0) or 0),
        ability_taunt_duration_ms=int(
            external.get('ability_taunt_duration_ms', 0) or 0),
        ability_hurl_radius_mt=int(external.get('ability_hurl_radius_mt', 0) or 0),
        ability_hurl_distance_mt=int(
            external.get('ability_hurl_distance_mt', 0) or 0),
        ability_hurl_delay_ms=int(external.get('ability_hurl_delay_ms', 0) or 0),
        ability_hurl_flight_ms=int(
            external.get('ability_hurl_flight_ms', 0) or 0),
        ability_hurl_stun_ms=int(external.get('ability_hurl_stun_ms', 0) or 0),
        ability_hurl_damage=int(external.get('ability_hurl_damage', 0) or 0),
        ability_hurl_damage_radius_mt=int(
            external.get('ability_hurl_damage_radius_mt', 0) or 0),
        ability_siege_range_mt=int(external.get('ability_siege_range_mt', 0) or 0),
        ability_siege_duration_ms=int(
            external.get('ability_siege_duration_ms', 0) or 0),
        ability_siege_lock_ms=int(external.get('ability_siege_lock_ms', 0) or 0),
        ability_siege_damage=int(external.get('ability_siege_damage', 0) or 0),
        ability_siege_tower_damage=int(
            external.get('ability_siege_tower_damage', 0) or 0),
        ability_siege_radius_mt=int(
            external.get('ability_siege_radius_mt', 0) or 0),
        ability_siege_projectile_speed_mt_per_sec=int(
            external.get('ability_siege_projectile_speed_mt_per_sec', 0) or 0),
        ability_siege_hit_speed_ms=int(
            external.get('ability_siege_hit_speed_ms', 0) or 0),
        ability_split_character=str(
            external.get('ability_split_character', '') or ''),
        ability_split_mount=str(external.get('ability_split_mount', '') or ''),
        ability_split_warp_mt=int(external.get('ability_split_warp_mt', 0) or 0),
        ability_split_warp_ms=int(external.get('ability_split_warp_ms', 0) or 0),
        ability_split_spawn_damage_delay_ms=int(
            external.get('ability_split_spawn_damage_delay_ms', 0) or 0),
        ability_split_spawn_damage=int(
            external.get('ability_split_spawn_damage', 0) or 0),
        ability_split_spawn_tower_damage=int(
            external.get('ability_split_spawn_tower_damage', 0) or 0),
        ability_split_spawn_radius_mt=int(
            external.get('ability_split_spawn_radius_mt', 0) or 0),
        ability_split_spawn_pushback_mt=int(
            external.get('ability_split_spawn_pushback_mt', 0) or 0),
        ability_reroll_range_mt=int(external.get('ability_reroll_range_mt', 0) or 0),
        ability_reroll_duration_ms=int(
            external.get('ability_reroll_duration_ms', 0) or 0),
        ability_reroll_start_delay_ms=int(
            external.get('ability_reroll_start_delay_ms', 0) or 0),
        ability_reroll_damage=int(external.get('ability_reroll_damage', 0) or 0),
        ability_reroll_tower_damage=int(
            external.get('ability_reroll_tower_damage', 0) or 0),
        ability_reroll_radius_mt=int(
            external.get('ability_reroll_radius_mt', 0) or 0),
        ability_reroll_radius_y_mt=int(
            external.get('ability_reroll_radius_y_mt', 0) or 0),
        ability_reroll_heal_missing_pct=int(
            external.get('ability_reroll_heal_missing_pct', 0) or 0),
        ability_spin_seek_radius_mt=int(
            external.get('ability_spin_seek_radius_mt', 0) or 0),
        ability_spin_pending_speed_mt_per_sec=int(
            external.get('ability_spin_pending_speed_mt_per_sec', 0) or 0),
        ability_spin_speed_mt_per_sec=int(
            external.get('ability_spin_speed_mt_per_sec', 0) or 0),
        ability_spin_duration_ms=int(
            external.get('ability_spin_duration_ms', 0) or 0),
        ability_spin_interval_ms=int(
            external.get('ability_spin_interval_ms', 0) or 0),
        ability_spin_damage=int(external.get('ability_spin_damage', 0) or 0),
        ability_spin_tower_damage=int(
            external.get('ability_spin_tower_damage', 0) or 0),
        ability_spin_radius_mt=int(
            external.get('ability_spin_radius_mt', 0) or 0),
        ability_spin_damage_reduction_pct=int(
            external.get('ability_spin_damage_reduction_pct', 0) or 0),
        last_group_death_spawn_character=str(
            external.get('last_group_death_spawn_character', '') or ''),
        ability_window_ms=int(external.get('ability_window_ms', 0) or 0),
        ability_reinforcement_character=str(
            external.get('ability_reinforcement_character', '') or ''),
        ability_reinforcement_damage=int(
            external.get('ability_reinforcement_damage', 0) or 0),
        ability_reinforcement_offsets=tuple(
            (int(row[0]), int(row[1]), int(row[2]))
            for row in external.get('ability_reinforcement_offsets', ())),
        ability_self_destruct_delay_ms=int(
            external.get('ability_self_destruct_delay_ms', 0) or 0),
        always_untargetable=bool(external.get('always_untargetable', False)),
        ability_transform_character=str(
            external.get('ability_transform_character', '') or ''),
        ability_destroy_group_character=str(
            external.get('ability_destroy_group_character', '') or ''),
        ability_post_source_death_window_ms=int(
            external.get('ability_post_source_death_window_ms', 0) or 0),
        ability_transform_lock_ms=int(
            external.get('ability_transform_lock_ms', 0) or 0),
        parry_cooldown_ms=int(external.get('parry_cooldown_ms', 0) or 0),
        parry_damage_pct=int(external.get('parry_damage_pct', 0) or 0),
        parry_stun_ms=int(external.get('parry_stun_ms', 0) or 0),
        parry_stun_delay_ms=int(external.get('parry_stun_delay_ms', 0) or 0),
        parry_damage_delay_ms=int(
            external.get('parry_damage_delay_ms', 0) or 0),
        ability_warp_to_target_speed=_warp_to_target(raw)[0],
        ability_warp_to_target_strategy=_warp_to_target(raw)[1],
        ability_warp_backward_mt=int(
            external.get('ability_warp_backward_mt', 0) or 0),
        ability_warp_delay_ms=int(
            external.get('ability_warp_delay_ms', 0) or 0),
        ability_invisible_ms=int(external.get('ability_invisible_ms', 0) or 0),
        ability_max_charges=int(external.get('ability_max_charges', 0) or 0),
        ability_cooldown_ms=int(external.get('ability_cooldown_ms', 0) or 0),
        ability_buff_delay_ms=int(external.get('ability_buff_delay_ms', 0) or 0),
        deflect_radius_mt=int(external.get('deflect_radius_mt', 0) or 0),
        ability_temporary_character=str(
            external.get('ability_temporary_character', '') or ''),
        ability_temporary_transition_ms=int(
            external.get('ability_temporary_transition_ms', 0) or 0),
        ability_temporary_duration_ms=int(
            external.get('ability_temporary_duration_ms', 0) or 0),
        ground_on_damage_hp_pct=int((starting_action.get('HealthPercentages') or [0])[0]
                                    if ground_air_action and isinstance(
                                        starting_action.get('HealthPercentages'), list)
                                    else 0),
        ground_on_attack=bool(ground_air_action and on_attack_ground == ground_group),
        ground_transition_ms=int(ground_air_action.get('TransitionDuration', 0) or 0),
        ground_character=str(ground_change_action.get('NewCharacterData', '') or ''),
        ground_landing_damage=verified_or_scaled(
            external, 'ground_landing_damage_override',
            ground_landing_area.get('Damage', 0), card_rarity, level, rarities_dict),
        ground_landing_radius_mt=int(ground_landing_area.get('Radius', 0) or 0),
        control_range_mt=int(control_action.get('Range', 0) or 0),
        control_initial_cooldown_ms=int(control_action.get('InitialCooldown', 0) or 0),
        control_cooldown_ms=int(control_action.get('Cooldown', 0) or 0),
        control_cast_ms=int(control_action.get('TrapCastTime', 0) or 0),
        control_projectile_speed_mt_per_sec=(
            int(control_projectile.get('Speed', 0) or 0) * 1000 // 60),
        control_buff=str(control_spawn.get('SpawnData', '') or ''),
        control_duration_ms=int(control_spawn.get('SpawnTime', 0) or 0),
        control_grounds_air=bool(control_air_action),
        wind_width_mt=int(wind_shape.get('Width', 0) or 0),
        wind_height_mt=int(wind_shape.get('Height', 0) or 0),
        wind_forward_offset_mt=int(attack_action.get('OffsetY', 0) or 0),
        wind_duration_ms=int(wind_area.get('LifeDuration', 0) or 0),
        wind_after_death_ms=int(attack_action.get('StayAliveAfterParentDiesDuration', 0) or 0),
        wind_ally_speed_pct=((int(wind_friend_buff.get('SpeedMultiplier', 0) or 0) - 100)
                             if int(wind_friend_buff.get('SpeedMultiplier', 0) or 0) > 0
                             else int(wind_friend_buff.get('SpeedMultiplier', 0) or 0)),
        wind_enemy_speed_pct=int(wind_enemy_buff.get('SpeedMultiplier', 0) or 0),
        wind_buff_linger_ms=max(
            int(wind_friend_action.get('SpawnTime', 0) or 0),
            int(wind_enemy_action.get('SpawnTime', 0) or 0)),
        uppercut_every_hits=int(external.get('uppercut_every_hits', 0) or 0),
        uppercut_push_mt=int(uppercut_action.get('PushBackStrength', 0) or 0),
        uppercut_flight_ms=int(uppercut_flight_action.get('Duration', 0) or 0),
        uppercut_root_ms=int(uppercut_root_action.get('ActionDuration', 0) or 0),
        reflect_damage=scale_stat(int(raw.get('ReflectedAttackDamage', 0) or 0),
                                  card_rarity, level, rarities_dict),
        reflect_radius_mt=int(raw.get('ReflectedAttackRadius', 0) or 0),
        reflect_buff=str(raw.get('ReflectedAttackBuff', '') or ''),
        reflect_buff_ms=int(raw.get('ReflectedAttackBuffDuration', 0) or 0),
        dash_min_range_mt=int(raw.get('DashMinRange', 0) or 0),
        dash_max_range_mt=int(raw.get('DashMaxRange', 0) or 0),
        dash_damage=verified_or_scaled(
            external, 'dash_damage_override',
            raw.get('DashDamage', 0), card_rarity, level, rarities_dict),
        dash_cooldown_ms=int(raw.get('DashCooldown', 0) or 0),
        dash_pushback_mt=int(raw.get('DashPushBack', 0) or 0),
        dash_radius_mt=int(raw.get('DashRadius', 0) or 0),
        burrow_speed_mt_per_sec=int(raw.get('SpawnPathfindSpeed', 0) or 0) * 1000 // 60,
        ignore_pushback=bool(raw.get('IgnorePushback', False)),
        kamikaze=bool(raw.get('Kamikaze', False)),
        lifetime_ms=(int(external['lifetime_override_ms'])
                     if external.get('lifetime_override_ms') is not None
                     else (int(raw.get('LifeTime', 0) or 0)
                           or _action_lifetime(raw))),
        # ChargeRange is hundredths of a tile; Range is millitiles.
        charge_range_mt=int(raw.get('ChargeRange', 0) or 0) * 10,
        charge_speed_multiplier=int(raw.get('ChargeSpeedMultiplier', 0) or 0),
        damage_special=scale_stat(int(raw.get('DamageSpecial', 0) or 0),
                                  card_rarity, level, rarities_dict),
        shield_hitpoints=scale_stat(int(raw.get('ShieldHitpoints', 0) or 0),
                                    card_rarity, level, rarities_dict),
        initial_shield_pct=initial_shield_pct,
        raw=raw
    )

GAMEDATA_ROOT = Path(__file__).resolve().parents[1] / "tmp" / "gamedata" / "csv_logic"

# card -> (character, count). Inferred from the card name because the data
# gives neither. Kept short and explicit; anything not here stays unresolved
# rather than being guessed at.
_SUMMON_INFERRED = {
    "three_musketeers": ("Musketeer", 3),
}

_CHARACTER_CACHE: dict = {}
_BUFF_CACHE: dict = {}
_DEATH_SPAWN_BUFF_CACHE: dict = {}
_BUFF_FLAGS_CACHE: dict = {}
_BUFF_DAMAGE_REDUCTION_CACHE: dict = {}
_BUFF_OVERHEAL_CACHE: dict = {}
_BUFF_SPAWN_CACHE: dict = {}
_BUFF_CHARGE_RANGE_CACHE: dict = {}
_BUFF_ATTRACT_CACHE: dict = {}
_BUFF_RE = re.compile(r"\[BUFF\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)", re.S)


def load_buffs(root=None) -> dict:
    """name -> (speed percent, hit speed percent), both deltas.

    Freeze is -100 on both, meaning stopped and unable to swing. An Ice
    Wizard's chill is -30. Reading them as percentages rather than as special
    cases makes freeze, slow and rage one mechanic instead of three.
    """
    if _BUFF_CACHE:
        return _BUFF_CACHE
    import re as _re
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _re.finditer(r"\[BUFF\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)",
                                  text, _re.S):
            body = match.group(2)

            def pct(key, body=body):
                # Anchored to the start of a line: searching for SpeedMultiplier
                # unanchored also matches inside HitSpeedMultiplier, so any buff
                # setting the two differently read one number twice. Archer Queen's
                # ability is +280 attack speed and -25 movement, and came out as
                # +280 to both. Freeze and the slows hid it by setting both equal.
                found = _re.search(r"^\s*" + key + r"\s*=\s*(-?\d+)", body, _re.M)
                if not found:
                    return 0
                value = int(found.group(1))
                # Positive client fields are absolute multipliers (130 means
                # 130% of base, a +30% delta); negative fields are already
                # deltas (-30 means 70% of base). The engine stores deltas.
                return value - 100 if value > 0 else value

            # A buff is three things, not two: how it changes movement, how it
            # changes attack speed, and whether it heals. A Battle Healer and
            # every evolution heal work through the same field.
            _BUFF_CACHE[match.group(1)] = (pct("SpeedMultiplier"),
                                           pct("HitSpeedMultiplier"),
                                           pct("HealPerSecond"))
    # Evolution buffs are intentionally not in the legacy BUFF namespace.
    # Parse only the dedicated file: treating every top-level TOML section as
    # a buff would misclassify characters, projectiles and action graphs.
    evo_path = directory / "character_buffs_evo.toml"
    if evo_path.exists():
        for name, body in parse_toml_file(evo_path).items():
            if not isinstance(body, dict):
                continue
            _BUFF_CACHE[name] = (
                ((int(body.get("SpeedMultiplier", 0) or 0) - 100)
                 if int(body.get("SpeedMultiplier", 0) or 0) > 0
                 else int(body.get("SpeedMultiplier", 0) or 0)),
                ((int(body.get("HitSpeedMultiplier", 0) or 0) - 100)
                 if int(body.get("HitSpeedMultiplier", 0) or 0) > 0
                 else int(body.get("HitSpeedMultiplier", 0) or 0)),
                int(body.get("HealPerSecond", 0) or 0),
            )
    return _BUFF_CACHE


def load_death_spawn_buffs(root=None) -> dict:
    """Buff -> (spawn character, count) for conversions such as Mother Witch.

    These buffs have no speed/heal fields, so treating them as ordinary timed
    stat buffs silently turns their defining on-death effect into nothing.
    """
    if _DEATH_SPAWN_BUFF_CACHE:
        return _DEATH_SPAWN_BUFF_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _BUFF_RE.finditer(text):
            body = match.group(2)
            spawn = re.search(r'^\s*DeathSpawn\s*=\s*"?([A-Za-z0-9_]+)"?', body, re.M)
            if not spawn or "DeathSpawnIsEnemy" not in body:
                continue
            count = re.search(r"^\s*DeathSpawnCount\s*=\s*(\d+)", body, re.M)
            _DEATH_SPAWN_BUFF_CACHE[match.group(1)] = (
                spawn.group(1), int(count.group(1)) if count else 1)
    return _DEATH_SPAWN_BUFF_CACHE


def load_buff_flags(root=None) -> dict:
    """Non-numeric buff semantics required by targeting (currently invisibility)."""
    if _BUFF_FLAGS_CACHE:
        return _BUFF_FLAGS_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _BUFF_RE.finditer(text):
            body = match.group(2)
            if re.search(r"^\s*Invisible\s*=\s*true\s*$", body, re.M | re.I):
                _BUFF_FLAGS_CACHE[match.group(1)] = {"invisible": True}
    return _BUFF_FLAGS_CACHE


def load_buff_damage_reductions(root=None) -> dict:
    """Buff -> percentage damage reduction, read from the client BUFF row."""
    if _BUFF_DAMAGE_REDUCTION_CACHE:
        return _BUFF_DAMAGE_REDUCTION_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _BUFF_RE.finditer(text):
            found = re.search(r"^\s*DamageReduction\s*=\s*(\d+)", match.group(2), re.M)
            if found:
                _BUFF_DAMAGE_REDUCTION_CACHE[match.group(1)] = int(found.group(1))
    evo_path = directory / "character_buffs_evo.toml"
    if evo_path.exists():
        for name, body in parse_toml_file(evo_path).items():
            if isinstance(body, dict) and body.get("DamageReduction") is not None:
                _BUFF_DAMAGE_REDUCTION_CACHE[name] = int(body["DamageReduction"])
    return _BUFF_DAMAGE_REDUCTION_CACHE


def load_buff_overheal_percentages(root=None) -> dict:
    """Buff -> maximum hitpoints percentage allowed by healing.

    Ordinary healing caps at 100%. Evolved Bats explicitly declares 200%, so
    this loader only records source rows that opt into overhealing.
    """
    if _BUFF_OVERHEAL_CACHE:
        return _BUFF_OVERHEAL_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    evo_path = directory / "character_buffs_evo.toml"
    if evo_path.exists():
        for name, body in parse_toml_file(evo_path).items():
            if isinstance(body, dict) and body.get("AllowedOverHealPerc") is not None:
                _BUFF_OVERHEAL_CACHE[name] = int(body["AllowedOverHealPerc"])
    return _BUFF_OVERHEAL_CACHE


def load_buff_spawns(root=None) -> dict:
    """Buff -> (character, count, interval) for on-hit evo duplication."""
    if _BUFF_SPAWN_CACHE:
        return _BUFF_SPAWN_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    evo_path = directory / "character_buffs_evo.toml"
    if evo_path.exists():
        for name, body in parse_toml_file(evo_path).items():
            if not isinstance(body, dict) or not body.get("SpawnObject"):
                continue
            count = int(body.get("SpawnNumber", 1) or 1)
            limit = int(body.get("SpawnLimit", count) or count)
            _BUFF_SPAWN_CACHE[name] = (
                str(body["SpawnObject"]), min(count, limit),
                int(body.get("SpawnInterval", 0) or 0),
            )
    return _BUFF_SPAWN_CACHE


def load_buff_attractions(root=None) -> dict:
    """Buff -> `AttractPercentage`, a pull speed in percent of one tile per second.

    Evolved Valkyrie's whole evolution is here and nothing read it: every swing
    spawns `Valkyrie_MiniTornado_EV1`, a half-second area whose buff declares
    `AttractPercentage = 300`, dragging what she hits toward her. The published
    description is exactly that - "Evolved Valkyrie draws all enemies towards
    her with each swing" - and in the simulator she just swung.

    Both the evolution table and the base one, because the evo buff inherits
    `Base = "Tornado"` and only overrides the number.
    """
    if _BUFF_ATTRACT_CACHE:
        return _BUFF_ATTRACT_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for filename in ("character_buffs.toml", "character_buffs_evo.toml"):
        path = directory / filename
        if not path.exists():
            continue
        for name, body in parse_toml_file(path).items():
            if isinstance(body, dict) and body.get("AttractPercentage") is not None:
                _BUFF_ATTRACT_CACHE[name] = int(body["AttractPercentage"])
    return _BUFF_ATTRACT_CACHE


def load_buff_charge_ranges(root=None) -> dict:
    """Buff -> charge range in the client's hundredths-of-a-tile unit."""
    if _BUFF_CHARGE_RANGE_CACHE:
        return _BUFF_CHARGE_RANGE_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    evo_path = directory / "character_buffs_evo.toml"
    if evo_path.exists():
        for name, body in parse_toml_file(evo_path).items():
            if isinstance(body, dict) and body.get("OverrideChargeRange") is not None:
                _BUFF_CHARGE_RANGE_CACHE[name] = int(body["OverrideChargeRange"])
    return _BUFF_CHARGE_RANGE_CACHE



_ABILITY_RE = re.compile(r"\[ABILITY\.([A-Za-z0-9_]+)\](.*?)(?=\n\[|\Z)", re.S)
_ABILITY_CACHE: dict = {}
_ABILITY_DETAILS_CACHE: dict = {}


def load_abilities(root=None) -> dict:
    """name -> (buff_time_ms, cast_time_ms, mana_cost).

    Champion abilities are ordinary buffs with a price. ArcherQueenRapid is
    HitSpeedMultiplier +280 and SpeedMultiplier -25 for 3500ms at one elixir;
    Monk's Deflect runs 4000ms. Reading the ABILITY section for the price and
    the BUFF section for the effect means champions need no special case.
    """
    if _ABILITY_CACHE:
        return _ABILITY_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for match in _ABILITY_RE.finditer(text):
            body = match.group(2)

            def num(key, body=body):
                # Anchor at the start of a line. Without it, searching for
                # SpeedMultiplier also matches inside HitSpeedMultiplier, so a
                # buff that sets the two differently - Archer Queen's ability is
                # +280 attack speed and -25 movement - read the same number twice.
                # Freeze and the slows hid this by setting both to one value.
                found = re.search(r"^\s*" + key + r"\s*=\s*(-?\d+)", body, re.M)
                return int(found.group(1)) if found else 0

            _ABILITY_CACHE[match.group(1)] = (num("BuffTime"), num("CastTime"),
                                              num("ManaCost"))
    # Two abilities are declared only in character_abilities.csv and in no TOML
    # at all - SuperHogJump and MegaDeflect, both party-mode cards - so they
    # were invisible here and their cards could not use them. The TOML wins
    # where both exist.
    table = directory / "character_abilities.csv"
    if table.exists():
        with open(table, encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        if rows:
            header = rows[0]
            index = {key: header.index(key) for key in
                     ("Name", "BuffTime", "CastTime", "ManaCost")
                     if key in header}
            for row in rows[2:]:
                if not row or not row[index["Name"]]:
                    continue
                name = row[index["Name"]]
                if name in _ABILITY_CACHE or "NOTINUSE" in name:
                    continue

                def value(key, row=row):
                    if key not in index:
                        return 0
                    try:
                        return int(row[index[key]] or 0)
                    except (TypeError, ValueError):
                        return 0

                _ABILITY_CACHE[name] = (value("BuffTime"), value("CastTime"),
                                        value("ManaCost"))
    return _ABILITY_CACHE


def load_ability_details(root=None) -> dict:
    """Source-declared effects reachable from an ability's activation graph.

    The ability row alone is not always the effect.  Hero Knight, for example,
    points at an ActionGroup that re-arms its shield and spawns a five-second
    self buff.  Walking the explicit action edges captures those facts without
    pretending that arbitrary action classes are supported.
    """
    if _ABILITY_DETAILS_CACHE:
        return _ABILITY_DETAILS_CACHE
    directory = Path(root) if root else Path(GAMEDATA_ROOT)
    for path in directory.rglob("*.toml"):
        try:
            data = parse_toml_file(path)
        except Exception:
            continue
        actions = data.get("ACTION", {})
        for ability_name, ability in data.get("ABILITY", {}).items():
            if not isinstance(ability, dict):
                continue
            details = {}
            for key in ("DashRange", "Buff"):
                if ability.get(key) not in (None, ""):
                    details[key] = ability[key]

            seen: set[str] = set()
            aeos = data.get("AEO", {})

            # A summon the ability names outright rather than reaching through
            # an action graph. Skeleton King is the one that does this, and it
            # is why his ability did nothing at all: the loader looked for a
            # buff, a dash or a guard, found none of them, and the activation
            # gate refused a champion whose whole card is the summon.
            #
            # Everything the mechanic needs is declared. The ability says
            # `ResurrectBaseCount = 6` skeletons and `SpawnLimit = 16`; the
            # graveyard it points at says where and how fast they arrive.
            summon_aeo = aeos.get(str(ability.get("AreaEffectObject", "") or ""), {})
            if isinstance(summon_aeo, dict) and summon_aeo.get("SpawnCharacter"):
                details["SummonCharacter"] = str(summon_aeo["SpawnCharacter"])
                details["SummonBaseCount"] = int(
                    ability.get("ResurrectBaseCount", 0) or 0)
                details["SummonMaxCount"] = int(ability.get("SpawnLimit", 0) or 0)
                for key, source_key in (
                        ("SummonIntervalMs", "SpawnInterval"),
                        ("SummonInitialDelayMs", "SpawnInitialDelay"),
                        ("SummonDeployMs", "SpawnTime"),
                        ("SummonMinRadius", "SpawnMinRadius"),
                        ("SummonMaxRadius", "SpawnMaxRadius")):
                    if summon_aeo.get(source_key) is not None:
                        details[key] = int(summon_aeo[source_key] or 0)
            def walk_inline(action: dict) -> None:
                if not isinstance(action, dict):
                    return
                # A decoy placed where the caster stands. Elite Archer Hero
                # leaves `EliteArcherHero_Dummy` behind while he slips away,
                # and only the `ActionSpawnGuard` shape below was read - so his
                # ability had no declared effect at all and the activation gate
                # offered it and then refused it.
                if (action.get("ClassType") == "ActionSpawnToLocation"
                        and action.get("SpawnType") == "CharacterType"
                        and action.get("SpawnData")):
                    details["DeployCharacter"] = str(action["SpawnData"])
                    details["DeployForward"] = int(
                        action.get("RelativeY", 0) or 0) * 1000
                    if action.get("DeployTime") is not None:
                        details["DeployTime"] = int(action["DeployTime"] or 0)
                # Parallel arrows: two more beside the ordinary shot, 1500
                # apart, for as long as the window lasts.
                if action.get("ClassType") == "ActionCreateParallelProjectiles":
                    details["ExtraProjectiles"] = int(
                        action.get("ProjectileCount", 0) or 0)
                    details["ExtraProjectileSpacing"] = int(
                        action.get("ProjectileDistance", 0) or 0)
                    details["ExtraProjectileType"] = str(
                        action.get("ProjectileType", "") or "")
                # How long an ability's state lasts when it is a window rather
                # than a buff - the seven seconds of triple shot.
                if (action.get("ClassType") == "ActionWithDuration"
                        and action.get("ActionDuration") is not None):
                    details["ShotWindow"] = int(action["ActionDuration"] or 0)
                if action.get("ClassType") == "ActionSpawnGuard" and action.get("SpawnData"):
                    details["SpawnCharacter"] = str(action["SpawnData"])
                    for key in ("ActionDelay", "PushBackDamage", "PushBackRadius",
                                "PushBackStrength", "AppearBehindAtDistance"):
                        if action.get(key) is not None:
                            details[key] = int(action[key] or 0)
                if (action.get("ClassType") == "ActionSpawn"
                        and action.get("SpawnType") == "AreaEffectType"):
                    aeo = aeos.get(str(action.get("SpawnData", "")), {})
                    if isinstance(aeo, dict) and aeo.get("OnStartingAction"):
                        walk(str(aeo["OnStartingAction"]))
                nested = action.get("NextAction")
                if isinstance(nested, dict):
                    walk_inline(nested)
            def walk(action_name: str) -> None:
                if action_name in seen:
                    return
                seen.add(action_name)
                action = actions.get(action_name, {})
                if not isinstance(action, dict):
                    return
                walk_inline(action)
                if (action.get("ClassType") == "ActionSpawn"
                        and action.get("SpawnType") == "BuffType"):
                    if action.get("SpawnData"):
                        details["Buff"] = str(action["SpawnData"])
                    if action.get("SpawnTime") is not None:
                        details["BuffTime"] = int(action["SpawnTime"] or 0)
                if action.get("ClassType") == "ActionSetShield":
                    details["ShieldPercent"] = int(action.get("ShieldPercent", 0) or 0)
                children = action.get("SubActions", [])
                if isinstance(children, str):
                    children = [children]
                for child in children:
                    walk(str(child))
            root_action = ability.get("OnActivationAction")
            if root_action:
                walk(str(root_action))
            if details:
                _ABILITY_DETAILS_CACHE[ability_name] = details
    table = directory / "character_abilities.csv"
    if table.exists():
        with open(table, encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        if rows:
            header = rows[0]
            wanted = {"DashRange": "DashRange", "Buff": "Buff",
                      "PendingBuff": "Buff"}
            name_at = header.index("Name") if "Name" in header else 0
            for row in rows[2:]:
                if not row or not row[name_at]:
                    continue
                name = row[name_at]
                if name in _ABILITY_DETAILS_CACHE or "NOTINUSE" in name:
                    continue
                details = {}
                for column, key in wanted.items():
                    if column not in header:
                        continue
                    raw_value = row[header.index(column)]
                    if raw_value in (None, ""):
                        continue
                    details.setdefault(
                        key, int(raw_value) if raw_value.lstrip("-").isdigit()
                        else raw_value)
                if details:
                    _ABILITY_DETAILS_CACHE[name] = details
    return _ABILITY_DETAILS_CACHE


def load_characters(level: int = 11) -> dict:
    """Every character in the data, keyed snake_case, playable or not.

    Death spawns and hut spawns name units that have no card - Golemite,
    BalloonBomb, LavaPups - so looking them up in the card table always failed
    and the spawn was silently skipped.
    """
    if level not in _CHARACTER_CACHE:
        load_gamedata(level=level)
    return _CHARACTER_CACHE.get(level, {})


def load_gamedata(level: int = 11, root: Path | None = None) -> dict[str, CardSpec]:
    # Every other loader in this module already resolves through GAMEDATA_ROOT,
    # which is relative to the file. This one carried an absolute path into one
    # developer's home directory, so the simulator ran on exactly one machine.
    if root is None:
        root = GAMEDATA_ROOT
    root = Path(root)
    # Missing data does not raise on its own, which is the dangerous part: with
    # no rarities.csv, `scale_stat` falls through to compounding the default
    # 110% step and returns stats about 1.3% off the shipped table. Silently
    # slightly-wrong numbers are this project's signature failure, so both of
    # these are made loud.
    if not root.is_dir():
        raise FileNotFoundError(
            f"no extracted client data at {root}; every card stat is read "
            f"from there")

    rarities_dict = {}
    rarities_csv = root / "rarities.csv"
    if not rarities_csv.exists():
        raise FileNotFoundError(
            f"{rarities_csv} is missing; level scaling comes from its "
            f"PowerLevelMultipliers table and would silently fall back to a "
            f"flat 110% step")
    if rarities_csv.exists():
        with open(rarities_csv, encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            next(reader)
            current = None
            for row in reader:
                if not row:
                    continue
                d = dict(zip(headers, row))
                name = d.get('Name')
                if name:
                    current = name
                    rarities_dict[name] = {
                        'RelativeLevel': int(d.get('RelativeLevel') or 0),
                        'TournamentLevelIndex': int(d.get('TournamentLevelIndex') or 0),
                        'PowerLevelMultiplier': int(d.get('PowerLevelMultiplier') or 110),
                        'PowerLevelMultipliers': []
                    }
                if current and d.get('PowerLevelMultiplier'):
                    rarities_dict[current]['PowerLevelMultipliers'].append(
                        int(d['PowerLevelMultiplier']))

    proj_dict = {}
    csv_projectile_defs = {}
    proj_csv = root / "projectiles.csv"
    if proj_csv.exists():
        with open(proj_csv, encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            next(reader)
            for row in reader:
                if not row or not row[0]: continue
                d = dict(zip(headers, row))
                name = d.get('Name')
                if name:
                    rad = int(d.get('Radius') or 0)
                    if not rad: rad = int(d.get('AreaDamageRadius') or 0)
                    proj_dict[name] = rad
                    parsed = {}
                    for key, value in d.items():
                        value = value.strip()
                        if not value:
                            continue
                        if value.lower() in {"true", "false"}:
                            parsed[key] = value.lower() == "true"
                        else:
                            try:
                                parsed[key] = int(value)
                            except ValueError:
                                parsed[key] = value
                    csv_projectile_defs[name] = parsed

    raw_units = {}
    ext_character_bases = {}
    ext_character_overrides = {}
    ext_projectile_overrides = {}
    hero_cards: dict[str, dict] = {}
    evolved_spell_overlays: dict[str, dict] = {}
    projectile_defs: dict[str, dict] = dict(csv_projectile_defs)
    search_paths = []
    char_dir = root / "characters"
    if char_dir.exists() and char_dir.is_dir():
        # Hero forms live in characters/hero_form/, not alongside ordinary
        # troops.  Recursing is required to see their SPELL_HERO declarations
        # and EXT combat overlays.
        search_paths.extend(char_dir.rglob("*.toml"))
    build_dir = root / "buildings"
    if build_dir.exists() and build_dir.is_dir():
        search_paths.extend(build_dir.glob("*.toml"))

    for p in search_paths:
        data = parse_toml_file(p)
        for evolved_name, overlay in data.get('SPELL_EVOLVED', {}).items():
            if isinstance(overlay, dict):
                evolved_spell_overlays[evolved_name] = dict(overlay)
        action_table = data.get('ACTION', {})

        def find_character_change(node, seen: set[str] | None = None):
            """Follow semantic action groups to a character-data swap."""
            if seen is None:
                seen = set()
            if isinstance(node, str):
                if node in seen:
                    return None
                seen.add(node)
                node = action_table.get(node, {})
            if not isinstance(node, dict):
                return None
            if node.get('ClassType') == 'ActionChangeGameObjectData':
                return node.get('NewCharacterData')
            children = []
            for key in ('Actions', 'SubActions'):
                value = node.get(key, [])
                children.extend(value if isinstance(value, list) else [value])
            next_action = node.get('NextAction')
            if next_action:
                children.append(next_action)
            for child in children:
                replacement = find_character_change(child, seen)
                if replacement:
                    return replacement
            return None

        projectile_defs.update(data.get('PROJECTILE', {}))
        for ext_name, ext in data.get('EXT', {}).items():
            base = str(ext.get('Base', '') or '')
            if base.startswith('CHARACTER.') or base.startswith('BUILDING.'):
                ext_character_bases[to_snake_case(ext_name)] = to_snake_case(base.split('.', 1)[1])
                # An EXT is a client-side overlay, not a mere synonym.  Hero
                # forms such as KnightHero inherit Knight but override shield,
                # ability and visual/action data.  Preserve that overlay and
                # materialise it only after every base character is loaded.
                overlay = dict(ext)
                overlay['_ACTION_DATA'] = data.get('ACTION', {})
                overlay['_AEO_DATA'] = data.get('AEO', {})
                overlay['_EXT_DATA'] = data.get('EXT', {})
                overlay['_BUFF_DATA'] = data.get('BUFF', {})
                overlay['_SHAPE_DATA'] = data.get('SHAPE', {})
                overlay['_RESOLVER_DATA'] = data.get('TARGET_RESOLVER', {})
                ext_character_overrides[ext_name] = overlay
            elif base.startswith('PROJECTILE.'):
                ext_projectile_overrides[ext_name] = dict(ext)
        for hero_name, hero in data.get('SPELL_HERO', {}).items():
            if isinstance(hero, dict):
                hero_cards[hero_name] = dict(hero)
        for category in ['CHARACTER', 'BUILDING']:
            if category in data:
                for k, v in data[category].items():
                    if 'PROJECTILE' in data:
                        v['_PROJECTILE_DATA'] = data['PROJECTILE']
                    v['_ACTION_DATA'] = data.get('ACTION', {})
                    v['_AEO_DATA'] = data.get('AEO', {})
                    v['_EXT_DATA'] = data.get('EXT', {})
                    v['_BUFF_DATA'] = data.get('BUFF', {})
                    v['_SHAPE_DATA'] = data.get('SHAPE', {})
                    # A resolver says which target an action picks and how
                    # it breaks ties. Without it a warp knows its speed
                    # and not where it is going.
                    v['_RESOLVER_DATA'] = data.get('TARGET_RESOLVER', {})
                    # A deployment AEO names an action which spawns this
                    # character.  Keep the AEO on the character so the battle
                    # layer can execute the real deployment shock (Electro
                    # Wizard / Ice Wizard) without a card-name special case.
                    # The direct form: a character naming its own emergence
                    # area outright. Goblin Drill declares
                    # `SpawnAreaObject = "GoblinDrillDamage"` - 33 damage in a
                    # two-tile radius with a pushback, and no damage to crown
                    # towers - and only the indirect Electro Wizard shape below
                    # was ever read, so the drill surfaced silently and the
                    # swarm it was dropped on took nothing.
                    # A burrower is two rows: the digging form the card
                    # actually places, and the thing it becomes when it
                    # surfaces. `SpawnPathfindMorph` names the second, and the
                    # emergence damage is declared there - so the form the
                    # simulator instantiates had none of it.
                    named_area = v.get('SpawnAreaObject')
                    morph = v.get('SpawnPathfindMorph')
                    if not named_area and isinstance(morph, str) and morph:
                        # Across categories: the digging form is a CHARACTER
                        # and what it surfaces as is a BUILDING.
                        for other in ('CHARACTER', 'BUILDING'):
                            surfaced = data.get(other, {}).get(morph, {})
                            if isinstance(surfaced, dict) and surfaced.get(
                                    'SpawnAreaObject'):
                                named_area = surfaced['SpawnAreaObject']
                                break
                    if isinstance(named_area, str) and named_area:
                        aeo = data.get('AEO', {}).get(named_area)
                        if isinstance(aeo, dict) and aeo:
                            v['_SPAWN_AREA_DATA'] = aeo
                    for aeo in data.get('AEO', {}).values():
                        if '_SPAWN_AREA_DATA' in v:
                            break
                        action_name = aeo.get('OnStartingAction')
                        if not isinstance(action_name, str):
                            continue
                        action = data.get('ACTION', {}).get(action_name, {})
                        if action.get('SpawnData') == k:
                            v['_SPAWN_AREA_DATA'] = aeo
                            break
                    # Character transformations are represented by a health
                    # threshold action followed by ActionChangeGameObjectData
                    # (Cannon Cart -> BrokenCannon). Preserve that graph edge
                    # in the spec instead of keying off a card name.
                    for trigger_name, trigger in data.get('ACTION', {}).items():
                        if v.get('OnStartingAction') != trigger_name:
                            continue
                        if trigger.get('ClassType') != 'ActionRunActionAtHealth':
                            continue
                        replacement = find_character_change(trigger)
                        values = trigger.get('HealthPercentages', [])
                        if isinstance(values, int):
                            values = [values]
                        if replacement and values:
                            v['_TRANSFORM_DATA'] = {
                                'HealthPercent': int(values[0]),
                                'Character': str(replacement),
                            }
                    raw_units[k] = v

    # A substantial number of spawn-only combat objects exist only in the
    # canonical CSV tables. Goblin Barrel Evolution's `GoblinDummy` is one;
    # omitting this table made the exact name fall through to the unrelated
    # Hero `Goblin_dummy` EXT after snake-case normalization.
    def csv_scalar(value: str):
        value = value.strip()
        if not value:
            return None
        if value.lower() in {"true", "false"}:
            return value.lower() == "true"
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value

    for csv_name in ("characters.csv", "buildings.csv"):
        csv_path = root / csv_name
        if not csv_path.exists():
            continue
        with csv_path.open(encoding="utf-8") as handle:
            reader = csv.reader(handle)
            headers = next(reader)
            next(reader, None)
            for row in reader:
                if not row or not row[0]:
                    continue
                values = {key: csv_scalar(value)
                          for key, value in zip(headers, row) if value.strip()}
                raw_name = str(values.get("Name", "") or "")
                if not raw_name or raw_name in raw_units:
                    continue
                values['_PROJECTILE_DATA'] = projectile_defs
                values['_ACTION_DATA'] = {}
                raw_units[raw_name] = values

    evolved_overlay_path = root / "spells_evolved.toml"
    if evolved_overlay_path.exists():
        for evolved_name, overlay in parse_toml_file(
                evolved_overlay_path).items():
            if isinstance(overlay, dict):
                evolved_spell_overlays.setdefault(evolved_name, {}).update(overlay)

    # Resolve projectile inheritance before character EXT rows. Newer cards
    # commonly declare their combat projectile as EXT.PROJECTILE rather than
    # a standalone PROJECTILE block (evolved Hunter is one), and dropping
    # that overlay turns a valid attack into zero damage.
    unresolved_projectiles = dict(ext_projectile_overrides)
    while unresolved_projectiles:
        progressed = False
        for ext_name, overlay in list(unresolved_projectiles.items()):
            base_ref = str(overlay.get('Base', '') or '')
            base_name = base_ref.split('.', 1)[1] if '.' in base_ref else ''
            base = projectile_defs.get(base_name)
            if base is None:
                continue
            projectile_defs[ext_name] = _merge_character_overlay(base, overlay)
            del unresolved_projectiles[ext_name]
            progressed = True
        if not progressed:
            break

    # Resolve character EXT inheritance after the complete client table has
    # been collected; a hero file may precede its base character on disk.
    for ext_name, overlay in ext_character_overrides.items():
        base_ref = str(overlay.get('Base', '') or '')
        base_name = base_ref.split('.', 1)[1] if '.' in base_ref else ''
        base = raw_units.get(base_name)
        if base is None:
            continue
        resolved = _merge_character_overlay(base, overlay)
        inherited_projectiles = dict(projectile_defs)
        inherited_projectiles.update(base.get('_PROJECTILE_DATA', {}))
        resolved['_PROJECTILE_DATA'] = inherited_projectiles
        raw_units[ext_name] = resolved

    # Every unit must be able to resolve an EXT projectile declared elsewhere
    # in the same source file.  BUILDING rows were captured before EXT
    # inheritance was materialised, so spawned objects such as Hero
    # Musketeer's turret retained only the file's literal PROJECTILE rows and
    # consequently fired its `MusketeerTurret_Projectile` for zero damage.
    # Keep local declarations authoritative while filling inherited/global
    # definitions underneath them.
    for raw in raw_units.values():
        local_projectiles = raw.get('_PROJECTILE_DATA', {})
        merged_projectiles = dict(projectile_defs)
        if isinstance(local_projectiles, dict):
            merged_projectiles.update(local_projectiles)
        raw['_PROJECTILE_DATA'] = merged_projectiles

    # Older evolutions are compact overlays in characters_evo.toml rather
    # than CHARACTER/EXT blocks in per-card files. They are real deployable
    # character data and were previously discarded with every _EV1 card row.
    # Building evolutions live in their own file with exactly the same overlay
    # shape. Reading only the character one left Mortar Evolution and Tesla
    # Evolution with no character data at all, so both card rows were dropped
    # and the simulator reported 40 evolutions while the client ships 42 - the
    # same shape as the spell table that named two files which did not exist.
    evo_data = {}
    for evo_filename in ("characters_evo.toml", "buildings_evo.toml"):
        evo_file = root / evo_filename
        if evo_file.exists():
            evo_data.update(parse_toml_file(evo_file))
    evo_characters = root / "characters_evo.toml"
    if evo_data:
        evo_actions_path = root / "actions.toml"
        evo_actions = (parse_toml_file(evo_actions_path)
                       if evo_actions_path.exists() else {})
        evo_aeo_path = root / "area_effect_objects_evo.toml"
        evo_aeos = (parse_toml_file(evo_aeo_path)
                    if evo_aeo_path.exists() else {})
        evo_projectiles_path = root / "projectiles_evo.toml"
        evo_projectile_overlays = (parse_toml_file(evo_projectiles_path)
                                   if evo_projectiles_path.exists() else {})
        evo_projectiles = dict(projectile_defs)
        for projectile_name, projectile_overlay in evo_projectile_overlays.items():
            if not isinstance(projectile_overlay, dict):
                continue
            base_projectile = projectile_defs.get(
                str(projectile_overlay.get('Base', '') or ''), {})
            evo_projectiles[projectile_name] = _merge_character_overlay(
                base_projectile, projectile_overlay)
        for evo_name, overlay in evo_data.items():
            if not isinstance(overlay, dict):
                continue
            base_name = str(overlay.get("Base", "") or "")
            base = raw_units.get(base_name)
            if base is None:
                continue
            resolved = _merge_character_overlay(base, overlay)
            resolved['_ACTION_DATA'] = evo_actions
            resolved['_AEO_DATA'] = evo_aeos
            inherited_projectiles = dict(base.get('_PROJECTILE_DATA', {}))
            inherited_projectiles.update(evo_projectiles)
            resolved['_PROJECTILE_DATA'] = inherited_projectiles
            raw_units[evo_name] = resolved

    # Every character in the files, not just the playable ones. Spawned units
    # like Golemite and BalloonBomb never appear as cards, so a Golem could not
    # leave anything behind until these were reachable.
    characters = {}
    for raw_name, raw_u in raw_units.items():
        try:
            spec = build_unit_spec(raw_name, raw_u, level,
                                   str(raw_u.get('Rarity', 'Common')),
                                   rarities_dict, proj_dict)
        except Exception:
            continue
        # Preserve the exact client identifier as well as a convenient card
        # key. Exact lookup disambiguates names such as GoblinDummy (evolution
        # decoy) and Goblin_dummy (Hero banner unit), which intentionally
        # collapse to the same snake-case spelling.
        characters[raw_name] = spec
        characters.setdefault(to_snake_case(raw_name), spec)
    # EXT rows can customise a normal character for one action (for example
    # GoblinCurseGoblin bases on CHARACTER.Goblin). Alias them to their
    # declared base rather than failing conversion because no standalone
    # CHARACTER row exists.
    for ext_name, base_name in ext_character_bases.items():
        if ext_name not in characters and base_name in characters:
            characters[ext_name] = characters[base_name]
    _CHARACTER_CACHE[level] = characters

    cards = {}
    for filename in ["spells.csv", "spells_characters.csv", "spells_buildings.csv",
                     "spells_other.csv", "spells_evolved.csv"]:
        p = root / filename
        if not p.exists(): continue
        with open(p, encoding='utf-8') as f:
            reader = csv.reader(f)
            headers = next(reader)
            next(reader)
            for row in reader:
                if not row or not row[0]: continue
                d = dict(zip(headers, row))
                name = d.get('Name')
                if not name: continue
                n_lower = name.lower()
                is_evolution = filename == "spells_evolved.csv"
                if is_evolution and str(d.get('NotVisible', '')).lower() == 'true':
                    continue
                if (not is_evolution and
                        (n_lower.endswith('_ev1') or n_lower.endswith('_evo')
                         or 'rework' in n_lower)):
                    continue
                    
                snake_name = to_snake_case(name)
                cost = int(d.get('ManaCost') or 0)
                rarity = d.get('Rarity', 'Common')
                summon_character = d.get('SummonCharacter')
                
                # A few cards name neither a summon nor a count anywhere in
                # the files. These are inferences from the card's own name, not
                # data, and are listed rather than derived so that is obvious.
                if not summon_character and snake_name in _SUMMON_INFERRED:
                    summon_character, inferred_count = _SUMMON_INFERRED[snake_name]
                    if not d.get('SummonNumber'):
                        d['SummonNumber'] = str(inferred_count)

                # Some cards leave SummonCharacter blank and rely on the
                # character sharing the card's own name - the Ice Wizard and
                # Electro Wizard both do, and both were loading as spells with
                # no unit at all, which is why they showed up in the spell list.
                if not summon_character and name in raw_units:
                    summon_character = name

                if not summon_character:
                    unit = None
                else:
                    raw_u = raw_units.get(summon_character)
                    if not raw_u:
                        continue
                    # Clean up _PROJECTILE_DATA from raw_u before storing if we want, but it's fine.
                    unit = build_unit_spec(summon_character, raw_u, level, rarity, rarities_dict, proj_dict)
                    # Which file the card was declared in is the client's own
                    # statement of what kind of card it is, and it is the only
                    # authority available: whether a card is a building was
                    # otherwise inferred from Speed == 0, which is true of most
                    # buildings and not all of them. The reworked Furnace and
                    # Goblin Drill both carry a real Speed in their character
                    # section, so the inference classed them as troops - they
                    # walked up the lane, took no building-targeted aggro and
                    # were not solid.
                    if filename == "spells_buildings.csv":
                        unit = replace(unit, from_building_card=True)

                summon_number = int(d.get('SummonNumber') or 1)
                secondary_character = str(d.get('SummonCharacterSecond') or '')
                secondary_unit = None
                if secondary_character:
                    secondary_raw = raw_units.get(secondary_character)
                    if secondary_raw:
                        secondary_unit = build_unit_spec(
                            secondary_character, secondary_raw, level, rarity,
                            rarities_dict, proj_dict)
                evolved_overlay = evolved_spell_overlays.get(name, {})
                extra_names = evolved_overlay.get('SummonCharactersList', [])
                if isinstance(extra_names, str):
                    extra_names = [extra_names]
                extra_x = evolved_overlay.get('SummonCharactersOffsetsX', [])
                extra_y = evolved_overlay.get('SummonCharactersOffsetsY', [])
                if not isinstance(extra_x, list):
                    extra_x = [extra_x]
                if not isinstance(extra_y, list):
                    extra_y = [extra_y]
                additional_summons = []
                for extra_index, extra_name in enumerate(extra_names):
                    extra_raw = raw_units.get(str(extra_name))
                    if extra_raw is None:
                        continue
                    additional_summons.append((
                        build_unit_spec(str(extra_name), extra_raw, level,
                                        rarity, rarities_dict, proj_dict),
                        int(extra_x[extra_index] if extra_index < len(extra_x) else 0),
                        int(extra_y[extra_index] if extra_index < len(extra_y) else 0),
                    ))
                deploy = int(d.get('CustomDeployTime') or 0)
                if not deploy and unit:
                    deploy = unit.deploy_time_ms
                    
                cards[snake_name] = CardSpec(
                    name=snake_name,
                    cost=cost,
                    rarity=rarity,
                    unit=unit,
                    summon_number=summon_number,
                    summon_radius_mt=int(d.get('SummonRadius') or 0),
                    summon_deploy_delay_ms=int(d.get('SummonDeployDelay') or 0),
                    deploy_time_ms=deploy,
                    form=("Evolution" if is_evolution
                          else str(d.get('CardForm', '') or '')),
                    evolution_cycles=(int(d.get('DarkElixirCost') or 0)
                                      if is_evolution else 0),
                    secondary_unit=secondary_unit,
                    secondary_summon_number=(
                        int(d.get('SummonCharacterSecondCount') or 1)
                        if secondary_unit else 0),
                    secondary_summon_deploy_delay_ms=int(
                        d.get('SummonDeployDelaySecond') or 0),
                    # Group rows express this as SummonWidth=-1000. Public
                    # deployment documentation confirms that Goblinstein's
                    # Doctor is one tile closer to arena centre.
                    secondary_offset_toward_centre_mt=abs(int(
                        d.get('SummonWidth') or 0)),
                    additional_summons=tuple(additional_summons),
                )

    # Hero forms are declared in the client as SPELL_HERO blocks rather than
    # as ordinary CSV spell rows.  They name their actual EXT character (for
    # example KnightHero), so loading the CSV placeholder alone would deploy a
    # plain Knight and erase the hero's shield/ability graph.
    for name, hero in hero_cards.items():
        summon_character = str(hero.get('SummonCharacter', '') or '')
        raw_u = raw_units.get(summon_character)
        hero_group_names = hero.get('SummonCharactersList', [])
        if isinstance(hero_group_names, str):
            hero_group_names = [hero_group_names]
        # Group heroes can ship an empty SummonCharacter and list their
        # gameplay objects separately. Select the real combat body as primary;
        # purely visual dummies are deliberately not arena entities.
        if raw_u is None and hero_group_names:
            candidates = [str(value) for value in hero_group_names
                          if 'visual_dummy' not in str(value).lower()]
            playable = [value for value in candidates
                        if 'passive' not in value.lower()]
            if playable:
                summon_character = playable[0]
                raw_u = raw_units.get(summon_character)
        # Hero Barbarian Barrel is itself a projectile card. Its combatant is
        # named by LinkedChampionCharacter and appears only when the rolling
        # projectile ends, so representing it as an immediately deployed unit
        # would erase the first barrel sweep. Keep it spell-shaped here; the
        # spell loader binds the base barrel trajectory to the linked Hero.
        if raw_u is None and hero.get('LinkedChampionCharacter'):
            snake_name = to_snake_case(name)
            base_name = snake_name.removesuffix('_hero')
            base_card = cards.get(base_name)
            if base_card is not None:
                cards[snake_name] = CardSpec(
                    name=snake_name,
                    cost=base_card.cost,
                    rarity=base_card.rarity,
                    unit=None,
                    summon_number=0,
                    summon_radius_mt=0,
                    summon_deploy_delay_ms=0,
                    deploy_time_ms=0,
                    form=str(hero.get('CardForm', 'HeroForm') or 'HeroForm'),
                )
            continue
        if raw_u is None:
            continue
        rarity = str(hero.get('Rarity', raw_u.get('Rarity', 'Common')) or 'Common')
        unit = build_unit_spec(summon_character, raw_u, level, rarity,
                               rarities_dict, proj_dict)
        snake_name = to_snake_case(name)
        base_card = cards.get(snake_name.removesuffix('_hero'))
        additional_summons = []
        group_x = hero.get('SummonCharactersOffsetsX', [])
        group_y = hero.get('SummonCharactersOffsetsY', [])
        if not isinstance(group_x, list):
            group_x = [group_x]
        if not isinstance(group_y, list):
            group_y = [group_y]
        for group_index, extra_name in enumerate(hero_group_names):
            extra_name = str(extra_name)
            if (extra_name == summon_character
                    or 'visual_dummy' in extra_name.lower()):
                continue
            extra_raw = raw_units.get(extra_name)
            if extra_raw is None:
                continue
            additional_summons.append((
                build_unit_spec(extra_name, extra_raw, level, rarity,
                                rarities_dict, proj_dict),
                int(group_x[group_index] if group_index < len(group_x) else 0),
                int(group_y[group_index] if group_index < len(group_y) else 0),
            ))
        cards[snake_name] = CardSpec(
            name=snake_name,
            cost=int(hero.get('ManaCost', 0)
                     or (base_card.cost if base_card is not None else 0)),
            rarity=rarity,
            unit=unit,
            summon_number=max(1, int(hero.get('SummonNumber', 1) or 1)),
            summon_radius_mt=int(hero.get('SummonRadius', 0) or 0),
            summon_deploy_delay_ms=int(hero.get('SummonDeployDelay', 0) or 0),
            deploy_time_ms=int(hero.get('CustomDeployTime', 0) or unit.deploy_time_ms),
            form=str(hero.get('CardForm', 'HeroForm') or 'HeroForm'),
            additional_summons=tuple(additional_summons),
        )
    return cards

if __name__ == "__main__":
    cards = load_gamedata(11)
    
    check_names = ["hog_rider", "musketeer", "giant", "pekka"]
    for n in check_names:
        c = cards.get(n)
        if c and c.unit:
            print(f"{n}: {c.unit.hitpoints}")
        else:
            print(f"{n}: not found")
    print(f"GAMEDATA_LOADER_DONE {len(cards)}")
