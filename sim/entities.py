"""Entities on the battlefield: troops, buildings and towers.

One class covers all three. In Clash Royale a tower really is just a building
that cannot be deployed, and a building really is a troop with zero speed - the
targeting, attacking and dying code is identical for all of them, so splitting
them into a hierarchy would only mean writing the same logic three times and
letting the copies drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .arena import MT, Point

# The client's `Speed` is not millitiles per second - it is the game's own
# speed scale, where the named tiers come out as:
#     Slow 45, Medium 60, Fast 90, Very Fast 120
# and those correspond to roughly 0.56, 0.75, 1.13 and 1.5 tiles per second.
# That gives tiles/sec = Speed / 80, so millitiles/sec = Speed * 12.5.
#
# Taking `Speed` as millitiles/sec directly made every unit ten times too slow:
# a Hog Rider took over two minutes to cross the arena, no push ever arrived,
# and every simulated match ended 0-0 at full time.
# The data's Speed is **tiles per minute**: Slow 45, Medium 60, Fast 90, Very
# Fast 120. So a tile per second is 60, and the conversion to millitiles per
# second is x1000/60. This used to be x12.5, which moved every unit in the game
# at three quarters of its real speed - Slow came out at 0.56 tiles/sec instead
# of 0.75. Caught by playing the situation in a real match: a lone Ice Golem
# reaches an enemy princess tower and lands one hit, and the simulator had it
# dying a tile and a half short every time.
SPEED_SCALE_NUM, SPEED_SCALE_DEN = 50, 3      # x1000/60, in integers


def speed_to_mt_per_sec(raw_speed: int) -> int:
    return raw_speed * SPEED_SCALE_NUM // SPEED_SCALE_DEN

# Attack windup can be interrupted by retargeting, so it is tracked separately
# from the hit cycle rather than folded into one timer.
IDLE, MOVING, WINDUP, ATTACKING, DEAD = range(5)


@dataclass
class Entity:
    uid: int
    name: str
    side: int                      # +1 bottom player, -1 top player
    pos: Point
    hitpoints: int
    max_hitpoints: int
    damage: int
    hit_speed_ms: int
    load_time_ms: int
    range_mt: int
    sight_range_mt: int
    speed_mt_per_sec: int
    collision_radius_mt: int
    mass: int
    attacks_ground: bool
    attacks_air: bool
    flying: bool
    target_only_buildings: bool
    target_only_troops: bool
    splash_radius_mt: int
    jump_enabled: bool = False     # can leap the river instead of using a bridge
    retarget_after_attack: bool = False
    attack_self_pushback_mt: int = 0
    # Charge: after walking charge_range_mt uninterrupted the unit moves at
    # charge_speed_multiplier percent and its next hit deals damage_special,
    # which resets the charge. Zeroes mean the unit does not charge.
    projectile_speed_mt_per_sec: int = 0
    projectile_homing: bool = False
    death_damage: int = 0
    death_damage_radius_mt: int = 0
    death_damage_pushback_mt: int = 0
    death_spawn_character: str = ""
    death_spawn_count: int = 0
    death_spawn_radius_mt: int = 0
    death_spawn_at_source: bool = False
    death_spawn_deploy_ms: int = 0
    death_spawn_offsets: tuple[tuple[int, int], ...] = ()
    spawn_character: str = ""
    spawn_count: int = 0
    spawn_pause_ms: int = 0
    spawn_start_ms: int = 0
    spawn_due_ms: int = -1          # when this spawner next produces a wave
    spawn_forward_mt: int = 0
    spawn_deploy_ms: int = 0
    hot_spawn_character: str = ""
    hot_spawn_interval_ms: int = 0
    hot_spawn_first_delay_ms: int = 0
    hot_spawn_side_mt: int = 0
    hot_spawn_behind_mt: int = 0
    hot_spawn_deploy_ms: int = 0
    hot_spawn_stop_moving_ms: int = 0
    hot_spawn_normal_resume_ms: int = 0
    hot_spawn_active: bool = False
    hot_spawn_due_ms: int = -1
    hot_spawn_alternate: bool = False
    hot_spawn_moving_ms: int = 0
    hot_spawn_pause_started_ms: int = -1
    normal_spawn_resume_ms: int = 0
    threshold_spawn_hp_pct: int = 0
    threshold_spawn_character: str = ""
    threshold_spawn_interval_ms: int = 0
    threshold_spawn_behind_mt: int = 0
    threshold_spawn_active: bool = False
    threshold_spawn_due_ms: int = -1
    death_resolved: bool = False    # its death effects have already fired
    # A timed buff, held as percentage deltas. -100 speed is frozen in place,
    # -100 hit speed is unable to swing, -30 is an Ice Wizard's chill. One
    # mechanic covers freeze, slow and rage.
    buff_until_ms: int = 0
    buff_speed_pct: int = 0
    buff_hit_speed_pct: int = 0
    buff_heal_per_second: int = 0
    buff_invisible_until_ms: int = 0
    damage_reduction_pct: int = 0
    idle_damage_reduction_pct: int = 0
    buff_after_hits_count: int = 0
    buff_after_hits_time_ms: int = 0
    buff_after_hits_speed_pct: int = 0
    buff_after_hits_hit_speed_pct: int = 0
    buff_after_hits_heal_per_second: int = 0
    buff_after_hits_overheal_pct: int = 100
    buff_after_hits_landed: int = 0
    buff_max_hitpoints_pct: int = 100
    buff_after_hits_spawn_character: str = ""
    buff_after_hits_spawn_count: int = 0
    buff_after_hits_spawn_interval_ms: int = 0
    group_max_size: int = 0
    spawn_group_uid: int = 0
    spell_captured: bool = False
    kill_heal_thresholds: tuple[int, ...] = ()
    kill_heal_amounts: tuple[int, ...] = ()
    kill_heal_overheal_pct: int = 100
    death_area_damage: int = 0
    death_area_radius_mt: int = 0
    death_area_duration_ms: int = 0
    death_area_hit_frequency_ms: int = 0
    death_area_speed_pct: int = 0
    death_area_hit_speed_pct: int = 0
    death_area_buff_linger_ms: int = 0
    death_area_tower_damage: int = 0
    owned_spawn_death_heal: int = 0
    owned_spawn_death_heal_remaining: int = 0
    owned_spawn_death_heal_overheal_pct: int = 100
    spawn_after_first_character: str = ""
    spawn_after_first_pause_ms: int = 0
    spawn_owner_uid: int = 0
    owner_heal_on_death: int = 0
    owner_heal_overheal_pct: int = 100
    attack_area_damage: int = 0
    attack_area_radius_mt: int = 0
    attack_area_pushback_mt: int = 0
    attack_area_attract_percentage: int = 0
    attack_area_duration_ms: int = 0
    shield_lost_charge_range_mt: int = 0
    shield_lost_area_damage: int = 0
    shield_lost_area_radius_mt: int = 0
    shield_lost_area_pushback_mt: int = 0
    shield_lost_effect_pending: bool = False
    on_damage_invulnerable_ms: int = 0
    on_damage_speed_pct: int = 0
    on_damage_hit_speed_pct: int = 0
    on_damage_invisible: bool = False
    ability_warp_to_target_speed: int = 0
    ability_warp_to_target_strategy: str = ""
    on_damage_effect_used: bool = False
    on_damage_effect_pending: bool = False
    invulnerable_until_ms: int = 0
    starting_side_summons: tuple[str, str] = ("", "")
    starting_side_summon_distance_mt: int = 0
    starting_side_summon_damage: int = 0
    starting_side_summon_radius_mt: int = 0
    starting_side_summon_damage_delay_ms: int = 0
    far_attack_min_range_mt: int = 0
    far_attack_damage: int = 0
    projectile_area_damage: int = 0
    projectile_area_radius_mt: int = 0
    projectile_area_delay_ms: int = 0
    pingpong_range_mt: int = 0
    pingpong_radius_mt: int = 0
    pingpong_damage: int = 0
    pingpong_strong_damage: int = 0
    pingpong_strong_range_mt: int = 0
    pingpong_pushback_mt: int = 0
    hide_hp_thresholds: tuple = ()
    hide_time_ms: int = 0
    hide_goblin_counts: tuple = ()
    hide_spawn_character: str = ""
    hide_spawn_offset_mt: int = 0
    # How many of the declared thresholds this drill has already used.
    hides_used: int = 0
    hidden_until_ms: int = 0
    ability_shot_window_ms: int = 0
    ability_extra_projectiles: int = 0
    ability_extra_projectile_spacing_mt: int = 0
    ability_shot_damage: int = 0
    ability_shot_range_mt: int = 0
    # While this is in the future, his shots come in threes.
    ability_shots_until_ms: int = 0
    special_attack_every: int = 0
    special_attack_radius_mt: int = 0
    special_area_duration_ms: int = 0
    special_area_hit_frequency_ms: int = 0
    special_area_buff: str = ""
    special_area_buff_ms: int = 0
    special_attack_count: int = 0
    ability_drop_character: str = ""
    ability_drop_radius_mt: int = 0
    ability_drop_deploy_ms: int = 0
    ability_drop_height_mt: int = 0
    projectile_deflect_behaviour: str = ""
    projectile_deflector_damage: int = 0
    ignored_buffs: tuple = ()
    projectile_area_attract_percentage: int = 0
    projectile_area_attract_radius_mt: int = 0
    projectile_area_attract_duration_ms: int = 0
    projectile_area_buff: str = ""
    projectile_area_buff_ms: int = 0
    projectile_area_hits_ground: bool = False
    projectile_area_hits_air: bool = False
    target_poison_damage_tiers: tuple[int, ...] = ()
    target_poison_stack_thresholds: tuple[int, ...] = ()
    target_poison_radius_mt: int = 0
    target_poison_first_tick_ms: int = 0
    target_poison_interval_ms: int = 0
    target_poison_tower_pct: int = 0
    target_poison_tower_duration_ms: int = 0
    sniper_ammo: int = 0
    sniper_min_range_mt: int = 0
    sniper_max_range_mt: int = 0
    sniper_side_clip_mt: int = 0
    sniper_damage: int = 0
    sniper_projectile_speed_mt_per_sec: int = 0
    group_death_spawn_character: str = ""
    group_required_guard_character: str = ""
    group_death_kill_character: str = ""
    permanent_invulnerable: bool = False
    always_invisible: bool = False
    periodic_ranged_damage: int = 0
    periodic_ranged_min_mt: int = 0
    periodic_ranged_max_mt: int = 0
    periodic_ranged_cooldown_ms: int = 0
    periodic_ranged_projectile_speed_mt_per_sec: int = 0
    periodic_ranged_trail_interval_ms: int = 0
    periodic_ranged_trail_delay_ms: int = 0
    periodic_ranged_area_radius_mt: int = 0
    periodic_ranged_area_duration_ms: int = 0
    periodic_ranged_area_speed_pct: int = 0
    periodic_ranged_next_ms: int = 0
    container_drop_hp_pct: int = 0
    container_drop_damage: int = 0
    container_drop_radius_mt: int = 0
    container_drop_pushback_mt: int = 0
    container_drop_delay_ms: int = 0
    container_drop_spawn_character: str = ""
    container_drop_spawn_count: int = 0
    container_drop_spawn_radius_mt: int = 0
    container_drop_spawn_deploy_ms: int = 0
    container_drop_threshold_offset: tuple[int, int] = (0, 0)
    container_drop_death_offset: tuple[int, int] = (0, 0)
    container_threshold_dropped: bool = False
    deploy_barrage_x_mt: tuple[int, ...] = ()
    deploy_barrage_forward_mt: tuple[int, ...] = ()
    deploy_barrage_delays_ms: tuple[int, ...] = ()
    deploy_barrage_damage: int = 0
    deploy_barrage_tower_damage: int = 0
    deploy_barrage_radius_mt: int = 0
    deploy_barrage_pushback_mt: int = 0
    capture_radius_mt: int = 0
    capture_damage: int = 0
    capture_hit_frequency_ms: int = 0
    capture_drag_delay_ms: int = 0
    capture_drag_time_ms: int = 0
    capture_cooldown_ms: int = 0
    captured_uid: int = 0
    capture_drag_start_ms: int = 0
    capture_started: bool = False
    capture_due_ms: int = 0
    capture_next_damage_ms: int = 0
    capture_cooldown_until_ms: int = 0
    quest_interval_ms: int = 0
    quest_hit_advance_ms: int = 0
    quest_start_delay_ms: int = 0
    quest_max_stacks: int = 0
    quest_progress_ms: int = 0
    quest_stacks: int = 0
    ability_level_adjustments: tuple[int, ...] = ()
    ability_level_hitpoints: tuple[int, ...] = ()
    ability_level_damages: tuple[int, ...] = ()
    ability_missing_hp_heal_pct: int = 0
    applied_level_adjustment: int = 0
    ability_taunt_radius_mt: int = 0
    ability_taunt_area_ms: int = 0
    ability_taunt_duration_ms: int = 0
    taunted_by_uid: int = 0
    taunt_until_ms: int = 0
    ability_hurl_radius_mt: int = 0
    ability_hurl_distance_mt: int = 0
    ability_hurl_delay_ms: int = 0
    ability_hurl_flight_ms: int = 0
    ability_hurl_stun_ms: int = 0
    ability_hurl_damage: int = 0
    ability_hurl_damage_radius_mt: int = 0
    ability_siege_range_mt: int = 0
    ability_siege_duration_ms: int = 0
    ability_siege_lock_ms: int = 0
    ability_siege_damage: int = 0
    ability_siege_tower_damage: int = 0
    ability_siege_radius_mt: int = 0
    ability_siege_projectile_speed_mt_per_sec: int = 0
    ability_siege_hit_speed_ms: int = 0
    siege_until_ms: int = 0
    ability_split_character: str = ""
    ability_split_mount: str = ""
    ability_split_warp_mt: int = 0
    ability_split_warp_ms: int = 0
    ability_split_spawn_damage_delay_ms: int = 0
    ability_split_spawn_damage: int = 0
    ability_split_spawn_tower_damage: int = 0
    ability_split_spawn_radius_mt: int = 0
    ability_split_spawn_pushback_mt: int = 0
    ability_reroll_range_mt: int = 0
    ability_reroll_duration_ms: int = 0
    ability_reroll_start_delay_ms: int = 0
    ability_reroll_damage: int = 0
    ability_reroll_tower_damage: int = 0
    ability_reroll_radius_mt: int = 0
    ability_reroll_radius_y_mt: int = 0
    ability_reroll_heal_missing_pct: int = 0
    ability_spin_seek_radius_mt: int = 0
    ability_spin_pending_speed_mt_per_sec: int = 0
    ability_spin_speed_mt_per_sec: int = 0
    ability_spin_duration_ms: int = 0
    ability_spin_interval_ms: int = 0
    ability_spin_damage: int = 0
    ability_spin_tower_damage: int = 0
    ability_spin_radius_mt: int = 0
    ability_spin_damage_reduction_pct: int = 0
    last_group_death_spawn_character: str = ""
    ability_window_ms: int = 0
    ability_reinforcement_character: str = ""
    ability_reinforcement_damage: int = 0
    ability_reinforcement_offsets: tuple[tuple[int, int, int], ...] = ()
    ability_self_destruct_delay_ms: int = 0
    always_untargetable: bool = False
    ability_transform_character: str = ""
    ability_destroy_group_character: str = ""
    ability_post_source_death_window_ms: int = 0
    ability_transform_lock_ms: int = 0
    ability_source_died_at_ms: int = -1
    parry_cooldown_ms: int = 0
    parry_damage_pct: int = 0
    parry_stun_ms: int = 0
    parry_stun_delay_ms: int = 0
    parry_damage_delay_ms: int = 0
    parry_ready_at_ms: int = 0
    ability_warp_backward_mt: int = 0
    ability_warp_delay_ms: int = 0
    ability_invisible_ms: int = 0
    ability_max_charges: int = 0
    ability_charges_used: int = 0
    ability_cooldown_ms: int = 0
    ability_ready_at_ms: int = 0
    ability_buff_delay_ms: int = 0
    deflect_radius_mt: int = 0
    deflect_from_ms: int = 0
    deflect_until_ms: int = 0
    ability_summon_character: str = ""
    ability_summon_base_count: int = 0
    ability_summon_max_count: int = 0
    ability_summon_interval_ms: int = 0
    ability_summon_initial_delay_ms: int = 0
    ability_summon_deploy_ms: int = 0
    ability_summon_min_radius_mt: int = 0
    ability_summon_max_radius_mt: int = 0
    # Souls banked from deaths anywhere in the arena while he is on the board.
    souls: int = 0
    ability_temporary_character: str = ""
    ability_temporary_transition_ms: int = 0
    ability_temporary_duration_ms: int = 0
    ground_on_damage_hp_pct: int = 0
    ground_on_attack: bool = False
    ground_transition_ms: int = 0
    ground_character: str = ""
    ground_landing_damage: int = 0
    ground_landing_radius_mt: int = 0
    grounding_due_ms: int = 0
    control_range_mt: int = 0
    control_initial_cooldown_ms: int = 0
    control_cooldown_ms: int = 0
    control_cast_ms: int = 0
    control_projectile_speed_mt_per_sec: int = 0
    control_buff: str = ""
    control_duration_ms: int = 0
    control_grounds_air: bool = False
    control_next_ms: int = 0
    control_cast_until_ms: int = 0
    wind_width_mt: int = 0
    wind_height_mt: int = 0
    wind_forward_offset_mt: int = 0
    wind_duration_ms: int = 0
    wind_after_death_ms: int = 0
    wind_ally_speed_pct: int = 0
    wind_enemy_speed_pct: int = 0
    wind_buff_linger_ms: int = 0
    uppercut_every_hits: int = 0
    uppercut_push_mt: int = 0
    uppercut_flight_ms: int = 0
    uppercut_root_ms: int = 0
    uppercut_attack_count: int = 0
    forced_move_until_ms: int = 0
    grounded_until_ms: int = 0  # Vines temporarily makes air troops ground targets
    # Goblin Curse: who gets a goblin if this unit dies, and what it leaves.
    cursed_by_side: int = 0
    cursed_until_ms: int = 0
    cursed_spawn: str = ""
    cursed_spawn_count: int = 1
    target_buff: str = ""
    buff_time_ms: int = 0
    multiple_targets: int = 1
    all_targets_hit: bool = False
    variable_damage2: int = 0
    variable_damage3: int = 0
    variable_damage_time1_ms: int = 0
    variable_damage_time2_ms: int = 0
    persistent_ramp_damages: tuple[int, ...] = ()
    persistent_ramp_thresholds: tuple[int, ...] = ()
    persistent_ramp_decay_ms: int = 0
    persistent_ramp_attack_count: int = 0
    persistent_ramp_last_attack_ms: int = 0
    spawn_area_damage: int = 0
    spawn_area_tower_percent: int = 100
    spawn_area_tower_damage: int = 0
    spawn_area_radius_mt: int = 0
    spawn_area_buff: str = ""
    spawn_area_buff_ms: int = 0
    spawn_area_done: bool = False
    chained_hit_count: int = 1
    chained_hit_radius_mt: int = 0
    chain_unlimited: bool = False
    chain_full_damage_hits: int = 0
    chain_reduced_damage: int = 0
    chain_reduced_speed_mt_per_sec: int = 0
    chain_repeat_memory: int = 0
    special_min_range_mt: int = 0
    special_range_mt: int = 0
    special_load_time_ms: int = 0
    pull_projectile_speed_mt_per_sec: int = 0
    pull_target_speed_mt_per_sec: int = 0
    pull_self_speed_mt_per_sec: int = 0
    pull_margin_mt: int = 0
    pull_speed_pct: int = 0
    pull_buff_ms: int = 0
    projectile_radius_mt: int = 0
    projectile_range_mt: int = 0
    pierces: bool = False
    attached_character: str = ""
    attached_to_uid: Optional[int] = None
    transform_at_hp_pct: int = 0
    transform_character: str = ""
    transformed: bool = False
    ramp_target_uid: Optional[int] = None
    ramp_started_ms: int = 0
    ability_buff: str = ""
    ability_buff_ms: int = 0
    ability_cast_ms: int = 0
    ability_cost: int = 0
    ability_dash_range_mt: int = 0
    ability_dash_count: int = 0
    ability_dash_landing_ms: int = 0
    ability_shield_pct: int = 0
    ability_spawn_character: str = ""
    ability_action_delay_ms: int = 0
    ability_pushback_damage: int = 0
    ability_pushback_radius_mt: int = 0
    ability_pushback_strength_mt: int = 0
    ability_appear_behind_mt: int = 0
    ability_area_damage: int = 0
    ability_area_radius_mt: int = 0
    ability_area_pulse_times_ms: tuple[int, ...] = ()
    ability_area_slow_pct: int = 0
    ability_area_duration_ms: int = 0
    ability_area_slow_linger_ms: int = 0
    ability_deploy_character: str = ""
    ability_deploy_forward_mt: int = 0
    ability_deploy_delay_ms: int = 0
    ability_deploy_damage: int = 0
    ability_deploy_radius_mt: int = 0
    ability_deploy_pushback_mt: int = 0
    ability_lane_switch: bool = False
    ability_lane_switch_delay_ms: int = 0
    ability_bomb_damage: int = 0
    ability_bomb_radius_mt: int = 0
    ability_bomb_pushback_mt: int = 0
    ability_link_target: str = ""
    ability_link_duration_ms: int = 0
    ability_link_interval_ms: int = 0
    ability_link_width_mt: int = 0
    ability_link_damage: int = 0
    ability_link_tower_damage: int = 0
    link_receiver_on_death: bool = False
    cannot_target_towers: bool = False
    # Where to walk when there is nothing this unit may attack. A Fire Spirit
    # cannot connect to a crown tower on its own, but it still advances on one
    # - the rule is about connecting, not about pathing.
    walk_target_uid: "int | None" = None
    # What this body cost its owner, in milli-elixir, split across a swarm so
    # three Skeletons are one elixir between them. Zero for towers and for
    # anything spawned by a death or a spawner, because that value was already
    # paid for when the parent was played and counting it twice would make a
    # Witch look like a bargain the longer she lives.
    elixir_value: int = 0
    # Which way this unit committed to going round the building in front of it.
    # Held until it is clear, because recomputing the choice every tick is what
    # made units oscillate against a tower instead of rounding it.
    avoid_turn: int = 0
    avoid_uid: int = 0
    ability_damage_pct: int = 0
    ability_tower_damage_pct: int = 0
    ability_unkillable: bool = False
    ability_duration_includes_cast: bool = False
    ability_cast_locks_actions: bool = False
    tower_damage_pct: int = 100
    buff_damage_pct: int = 0
    buff_tower_damage_pct: int = 0
    unkillable_until_ms: int = 0
    ability_used: bool = False
    ability_dashing: bool = False
    ability_digging: bool = False
    invisible_after_ms: int = 0
    last_attacked_ms: int = 0
    last_scan_ms: int = 0
    reflect_damage: int = 0
    reflect_radius_mt: int = 0
    reflect_buff: str = ""
    reflect_buff_ms: int = 0
    dash_min_range_mt: int = 0
    dash_max_range_mt: int = 0
    dash_damage: int = 0
    dash_cooldown_ms: int = 0
    dash_pushback_mt: int = 0
    dash_radius_mt: int = 0
    dashing: bool = False
    dash_ready_at_ms: int = 0
    burrow_speed_mt_per_sec: int = 0    # tunnels to where it was placed
    ignore_pushback: bool = False   # heavies are not moved by the Log
    kamikaze: bool = False      # dies on its own attack
    lifetime_ms: int = 0        # expires on its own after this long
    charge_range_mt: int = 0
    charge_speed_multiplier: int = 0
    damage_special: int = 0
    charge_distance_mt: int = 0
    charging: bool = False
    shield_hitpoints: int = 0   # re-picks a target after every hit
    shield_max_hitpoints: int = 0
    is_clone: bool = False      # Clone copies retain card mechanics but have 1 HP
    is_building: bool = False
    is_tower: bool = False
    deploy_remaining_ms: int = 0   # counts down before the unit becomes active

    state: int = IDLE
    target_uid: Optional[int] = None
    windup_remaining_ms: int = 0
    attack_cooldown_ms: int = 0
    crossed_river: bool = False
    spawned_at_ms: int = 0
    damage_dealt: int = 0

    @property
    def alive(self) -> bool:
        return self.hitpoints > 0

    @property
    def active(self) -> bool:
        """Deployed units spend `DeployTime` unable to act."""
        return self.alive and self.deploy_remaining_ms <= 0 and not self.spell_captured

    @property
    def hp_fraction(self) -> float:
        return max(0.0, self.hitpoints / self.max_hitpoints) if self.max_hitpoints else 0.0

    def can_attack(self, other: "Entity", now_ms: int = 0) -> bool:
        if other.flying and other.grounded_until_ms <= now_ms:
            return self.attacks_air
        return self.attacks_ground

    @property
    def underground(self) -> bool:
        """Tunnelling to where it was placed, and unhittable until it arrives.

        This is the whole point of a Miner: nothing can answer it in transit,
        so the defence only starts once it is already where it wanted to be.
        """
        return self.burrow_speed_mt_per_sec > 0 and self.deploy_remaining_ms > 0

    def invisible(self, now_ms: int) -> bool:
        """Vanished through not having attacked recently.

        A Royal Ghost is invisible until it swings, and a spell aimed at one
        hits nothing at all - that is the card, not a detail of it.
        """
        if self.always_invisible or self.buff_invisible_until_ms > now_ms:
            return True
        return (self.invisible_after_ms > 0
                and now_ms - self.last_attacked_ms >= self.invisible_after_ms)

    @property
    def untargetable(self) -> bool:
        """Underground, or mid-dash. Both are unhittable for the same reason:
        the unit is not on the board where the defender can reach it."""
        return (self.always_untargetable or self.underground or self.dashing or self.ability_dashing
                or self.ability_digging
                or self.spell_captured)

    def is_valid_target(self, other: "Entity", now_ms: int = 0) -> bool:
        if other.side == self.side or not other.alive:
            return False
        if other.untargetable:
            return False        # underground or mid-dash: nothing can reach it
        if not self.can_attack(other, now_ms):
            return False
        if self.target_only_buildings and not (other.is_building or other.is_tower):
            return False
        if self.target_only_troops and (other.is_building or other.is_tower):
            return False
        if self.cannot_target_towers and other.is_tower:
            return False
        return True

    def heal(self, amount: int) -> int:
        """Put hitpoints back, respecting a source-declared overheal cap."""
        if amount <= 0 or not self.alive:
            return 0
        cap = self.max_hitpoints * max(100, self.buff_max_hitpoints_pct) // 100
        healed = min(amount, cap - self.hitpoints)
        self.hitpoints += healed
        return healed

    def immune_to(self, buff_name: str) -> bool:
        """Is this unit declared immune to a named buff?

        Matched loosely on purpose: the client writes `GoblinCurse` in
        `IgnoreBuff` and the spell that applies it is loaded as `goblin_curse`.
        """
        if not buff_name or not self.ignored_buffs:
            return False
        wanted = buff_name.replace("_", "").lower()
        return any(name.replace("_", "").lower() == wanted
                   for name in self.ignored_buffs)

    def buffed(self, now_ms: int) -> bool:
        return self.buff_until_ms > now_ms

    def take_damage(self, amount: int) -> int:
        if self.permanent_invulnerable:
            return 0
        if self.invulnerable_until_ms > 0:
            return 0
        # A shield is a separate pool that soaks damage before hitpoints and
        # does not regenerate. Without it a Dark Prince is 242 hitpoints
        # lighter than the card says at level 11.
        if self.damage_reduction_pct:
            amount = amount * max(0, 100 - self.damage_reduction_pct) // 100
        shield_before = self.shield_hitpoints
        if self.shield_hitpoints > 0 and amount > 0:
            soaked = min(self.shield_hitpoints, amount)
            self.shield_hitpoints -= soaked
            amount -= soaked
            if shield_before > 0 and self.shield_hitpoints <= 0:
                self._activate_shield_lost_charge()
            if amount <= 0:
                dealt = soaked
            else:
                dealt = soaked + self._take_hitpoint_damage(amount)
        else:
            dealt = self._take_hitpoint_damage(amount)
        if (dealt > 0 and self.on_damage_invulnerable_ms > 0
                and not self.on_damage_effect_used):
            self.on_damage_effect_used = True
            self.on_damage_effect_pending = True
        return dealt

    def _activate_shield_lost_charge(self) -> None:
        if self.shield_lost_area_radius_mt > 0:
            self.shield_lost_effect_pending = True
        if self.shield_lost_charge_range_mt <= 0:
            return
        self.charge_range_mt = self.shield_lost_charge_range_mt
        self.charge_distance_mt = 0
        self.charging = False

    def _take_hitpoint_damage(self, amount: int) -> int:
        """Apply damage, returning how much was actually dealt."""
        available = (max(0, self.hitpoints - 1)
                     if self.unkillable_until_ms > 0 else self.hitpoints)
        dealt = min(available, max(0, amount))
        self.hitpoints -= dealt
        if self.hitpoints <= 0:
            self.state = DEAD
        return dealt


def make_unit(uid: int, spec, side: int, pos: Point, now_ms: int = 0) -> Entity:
    """Build an Entity from a UnitSpec produced by the game-data loader."""
    return Entity(
        uid=uid,
        name=spec.name,
        side=side,
        pos=pos,
        hitpoints=spec.hitpoints,
        max_hitpoints=spec.hitpoints,
        damage=spec.damage,
        hit_speed_ms=max(100, spec.hit_speed_ms),
        load_time_ms=max(0, spec.load_time_ms),
        range_mt=spec.range_mt,
        sight_range_mt=max(spec.sight_range_mt, spec.range_mt),
        speed_mt_per_sec=speed_to_mt_per_sec(spec.speed_mt_per_sec),
        collision_radius_mt=spec.collision_radius_mt or 400,
        mass=spec.mass or 1,
        attacks_ground=spec.attacks_ground,
        attacks_air=spec.attacks_air,
        flying=spec.flying,
        target_only_buildings=spec.target_only_buildings,
        target_only_troops=bool(getattr(spec, "target_only_troops", False)),
        splash_radius_mt=spec.splash_radius_mt,
        jump_enabled=bool(getattr(spec, "jump_enabled", False)),
        retarget_after_attack=bool(getattr(spec, "retarget_after_attack", False)),
        attack_self_pushback_mt=int(getattr(
            spec, "attack_self_pushback_mt", 0) or 0),
        projectile_speed_mt_per_sec=int(getattr(spec, "projectile_speed_mt_per_sec", 0) or 0),
        projectile_homing=bool(getattr(spec, "projectile_homing", False)),
        death_damage=int(getattr(spec, "death_damage", 0) or 0),
        death_damage_radius_mt=int(getattr(spec, "death_damage_radius_mt", 0) or 0),
        death_damage_pushback_mt=int(
            getattr(spec, "death_damage_pushback_mt", 0) or 0),
        death_spawn_character=str(getattr(spec, "death_spawn_character", "") or ""),
        death_spawn_count=int(getattr(spec, "death_spawn_count", 0) or 0),
        death_spawn_radius_mt=int(getattr(spec, "death_spawn_radius_mt", 0) or 0),
        death_spawn_at_source=bool(getattr(spec, "death_spawn_at_source", False)),
        death_spawn_deploy_ms=int(getattr(
            spec, "death_spawn_deploy_ms", 0) or 0),
        death_spawn_offsets=tuple(getattr(spec, "death_spawn_offsets", ()) or ()),
        spawn_character=str(getattr(spec, "spawn_character", "") or ""),
        spawn_count=int(getattr(spec, "spawn_count", 0) or 0),
        spawn_pause_ms=int(getattr(spec, "spawn_pause_ms", 0) or 0),
        spawn_start_ms=int(getattr(spec, "spawn_start_ms", 0) or 0),
        spawn_forward_mt=int(getattr(spec, "spawn_forward_mt", 0) or 0),
        spawn_deploy_ms=int(getattr(spec, "spawn_deploy_ms", 0) or 0),
        hot_spawn_character=str(getattr(spec, "hot_spawn_character", "") or ""),
        hot_spawn_interval_ms=int(
            getattr(spec, "hot_spawn_interval_ms", 0) or 0),
        hot_spawn_first_delay_ms=int(
            getattr(spec, "hot_spawn_first_delay_ms", 0) or 0),
        hot_spawn_side_mt=int(getattr(spec, "hot_spawn_side_mt", 0) or 0),
        hot_spawn_behind_mt=int(getattr(spec, "hot_spawn_behind_mt", 0) or 0),
        hot_spawn_deploy_ms=int(getattr(spec, "hot_spawn_deploy_ms", 0) or 0),
        hot_spawn_stop_moving_ms=int(
            getattr(spec, "hot_spawn_stop_moving_ms", 0) or 0),
        hot_spawn_normal_resume_ms=int(
            getattr(spec, "hot_spawn_normal_resume_ms", 0) or 0),
        threshold_spawn_hp_pct=int(getattr(spec, "threshold_spawn_hp_pct", 0) or 0),
        threshold_spawn_character=str(getattr(spec, "threshold_spawn_character", "") or ""),
        threshold_spawn_interval_ms=int(getattr(spec, "threshold_spawn_interval_ms", 0) or 0),
        threshold_spawn_behind_mt=int(getattr(spec, "threshold_spawn_behind_mt", 0) or 0),
        target_buff=str(getattr(spec, "target_buff", "") or ""),
        multiple_targets=max(1, int(getattr(spec, "multiple_targets", 1) or 1)),
        all_targets_hit=bool(getattr(spec, "all_targets_hit", False)),
        variable_damage2=int(getattr(spec, "variable_damage2", 0) or 0),
        variable_damage3=int(getattr(spec, "variable_damage3", 0) or 0),
        variable_damage_time1_ms=int(getattr(spec, "variable_damage_time1_ms", 0) or 0),
        variable_damage_time2_ms=int(getattr(spec, "variable_damage_time2_ms", 0) or 0),
        persistent_ramp_damages=tuple(getattr(spec, "persistent_ramp_damages", ()) or ()),
        persistent_ramp_thresholds=tuple(getattr(spec, "persistent_ramp_thresholds", ()) or ()),
        persistent_ramp_decay_ms=int(getattr(spec, "persistent_ramp_decay_ms", 0) or 0),
        spawn_area_damage=int(getattr(spec, "spawn_area_damage", 0) or 0),
        spawn_area_tower_percent=int(getattr(
            spec, "spawn_area_tower_percent", 100) or 0),
        spawn_area_tower_damage=int(getattr(
            spec, "spawn_area_tower_damage", 0) or 0),
        spawn_area_radius_mt=int(getattr(spec, "spawn_area_radius_mt", 0) or 0),
        spawn_area_buff=str(getattr(spec, "spawn_area_buff", "") or ""),
        spawn_area_buff_ms=int(getattr(spec, "spawn_area_buff_ms", 0) or 0),
        chained_hit_count=max(1, int(getattr(spec, "chained_hit_count", 1) or 1)),
        chained_hit_radius_mt=int(getattr(spec, "chained_hit_radius_mt", 0) or 0),
        chain_unlimited=bool(getattr(spec, "chain_unlimited", False)),
        chain_full_damage_hits=int(getattr(spec, "chain_full_damage_hits", 0) or 0),
        chain_reduced_damage=int(getattr(spec, "chain_reduced_damage", 0) or 0),
        chain_reduced_speed_mt_per_sec=int(getattr(spec, "chain_reduced_speed_mt_per_sec", 0) or 0),
        chain_repeat_memory=int(getattr(spec, "chain_repeat_memory", 0) or 0),
        special_min_range_mt=int(getattr(spec, "special_min_range_mt", 0) or 0),
        special_range_mt=int(getattr(spec, "special_range_mt", 0) or 0),
        special_load_time_ms=int(getattr(spec, "special_load_time_ms", 0) or 0),
        pull_projectile_speed_mt_per_sec=int(getattr(spec, "pull_projectile_speed_mt_per_sec", 0) or 0),
        pull_target_speed_mt_per_sec=int(getattr(spec, "pull_target_speed_mt_per_sec", 0) or 0),
        pull_self_speed_mt_per_sec=int(getattr(spec, "pull_self_speed_mt_per_sec", 0) or 0),
        pull_margin_mt=int(getattr(spec, "pull_margin_mt", 0) or 0),
        pull_speed_pct=int(getattr(spec, "pull_speed_pct", 0) or 0),
        pull_buff_ms=int(getattr(spec, "pull_buff_ms", 0) or 0),
        projectile_radius_mt=int(getattr(spec, "projectile_radius_mt", 0) or 0),
        projectile_range_mt=int(getattr(spec, "projectile_range_mt", 0) or 0),
        pierces=bool(getattr(spec, "pierces", False)),
        attached_character=str(getattr(spec, "attached_character", "") or ""),
        transform_at_hp_pct=int(getattr(spec, "transform_at_hp_pct", 0) or 0),
        transform_character=str(getattr(spec, "transform_character", "") or ""),
        ability_buff=str(getattr(spec, "ability_buff", "") or ""),
        ability_buff_ms=int(getattr(spec, "ability_buff_ms", 0) or 0),
        ability_cast_ms=int(getattr(spec, "ability_cast_ms", 0) or 0),
        ability_cost=int(getattr(spec, "ability_cost", 0) or 0),
        ability_dash_range_mt=int(getattr(spec, "ability_dash_range_mt", 0) or 0),
        ability_dash_count=int(getattr(spec, "ability_dash_count", 0) or 0),
        ability_dash_landing_ms=int(getattr(spec, "ability_dash_landing_ms", 0) or 0),
        ability_shield_pct=int(getattr(spec, "ability_shield_pct", 0) or 0),
        ability_spawn_character=str(getattr(spec, "ability_spawn_character", "") or ""),
        ability_action_delay_ms=int(getattr(spec, "ability_action_delay_ms", 0) or 0),
        ability_pushback_damage=int(getattr(spec, "ability_pushback_damage", 0) or 0),
        ability_pushback_radius_mt=int(getattr(spec, "ability_pushback_radius_mt", 0) or 0),
        ability_pushback_strength_mt=int(getattr(spec, "ability_pushback_strength_mt", 0) or 0),
        ability_appear_behind_mt=int(getattr(spec, "ability_appear_behind_mt", 0) or 0),
        ability_area_damage=int(getattr(spec, "ability_area_damage", 0) or 0),
        ability_area_radius_mt=int(getattr(spec, "ability_area_radius_mt", 0) or 0),
        ability_area_pulse_times_ms=tuple(getattr(spec, "ability_area_pulse_times_ms", ()) or ()),
        ability_area_slow_pct=int(getattr(spec, "ability_area_slow_pct", 0) or 0),
        ability_area_duration_ms=int(getattr(spec, "ability_area_duration_ms", 0) or 0),
        ability_area_slow_linger_ms=int(getattr(spec, "ability_area_slow_linger_ms", 0) or 0),
        ability_deploy_character=str(getattr(spec, "ability_deploy_character", "") or ""),
        ability_deploy_forward_mt=int(getattr(spec, "ability_deploy_forward_mt", 0) or 0),
        ability_deploy_delay_ms=int(getattr(spec, "ability_deploy_delay_ms", 0) or 0),
        ability_deploy_damage=int(getattr(spec, "ability_deploy_damage", 0) or 0),
        ability_deploy_radius_mt=int(getattr(spec, "ability_deploy_radius_mt", 0) or 0),
        ability_deploy_pushback_mt=int(getattr(spec, "ability_deploy_pushback_mt", 0) or 0),
        ability_lane_switch=bool(getattr(spec, "ability_lane_switch", False)),
        ability_lane_switch_delay_ms=int(getattr(spec, "ability_lane_switch_delay_ms", 0) or 0),
        ability_bomb_damage=int(getattr(spec, "ability_bomb_damage", 0) or 0),
        ability_bomb_radius_mt=int(getattr(spec, "ability_bomb_radius_mt", 0) or 0),
        ability_bomb_pushback_mt=int(getattr(spec, "ability_bomb_pushback_mt", 0) or 0),
        ability_link_target=str(getattr(spec, "ability_link_target", "") or ""),
        ability_link_duration_ms=int(getattr(spec, "ability_link_duration_ms", 0) or 0),
        ability_link_interval_ms=int(getattr(spec, "ability_link_interval_ms", 0) or 0),
        ability_link_width_mt=int(getattr(spec, "ability_link_width_mt", 0) or 0),
        ability_link_damage=int(getattr(spec, "ability_link_damage", 0) or 0),
        ability_link_tower_damage=int(getattr(spec, "ability_link_tower_damage", 0) or 0),
        link_receiver_on_death=bool(getattr(spec, "link_receiver_on_death", False)),
        cannot_target_towers=bool(getattr(spec, "cannot_target_towers", False)),
        ability_damage_pct=int(getattr(spec, "ability_damage_pct", 0) or 0),
        ability_tower_damage_pct=int(getattr(spec, "ability_tower_damage_pct", 0) or 0),
        ability_unkillable=bool(getattr(spec, "ability_unkillable", False)),
        ability_duration_includes_cast=bool(getattr(spec, "ability_duration_includes_cast", False)),
        ability_cast_locks_actions=bool(getattr(spec, "ability_cast_locks_actions", False)),
        tower_damage_pct=int(getattr(spec, "tower_damage_pct", 100) or 100),
        invisible_after_ms=int(getattr(spec, "invisible_after_ms", 0) or 0),
        idle_damage_reduction_pct=int(getattr(spec, "idle_damage_reduction_pct", 0) or 0),
        buff_after_hits_count=int(getattr(spec, "buff_after_hits_count", 0) or 0),
        buff_after_hits_time_ms=int(getattr(spec, "buff_after_hits_time_ms", 0) or 0),
        buff_after_hits_speed_pct=int(getattr(spec, "buff_after_hits_speed_pct", 0) or 0),
        buff_after_hits_hit_speed_pct=int(getattr(spec, "buff_after_hits_hit_speed_pct", 0) or 0),
        buff_after_hits_heal_per_second=int(getattr(spec, "buff_after_hits_heal_per_second", 0) or 0),
        buff_after_hits_overheal_pct=int(getattr(spec, "buff_after_hits_overheal_pct", 100) or 100),
        buff_after_hits_spawn_character=str(getattr(spec, "buff_after_hits_spawn_character", "") or ""),
        buff_after_hits_spawn_count=int(getattr(spec, "buff_after_hits_spawn_count", 0) or 0),
        buff_after_hits_spawn_interval_ms=int(getattr(spec, "buff_after_hits_spawn_interval_ms", 0) or 0),
        group_max_size=int(getattr(spec, "group_max_size", 0) or 0),
        kill_heal_thresholds=tuple(getattr(spec, "kill_heal_thresholds", ()) or ()),
        kill_heal_amounts=tuple(getattr(spec, "kill_heal_amounts", ()) or ()),
        kill_heal_overheal_pct=int(getattr(spec, "kill_heal_overheal_pct", 100) or 100),
        death_area_damage=int(getattr(spec, "death_area_damage", 0) or 0),
        death_area_radius_mt=int(getattr(spec, "death_area_radius_mt", 0) or 0),
        death_area_duration_ms=int(getattr(spec, "death_area_duration_ms", 0) or 0),
        death_area_hit_frequency_ms=int(getattr(spec, "death_area_hit_frequency_ms", 0) or 0),
        death_area_speed_pct=int(getattr(spec, "death_area_speed_pct", 0) or 0),
        death_area_hit_speed_pct=int(getattr(spec, "death_area_hit_speed_pct", 0) or 0),
        death_area_buff_linger_ms=int(getattr(spec, "death_area_buff_linger_ms", 0) or 0),
        death_area_tower_damage=int(
            getattr(spec, "death_area_tower_damage", 0) or 0),
        owned_spawn_death_heal=int(getattr(spec, "owned_spawn_death_heal", 0) or 0),
        owned_spawn_death_heal_remaining=int(getattr(spec, "owned_spawn_death_heal_count", 0) or 0),
        owned_spawn_death_heal_overheal_pct=int(getattr(spec, "owned_spawn_death_heal_overheal_pct", 100) or 100),
        spawn_after_first_character=str(getattr(spec, "spawn_after_first_character", "") or ""),
        spawn_after_first_pause_ms=int(getattr(spec, "spawn_after_first_pause_ms", 0) or 0),
        attack_area_damage=int(getattr(spec, "attack_area_damage", 0) or 0),
        attack_area_radius_mt=int(getattr(spec, "attack_area_radius_mt", 0) or 0),
        attack_area_pushback_mt=int(getattr(spec, "attack_area_pushback_mt", 0) or 0),
        attack_area_attract_percentage=int(getattr(
            spec, "attack_area_attract_percentage", 0) or 0),
        attack_area_duration_ms=int(getattr(
            spec, "attack_area_duration_ms", 0) or 0),
        shield_lost_charge_range_mt=int(getattr(spec, "shield_lost_charge_range_mt", 0) or 0),
        shield_lost_area_damage=int(getattr(spec, "shield_lost_area_damage", 0) or 0),
        shield_lost_area_radius_mt=int(getattr(spec, "shield_lost_area_radius_mt", 0) or 0),
        shield_lost_area_pushback_mt=int(getattr(spec, "shield_lost_area_pushback_mt", 0) or 0),
        on_damage_invulnerable_ms=int(getattr(spec, "on_damage_invulnerable_ms", 0) or 0),
        on_damage_speed_pct=int(getattr(spec, "on_damage_speed_pct", 0) or 0),
        on_damage_hit_speed_pct=int(getattr(spec, "on_damage_hit_speed_pct", 0) or 0),
        on_damage_invisible=bool(getattr(spec, "on_damage_invisible", False)),
        ability_warp_to_target_speed=int(
            getattr(spec, "ability_warp_to_target_speed", 0) or 0),
        ability_warp_to_target_strategy=str(
            getattr(spec, "ability_warp_to_target_strategy", "") or ""),
        starting_side_summons=tuple(getattr(spec, "starting_side_summons", ("", "")) or ("", "")),
        starting_side_summon_distance_mt=int(getattr(spec, "starting_side_summon_distance_mt", 0) or 0),
        starting_side_summon_damage=int(getattr(spec, "starting_side_summon_damage", 0) or 0),
        starting_side_summon_radius_mt=int(getattr(spec, "starting_side_summon_radius_mt", 0) or 0),
        starting_side_summon_damage_delay_ms=int(getattr(spec, "starting_side_summon_damage_delay_ms", 0) or 0),
        far_attack_min_range_mt=int(getattr(spec, "far_attack_min_range_mt", 0) or 0),
        far_attack_damage=int(getattr(spec, "far_attack_damage", 0) or 0),
        projectile_area_damage=int(getattr(spec, "projectile_area_damage", 0) or 0),
        projectile_area_radius_mt=int(getattr(spec, "projectile_area_radius_mt", 0) or 0),
        projectile_area_delay_ms=int(getattr(spec, "projectile_area_delay_ms", 0) or 0),
        pingpong_range_mt=int(getattr(spec, "pingpong_range_mt", 0) or 0),
        pingpong_radius_mt=int(getattr(spec, "pingpong_radius_mt", 0) or 0),
        pingpong_damage=int(getattr(spec, "pingpong_damage", 0) or 0),
        pingpong_strong_damage=int(getattr(spec, "pingpong_strong_damage", 0) or 0),
        pingpong_strong_range_mt=int(getattr(spec, "pingpong_strong_range_mt", 0) or 0),
        pingpong_pushback_mt=int(getattr(spec, "pingpong_pushback_mt", 0) or 0),
        hide_hp_thresholds=tuple(getattr(spec, "hide_hp_thresholds", ()) or ()),
        hide_time_ms=int(getattr(spec, "hide_time_ms", 0) or 0),
        hide_goblin_counts=tuple(getattr(spec, "hide_goblin_counts", ()) or ()),
        hide_spawn_character=str(getattr(spec, "hide_spawn_character", "") or ""),
        hide_spawn_offset_mt=int(getattr(spec, "hide_spawn_offset_mt", 0) or 0),
        ability_shot_window_ms=int(getattr(spec, "ability_shot_window_ms", 0) or 0),
        ability_extra_projectiles=int(getattr(
            spec, "ability_extra_projectiles", 0) or 0),
        ability_extra_projectile_spacing_mt=int(getattr(
            spec, "ability_extra_projectile_spacing_mt", 0) or 0),
        ability_shot_damage=int(getattr(spec, "ability_shot_damage", 0) or 0),
        ability_shot_range_mt=int(getattr(spec, "ability_shot_range_mt", 0) or 0),
        special_attack_every=int(getattr(spec, "special_attack_every", 0) or 0),
        special_attack_radius_mt=int(getattr(
            spec, "special_attack_radius_mt", 0) or 0),
        special_area_duration_ms=int(getattr(
            spec, "special_area_duration_ms", 0) or 0),
        special_area_hit_frequency_ms=int(getattr(
            spec, "special_area_hit_frequency_ms", 0) or 0),
        special_area_buff=str(getattr(spec, "special_area_buff", "") or ""),
        special_area_buff_ms=int(getattr(spec, "special_area_buff_ms", 0) or 0),
        ability_drop_character=str(getattr(spec, "ability_drop_character", "") or ""),
        ability_drop_radius_mt=int(getattr(spec, "ability_drop_radius_mt", 0) or 0),
        ability_drop_deploy_ms=int(getattr(spec, "ability_drop_deploy_ms", 0) or 0),
        ability_drop_height_mt=int(getattr(spec, "ability_drop_height_mt", 0) or 0),
        projectile_deflect_behaviour=str(getattr(
            spec, "projectile_deflect_behaviour", "") or ""),
        projectile_deflector_damage=int(getattr(
            spec, "projectile_deflector_damage", 0) or 0),
        ignored_buffs=tuple(getattr(spec, "ignored_buffs", ()) or ()),
        projectile_area_attract_percentage=int(getattr(
            spec, "projectile_area_attract_percentage", 0) or 0),
        projectile_area_attract_radius_mt=int(getattr(
            spec, "projectile_area_attract_radius_mt", 0) or 0),
        projectile_area_attract_duration_ms=int(getattr(
            spec, "projectile_area_attract_duration_ms", 0) or 0),
        projectile_area_buff=str(getattr(spec, "projectile_area_buff", "") or ""),
        projectile_area_buff_ms=int(getattr(spec, "projectile_area_buff_ms", 0) or 0),
        projectile_area_hits_ground=bool(getattr(spec, "projectile_area_hits_ground", False)),
        projectile_area_hits_air=bool(getattr(spec, "projectile_area_hits_air", False)),
        target_poison_damage_tiers=tuple(
            getattr(spec, "target_poison_damage_tiers", ()) or ()),
        target_poison_stack_thresholds=tuple(
            getattr(spec, "target_poison_stack_thresholds", ()) or ()),
        target_poison_radius_mt=int(
            getattr(spec, "target_poison_radius_mt", 0) or 0),
        target_poison_first_tick_ms=int(
            getattr(spec, "target_poison_first_tick_ms", 0) or 0),
        target_poison_interval_ms=int(
            getattr(spec, "target_poison_interval_ms", 0) or 0),
        target_poison_tower_pct=int(
            getattr(spec, "target_poison_tower_pct", 0) or 0),
        target_poison_tower_duration_ms=int(
            getattr(spec, "target_poison_tower_duration_ms", 0) or 0),
        sniper_ammo=int(getattr(spec, "sniper_ammo", 0) or 0),
        sniper_min_range_mt=int(getattr(spec, "sniper_min_range_mt", 0) or 0),
        sniper_max_range_mt=int(getattr(spec, "sniper_max_range_mt", 0) or 0),
        sniper_side_clip_mt=int(getattr(spec, "sniper_side_clip_mt", 0) or 0),
        sniper_damage=int(getattr(spec, "sniper_damage", 0) or 0),
        sniper_projectile_speed_mt_per_sec=int(
            getattr(spec, "sniper_projectile_speed_mt_per_sec", 0) or 0),
        group_death_spawn_character=str(
            getattr(spec, "group_death_spawn_character", "") or ""),
        group_required_guard_character=str(
            getattr(spec, "group_required_guard_character", "") or ""),
        group_death_kill_character=str(
            getattr(spec, "group_death_kill_character", "") or ""),
        permanent_invulnerable=bool(
            getattr(spec, "permanent_invulnerable", False)),
        always_invisible=bool(getattr(spec, "always_invisible", False)),
        periodic_ranged_damage=int(
            getattr(spec, "periodic_ranged_damage", 0) or 0),
        periodic_ranged_min_mt=int(
            getattr(spec, "periodic_ranged_min_mt", 0) or 0),
        periodic_ranged_max_mt=int(
            getattr(spec, "periodic_ranged_max_mt", 0) or 0),
        periodic_ranged_cooldown_ms=int(
            getattr(spec, "periodic_ranged_cooldown_ms", 0) or 0),
        periodic_ranged_projectile_speed_mt_per_sec=int(
            getattr(spec, "periodic_ranged_projectile_speed_mt_per_sec", 0) or 0),
        periodic_ranged_trail_interval_ms=int(
            getattr(spec, "periodic_ranged_trail_interval_ms", 0) or 0),
        periodic_ranged_trail_delay_ms=int(
            getattr(spec, "periodic_ranged_trail_delay_ms", 0) or 0),
        periodic_ranged_area_radius_mt=int(
            getattr(spec, "periodic_ranged_area_radius_mt", 0) or 0),
        periodic_ranged_area_duration_ms=int(
            getattr(spec, "periodic_ranged_area_duration_ms", 0) or 0),
        periodic_ranged_area_speed_pct=int(
            getattr(spec, "periodic_ranged_area_speed_pct", 0) or 0),
        periodic_ranged_next_ms=now_ms,
        container_drop_hp_pct=int(getattr(spec, "container_drop_hp_pct", 0) or 0),
        container_drop_damage=int(getattr(spec, "container_drop_damage", 0) or 0),
        container_drop_radius_mt=int(
            getattr(spec, "container_drop_radius_mt", 0) or 0),
        container_drop_pushback_mt=int(
            getattr(spec, "container_drop_pushback_mt", 0) or 0),
        container_drop_delay_ms=int(
            getattr(spec, "container_drop_delay_ms", 0) or 0),
        container_drop_spawn_character=str(
            getattr(spec, "container_drop_spawn_character", "") or ""),
        container_drop_spawn_count=int(
            getattr(spec, "container_drop_spawn_count", 0) or 0),
        container_drop_spawn_radius_mt=int(
            getattr(spec, "container_drop_spawn_radius_mt", 0) or 0),
        container_drop_spawn_deploy_ms=int(
            getattr(spec, "container_drop_spawn_deploy_ms", 0) or 0),
        container_drop_threshold_offset=tuple(
            getattr(spec, "container_drop_threshold_offset", (0, 0)) or (0, 0)),
        container_drop_death_offset=tuple(
            getattr(spec, "container_drop_death_offset", (0, 0)) or (0, 0)),
        deploy_barrage_x_mt=tuple(
            getattr(spec, "deploy_barrage_x_mt", ()) or ()),
        deploy_barrage_forward_mt=tuple(
            getattr(spec, "deploy_barrage_forward_mt", ()) or ()),
        deploy_barrage_delays_ms=tuple(
            getattr(spec, "deploy_barrage_delays_ms", ()) or ()),
        deploy_barrage_damage=int(
            getattr(spec, "deploy_barrage_damage", 0) or 0),
        deploy_barrage_tower_damage=int(
            getattr(spec, "deploy_barrage_tower_damage", 0) or 0),
        deploy_barrage_radius_mt=int(
            getattr(spec, "deploy_barrage_radius_mt", 0) or 0),
        deploy_barrage_pushback_mt=int(
            getattr(spec, "deploy_barrage_pushback_mt", 0) or 0),
        capture_radius_mt=int(getattr(spec, "capture_radius_mt", 0) or 0),
        capture_damage=int(getattr(spec, "capture_damage", 0) or 0),
        capture_hit_frequency_ms=int(
            getattr(spec, "capture_hit_frequency_ms", 0) or 0),
        capture_drag_delay_ms=int(
            getattr(spec, "capture_drag_delay_ms", 0) or 0),
        capture_drag_time_ms=int(getattr(spec, "capture_drag_time_ms", 0) or 0),
        capture_cooldown_ms=int(getattr(spec, "capture_cooldown_ms", 0) or 0),
        quest_interval_ms=int(getattr(spec, "quest_interval_ms", 0) or 0),
        quest_hit_advance_ms=int(getattr(spec, "quest_hit_advance_ms", 0) or 0),
        quest_start_delay_ms=int(getattr(spec, "quest_start_delay_ms", 0) or 0),
        quest_max_stacks=int(getattr(spec, "quest_max_stacks", 0) or 0),
        ability_level_adjustments=tuple(
            getattr(spec, "ability_level_adjustments", ()) or ()),
        ability_level_hitpoints=tuple(
            getattr(spec, "ability_level_hitpoints", ()) or ()),
        ability_level_damages=tuple(
            getattr(spec, "ability_level_damages", ()) or ()),
        ability_missing_hp_heal_pct=int(
            getattr(spec, "ability_missing_hp_heal_pct", 0) or 0),
        ability_taunt_radius_mt=int(
            getattr(spec, "ability_taunt_radius_mt", 0) or 0),
        ability_taunt_area_ms=int(getattr(spec, "ability_taunt_area_ms", 0) or 0),
        ability_taunt_duration_ms=int(
            getattr(spec, "ability_taunt_duration_ms", 0) or 0),
        ability_hurl_radius_mt=int(
            getattr(spec, "ability_hurl_radius_mt", 0) or 0),
        ability_hurl_distance_mt=int(
            getattr(spec, "ability_hurl_distance_mt", 0) or 0),
        ability_hurl_delay_ms=int(getattr(spec, "ability_hurl_delay_ms", 0) or 0),
        ability_hurl_flight_ms=int(
            getattr(spec, "ability_hurl_flight_ms", 0) or 0),
        ability_hurl_stun_ms=int(getattr(spec, "ability_hurl_stun_ms", 0) or 0),
        ability_hurl_damage=int(getattr(spec, "ability_hurl_damage", 0) or 0),
        ability_hurl_damage_radius_mt=int(
            getattr(spec, "ability_hurl_damage_radius_mt", 0) or 0),
        ability_siege_range_mt=int(
            getattr(spec, "ability_siege_range_mt", 0) or 0),
        ability_siege_duration_ms=int(
            getattr(spec, "ability_siege_duration_ms", 0) or 0),
        ability_siege_lock_ms=int(
            getattr(spec, "ability_siege_lock_ms", 0) or 0),
        ability_siege_damage=int(
            getattr(spec, "ability_siege_damage", 0) or 0),
        ability_siege_tower_damage=int(
            getattr(spec, "ability_siege_tower_damage", 0) or 0),
        ability_siege_radius_mt=int(
            getattr(spec, "ability_siege_radius_mt", 0) or 0),
        ability_siege_projectile_speed_mt_per_sec=int(getattr(
            spec, "ability_siege_projectile_speed_mt_per_sec", 0) or 0),
        ability_siege_hit_speed_ms=int(getattr(
            spec, "ability_siege_hit_speed_ms", 0) or 0),
        ability_split_character=str(
            getattr(spec, "ability_split_character", "") or ""),
        ability_split_mount=str(
            getattr(spec, "ability_split_mount", "") or ""),
        ability_split_warp_mt=int(
            getattr(spec, "ability_split_warp_mt", 0) or 0),
        ability_split_warp_ms=int(
            getattr(spec, "ability_split_warp_ms", 0) or 0),
        ability_split_spawn_damage_delay_ms=int(getattr(
            spec, "ability_split_spawn_damage_delay_ms", 0) or 0),
        ability_split_spawn_damage=int(getattr(
            spec, "ability_split_spawn_damage", 0) or 0),
        ability_split_spawn_tower_damage=int(getattr(
            spec, "ability_split_spawn_tower_damage", 0) or 0),
        ability_split_spawn_radius_mt=int(getattr(
            spec, "ability_split_spawn_radius_mt", 0) or 0),
        ability_split_spawn_pushback_mt=int(getattr(
            spec, "ability_split_spawn_pushback_mt", 0) or 0),
        ability_reroll_range_mt=int(getattr(
            spec, "ability_reroll_range_mt", 0) or 0),
        ability_reroll_duration_ms=int(getattr(
            spec, "ability_reroll_duration_ms", 0) or 0),
        ability_reroll_start_delay_ms=int(getattr(
            spec, "ability_reroll_start_delay_ms", 0) or 0),
        ability_reroll_damage=int(getattr(
            spec, "ability_reroll_damage", 0) or 0),
        ability_reroll_tower_damage=int(getattr(
            spec, "ability_reroll_tower_damage", 0) or 0),
        ability_reroll_radius_mt=int(getattr(
            spec, "ability_reroll_radius_mt", 0) or 0),
        ability_reroll_radius_y_mt=int(getattr(
            spec, "ability_reroll_radius_y_mt", 0) or 0),
        ability_reroll_heal_missing_pct=int(getattr(
            spec, "ability_reroll_heal_missing_pct", 0) or 0),
        ability_spin_seek_radius_mt=int(getattr(
            spec, "ability_spin_seek_radius_mt", 0) or 0),
        ability_spin_pending_speed_mt_per_sec=int(getattr(
            spec, "ability_spin_pending_speed_mt_per_sec", 0) or 0),
        ability_spin_speed_mt_per_sec=int(getattr(
            spec, "ability_spin_speed_mt_per_sec", 0) or 0),
        ability_spin_duration_ms=int(getattr(
            spec, "ability_spin_duration_ms", 0) or 0),
        ability_spin_interval_ms=int(getattr(
            spec, "ability_spin_interval_ms", 0) or 0),
        ability_spin_damage=int(getattr(
            spec, "ability_spin_damage", 0) or 0),
        ability_spin_tower_damage=int(getattr(
            spec, "ability_spin_tower_damage", 0) or 0),
        ability_spin_radius_mt=int(getattr(
            spec, "ability_spin_radius_mt", 0) or 0),
        ability_spin_damage_reduction_pct=int(getattr(
            spec, "ability_spin_damage_reduction_pct", 0) or 0),
        last_group_death_spawn_character=str(getattr(
            spec, "last_group_death_spawn_character", "") or ""),
        ability_window_ms=int(getattr(spec, "ability_window_ms", 0) or 0),
        ability_reinforcement_character=str(getattr(
            spec, "ability_reinforcement_character", "") or ""),
        ability_reinforcement_damage=int(getattr(
            spec, "ability_reinforcement_damage", 0) or 0),
        ability_reinforcement_offsets=tuple(getattr(
            spec, "ability_reinforcement_offsets", ()) or ()),
        ability_self_destruct_delay_ms=int(getattr(
            spec, "ability_self_destruct_delay_ms", 0) or 0),
        always_untargetable=bool(getattr(spec, "always_untargetable", False)),
        ability_transform_character=str(getattr(
            spec, "ability_transform_character", "") or ""),
        ability_destroy_group_character=str(getattr(
            spec, "ability_destroy_group_character", "") or ""),
        ability_post_source_death_window_ms=int(getattr(
            spec, "ability_post_source_death_window_ms", 0) or 0),
        ability_transform_lock_ms=int(getattr(
            spec, "ability_transform_lock_ms", 0) or 0),
        parry_cooldown_ms=int(getattr(spec, "parry_cooldown_ms", 0) or 0),
        parry_damage_pct=int(getattr(spec, "parry_damage_pct", 0) or 0),
        parry_stun_ms=int(getattr(spec, "parry_stun_ms", 0) or 0),
        parry_stun_delay_ms=int(getattr(spec, "parry_stun_delay_ms", 0) or 0),
        parry_damage_delay_ms=int(getattr(
            spec, "parry_damage_delay_ms", 0) or 0),
        ability_warp_backward_mt=int(getattr(
            spec, "ability_warp_backward_mt", 0) or 0),
        ability_warp_delay_ms=int(getattr(spec, "ability_warp_delay_ms", 0) or 0),
        ability_invisible_ms=int(getattr(spec, "ability_invisible_ms", 0) or 0),
        ability_max_charges=int(getattr(spec, "ability_max_charges", 0) or 0),
        ability_cooldown_ms=int(getattr(spec, "ability_cooldown_ms", 0) or 0),
        ability_buff_delay_ms=int(getattr(
            spec, "ability_buff_delay_ms", 0) or 0),
        deflect_radius_mt=int(getattr(spec, "deflect_radius_mt", 0) or 0),
        ability_summon_character=str(getattr(
            spec, "ability_summon_character", "") or ""),
        ability_summon_base_count=int(getattr(
            spec, "ability_summon_base_count", 0) or 0),
        ability_summon_max_count=int(getattr(
            spec, "ability_summon_max_count", 0) or 0),
        ability_summon_interval_ms=int(getattr(
            spec, "ability_summon_interval_ms", 0) or 0),
        ability_summon_initial_delay_ms=int(getattr(
            spec, "ability_summon_initial_delay_ms", 0) or 0),
        ability_summon_deploy_ms=int(getattr(
            spec, "ability_summon_deploy_ms", 0) or 0),
        ability_summon_min_radius_mt=int(getattr(
            spec, "ability_summon_min_radius_mt", 0) or 0),
        ability_summon_max_radius_mt=int(getattr(
            spec, "ability_summon_max_radius_mt", 0) or 0),
        ability_temporary_character=str(getattr(
            spec, "ability_temporary_character", "") or ""),
        ability_temporary_transition_ms=int(getattr(
            spec, "ability_temporary_transition_ms", 0) or 0),
        ability_temporary_duration_ms=int(getattr(
            spec, "ability_temporary_duration_ms", 0) or 0),
        ground_on_damage_hp_pct=int(getattr(spec, "ground_on_damage_hp_pct", 0) or 0),
        ground_on_attack=bool(getattr(spec, "ground_on_attack", False)),
        ground_transition_ms=int(getattr(spec, "ground_transition_ms", 0) or 0),
        ground_character=str(getattr(spec, "ground_character", "") or ""),
        ground_landing_damage=int(getattr(spec, "ground_landing_damage", 0) or 0),
        ground_landing_radius_mt=int(getattr(spec, "ground_landing_radius_mt", 0) or 0),
        control_range_mt=int(getattr(spec, "control_range_mt", 0) or 0),
        control_initial_cooldown_ms=int(getattr(spec, "control_initial_cooldown_ms", 0) or 0),
        control_cooldown_ms=int(getattr(spec, "control_cooldown_ms", 0) or 0),
        control_cast_ms=int(getattr(spec, "control_cast_ms", 0) or 0),
        control_projectile_speed_mt_per_sec=int(getattr(spec, "control_projectile_speed_mt_per_sec", 0) or 0),
        control_buff=str(getattr(spec, "control_buff", "") or ""),
        control_duration_ms=int(getattr(spec, "control_duration_ms", 0) or 0),
        control_grounds_air=bool(getattr(spec, "control_grounds_air", False)),
        control_next_ms=now_ms + int(getattr(spec, "control_initial_cooldown_ms", 0) or 0),
        wind_width_mt=int(getattr(spec, "wind_width_mt", 0) or 0),
        wind_height_mt=int(getattr(spec, "wind_height_mt", 0) or 0),
        wind_forward_offset_mt=int(getattr(spec, "wind_forward_offset_mt", 0) or 0),
        wind_duration_ms=int(getattr(spec, "wind_duration_ms", 0) or 0),
        wind_after_death_ms=int(getattr(spec, "wind_after_death_ms", 0) or 0),
        wind_ally_speed_pct=int(getattr(spec, "wind_ally_speed_pct", 0) or 0),
        wind_enemy_speed_pct=int(getattr(spec, "wind_enemy_speed_pct", 0) or 0),
        wind_buff_linger_ms=int(getattr(spec, "wind_buff_linger_ms", 0) or 0),
        uppercut_every_hits=int(getattr(spec, "uppercut_every_hits", 0) or 0),
        uppercut_push_mt=int(getattr(spec, "uppercut_push_mt", 0) or 0),
        uppercut_flight_ms=int(getattr(spec, "uppercut_flight_ms", 0) or 0),
        uppercut_root_ms=int(getattr(spec, "uppercut_root_ms", 0) or 0),
        reflect_damage=int(getattr(spec, "reflect_damage", 0) or 0),
        reflect_radius_mt=int(getattr(spec, "reflect_radius_mt", 0) or 0),
        reflect_buff=str(getattr(spec, "reflect_buff", "") or ""),
        reflect_buff_ms=int(getattr(spec, "reflect_buff_ms", 0) or 0),
        dash_min_range_mt=int(getattr(spec, "dash_min_range_mt", 0) or 0),
        dash_max_range_mt=int(getattr(spec, "dash_max_range_mt", 0) or 0),
        dash_damage=int(getattr(spec, "dash_damage", 0) or 0),
        dash_cooldown_ms=int(getattr(spec, "dash_cooldown_ms", 0) or 0),
        dash_pushback_mt=int(getattr(spec, "dash_pushback_mt", 0) or 0),
        dash_radius_mt=int(getattr(spec, "dash_radius_mt", 0) or 0),
        burrow_speed_mt_per_sec=int(getattr(spec, "burrow_speed_mt_per_sec", 0) or 0),
        ignore_pushback=bool(getattr(spec, "ignore_pushback", False)),
        kamikaze=bool(getattr(spec, "kamikaze", False)),
        lifetime_ms=int(getattr(spec, "lifetime_ms", 0) or 0),
        buff_time_ms=int(getattr(spec, "buff_time_ms", 0) or 0),
        charge_range_mt=int(getattr(spec, "charge_range_mt", 0) or 0),
        charge_speed_multiplier=int(getattr(spec, "charge_speed_multiplier", 0) or 0),
        damage_special=int(getattr(spec, "damage_special", 0) or 0),
        shield_hitpoints=(int(getattr(spec, "shield_hitpoints", 0) or 0)
                          * int(getattr(spec, "initial_shield_pct", 100) or 0) // 100),
        shield_max_hitpoints=int(getattr(spec, "shield_hitpoints", 0) or 0),
        # Most buildings are Speed = 0, which is why that inference stood for a
        # long time, but it is an inference. The reworked Furnace and Goblin
        # Drill both carry a real Speed in their character section, so they
        # were classed as troops: they walked up the lane, drew no
        # building-targeted aggro and were not solid. `from_building_card` is
        # the client's own answer - the card is declared in spells_buildings.csv
        # - and it agrees with the public snapshot's card type.
        is_building=(spec.speed_mt_per_sec == 0
                     or bool(getattr(spec, "from_building_card", False))),

        deploy_remaining_ms=spec.deploy_time_ms,
        spawned_at_ms=now_ms,
    )


# Tower hitboxes, straight out of buildings.csv: every PrincessTower variant
# carries CollisionRadius 1000 and every KingTower variant 1400. Both towers
# were built at a flat 1500, which made the princess tower half a tile wider
# than it is - and since reach is range plus the *target's* radius, that let
# everything attack it from half a tile further out than the game allows.
PRINCESS_COLLISION_MT = 1000
KING_COLLISION_MT = 1400
# TowerPrincessProjectile has Speed 600 - the same tiles-per-minute unit as
# movement - so a tower's arrow flies 10 tiles a second and a shot at the edge
# of its 7.5 tile range takes three quarters of a second to arrive. Towers are
# built here by hand rather than from a card, so this has to be set explicitly
# or they would hit instantly while every other shooter's arrows travel.
TOWER_PROJECTILE_MT_PER_SEC = 600 * 1000 // 60
# Towers wind up before their first shot at a new target, and it is not a small
# number: princesstower.toml gives LoadTime 1000 and every KingTower variant
# 500. Both were built with no windup at all, which handed each tower a free
# second of damage against everything that walked into range - the difference
# between a lone Ice Golem dying a step short of the tower and landing a hit on
# it, which is what it does in a real game.
PRINCESS_LOAD_MS = 1000
KING_LOAD_MS = 500


def make_tower(uid: int, side: int, pos: Point, hitpoints: int, damage: int,
               hit_speed_ms: int, range_mt: int, king: bool = False) -> Entity:
    """Princess and king towers.

    A king tower starts asleep in Clash Royale: it does not fire until it is
    damaged or a princess tower falls. That is modelled by the engine flipping
    `target_only_buildings` off when it activates, so an inactive king simply
    finds nothing to shoot.
    """
    return Entity(
        uid=uid, name="king_tower" if king else "princess_tower", side=side, pos=pos,
        hitpoints=hitpoints, max_hitpoints=hitpoints, damage=damage,
        hit_speed_ms=hit_speed_ms,
        load_time_ms=KING_LOAD_MS if king else PRINCESS_LOAD_MS,
        range_mt=range_mt,
        sight_range_mt=range_mt, speed_mt_per_sec=0,
        collision_radius_mt=KING_COLLISION_MT if king else PRINCESS_COLLISION_MT,
        projectile_speed_mt_per_sec=TOWER_PROJECTILE_MT_PER_SEC,
        # Both King Tower and Princess Tower projectile records explicitly
        # declare Homing = true in the client data.  Towers are constructed
        # directly (rather than through UnitSpec), so retain that fact here.
        projectile_homing=True,
        mass=100, attacks_ground=True, attacks_air=True, flying=False,
        target_only_buildings=False, target_only_troops=False, splash_radius_mt=0,
        is_building=True, is_tower=True,
    )
