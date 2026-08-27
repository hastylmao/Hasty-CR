"""The battle tick: target, move, attack, resolve collisions, remove the dead.

Fidelity notes
--------------
The card *parameters* come straight from the client's own data files, so
hitpoints, damage, range, sight, speed, mass and collision radius are exact.
What is not in those files - and therefore what this module approximates - is
the **procedure**: how targets are chosen and re-chosen, how a unit paths to a
bridge, how overlapping units push each other apart, and in what order all of
that happens within a tick.

Those approximations are stated explicitly at each site rather than buried, so
that when they are measured properly against the real game the corrections have
an obvious home. Getting them wrong is the main risk in the whole project: a
policy trained here will happily exploit any of them.

Order within a tick is fixed and matters:
    1. tick down deploy timers
    2. acquire or re-acquire targets
    3. attack (windup, then damage on the hit cycle)
    4. move whatever did not attack
    5. resolve collisions
    6. remove the dead
Attacking before moving means a unit already in range fires this tick instead
of stepping first, which is what stops units jittering in and out of range.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import arena
from . import pathfind
import math

from .arena import MT, Point, TICK_MS, distance
from .entities import (ATTACKING, DEAD, IDLE, MOVING, WINDUP, Entity,
                       make_unit, speed_to_mt_per_sec)

# --- documented approximations -------------------------------------------
# Real retarget rules depend on per-unit flags whose exact semantics are not
# documented in the data files. This is the placeholder: re-evaluate a target
# only when the current one dies or leaves sight, plus a periodic sweep.
RETARGET_INTERVAL_MS = 500
# Pushback is mass-weighted and resolved iteratively in the real game; one pass
# is enough to keep units from stacking without being a physics simulation.
# Two passes at full strength. One pass at 60% only decays an overlap rather
# than resolving it, so bodies stayed sunk into one another by up to a fifth of
# a tile indefinitely. The requirement is simply that nothing overlaps and
# nothing walks through anything, which needs the correction to converge.
SEPARATION_PASSES = 4
SEPARATION_STRENGTH = 100         # percent of the overlap corrected per pass


@dataclass
class Battle:
    entities: Dict[int, Entity] = field(default_factory=dict)
    now_ms: int = 0
    next_uid: int = 1
    damage_log: List[tuple] = field(default_factory=list)
    # Shots loosed but not yet arrived.  Homing shots are represented by their
    # target UID; positional shots retain their launch segment and are held in
    # `unmodelled_projectiles` until a measured collision rule is available.
    # This is preferable to fabricating homing behaviour for a projectile the
    # client did not declare as homing.
    # [arrival_ms, attacker, target_uid, amount]
    in_flight: List[list] = field(default_factory=list)
    # A projectile can leave a delayed target-bound area after impact.  The
    # target object itself is retained so a destroyed carrier leaves the area
    # at its final position, matching evolved Ice Spirit's Frost Blast.
    # [due_ms, attacker, carrier, damage, radius, buff, buff_ms, ground, air]
    projectile_area_events: List[list] = field(default_factory=list)
    # (source uid, carrier uid) -> [source object, carrier object, active darts,
    # next pulse, tower expiry, pending activation times]. Each evolved Dart
    # Goblin owns its controller;
    # two copies poisoning one troop therefore remain independent.
    target_poison_controllers: Dict[tuple[int, int], list] = field(
        default_factory=dict)
    # [arrival, source, target uid, launch point, aim point, launch time,
    # next trail time] for evolved Elite Barbarian Rage Spears.
    rage_spears: List[list] = field(default_factory=list)
    # [due, source object, centre] for each evolved Skeleton Barrel container.
    container_drop_events: List[list] = field(default_factory=list)
    # [due, source object, absolute centre] for Cannon Evolution's 4+5 rows.
    deploy_barrage_events: List[list] = field(default_factory=list)
    # Homing secondary control shots such as evolved Hunter's Net.
    # [arrival_ms, source, target_uid]
    control_in_flight: List[list] = field(default_factory=list)
    ability_summons: List[list] = field(default_factory=list)
    # Milli-elixir of enemy bodies each side has destroyed. The difference is
    # the elixir trade, which is what kiting, pulling a tank into both towers
    # and answering a Musketeer with an Ice Golem all actually produce.
    elixir_destroyed: Dict[int, int] = field(default_factory=dict)
    paratroopers: List[list] = field(default_factory=list)
    # source uid -> [source object, expires_ms, death_duration_clamped]
    wind_areas: Dict[int, list] = field(default_factory=dict)
    # [target object, start, end, start_ms, arrival_ms]
    forced_moves: List[list] = field(default_factory=list)
    # [arrival, source, target_uid, amount, hit_index, seen_uids, recent_uids]
    chain_projectiles: List[list] = field(default_factory=list)
    # [source, slow_expires_ms, next_slow_tick_ms, remaining_pulse_times]
    ability_area_events: List[list] = field(default_factory=list)
    unmodelled_projectiles: List[dict] = field(default_factory=list)
    # Opt-in normalized diagnostics. None is the hot-path feature flag:
    # when disabled no per-tick event objects or log records are allocated.
    diagnostics: Optional[object] = None
    # Opt-in comparison trace for live calibration. Kept off by default so RL
    # rollouts do not retain per-tick collision data.
    trace_contacts: bool = False
    contact_trace: List[dict] = field(default_factory=list)
    # Fisherman-style hooks have a projectile phase, then source-declared drag
    # motion. Kept separate from ordinary attack shots because a hook moves an
    # entity rather than landing damage.
    pull_flight: List[list] = field(default_factory=list)
    active_pulls: List[list] = field(default_factory=list)
    ability_dash_chains: List[list] = field(default_factory=list)
    # [due_ms, caster_uid, target_uid].  Populated only by a client-declared
    # ActionSpawnGuard ability; delayed resolution keeps it an RL action rather
    # than an immediate, invented Little Prince side effect.
    ability_guard_events: List[list] = field(default_factory=list)
    # [due_ms, caster object]. Source-declared hero structures are delayed
    # until their real deployment completes, then become ordinary buildings.
    ability_deploy_events: List[list] = field(default_factory=list)
    # [due_ms, source object, original position]. Mighty Miner's client action
    # explicitly mirrors X while retaining Y and explodes at the old point.
    ability_lane_switch_events: List[list] = field(default_factory=list)
    # [doctor, receiver entity or Point, expires, next hit]. Receiver objects
    # are intentionally retained after death so their final antenna position
    # continues to anchor Goblinstein's link.
    ability_link_events: List[list] = field(default_factory=list)
    link_receivers: Dict[int, Point] = field(default_factory=dict)
    # name -> UnitSpec, so death spawns and huts can build what they produce.
    # Match sets this; without it spawning is skipped rather than guessed.
    unit_lookup: Optional[object] = None
    # Lingering spell areas: Poison sitting for eight seconds, a Tornado for
    # one. Each entry is [spec, centre, side, expires_ms, next_tick_ms].
    areas: List[list] = field(default_factory=list)
    # Fixed-target spell projectiles and delayed drops. Units keep moving
    # before these resolve, so a cast can genuinely miss.
    spell_impacts: List[list] = field(default_factory=list)
    resolved_spell_damage: Dict[int, int] = field(default_factory=dict)
    spell_spawn_events: List[list] = field(default_factory=list)
    rolling_spells: List[list] = field(default_factory=list)
    spell_pulse_events: List[list] = field(default_factory=list)
    # [due_ms, parent_uid, character]. Used by evolved Skeletons; the parent
    # must still be alive when the client-declared spawn interval elapses.
    on_hit_spawn_events: List[list] = field(default_factory=list)
    starting_summon_damage_events: List[list] = field(default_factory=list)
    level_up_events: List[list] = field(default_factory=list)
    ability_taunt_events: List[list] = field(default_factory=list)
    taunt_areas: List[list] = field(default_factory=list)
    # Hero Giant's button remains pending until an eligible troop enters the
    # client-declared selector.  Throw events are [push time, landing time,
    # source, target, start, end, started].
    hurl_pending: List[Entity] = field(default_factory=list)
    hurl_events: List[list] = field(default_factory=list)
    # Fixed-position mortar-style impacts from Hero Bowler's Stone Swish:
    # [arrival, source, aim, damage, tower damage, radius].
    siege_impacts: List[list] = field(default_factory=list)
    # [due, mounted source] and [due, source, mount] for Hero Dark Prince.
    split_events: List[list] = field(default_factory=list)
    split_damage_events: List[list] = field(default_factory=list)
    # [start, end, source, origin, destination, hit uids, started]
    reroll_events: List[list] = field(default_factory=list)
    spin_pending: List[Entity] = field(default_factory=list)
    # [source, expires, next pulse]
    spin_events: List[list] = field(default_factory=list)
    # [due, banner, character, x offset, y offset]. Hero Goblins' banner is
    # itself the ability carrier; an empty character is its delayed cleanup.
    reinforcement_events: List[list] = field(default_factory=list)
    # [stun due, damage due, defender, attacker, reflected amount, stunned].
    parry_events: List[list] = field(default_factory=list)
    ability_warp_events: List[list] = field(default_factory=list)
    delayed_self_buffs: List[list] = field(default_factory=list)
    # [air due, return due, current entity, air spec, ground spec, transition].
    temporary_form_events: List[list] = field(default_factory=list)
    resolved_last_group_spawns: set[tuple[int, int, str]] = field(
        default_factory=set)
    _buildings_cache: List = field(default_factory=list)
    _buildings_stamp: int = -1

    # ------------------------------------------------------------- lifecycle

    def add(self, entity: Entity) -> Entity:
        # Deploying a fresh Hero Goblins group invalidates an older unspent
        # banner, as declared by ActionActivateOnCardDeploy in the client.
        if entity.last_group_death_spawn_character:
            for old in self.entities.values():
                if (old.side == entity.side and old.alive
                        and old.ability_reinforcement_character):
                    old.hitpoints = 0
                    old.state = DEAD
        # A new linked source invalidates the dormant ability carrier from an
        # older deployment (TombstoneHero_Monster_new_deploy_detected).
        for old in self.entities.values():
            if (old.side == entity.side and old.alive
                    and old.ability_destroy_group_character == entity.name):
                old.hitpoints = 0
                old.state = DEAD
        entity.uid = self.next_uid
        self.next_uid += 1
        self.entities[entity.uid] = entity
        if entity.spawn_group_uid <= 0:
            entity.spawn_group_uid = entity.uid
        if self.diagnostics is not None:
            self.diagnostics.emit(
                "spawn", source=entity, position=entity.pos,
                reason="battle_add", state=entity.state,
                metadata={"name": entity.name, "side": entity.side,
                          "owner_uid": entity.spawn_owner_uid,
                          "group_uid": entity.spawn_group_uid})
        for x, forward, delay in zip(
                entity.deploy_barrage_x_mt,
                entity.deploy_barrage_forward_mt,
                entity.deploy_barrage_delays_ms):
            centre = arena.clamp_to_arena(Point(
                x, entity.pos.y - entity.side * forward))
            self.deploy_barrage_events.append([
                self.now_ms + delay, entity, centre])
        if (entity.starting_side_summon_distance_mt > 0 and self.unit_lookup
                and any(entity.starting_side_summons)):
            for direction, character in zip((-1, 1), entity.starting_side_summons):
                if not character:
                    continue
                spec = self.unit_lookup(character)
                if spec is None:
                    continue
                pos = arena.clamp_to_arena(Point(
                    entity.pos.x + direction * entity.starting_side_summon_distance_mt,
                    entity.pos.y))
                child = make_unit(0, spec, entity.side, pos, self.now_ms)
                self.add(child)
                if entity.starting_side_summon_radius_mt > 0:
                    self.starting_summon_damage_events.append([
                        self.now_ms + entity.starting_side_summon_damage_delay_ms,
                        entity.uid, entity.side, pos,
                        entity.starting_side_summon_damage,
                        entity.starting_side_summon_radius_mt])
        attached_character = str(getattr(entity, "attached_character", "") or "")
        # `SpawnAttach` is not a periodic spawner: Ram Rider is one Ram plus a
        # rider that shares its position and has its own troop-targeting bola.
        # Build the companion from the client character table and link it,
        # rather than pretending the card is only its building-targeting Ram.
        if attached_character and self.unit_lookup is not None:
            spec = self.unit_lookup(attached_character)
            if spec is not None:
                rider = make_unit(0, spec, entity.side, entity.pos, self.now_ms)
                rider.attached_to_uid = entity.uid
                rider.deploy_remaining_ms = entity.deploy_remaining_ms
                self.add(rider)
        return entity

    def schedule_linked_transform(self, carrier: Entity) -> bool:
        if (not carrier.alive or not carrier.ability_transform_character
                or self.unit_lookup is None):
            return False
        if (carrier.ability_source_died_at_ms >= 0
                and self.now_ms > carrier.ability_source_died_at_ms
                + carrier.ability_post_source_death_window_ms):
            return False
        active_spec = self.unit_lookup(carrier.ability_transform_character)
        if active_spec is None:
            return False
        source = next((entity for entity in self.entities.values()
                       if entity.alive and entity.side == carrier.side
                       and entity.spawn_group_uid == carrier.spawn_group_uid
                       and entity.name == carrier.ability_destroy_group_character),
                      None)
        if source is not None:
            carrier.pos = source.pos
            source.hitpoints = 0
            source.state = DEAD
        active = make_unit(carrier.uid, active_spec, carrier.side, carrier.pos,
                           self.now_ms)
        active.deploy_remaining_ms = 0
        active.spawn_group_uid = carrier.spawn_group_uid
        active.ability_used = True
        active.control_cast_until_ms = self.now_ms + carrier.ability_transform_lock_ms
        self.entities[carrier.uid] = active
        return True

    def _tick_linked_ability_carriers(self) -> None:
        for carrier in list(self.entities.values()):
            if not carrier.alive or not carrier.ability_transform_character:
                continue
            source = next((entity for entity in self.entities.values()
                           if entity.alive and entity.side == carrier.side
                           and entity.spawn_group_uid == carrier.spawn_group_uid
                           and entity.name
                           == carrier.ability_destroy_group_character), None)
            if source is not None:
                carrier.pos = source.pos
                carrier.ability_source_died_at_ms = -1
                continue
            if carrier.ability_source_died_at_ms < 0:
                carrier.ability_source_died_at_ms = self.now_ms
            elif self.now_ms > (carrier.ability_source_died_at_ms
                                + carrier.ability_post_source_death_window_ms):
                carrier.hitpoints = 0
                carrier.state = DEAD

    def _tick_parries(self) -> None:
        pending = []
        for stun_due, damage_due, defender, attacker, amount, stunned in self.parry_events:
            if not stunned and stun_due <= self.now_ms:
                stunned = True
                if attacker.alive:
                    attacker.buff_until_ms = max(
                        attacker.buff_until_ms,
                        self.now_ms + defender.parry_stun_ms)
                    attacker.buff_speed_pct = -100
                    attacker.buff_hit_speed_pct = -95
                    attacker.ramp_target_uid = None
                    attacker.ramp_started_ms = 0
                    attacker.persistent_ramp_attack_count = 0
                    attacker.persistent_ramp_last_attack_ms = 0
            if damage_due <= self.now_ms:
                if attacker.alive:
                    dealt = attacker.take_damage(amount)
                    defender.damage_dealt += dealt
                    self.damage_log.append(
                        (self.now_ms, defender.uid, attacker.uid, dealt))
                continue
            pending.append([
                stun_due, damage_due, defender, attacker, amount, stunned])
        self.parry_events = pending

    def schedule_ability_warp(self, source: Entity) -> bool:
        if not source.alive or source.ability_warp_backward_mt <= 0:
            return False
        destination = arena.clamp_to_arena(Point(
            source.pos.x,
            source.pos.y + source.side * source.ability_warp_backward_mt))
        self.ability_warp_events.append([
            self.now_ms + source.ability_warp_delay_ms, source, destination])
        source.buff_invisible_until_ms = max(
            source.buff_invisible_until_ms,
            self.now_ms + source.ability_invisible_ms)
        source.control_cast_until_ms = max(
            source.control_cast_until_ms,
            self.now_ms + source.ability_warp_delay_ms + 50)
        return True

    def resolve_warp_target(self, source: Entity) -> Optional[Entity]:
        """The target an `ActionWarpCharacter` resolver would pick.

        Mega Minion Hero declares `RESOLVER_STRATEGY_LOWEST_MAX_HP` then
        `RESOLVER_STRATEGY_FURTHEST_TARGET`, with filter
        `default_targets_no_towers` over a Global shape: the frailest thing on
        the board, ties broken by distance, towers excluded. Global means the
        whole arena, not sight range - the ability marks a target anywhere.
        """
        strategy = source.ability_warp_to_target_strategy or ""
        candidates = [
            other for other in self.entities.values()
            if other.alive and not other.is_tower
            and source.is_valid_target(other, self.now_ms)
            and not other.invisible(self.now_ms)]
        if not candidates:
            return None
        lowest_hp = "LOWEST_MAX_HP" in strategy
        furthest = "FURTHEST_TARGET" in strategy

        def rank(other: Entity):
            gap = distance(source.pos, other.pos)
            return (other.max_hitpoints if lowest_hp else 0,
                    -gap if furthest else gap,
                    other.uid)                       # uid keeps replays stable

        return min(candidates, key=rank)

    def schedule_target_warp(self, source: Entity) -> bool:
        """Warp onto the resolved target at the declared speed."""
        if not source.alive or source.ability_warp_to_target_speed <= 0:
            return False
        target = self.resolve_warp_target(source)
        if target is None:
            return False
        speed = speed_to_mt_per_sec(source.ability_warp_to_target_speed)
        if speed <= 0:
            return False
        gap = distance(source.pos, target.pos)
        # Land at contact rather than inside the target: separation would eject
        # the warper on the next tick anyway, and arriving overlapped reads as
        # a bug on screen.
        reach = source.collision_radius_mt + target.collision_radius_mt
        destination = target.pos
        if gap > reach:
            dx, dy = target.pos.x - source.pos.x, target.pos.y - source.pos.y
            step = gap - reach
            destination = arena.clamp_to_arena(Point(
                source.pos.x + dx * step // gap,
                source.pos.y + dy * step // gap))
        travel = gap * 1000 // speed
        self.ability_warp_events.append(
            [self.now_ms + travel, source, destination])
        source.control_cast_until_ms = max(
            source.control_cast_until_ms, self.now_ms + travel + 50)
        return True

    def _tick_ability_warps(self) -> None:
        pending = []
        for due, source, destination in self.ability_warp_events:
            if due > self.now_ms:
                pending.append([due, source, destination])
                continue
            if source.alive:
                source.pos = destination
                source.target_uid = None
                source.windup_remaining_ms = 0
        self.ability_warp_events = pending

    def _tick_delayed_self_buffs(self) -> None:
        pending = []
        for due, expires, source, speed, hit_speed, heal, reduction in self.delayed_self_buffs:
            if due > self.now_ms:
                pending.append([
                    due, expires, source, speed, hit_speed, heal, reduction])
                continue
            if source.alive:
                source.buff_until_ms = max(source.buff_until_ms, expires)
                source.buff_speed_pct = speed
                source.buff_hit_speed_pct = hit_speed
                source.buff_heal_per_second = heal
                source.damage_reduction_pct = reduction
        self.delayed_self_buffs = pending

    def schedule_temporary_form(self, source: Entity) -> bool:
        if (not source.alive or not source.ability_temporary_character
                or self.unit_lookup is None):
            return False
        air_spec = self.unit_lookup(source.ability_temporary_character)
        ground_spec = self.unit_lookup(source.name)
        if air_spec is None or ground_spec is None:
            return False
        starts = self.now_ms + source.ability_action_delay_ms
        air_due = starts + source.ability_temporary_transition_ms
        return_due = starts + source.ability_temporary_duration_ms
        source.control_cast_until_ms = max(source.control_cast_until_ms, air_due)
        self.temporary_form_events.append([
            air_due, return_due, source, air_spec, ground_spec,
            source.ability_temporary_transition_ms])
        return True

    @staticmethod
    def _copy_form_state(old: Entity, new: Entity) -> None:
        new.hitpoints = min(new.max_hitpoints, old.hitpoints)
        new.shield_hitpoints = min(new.shield_max_hitpoints,
                                   old.shield_hitpoints)
        new.deploy_remaining_ms = 0
        new.spawn_group_uid = old.spawn_group_uid
        new.target_uid = old.target_uid
        new.ability_used = True
        new.ability_charges_used = old.ability_charges_used

    def _tick_temporary_forms(self) -> None:
        pending = []
        for air_due, return_due, current, air_spec, ground_spec, transition in self.temporary_form_events:
            if not current.alive:
                continue
            if current.name != air_spec.name:
                if air_due > self.now_ms:
                    pending.append([
                        air_due, return_due, current, air_spec, ground_spec,
                        transition])
                    continue
                airborne = make_unit(
                    current.uid, air_spec, current.side, current.pos, self.now_ms)
                self._copy_form_state(current, airborne)
                airborne.buff_until_ms = return_due
                airborne.buff_speed_pct = 50
                self.entities[current.uid] = airborne
                current = airborne
            if return_due > self.now_ms:
                pending.append([
                    air_due, return_due, current, air_spec, ground_spec,
                    transition])
                continue
            grounded = make_unit(
                current.uid, ground_spec, current.side, current.pos, self.now_ms)
            self._copy_form_state(current, grounded)
            grounded.control_cast_until_ms = self.now_ms + transition
            self.entities[current.uid] = grounded
        self.temporary_form_events = pending

    def schedule_reinforcements(self, banner: Entity) -> bool:
        """Queue a source-authored reinforcement formation from a hero banner."""
        if (not banner.alive or not banner.ability_reinforcement_character
                or self.now_ms > banner.spawned_at_ms + banner.ability_window_ms):
            return False
        start = self.now_ms + banner.ability_action_delay_ms
        lane_direction = -1 if banner.pos.x > arena.WIDTH // 2 else 1
        for offset_x, offset_y, delay in banner.ability_reinforcement_offsets:
            self.reinforcement_events.append([
                start + delay, banner, banner.ability_reinforcement_character,
                offset_x * lane_direction, offset_y * banner.side])
        self.reinforcement_events.append([
            start + banner.ability_self_destruct_delay_ms, banner, "", 0, 0])
        banner.attack_cooldown_ms = max(
            banner.attack_cooldown_ms,
            banner.ability_action_delay_ms + banner.ability_self_destruct_delay_ms)
        return True

    def _tick_reinforcements(self) -> None:
        pending = []
        for due, banner, character, offset_x, offset_y in self.reinforcement_events:
            if due > self.now_ms:
                pending.append([due, banner, character, offset_x, offset_y])
                continue
            if not character:
                if banner.alive:
                    banner.hitpoints = 0
                    banner.state = DEAD
                continue
            if self.unit_lookup is None:
                continue
            spec = self.unit_lookup(character)
            if spec is None:
                continue
            pos = arena.clamp_to_arena(Point(
                banner.pos.x + offset_x, banner.pos.y + offset_y))
            child = make_unit(0, spec, banner.side, pos, self.now_ms)
            if banner.ability_reinforcement_damage > 0:
                child.damage = banner.ability_reinforcement_damage
            added = self.add(child)
            added.spawn_group_uid = banner.spawn_group_uid
        self.reinforcement_events = pending

    def _resolve_starting_summon_damage(self) -> None:
        pending = []
        for due, source_uid, side, centre, amount, radius in self.starting_summon_damage_events:
            if due > self.now_ms:
                pending.append([due, source_uid, side, centre, amount, radius])
                continue
            for other in list(self.entities.values()):
                if other.side == side or not other.alive or other.flying:
                    continue
                if distance(centre, other.pos) > radius + other.collision_radius_mt:
                    continue
                dealt = other.take_damage(amount)
                self.damage_log.append((self.now_ms, source_uid, other.uid, dealt))
        self.starting_summon_damage_events = pending

    def schedule_level_up(self, entity: Entity) -> bool:
        if not entity.ability_level_adjustments:
            return False
        self.level_up_events.append([
            self.now_ms + entity.ability_action_delay_ms, entity])
        entity.control_cast_until_ms = max(
            entity.control_cast_until_ms,
            self.now_ms + entity.ability_cast_ms)
        return True

    def _resolve_level_ups(self) -> None:
        pending = []
        for due_ms, entity in self.level_up_events:
            if due_ms > self.now_ms:
                pending.append([due_ms, entity])
                continue
            if not entity.alive:
                continue
            index = min(entity.quest_stacks,
                        len(entity.ability_level_adjustments) - 1)
            if (index >= len(entity.ability_level_hitpoints)
                    or index >= len(entity.ability_level_damages)):
                continue
            entity.applied_level_adjustment = (
                entity.ability_level_adjustments[index])
            entity.max_hitpoints = entity.ability_level_hitpoints[index]
            entity.damage = entity.ability_level_damages[index]
            missing = max(0, entity.max_hitpoints - entity.hitpoints)
            entity.heal(missing * entity.ability_missing_hp_heal_pct // 100)
        self.level_up_events = pending

    def schedule_taunt(self, entity: Entity) -> bool:
        if entity.ability_taunt_radius_mt <= 0:
            return False
        self.ability_taunt_events.append([
            self.now_ms + entity.ability_action_delay_ms, entity])
        entity.control_cast_until_ms = max(
            entity.control_cast_until_ms,
            self.now_ms + entity.ability_cast_ms)
        return True

    def _tick_taunts(self) -> None:
        pending = []
        for due_ms, source in self.ability_taunt_events:
            if due_ms > self.now_ms:
                pending.append([due_ms, source])
                continue
            if not source.alive:
                continue
            source.shield_hitpoints = source.shield_max_hitpoints
            self.taunt_areas.append([
                source, self.now_ms + source.ability_taunt_area_ms, set()])
        self.ability_taunt_events = pending
        active = []
        for source, expires_ms, seen in self.taunt_areas:
            if not source.alive or self.now_ms >= expires_ms:
                continue
            for target in self.entities.values():
                if (target.uid in seen or target.side == source.side
                        or not target.alive or target.untargetable
                        or target.name == "goblin_demolisher_kamikaze_form"
                        or distance(source.pos, target.pos)
                            > source.ability_taunt_radius_mt):
                    continue
                seen.add(target.uid)
                target.taunted_by_uid = source.uid
                target.taunt_until_ms = (
                    self.now_ms + source.ability_taunt_duration_ms)
                target.target_uid = source.uid
            active.append([source, expires_ms, seen])
        self.taunt_areas = active

    def schedule_hurl(self, entity: Entity) -> bool:
        """Arm Hero Giant's source-declared wait-for-target selector."""
        if entity.ability_hurl_radius_mt <= 0:
            return False
        self.hurl_pending.append(entity)
        return True

    def schedule_siege(self, entity: Entity) -> bool:
        if entity.ability_siege_range_mt <= 0:
            return False
        starts = self.now_ms + entity.ability_action_delay_ms
        entity.siege_until_ms = starts + entity.ability_siege_duration_ms
        entity.control_cast_until_ms = max(
            entity.control_cast_until_ms,
            self.now_ms + entity.ability_siege_lock_ms)
        entity.target_uid = None
        return True

    def schedule_split(self, entity: Entity) -> bool:
        if (not entity.ability_split_character or not entity.ability_split_mount
                or self.unit_lookup is None
                or self.unit_lookup(entity.ability_split_character) is None
                or self.unit_lookup(entity.ability_split_mount) is None):
            return False
        self.split_events.append([
            self.now_ms + entity.ability_action_delay_ms, entity])
        return True

    def schedule_reroll(self, entity: Entity) -> bool:
        if entity.ability_reroll_range_mt <= 0:
            return False
        start_ms = (self.now_ms + entity.ability_action_delay_ms
                    + entity.ability_reroll_start_delay_ms)
        end_ms = start_ms + entity.ability_reroll_duration_ms
        destination = arena.clamp_to_arena(Point(
            entity.pos.x,
            entity.pos.y - entity.side * entity.ability_reroll_range_mt))
        self.reroll_events.append([
            start_ms, end_ms, entity, entity.pos, destination, set(), False])
        entity.control_cast_until_ms = max(entity.control_cast_until_ms, end_ms)
        return True

    def schedule_spin(self, entity: Entity) -> bool:
        if entity.ability_spin_seek_radius_mt <= 0:
            return False
        self.spin_pending.append(entity)
        # The action-chain controller, rather than ordinary combat, owns her
        # movement and attacks until it ends. She remains targetable.
        entity.control_cast_until_ms = 2 ** 31 - 1
        entity.target_uid = None
        return True

    def _spin_targets(self, source: Entity) -> list[Entity]:
        return [target for target in self.entities.values()
                if (target.side != source.side and target.alive
                    and not target.flying and not target.untargetable)]

    def _spin_move(self, source: Entity, targets: list[Entity], speed: int,
                   dt_ms: int) -> None:
        if not targets or speed <= 0:
            return
        target = min(targets, key=lambda unit: (
            distance(source.pos, unit.pos), unit.uid))
        dx, dy = target.pos.x - source.pos.x, target.pos.y - source.pos.y
        span = arena.isqrt(dx * dx + dy * dy) or 1
        stop = source.collision_radius_mt + target.collision_radius_mt
        step = min(max(0, span - stop), speed * dt_ms // 1000)
        source.pos = arena.clamp_to_arena(Point(
            source.pos.x + dx * step // span,
            source.pos.y + dy * step // span))

    def _tick_spins(self, dt_ms: int) -> None:
        pending = []
        for source in self.spin_pending:
            if not source.alive:
                continue
            targets = self._spin_targets(source)
            in_range = [target for target in targets
                        if distance(source.pos, target.pos)
                           <= source.ability_spin_seek_radius_mt
                           + target.collision_radius_mt]
            if not in_range:
                self._spin_move(
                    source, targets, source.ability_spin_pending_speed_mt_per_sec,
                    dt_ms)
                pending.append(source)
                continue
            expires = self.now_ms + source.ability_spin_duration_ms
            self.spin_events.append([
                source, expires, self.now_ms + source.ability_spin_interval_ms])
            source.damage_reduction_pct = max(
                source.damage_reduction_pct,
                source.ability_spin_damage_reduction_pct)
            source.buff_until_ms = max(source.buff_until_ms, expires)
        self.spin_pending = pending

        active = []
        for source, expires, next_pulse in self.spin_events:
            if not source.alive:
                continue
            targets = self._spin_targets(source)
            self._spin_move(
                source, targets, source.ability_spin_speed_mt_per_sec, dt_ms)
            while next_pulse <= self.now_ms and next_pulse <= expires:
                for target in list(self.entities.values()):
                    if (target.side == source.side or not target.alive
                            or target.flying or target.untargetable
                            or distance(source.pos, target.pos)
                               > source.ability_spin_radius_mt
                               + target.collision_radius_mt):
                        continue
                    amount = (source.ability_spin_tower_damage
                              if target.is_tower else source.ability_spin_damage)
                    dealt = target.take_damage(amount)
                    source.damage_dealt += dealt
                    self.damage_log.append(
                        (next_pulse, source.uid, target.uid, dealt))
                next_pulse += source.ability_spin_interval_ms
            if self.now_ms < expires:
                active.append([source, expires, next_pulse])
            else:
                source.damage_reduction_pct = 0
                source.control_cast_until_ms = self.now_ms + 400
        self.spin_events = active

    def _tick_rerolls(self) -> None:
        active = []
        for start_ms, end_ms, source, origin, end, hit_uids, started in self.reroll_events:
            if not source.alive:
                continue
            if self.now_ms < start_ms:
                active.append([
                    start_ms, end_ms, source, origin, end, hit_uids, started])
                continue
            if not started:
                started = True
                missing = max(0, source.max_hitpoints - source.hitpoints)
                source.heal(missing * source.ability_reroll_heal_missing_pct // 100)
                source.spell_captured = True
                source.invulnerable_until_ms = end_ms
                source.target_uid = None
            duration = max(1, end_ms - start_ms)
            elapsed = min(duration, self.now_ms - start_ms)
            old = source.pos
            source.pos = arena.clamp_to_arena(Point(
                origin.x + (end.x - origin.x) * elapsed // duration,
                origin.y + (end.y - origin.y) * elapsed // duration))
            low_y, high_y = sorted((old.y, source.pos.y))
            for target in list(self.entities.values()):
                if (target.side == source.side or not target.alive
                        or target.uid in hit_uids or target.flying
                        or target.untargetable):
                    continue
                if abs(target.pos.x - source.pos.x) > (
                        source.ability_reroll_radius_mt
                        + target.collision_radius_mt):
                    continue
                margin = (source.ability_reroll_radius_y_mt
                          + target.collision_radius_mt)
                if target.pos.y < low_y - margin or target.pos.y > high_y + margin:
                    continue
                hit_uids.add(target.uid)
                amount = (source.ability_reroll_tower_damage
                          if target.is_tower else source.ability_reroll_damage)
                dealt = target.take_damage(amount)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
            if self.now_ms < end_ms:
                active.append([
                    start_ms, end_ms, source, origin, end, hit_uids, started])
            else:
                source.pos = end
                source.spell_captured = False
                source.invulnerable_until_ms = 0
        self.reroll_events = active

    def _tick_splits(self) -> None:
        pending = []
        for due, source in self.split_events:
            if due > self.now_ms:
                pending.append([due, source])
                continue
            if not source.alive or self.unit_lookup is None:
                continue
            walking_spec = self.unit_lookup(source.ability_split_character)
            mount_spec = self.unit_lookup(source.ability_split_mount)
            if walking_spec is None or mount_spec is None:
                continue
            origin = source.pos
            target = self.get(source.target_uid)
            walking = make_unit(
                source.uid, walking_spec, source.side, origin, self.now_ms)
            walking.hitpoints = min(walking.max_hitpoints, source.hitpoints)
            walking.shield_hitpoints = min(
                walking.shield_max_hitpoints, source.shield_hitpoints)
            walking.deploy_remaining_ms = 0
            walking.ability_used = True
            walking.spawn_group_uid = source.spawn_group_uid
            if target is not None and target.alive:
                dx, dy = target.pos.x - origin.x, target.pos.y - origin.y
                span = arena.isqrt(dx * dx + dy * dy) or 1
                end = arena.clamp_to_arena(Point(
                    origin.x - dx * source.ability_split_warp_mt // span,
                    origin.y - dy * source.ability_split_warp_mt // span))
            else:
                end = arena.clamp_to_arena(Point(
                    origin.x, origin.y + source.side
                    * source.ability_split_warp_mt))
            walking.forced_move_until_ms = (
                self.now_ms + source.ability_split_warp_ms)
            self.entities[source.uid] = walking
            self.forced_moves.append([
                walking, origin, end, self.now_ms,
                self.now_ms + source.ability_split_warp_ms])

            mount = make_unit(0, mount_spec, source.side, origin, self.now_ms)
            self.add(mount)
            self.split_damage_events.append([
                self.now_ms + source.ability_split_spawn_damage_delay_ms,
                source, mount])
        self.split_events = pending

        damage_pending = []
        for due, source, mount in self.split_damage_events:
            if due > self.now_ms:
                damage_pending.append([due, source, mount])
                continue
            if not mount.alive:
                continue
            for target in list(self.entities.values()):
                if (target.side == source.side or not target.alive
                        or target.flying or target.uid == mount.uid
                        or distance(mount.pos, target.pos)
                            > source.ability_split_spawn_radius_mt
                            + target.collision_radius_mt):
                    continue
                amount = (source.ability_split_spawn_tower_damage
                          if target.is_tower
                          else source.ability_split_spawn_damage)
                dealt = target.take_damage(amount)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
                if (source.ability_split_spawn_pushback_mt > 0
                        and not target.is_building and not target.ignore_pushback):
                    dx, dy = target.pos.x - mount.pos.x, target.pos.y - mount.pos.y
                    span = arena.isqrt(dx * dx + dy * dy) or 1
                    target.pos = arena.clamp_to_arena(Point(
                        target.pos.x + dx * source.ability_split_spawn_pushback_mt // span,
                        target.pos.y + dy * source.ability_split_spawn_pushback_mt // span))
        self.split_damage_events = damage_pending

    def _siege_active(self, entity: Entity) -> bool:
        return (entity.ability_siege_range_mt > 0
                and self.now_ms >= (entity.siege_until_ms
                                    - entity.ability_siege_duration_ms)
                and self.now_ms < entity.siege_until_ms)

    def _resolve_siege_impacts(self) -> None:
        pending = []
        for arrival, source, centre, damage, tower_damage, radius in self.siege_impacts:
            if arrival > self.now_ms:
                pending.append([
                    arrival, source, centre, damage, tower_damage, radius])
                continue
            for target in list(self.entities.values()):
                if (target.side == source.side or not target.alive
                        or target.flying or target.untargetable
                        or distance(centre, target.pos)
                            > radius + target.collision_radius_mt):
                    continue
                amount = tower_damage if target.is_tower else damage
                dealt = target.take_damage(amount)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
        self.siege_impacts = pending

    def _tick_hurls(self) -> None:
        still_pending = []
        for source in self.hurl_pending:
            if not source.alive:
                continue
            candidates = [target for target in self.entities.values()
                          if (target.side != source.side and target.alive
                              and not target.is_building and not target.is_tower
                              and not target.untargetable
                              and not target.ignore_pushback
                              and not target.spell_captured
                              and distance(source.pos, target.pos)
                                  <= source.ability_hurl_radius_mt
                                  + target.collision_radius_mt)]
            if not candidates:
                still_pending.append(source)
                continue
            # Client selector: HighestCurrentHpIncludeShields. Stable distance
            # and UID tie-breakers keep deterministic RL rollouts.
            target = min(candidates, key=lambda unit: (
                -(unit.hitpoints + unit.shield_hitpoints),
                distance(source.pos, unit.pos), unit.uid))
            direction = 1 if target.pos.x < arena.WIDTH // 2 else -1
            end = arena.clamp_to_arena(Point(
                target.pos.x + direction * source.ability_hurl_distance_mt,
                target.pos.y))
            push_ms = self.now_ms + source.ability_hurl_delay_ms
            landing_ms = push_ms + source.ability_hurl_flight_ms
            self.hurl_events.append([
                push_ms, landing_ms, source, target, target.pos, end, False])
            source.control_cast_until_ms = max(
                source.control_cast_until_ms, self.now_ms + 800)
        self.hurl_pending = still_pending

        active = []
        for push_ms, landing_ms, source, target, start, end, started in self.hurl_events:
            if not target.alive:
                continue
            if not started and self.now_ms >= push_ms:
                started = True
                target.spell_captured = True
                target.target_uid = None
                target.state = IDLE
                target.forced_move_until_ms = max(
                    target.forced_move_until_ms,
                    push_ms + source.ability_hurl_stun_ms)
                target.buff_until_ms = max(
                    target.buff_until_ms,
                    push_ms + source.ability_hurl_stun_ms)
                target.buff_speed_pct = -100
                target.buff_hit_speed_pct = -100
                self.forced_moves.append(
                    [target, start, end, push_ms, landing_ms])
            if self.now_ms < landing_ms:
                active.append([
                    push_ms, landing_ms, source, target, start, end, started])
                continue
            target.spell_captured = False
            target.pos = end
            # The thrown troop always takes the landing hit, including air;
            # the spawned landing area itself uses GroundCharacterTargets.
            victims = [target]
            victims.extend(other for other in self.entities.values()
                           if (other.uid != target.uid
                               and other.side != source.side and other.alive
                               and not other.flying and not other.is_building
                               and distance(end, other.pos)
                                   <= source.ability_hurl_damage_radius_mt
                                   + other.collision_radius_mt))
            for victim in victims:
                if not victim.alive:
                    continue
                dealt = victim.take_damage(source.ability_hurl_damage)
                self.damage_log.append(
                    (self.now_ms, source.uid, victim.uid, dealt))
        self.hurl_events = active

    def _resolve_on_hit_spawns(self) -> None:
        if not self.on_hit_spawn_events:
            return
        pending = []
        for due_ms, parent_uid, character in self.on_hit_spawn_events:
            if due_ms > self.now_ms:
                pending.append([due_ms, parent_uid, character])
                continue
            parent = self.get(parent_uid)
            if parent is None or not parent.alive or self.unit_lookup is None:
                continue
            if parent.group_max_size > 0:
                living = sum(1 for member in self.entities.values()
                             if member.alive
                             and member.spawn_group_uid == parent.spawn_group_uid)
                if living >= parent.group_max_size:
                    continue
            spec = self.unit_lookup(character)
            if spec is None:
                continue
            child = make_unit(0, spec, parent.side, parent.pos, self.now_ms)
            child.spawn_group_uid = parent.spawn_group_uid
            self.add(child)
        self.on_hit_spawn_events = pending

    def _resolve_projectiles(self) -> None:
        """Land every shot whose flight time has elapsed.

        These are only projectiles which the client explicitly marks Homing,
        so they follow the target rather than being dodged. A shot whose target
        dies mid-flight is simply wasted, which is why overkill on a dying unit
        is not free.
        """
        if not self.in_flight:
            return
        still_flying = []
        for shot in self.in_flight:
            arrival, src, tgt_uid, amount = shot[:4]
            reflection_count = int(shot[4]) if len(shot) > 4 else 0
            reflected_speed = int(shot[5]) if len(shot) > 5 else 0
            if arrival > self.now_ms:
                still_flying.append(shot)
                continue
            tgt = self.entities.get(tgt_uid)
            if tgt is None or not tgt.alive:
                if self.diagnostics is not None:
                    reason = ("homing_target_lost" if src.projectile_homing
                              else "target_lost")
                    self.diagnostics.emit(
                        "projectile_lost", source=src, target_uid=tgt_uid,
                        value=amount, reason=reason,
                        metadata={"arrival_ms": arrival})
                continue          # the target died first; the shot is wasted
            defender = next((entity for entity in self.entities.values()
                             if entity.alive and entity.side == tgt.side
                             and entity.deflect_radius_mt > 0
                             and entity.deflect_from_ms <= self.now_ms
                                 < entity.deflect_until_ms
                             and distance(entity.pos, tgt.pos)
                                 <= entity.deflect_radius_mt
                                    + tgt.collision_radius_mt), None)
            # Not every shot can be sent back. `DeflectBehaviour = "NoDeflect"`
            # is declared on twenty-three projectiles - Princess, Electro
            # Dragon, Mega Knight, the spirits - and the engine reflected all
            # of them, handing Monk a mechanic the client denies him.
            if "NoDeflect" in src.projectile_deflect_behaviour:
                defender = None
            if defender is not None and reflection_count < 2 and src.alive:
                # Some shots hurt whoever sends them back. Firecracker declares
                # `ActionOnDeflector` for 25, so catching her fireworks costs
                # the Monk something rather than being free.
                if src.projectile_deflector_damage > 0:
                    dealt = defender.take_damage(src.projectile_deflector_damage)
                    self.damage_log.append(
                        (self.now_ms, src.uid, defender.uid, dealt))
                reflected = amount * (25 if src.is_tower else 100) // 100
                speed = max(1, reflected_speed or src.projectile_speed_mt_per_sec)
                flight = distance(tgt.pos, src.pos) * 1000 // speed
                still_flying.append([
                    self.now_ms + flight, defender, src.uid, reflected,
                    reflection_count + 1, speed])
                continue
            self._land(src, tgt, amount)
            if self.diagnostics is not None:
                self.diagnostics.emit(
                    "projectile_impact", source=src, target=tgt, value=amount,
                    reason="target_hit", metadata={"arrival_ms": arrival})
        self.in_flight = still_flying

    def _resolve_projectile_areas(self) -> None:
        if not self.projectile_area_events:
            return
        from .gamedata import load_buffs
        pending = []
        for event in self.projectile_area_events:
            (due_ms, source, carrier, amount, radius, buff, buff_ms,
             hits_ground, hits_air) = event
            if due_ms > self.now_ms:
                pending.append(event)
                continue
            centre = carrier.pos
            # Wizard Hero drops a mini tornado beside the damage. Spawned as a
            # real area so it drags for its declared half second rather than
            # once; see `_spawn_attack_attraction` for the same shape.
            if source.projectile_area_attract_percentage > 0:
                from .spells import SpellSpec
                pull_ms = source.projectile_area_attract_duration_ms or 500
                self.areas.append([
                    SpellSpec(
                        name=f"{source.name}_hit_tornado", damage=0,
                        radius_mt=source.projectile_area_attract_radius_mt,
                        radius_y_mt=source.projectile_area_attract_radius_mt,
                        crown_tower_percent=0, pushback_mt=0,
                        life_duration_ms=pull_ms, hit_frequency_ms=pull_ms,
                        attract_percentage=(
                            source.projectile_area_attract_percentage),
                    ),
                    centre, source.side, self.now_ms + pull_ms,
                    self.now_ms + pull_ms, None])
            speed_pct, hit_pct, heal = load_buffs().get(buff, (0, 0, 0))
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or target.untargetable
                        or (target.flying and not hits_air)
                        or (not target.flying and not hits_ground)
                        or distance(centre, target.pos)
                            > radius + target.collision_radius_mt):
                    continue
                if buff and buff_ms > 0:
                    target.buff_until_ms = max(target.buff_until_ms,
                                               self.now_ms + buff_ms)
                    target.buff_speed_pct = speed_pct
                    target.buff_hit_speed_pct = hit_pct
                    target.buff_heal_per_second = heal
                    if hit_pct <= -100:
                        target.ramp_target_uid = None
                        target.ramp_started_ms = 0
                dealt = target.take_damage(amount)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
        self.projectile_area_events = pending

    def _apply_target_poison(self, source: Entity, carrier: Entity) -> None:
        """Attach or advance a source-declared target-bound poison.

        Dart count belongs to the source/carrier pair, not the carrier alone.
        Crown Towers remain on tier one and their controller is refreshed for
        the published duration by each dart.
        """
        if (not source.target_poison_damage_tiers
                or source.target_poison_radius_mt <= 0
                or source.target_poison_interval_ms <= 0):
            return
        key = (source.uid, carrier.uid)
        controller = self.target_poison_controllers.get(key)
        if controller is None:
            controller = [
                source, carrier, 0,
                self.now_ms + source.target_poison_first_tick_ms,
                0, [],
            ]
            self.target_poison_controllers[key] = controller
        # RoyaleAPI's frame-by-frame example establishes that a dart's tier
        # contribution activates after the same 1.25 s delay as its poison,
        # rather than upgrading an already-scheduled pulse immediately.
        controller[5].append(
            self.now_ms + source.target_poison_first_tick_ms)
        if carrier.is_tower:
            controller[4] = max(
                controller[4],
                self.now_ms + source.target_poison_tower_duration_ms)

    def _tick_target_poisons(self) -> None:
        if not self.target_poison_controllers:
            return
        for key, controller in list(self.target_poison_controllers.items()):
            (source, carrier, dart_count, next_tick_ms, tower_expiry_ms,
             pending_activations) = controller
            if (carrier.is_tower and self.now_ms >= tower_expiry_ms):
                del self.target_poison_controllers[key]
                continue
            if not carrier.alive:
                del self.target_poison_controllers[key]
                continue
            if self.now_ms < next_tick_ms:
                continue

            activated = sum(1 for due in pending_activations
                            if due <= self.now_ms)
            if activated:
                controller[2] += activated
                controller[5] = [due for due in pending_activations
                                 if due > self.now_ms]
                dart_count = controller[2]

            tier = 0
            if not carrier.is_tower:
                for threshold in source.target_poison_stack_thresholds[1:]:
                    if dart_count < threshold:
                        break
                    tier += 1
            tier = min(tier, len(source.target_poison_damage_tiers) - 1)
            amount = source.target_poison_damage_tiers[tier]
            centre = carrier.pos
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or target.ability_digging
                        or distance(centre, target.pos)
                            > source.target_poison_radius_mt
                                + target.collision_radius_mt):
                    continue
                hit = amount
                if target.is_tower:
                    hit = hit * source.target_poison_tower_pct // 100
                dealt = target.take_damage(hit)
                source.damage_dealt += dealt
                self.damage_log.append((self.now_ms, source.uid, target.uid, dealt))
            # Preserve phase under coarse ticks rather than accumulating drift.
            while controller[3] <= self.now_ms:
                controller[3] += source.target_poison_interval_ms

    def _spawn_periodic_rage_area(self, source: Entity, centre: Point) -> None:
        from .spells import SpellSpec
        spec = SpellSpec(
            name=f"{source.name}_rage_trail", damage=0,
            radius_mt=source.periodic_ranged_area_radius_mt,
            radius_y_mt=source.periodic_ranged_area_radius_mt,
            crown_tower_percent=100, pushback_mt=0,
            life_duration_ms=source.periodic_ranged_area_duration_ms,
            hit_frequency_ms=TICK_MS,
            area_speed_pct=source.periodic_ranged_area_speed_pct,
            area_hit_speed_pct=source.periodic_ranged_area_speed_pct,
            area_buff_linger_ms=TICK_MS,
            area_only_own_troops=True,
        )
        self.areas.append([
            spec, centre, source.side,
            self.now_ms + source.periodic_ranged_area_duration_ms,
            self.now_ms, None])

    def _tick_rage_spears(self) -> None:
        if not self.rage_spears:
            return
        pending = []
        for event in self.rage_spears:
            arrival, source, target_uid, start, aim, launch, next_trail = event
            interval = max(1, source.periodic_ranged_trail_interval_ms)
            while next_trail < arrival and next_trail <= self.now_ms:
                elapsed = next_trail - launch
                duration = max(1, arrival - launch)
                centre = Point(
                    start.x + (aim.x - start.x) * elapsed // duration,
                    start.y + (aim.y - start.y) * elapsed // duration)
                self._spawn_periodic_rage_area(source, centre)
                next_trail += interval
            event[6] = next_trail
            if arrival > self.now_ms:
                pending.append(event)
                continue
            target = self.get(target_uid)
            if target is not None and target.alive:
                self._land(source, target, source.periodic_ranged_damage)
                self._spawn_periodic_rage_area(source, target.pos)
        self.rage_spears = pending

    def _schedule_container_drop(
            self, source: Entity, offset: tuple[int, int]) -> None:
        ox, oy = (offset + (0, 0))[:2]
        centre = arena.clamp_to_arena(Point(
            source.pos.x + ox, source.pos.y + oy * source.side))
        self.container_drop_events.append([
            self.now_ms + source.container_drop_delay_ms, source, centre])

    def _tick_container_thresholds(self) -> None:
        for source in list(self.entities.values()):
            if (not source.alive or source.container_threshold_dropped
                    or source.container_drop_hp_pct <= 0):
                continue
            if (source.hitpoints * 100
                    > source.max_hitpoints * source.container_drop_hp_pct):
                continue
            source.container_threshold_dropped = True
            self._schedule_container_drop(
                source, source.container_drop_threshold_offset)

    def _resolve_container_drops(self) -> None:
        if not self.container_drop_events:
            return
        pending = []
        for due, source, centre in self.container_drop_events:
            if due > self.now_ms:
                pending.append([due, source, centre])
                continue
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or target.ability_digging
                        or distance(centre, target.pos)
                            > source.container_drop_radius_mt
                                + target.collision_radius_mt):
                    continue
                dealt = target.take_damage(source.container_drop_damage)
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
                if (source.container_drop_pushback_mt > 0 and target.alive
                        and not target.is_building and not target.ignore_pushback):
                    dx, dy = target.pos.x - centre.x, target.pos.y - centre.y
                    span = arena.isqrt(dx * dx + dy * dy) or 1
                    target.pos = arena.clamp_to_arena(Point(
                        target.pos.x + dx * source.container_drop_pushback_mt // span,
                        target.pos.y + dy * source.container_drop_pushback_mt // span))
            if self.unit_lookup is None or not source.container_drop_spawn_character:
                continue
            child_spec = self.unit_lookup(source.container_drop_spawn_character)
            if child_spec is None:
                continue
            count = source.container_drop_spawn_count
            for index in range(count):
                angle = 2 * math.pi * index / max(1, count)
                radius = source.container_drop_spawn_radius_mt
                pos = arena.clamp_to_arena(Point(
                    centre.x + int(radius * math.cos(angle)),
                    centre.y + int(radius * math.sin(angle))))
                child = make_unit(0, child_spec, source.side, pos, self.now_ms)
                # Created before this step's lifetime/deploy decrement; add one
                # tick so the authored 500 ms begins after the landing event.
                child.deploy_remaining_ms = (
                    source.container_drop_spawn_deploy_ms + TICK_MS)
                self.add(child)
        self.container_drop_events = pending

    def _resolve_deploy_barrages(self) -> None:
        if not self.deploy_barrage_events:
            return
        pending = []
        for due, source, centre in self.deploy_barrage_events:
            if due > self.now_ms:
                pending.append([due, source, centre])
                continue
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or target.ability_digging
                        or distance(centre, target.pos)
                            > source.deploy_barrage_radius_mt
                                + target.collision_radius_mt):
                    continue
                amount = (source.deploy_barrage_tower_damage
                          if target.is_tower
                          else source.deploy_barrage_damage)
                dealt = target.take_damage(amount)
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
                if (source.deploy_barrage_pushback_mt > 0 and target.alive
                        and not target.is_building and not target.ignore_pushback):
                    dx, dy = target.pos.x - centre.x, target.pos.y - centre.y
                    span = arena.isqrt(dx * dx + dy * dy) or 1
                    target.pos = arena.clamp_to_arena(Point(
                        target.pos.x + dx * source.deploy_barrage_pushback_mt // span,
                        target.pos.y + dy * source.deploy_barrage_pushback_mt // span))
        self.deploy_barrage_events = pending

    def _tick_control_attacks(self) -> None:
        for source in list(self.entities.values()):
            if (not source.active or source.control_range_mt <= 0
                    or source.control_projectile_speed_mt_per_sec <= 0
                    or self.now_ms < source.control_next_ms):
                continue
            candidates = [target for target in self.entities.values()
                          if target.alive and target.side != source.side
                          and not target.is_building and not target.is_tower
                          and not target.untargetable
                          and distance(source.pos, target.pos)
                              <= source.control_range_mt + target.collision_radius_mt]
            if not candidates:
                continue
            candidates.sort(key=lambda target: (
                distance(source.pos, target.pos), target.uid))
            target = candidates[0]
            flight_ms = (distance(source.pos, target.pos) * 1000
                         // source.control_projectile_speed_mt_per_sec)
            self.control_in_flight.append([
                self.now_ms + source.control_cast_ms + flight_ms,
                source, target.uid])
            source.control_cast_until_ms = self.now_ms + source.control_cast_ms
            source.control_next_ms = self.now_ms + source.control_cooldown_ms

    def _resolve_control_attacks(self) -> None:
        if not self.control_in_flight:
            return
        from .gamedata import load_buffs
        pending = []
        for arrival_ms, source, target_uid in self.control_in_flight:
            if arrival_ms > self.now_ms:
                pending.append([arrival_ms, source, target_uid])
                continue
            target = self.get(target_uid)
            if (target is None or not target.alive or target.dashing
                    or target.ability_dashing):
                continue
            speed_pct, hit_pct, heal = load_buffs().get(
                source.control_buff, (0, 0, 0))
            target.buff_until_ms = max(
                target.buff_until_ms, self.now_ms + source.control_duration_ms)
            target.buff_speed_pct = speed_pct
            target.buff_hit_speed_pct = hit_pct
            target.buff_heal_per_second = heal
            if source.control_grounds_air and target.flying:
                target.grounded_until_ms = max(
                    target.grounded_until_ms,
                    self.now_ms + source.control_duration_ms)
            if hit_pct <= -100:
                target.ramp_target_uid = None
                target.ramp_started_ms = 0
        self.control_in_flight = pending

    def _refresh_wind_area(self, source: Entity) -> None:
        if source.wind_width_mt <= 0 or source.wind_height_mt <= 0:
            return
        self.wind_areas[source.uid] = [
            source, self.now_ms + source.wind_duration_ms, False]

    def _tick_wind_areas(self) -> None:
        for uid, area in list(self.wind_areas.items()):
            source, expires_ms, death_clamped = area
            if not source.alive and not death_clamped:
                expires_ms = min(
                    expires_ms, self.now_ms + source.wind_after_death_ms)
                area[1], area[2] = expires_ms, True
            if self.now_ms >= expires_ms:
                del self.wind_areas[uid]
                continue
            centre = Point(
                source.pos.x,
                source.pos.y - source.side * source.wind_forward_offset_mt)
            half_width = source.wind_width_mt // 2
            half_height = source.wind_height_mt // 2
            for target in self.entities.values():
                if (not target.alive or target.is_building or target.is_tower
                        or abs(target.pos.x - centre.x) > half_width
                        or abs(target.pos.y - centre.y) > half_height):
                    continue
                if target.side == source.side:
                    if target.uid == source.uid or target.wind_width_mt > 0:
                        continue
                    speed_pct = source.wind_ally_speed_pct
                else:
                    speed_pct = source.wind_enemy_speed_pct
                target.buff_until_ms = max(
                    target.buff_until_ms,
                    self.now_ms + source.wind_buff_linger_ms)
                target.buff_speed_pct = speed_pct

    def _start_uppercut(self, source: Entity, target: Entity) -> None:
        towers = [unit.pos for unit in self.entities.values()
                  if unit.alive and unit.is_tower and unit.side == source.side]
        if not towers:
            anchors = (arena.ALLY_PRINCESS if source.side > 0
                       else arena.ENEMY_PRINCESS)
            towers = list(anchors.values())
            towers.append(arena.ALLY_KING if source.side > 0 else arena.ENEMY_KING)
        destination = min(towers, key=lambda point: distance(target.pos, point))
        dx, dy = destination.x - target.pos.x, destination.y - target.pos.y
        span = arena.isqrt(dx * dx + dy * dy) or 1
        end = arena.clamp_to_arena(Point(
            target.pos.x + dx * source.uppercut_push_mt // span,
            target.pos.y + dy * source.uppercut_push_mt // span))
        arrival = self.now_ms + max(1, source.uppercut_flight_ms)
        self.forced_moves.append(
            [target, target.pos, end, self.now_ms, arrival])
        target.forced_move_until_ms = (
            arrival + source.uppercut_root_ms)
        target.target_uid = None
        target.state = IDLE

    def _tick_forced_moves(self) -> None:
        pending = []
        for target, start, end, start_ms, arrival_ms in self.forced_moves:
            if not target.alive:
                continue
            duration = max(1, arrival_ms - start_ms)
            elapsed = min(duration, max(0, self.now_ms - start_ms))
            target.pos = arena.clamp_to_arena(Point(
                start.x + (end.x - start.x) * elapsed // duration,
                start.y + (end.y - start.y) * elapsed // duration))
            if self.now_ms < arrival_ms:
                pending.append([target, start, end, start_ms, arrival_ms])
        self.forced_moves = pending

    def _schedule_chain(self, source: Entity, struck: Entity, hit_index: int,
                        seen: set[int], recent: list[int]) -> None:
        if (not source.chain_unlimited
                and hit_index >= source.chained_hit_count):
            return
        candidates = [target for target in self.entities.values()
                      if target.uid not in recent and target.alive
                      and source.is_valid_target(target, self.now_ms)
                      and (hit_index < source.chain_full_damage_hits
                           or not target.is_tower)
                      and distance(struck.pos, target.pos)
                          <= source.chained_hit_radius_mt]
        if not candidates:
            return
        candidates.sort(key=lambda target: (
            target.uid in seen, distance(struck.pos, target.pos), target.uid))
        target = candidates[0]
        next_index = hit_index + 1
        reduced = (source.chain_unlimited
                   and next_index > source.chain_full_damage_hits)
        amount = source.chain_reduced_damage if reduced else source.damage
        speed = (source.chain_reduced_speed_mt_per_sec if reduced
                 else source.projectile_speed_mt_per_sec)
        flight = distance(struck.pos, target.pos) * 1000 // max(1, speed)
        self.chain_projectiles.append([
            self.now_ms + flight, source, target.uid, amount, next_index,
            set(seen), list(recent)])

    def _resolve_chain_projectiles(self) -> None:
        if not self.chain_projectiles:
            return
        events = self.chain_projectiles
        self.chain_projectiles = []
        pending = []
        for event in events:
            arrival, source, target_uid, amount, hit_index, seen, recent = event
            if arrival > self.now_ms:
                pending.append(event)
                continue
            target = self.get(target_uid)
            if target is None or not target.alive:
                continue
            self._land(source, target, amount, suppress_chain=True,
                       apply_attack_buff=(
                           not source.chain_unlimited
                           or hit_index <= source.chain_full_damage_hits))
            seen.add(target.uid)
            recent.append(target.uid)
            memory = (source.chain_repeat_memory if source.chain_unlimited
                      else max(source.chained_hit_count, len(recent)))
            recent = recent[-memory:] if memory > 0 else []
            self._schedule_chain(source, target, hit_index, seen, recent)
        self.chain_projectiles = pending + self.chain_projectiles

    def start_ability_area(self, source: Entity) -> bool:
        if (source.ability_area_radius_mt <= 0
                or not source.ability_area_pulse_times_ms):
            return False
        pulses = [self.now_ms + delay
                  for delay in source.ability_area_pulse_times_ms]
        self.ability_area_events.append([
            source, self.now_ms + source.ability_area_duration_ms,
            self.now_ms, pulses])
        return True

    def schedule_ability_deploy(self, source: Entity) -> bool:
        if not source.ability_deploy_character or self.unit_lookup is None:
            return False
        if self.unit_lookup(source.ability_deploy_character) is None:
            return False
        self.ability_deploy_events.append([
            self.now_ms + source.ability_deploy_delay_ms, source])
        return True

    def _tick_ability_deploys(self) -> None:
        pending = []
        for due, source in self.ability_deploy_events:
            if due > self.now_ms:
                pending.append([due, source])
                continue
            # "Forward" is toward the opposing towers for either player.
            centre = Point(source.pos.x,
                           source.pos.y - source.side
                           * source.ability_deploy_forward_mt)
            spec = self.unit_lookup(source.ability_deploy_character)
            if spec is None:
                continue
            turret = make_unit(0, spec, source.side, centre, self.now_ms)
            # The event itself represents the building's source DeployTime;
            # do not charge that delay twice after materialising it.
            turret.deploy_remaining_ms = 0
            # This event is resolved before the ordinary entity loop in the
            # same tick; compensate so its first lifetime decrement begins on
            # the following tick, not retroactively before it existed.
            if turret.lifetime_ms > 0:
                turret.lifetime_ms += TICK_MS
            self.add(turret)
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or target.flying or target.uid == turret.uid
                        or distance(centre, target.pos)
                           > source.ability_deploy_radius_mt
                             + target.collision_radius_mt):
                    continue
                dealt = target.take_damage(source.ability_deploy_damage)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
                if source.ability_deploy_pushback_mt and not target.ignore_pushback:
                    dx = target.pos.x - centre.x
                    dy = target.pos.y - centre.y
                    span = max(1, math.isqrt(dx * dx + dy * dy))
                    target.pos = Point(
                        target.pos.x + dx * source.ability_deploy_pushback_mt // span,
                        target.pos.y + dy * source.ability_deploy_pushback_mt // span)
        self.ability_deploy_events = pending

    def schedule_ability_lane_switch(self, source: Entity) -> bool:
        if not source.ability_lane_switch or source.ability_lane_switch_delay_ms <= 0:
            return False
        source.ability_digging = True
        source.target_uid = None
        source.ramp_target_uid = None
        source.ramp_started_ms = 0
        self.ability_lane_switch_events.append([
            self.now_ms + source.ability_lane_switch_delay_ms,
            source, source.pos])
        return True

    def _tick_ability_lane_switches(self) -> None:
        pending = []
        for due, source, origin in self.ability_lane_switch_events:
            if due > self.now_ms:
                pending.append([due, source, origin])
                continue
            if not source.alive:
                continue
            source.pos = Point(arena.WIDTH - origin.x, origin.y)
            source.ability_digging = False
            for target in list(self.entities.values()):
                if (not target.alive or target.side == source.side
                        or distance(origin, target.pos)
                           > source.ability_bomb_radius_mt
                             + target.collision_radius_mt):
                    continue
                dealt = target.take_damage(source.ability_bomb_damage)
                source.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, source.uid, target.uid, dealt))
                if source.ability_bomb_pushback_mt and not target.ignore_pushback:
                    dx = target.pos.x - origin.x
                    dy = target.pos.y - origin.y
                    span = max(1, math.isqrt(dx * dx + dy * dy))
                    # Exactly centred units need a stable direction; the bomb
                    # pushes them away from the arena's vertical centreline.
                    if dx == 0 and dy == 0:
                        dx = -1 if origin.x < arena.WIDTH // 2 else 1
                        span = 1
                    target.pos = Point(
                        target.pos.x + dx * source.ability_bomb_pushback_mt // span,
                        target.pos.y + dy * source.ability_bomb_pushback_mt // span)
        self.ability_lane_switch_events = pending

    def start_ability_link(self, source: Entity) -> bool:
        receiver = next((entity for entity in self.entities.values()
                         if entity.spawn_group_uid == source.spawn_group_uid
                         and entity.name == source.ability_link_target), None)
        endpoint = receiver or self.link_receivers.get(source.spawn_group_uid)
        if endpoint is None or source.ability_link_interval_ms <= 0:
            return False
        self.ability_link_events.append([
            source, endpoint, self.now_ms + source.ability_link_duration_ms,
            self.now_ms + source.ability_link_interval_ms])
        return True

    @staticmethod
    def _within_link(point: Point, start: Point, end: Point, radius: int) -> bool:
        dx, dy = end.x - start.x, end.y - start.y
        px, py = point.x - start.x, point.y - start.y
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            return px * px + py * py <= radius * radius
        dot = px * dx + py * dy
        if dot <= 0:
            return px * px + py * py <= radius * radius
        if dot >= length_sq:
            ex, ey = point.x - end.x, point.y - end.y
            return ex * ex + ey * ey <= radius * radius
        cross = px * dy - py * dx
        return cross * cross <= radius * radius * length_sq

    def _tick_ability_links(self) -> None:
        pending = []
        for source, endpoint, expires, next_hit in self.ability_link_events:
            if not source.alive or self.now_ms > expires:
                continue
            end = endpoint.pos if isinstance(endpoint, Entity) else endpoint
            while next_hit <= self.now_ms and next_hit <= expires:
                for target in list(self.entities.values()):
                    if not target.alive or target.side == source.side:
                        continue
                    radius = source.ability_link_width_mt + target.collision_radius_mt
                    if not self._within_link(target.pos, source.pos, end, radius):
                        continue
                    amount = (source.ability_link_tower_damage if target.is_tower
                              else source.ability_link_damage)
                    dealt = target.take_damage(amount)
                    source.damage_dealt += dealt
                    self.damage_log.append(
                        (next_hit, source.uid, target.uid, dealt))
                next_hit += source.ability_link_interval_ms
            pending.append([source, endpoint, expires, next_hit])
        self.ability_link_events = pending

    def _tick_ability_areas(self) -> None:
        pending = []
        for event in self.ability_area_events:
            source, slow_expires, next_slow, pulses = event
            targets = [target for target in self.entities.values()
                       if target.alive and target.side != source.side
                       and distance(source.pos, target.pos)
                           <= source.ability_area_radius_mt
                               + target.collision_radius_mt]
            if self.now_ms <= slow_expires and self.now_ms >= next_slow:
                for target in targets:
                    target.buff_until_ms = max(
                        target.buff_until_ms,
                        self.now_ms + source.ability_area_slow_linger_ms)
                    target.buff_speed_pct = source.ability_area_slow_pct
                    target.buff_hit_speed_pct = source.ability_area_slow_pct
                event[2] = self.now_ms + TICK_MS
            due = [pulse for pulse in pulses if pulse <= self.now_ms]
            if due:
                for _ in due:
                    for target in targets:
                        amount = source.ability_area_damage
                        if target.is_tower:
                            amount = amount * 5 // 100
                        dealt = target.take_damage(amount)
                        source.damage_dealt += dealt
                        self.damage_log.append(
                            (self.now_ms, source.uid, target.uid, dealt))
                event[3] = [pulse for pulse in pulses if pulse > self.now_ms]
            if event[3] or self.now_ms <= slow_expires:
                pending.append(event)
        self.ability_area_events = pending

    def _resolve_spell_impacts(self) -> None:
        if not self.spell_impacts:
            return
        from .spells import apply_spell
        pending = []
        for due_ms, spec, at, side in self.spell_impacts:
            if due_ms > self.now_ms:
                pending.append([due_ms, spec, at, side])
                continue
            dealt = apply_spell(self, spec, at, side)
            self.resolved_spell_damage[side] = (
                self.resolved_spell_damage.get(side, 0) + dealt)
        self.spell_impacts = pending

    def _resolve_spell_spawns(self) -> None:
        if not self.spell_spawn_events:
            return
        pending = []
        for due_ms, spec, centre, side, raw_x, raw_y in self.spell_spawn_events:
            if due_ms > self.now_ms:
                pending.append([due_ms, spec, centre, side, raw_x, raw_y])
                continue
            unit_spec = self.unit_lookup(spec.area_spawn_character) if self.unit_lookup else None
            if unit_spec is None:
                continue
            x_direction = -1 if centre.x > arena.WIDTH // 2 else 1
            team_direction = 1 if side > 0 else -1
            pos = arena.clamp_to_arena(Point(
                centre.x + raw_x * x_direction,
                centre.y - raw_y * team_direction))
            spawned = make_unit(0, unit_spec, side, pos, self.now_ms)
            if spec.area_spawn_deploy_time_ms > 0:
                spawned.deploy_remaining_ms = spec.area_spawn_deploy_time_ms
            self.add(spawned)
        self.spell_spawn_events = pending

    def _tick_rolling_spells(self, dt_ms: int) -> None:
        """Sweep Log/Barbarian Barrel hitboxes along their client range."""
        if not self.rolling_spells:
            return
        still = []
        for spec, head, side, travelled, hit_uids, captured_uids in self.rolling_spells:
            direction = -1 if side > 0 else 1
            remaining = max(0, spec.rolling_range_mt - travelled)
            rolling_speed = (spec.rolling_speed_mt_per_sec
                             or spec.projectile_speed_mt_per_sec)
            step = min(remaining, rolling_speed * dt_ms // 1000)
            old_y = head.y
            new_head = arena.clamp_to_arena(Point(head.x, head.y + direction * step))
            for uid in list(captured_uids):
                captured = self.get(uid)
                if captured is None or not captured.alive:
                    captured_uids.discard(uid)
                    continue
                captured.pos = new_head
            low_y, high_y = sorted((old_y, new_head.y))
            for entity in list(self.entities.values()):
                if (not entity.alive or entity.side == side or entity.untargetable
                        or entity.uid in hit_uids
                        or (entity.flying and not spec.hits_air)
                        or (not entity.flying and not spec.hits_ground)
                        or (entity.is_building and spec.ignore_buildings)):
                    continue
                if abs(entity.pos.x - head.x) > spec.radius_mt + entity.collision_radius_mt:
                    continue
                margin = spec.radius_y_mt + entity.collision_radius_mt
                if entity.pos.y < low_y - margin or entity.pos.y > high_y + margin:
                    continue
                hit_uids.add(entity.uid)
                dealt = entity.take_damage(spec.damage_to(entity))
                self.resolved_spell_damage[side] = (
                    self.resolved_spell_damage.get(side, 0) + dealt)
                self.damage_log.append((self.now_ms, 0, entity.uid, dealt))
                if (spec.target_buff and spec.buff_time_ms > 0 and entity.alive):
                    from .gamedata import load_buffs
                    speed_pct, hit_pct, _ = load_buffs().get(
                        spec.target_buff, (0, 0, 0))
                    entity.buff_until_ms = max(
                        entity.buff_until_ms, self.now_ms + spec.buff_time_ms)
                    entity.buff_speed_pct = speed_pct
                    entity.buff_hit_speed_pct = hit_pct
                if (spec.rolling_captures_troops and entity.alive
                        and not entity.is_building and not entity.is_tower):
                    captured_uids.add(entity.uid)
                    entity.spell_captured = True
                    entity.pos = new_head
                if (spec.pushback_mt > 0 and entity.alive
                        and not entity.is_building and not entity.ignore_pushback):
                    entity.pos = arena.clamp_to_arena(Point(
                        entity.pos.x,
                        entity.pos.y + direction * spec.pushback_mt))
            travelled += step
            if travelled < spec.rolling_range_mt and step > 0:
                still.append([spec, new_head, side, travelled,
                              hit_uids, captured_uids])
                continue
            for uid in captured_uids:
                captured = self.get(uid)
                if captured is None:
                    continue
                captured.spell_captured = False
                captured.pos = new_head
                if spec.rolling_release_slow_ms > 0:
                    captured.buff_until_ms = max(
                        captured.buff_until_ms,
                        self.now_ms + spec.rolling_release_slow_ms)
                    captured.buff_speed_pct = spec.rolling_release_slow_pct
                    captured.buff_hit_speed_pct = spec.rolling_release_slow_pct
            if spec.spawn_character and self.unit_lookup is not None:
                unit_spec = self.unit_lookup(spec.spawn_character)
                if unit_spec is not None:
                    spawned = make_unit(0, unit_spec, side, new_head, self.now_ms)
                    if spec.spawn_deploy_time_ms > 0:
                        spawned.deploy_remaining_ms = spec.spawn_deploy_time_ms
                    self.add(spawned)
        self.rolling_spells = still

    def _resolve_spell_pulses(self) -> None:
        if not self.spell_pulse_events:
            return
        from dataclasses import replace
        from .spells import apply_spell
        pending = []
        for due_ms, spec, at, side, radius_mt, damage_pct in self.spell_pulse_events:
            if due_ms > self.now_ms:
                pending.append([due_ms, spec, at, side, radius_mt, damage_pct])
                continue
            pulse = replace(
                spec, radius_mt=radius_mt, radius_y_mt=radius_mt,
                damage=spec.damage * damage_pct // 100,
                tower_damage_override=(spec.tower_damage_override * damage_pct // 100),
                pulse_events=())
            dealt = apply_spell(self, pulse, at, side)
            self.resolved_spell_damage[side] = (
                self.resolved_spell_damage.get(side, 0) + dealt)
        self.spell_pulse_events = pending

    def _resolve_pulls(self, dt_ms: int) -> None:
        if self.pull_flight:
            still_flying = []
            for arrival, src_uid, tgt_uid in self.pull_flight:
                if arrival > self.now_ms:
                    still_flying.append([arrival, src_uid, tgt_uid])
                    continue
                src, tgt = self.get(src_uid), self.get(tgt_uid)
                if src is not None and tgt is not None and src.alive and tgt.alive:
                    if (not tgt.is_building and src.pull_buff_ms > 0
                            and src.pull_speed_pct):
                        tgt.buff_until_ms = max(tgt.buff_until_ms,
                                                self.now_ms + src.pull_buff_ms)
                        tgt.buff_speed_pct = src.pull_speed_pct
                        tgt.buff_hit_speed_pct = src.pull_speed_pct
                    self.active_pulls.append([src_uid, tgt_uid])
            self.pull_flight = still_flying
        if not self.active_pulls:
            return
        still_active = []
        for src_uid, tgt_uid in self.active_pulls:
            src, tgt = self.get(src_uid), self.get(tgt_uid)
            if src is None or tgt is None or not src.alive or not tgt.alive:
                continue
            # The hook drags a troop to Fisherman, but drags Fisherman to a
            # building. `DragBackAsAttractor`, `DragBackSpeed`,
            # `DragSelfSpeed`, and `DragMargin` are all client fields.
            mover = src if tgt.is_building else tgt
            speed = src.pull_self_speed_mt_per_sec if tgt.is_building else src.pull_target_speed_mt_per_sec
            dx, dy = src.pos.x - tgt.pos.x, src.pos.y - tgt.pos.y
            if mover is src:
                dx, dy = -dx, -dy
            gap = arena.isqrt(dx * dx + dy * dy)
            stop_gap = src.collision_radius_mt + tgt.collision_radius_mt + src.pull_margin_mt
            if speed <= 0 or gap <= stop_gap:
                continue
            step = min(gap - stop_gap, speed * dt_ms // 1000)
            if step <= 0:
                still_active.append([src_uid, tgt_uid])
                continue
            mover.pos = arena.clamp_to_arena(Point(
                mover.pos.x + dx * step // gap,
                mover.pos.y + dy * step // gap))
            if gap - step > stop_gap:
                still_active.append([src_uid, tgt_uid])
        self.active_pulls = still_active

    def start_ability_dash_chain(self, entity: Entity) -> bool:
        """Start Golden Knight's data-declared ground-target dash chain."""
        if entity.ability_dash_range_mt <= 0 or entity.ability_dash_count <= 0:
            return False
        entity.ability_dashing = True
        self.ability_dash_chains.append([entity.uid, entity.ability_dash_count,
                                         set(), self.now_ms])
        return True

    def schedule_ability_guard(self, entity: Entity) -> bool:
        target = self.get(entity.target_uid)
        if (target is None or not target.alive or not entity.ability_spawn_character
                or entity.ability_pushback_radius_mt <= 0):
            return False
        self.ability_guard_events.append([
            self.now_ms + entity.ability_cast_ms + entity.ability_action_delay_ms,
            entity.uid, target.uid])
        return True

    def _tick_ability_guards(self) -> None:
        pending = []
        for due, caster_uid, target_uid in self.ability_guard_events:
            if due > self.now_ms:
                pending.append([due, caster_uid, target_uid])
                continue
            caster, target = self.get(caster_uid), self.get(target_uid)
            if caster is None or target is None or not caster.alive or not target.alive:
                continue
            # ActionSpawnGuard says AppearBehindAtDistance.  With no exposed
            # target-facing vector in client data, use the caster->target line
            # as the explicit, deterministic approximation and keep it local.
            dx, dy = target.pos.x - caster.pos.x, target.pos.y - caster.pos.y
            span = arena.isqrt(dx * dx + dy * dy) or 1
            centre = arena.clamp_to_arena(Point(
                target.pos.x + dx * caster.ability_appear_behind_mt // span,
                target.pos.y + dy * caster.ability_appear_behind_mt // span))
            spec = self.unit_lookup(caster.ability_spawn_character) if self.unit_lookup else None
            if spec is not None:
                self.add(make_unit(0, spec, caster.side, centre, self.now_ms))
            for other in list(self.entities.values()):
                if (other.side == caster.side or not other.alive or other.is_building
                        or other.flying or other.ignore_pushback
                        or distance(centre, other.pos) > caster.ability_pushback_radius_mt):
                    continue
                dealt = other.take_damage(caster.ability_pushback_damage)
                self.damage_log.append((self.now_ms, caster.uid, other.uid, dealt))
                vx, vy = other.pos.x - centre.x, other.pos.y - centre.y
                length = arena.isqrt(vx * vx + vy * vy) or 1
                other.pos = arena.clamp_to_arena(Point(
                    other.pos.x + vx * caster.ability_pushback_strength_mt // length,
                    other.pos.y + vy * caster.ability_pushback_strength_mt // length))
        self.ability_guard_events = pending

    def _tick_ability_dash_chains(self) -> None:
        if not self.ability_dash_chains:
            return
        still = []
        for uid, remaining, seen, due_ms in self.ability_dash_chains:
            entity = self.get(uid)
            if entity is None or not entity.alive:
                continue
            if self.now_ms < due_ms:
                still.append([uid, remaining, seen, due_ms])
                continue
            candidates = [other for other in self.entities.values()
                          if other.uid not in seen and other.alive
                          and not other.is_building and not other.flying
                          and entity.is_valid_target(other, self.now_ms)
                          and distance(entity.pos, other.pos) <= entity.ability_dash_range_mt]
            if not candidates or remaining <= 0:
                entity.ability_dashing = False
                continue
            candidates.sort(key=lambda other: (distance(entity.pos, other.pos), other.uid))
            target = candidates[0]
            seen.add(target.uid)
            # DashToTargetRadius means the landing point is at the target
            # edge, not centre. The effect is invulnerable while this state is
            # active; contact separation will settle the final exact position.
            dx, dy = target.pos.x - entity.pos.x, target.pos.y - entity.pos.y
            span = arena.isqrt(dx * dx + dy * dy) or 1
            reach = entity.range_mt + target.collision_radius_mt
            entity.pos = arena.clamp_to_arena(Point(
                target.pos.x - dx * reach // span,
                target.pos.y - dy * reach // span))
            self._land(entity, target, entity.dash_damage or entity.damage)
            if entity.dash_pushback_mt > 0:
                self._shove(entity.pos, entity.dash_pushback_mt, entity.side)
            remaining -= 1
            next_due = self.now_ms + max(1, entity.ability_dash_landing_ms)
            if remaining > 0:
                still.append([uid, remaining, seen, next_due])
            else:
                entity.ability_dashing = False
        self.ability_dash_chains = still

    def get(self, uid: Optional[int]) -> Optional[Entity]:
        return self.entities.get(uid) if uid is not None else None

    def living(self, side: Optional[int] = None) -> List[Entity]:
        return [e for e in self.entities.values()
                if e.alive and (side is None or e.side == side)]

    # ------------------------------------------------------------------ tick

    def step(self, dt_ms: int = TICK_MS) -> None:
        self.now_ms += dt_ms
        if self.diagnostics is not None:
            self.diagnostics.begin_tick(self.now_ms, dt_ms)
            self.diagnostics.set_phase("scheduled_effects")
        for entity in self.entities.values():
            if 0 < entity.invulnerable_until_ms <= self.now_ms:
                entity.invulnerable_until_ms = 0
            if 0 < entity.unkillable_until_ms <= self.now_ms:
                entity.unkillable_until_ms = 0
                entity.buff_damage_pct = 0
                entity.buff_tower_damage_pct = 0
        self._resolve_spell_impacts()
        self._resolve_spell_spawns()
        self._resolve_on_hit_spawns()
        self._resolve_starting_summon_damage()
        self._resolve_level_ups()
        self._tick_taunts()
        self._tick_splits()
        self._tick_rerolls()
        self._tick_spins(dt_ms)
        self._tick_reinforcements()
        self._tick_linked_ability_carriers()
        self._tick_parries()
        self._tick_ability_warps()
        self._tick_delayed_self_buffs()
        self._tick_temporary_forms()
        self._tick_rolling_spells(dt_ms)
        self._resolve_spell_pulses()
        self._resolve_shield_lost_effects()
        self._resolve_on_damage_effects()
        self._resolve_projectiles()
        self._resolve_projectile_areas()
        self._resolve_siege_impacts()
        self._tick_target_poisons()
        self._tick_rage_spears()
        self._resolve_container_drops()
        self._resolve_deploy_barrages()
        self._resolve_control_attacks()
        self._tick_control_attacks()
        self._resolve_chain_projectiles()
        self._resolve_pulls(dt_ms)
        self._tick_ability_guards()
        self._tick_ability_dash_chains()
        self._tick_ability_areas()
        self._tick_ability_deploys()
        self._tick_ability_lane_switches()
        self._tick_ability_links()
        self._tick_drill_relocation()
        self._tick_ability_summons()
        self._tick_paratroopers()
        self._tick_areas()
        self._tick_area_attraction(dt_ms)
        self._tick_wind_areas()
        self._tick_hurls()
        self._tick_forced_moves()
        self._tick_captures()
        self._tick_quests(dt_ms)
        self._tick_threshold_spawners()
        self._tick_container_thresholds()
        self._tick_grounding()
        self._tick_transformations()
        if self.diagnostics is not None:
            self.diagnostics.capture_damage(self.damage_log, self.entities)
            self.diagnostics.set_phase("deploy")
        units = [e for e in self.entities.values() if e.alive]

        for entity in units:
            if entity.attached_to_uid is not None:
                carrier = self.get(entity.attached_to_uid)
                if carrier is None or not carrier.alive:
                    entity.hitpoints = 0
                    entity.state = DEAD
                    continue
                entity.pos = carrier.pos
            if entity.deploy_remaining_ms > 0:
                entity.deploy_remaining_ms -= dt_ms
            if (entity.deploy_remaining_ms <= 0 and not entity.spawn_area_done
                    and entity.spawn_area_radius_mt > 0):
                self._spawn_area(entity)
            # Units with a LifeTime expire on their own - a Tombstone or an
            # Ice Golem's spawned bits are on a clock, not just hitpoints.
            if (entity.buff_heal_per_second and entity.buffed(self.now_ms)
                    and entity.alive):
                entity.heal(entity.buff_heal_per_second * dt_ms // 1000)
            if not entity.buffed(self.now_ms):
                entity.damage_reduction_pct = 0
                entity.buff_max_hitpoints_pct = 100
            if entity.lifetime_ms > 0:
                entity.lifetime_ms -= dt_ms
                if entity.lifetime_ms <= 0:
                    entity.hitpoints = 0
                    entity.state = DEAD

        active = [e for e in units
                  if (e.active and self.now_ms >= e.control_cast_until_ms
                      and self.now_ms >= e.forced_move_until_ms
                      and not e.ability_digging)]
        if self.diagnostics is not None:
            self.diagnostics.set_phase("targeting")
        for entity in active:
            self._acquire_target(entity)

        # Knight evolution's fortification is active while it is not in
        # attack range. The source opts into attack-range evaluation, so a
        # distant acquired target does not prematurely remove the protection.
        for entity in active:
            if not entity.idle_damage_reduction_pct:
                continue
            target = self.get(entity.target_uid)
            attacking = bool(target and target.alive and distance(entity.pos, target.pos)
                             <= entity.range_mt + target.collision_radius_mt)
            if not attacking:
                entity.damage_reduction_pct = max(
                    entity.damage_reduction_pct, entity.idle_damage_reduction_pct)
            elif not entity.buffed(self.now_ms):
                entity.damage_reduction_pct = 0

        for entity in active:
            self._dash(entity, dt_ms)

        if self.diagnostics is not None:
            self.diagnostics.set_phase("attack")
        moved: List[Entity] = []
        for entity in active:
            if entity.dashing or entity.ability_dashing:
                continue            # crossing the gap; it does neither
            if not self._attack(entity, dt_ms):
                # Load time is how long the weapon takes to be ready, and it
                # runs down while the unit walks. Only counting it inside
                # attack range made every troop stand at its target for another
                # windup after arriving - an Ice Golem that had walked ten
                # seconds still owed 1.5s before its first swing, which is the
                # difference between dying at the tower and landing a hit on it.
                if entity.windup_remaining_ms > 0 and entity.target_uid is not None:
                    entity.windup_remaining_ms -= dt_ms
                moved.append(entity)
        self._resolve_shield_lost_effects()
        self._resolve_on_damage_effects()
        if self.diagnostics is not None:
            self.diagnostics.capture_damage(self.damage_log, self.entities)
            self.diagnostics.set_phase("movement")
        for entity in moved:
            if entity.attached_to_uid is not None:
                continue
            self._move(entity, dt_ms)

        self._tick_hot_spawners(dt_ms)
        self._tick_spawners(dt_ms)

        # Carriers move after their rider has attacked, so re-sync the visual
        # and physical location before collision resolution.
        for entity in active:
            if entity.attached_to_uid is not None:
                carrier = self.get(entity.attached_to_uid)
                if carrier is not None and carrier.alive:
                    entity.pos = carrier.pos

        # Everything standing on the ground, which is not the same set as the
        # ones taking actions. A unit still deploying occupies space in the
        # real game, and excluding it let a freshly dropped Skeleton sit half a
        # tile inside a Cannon until its deploy timer ran out.
        #
        # A unit mid-ability is a different case and stays excluded: something
        # being hurled by a Hero Giant, dragged by a Fisherman, or tunnelling
        # is not a body to be shoved off its path, and separating those moved
        # a thrown troop off its declared landing tile.
        held = {entity.captured_uid for entity in units
                if getattr(entity, "captured_uid", 0)}
        settled = [e for e in units
                   if e.alive and self.now_ms >= e.control_cast_until_ms
                   and self.now_ms >= e.forced_move_until_ms
                   and not e.ability_digging
                   and not e.spell_captured
                   and e.uid not in held]
        if self.diagnostics is not None:
            self.diagnostics.set_phase("collision")
        self._separate(settled)
        if self.diagnostics is not None:
            self.diagnostics.set_phase("cleanup")
        self._reap()
        if self.diagnostics is not None:
            self.diagnostics.capture_damage(self.damage_log, self.entities)
            self.diagnostics.emit("tick_end", reason="step_complete")

    def _resolve_shield_lost_effects(self) -> None:
        for source in list(self.entities.values()):
            if not source.shield_lost_effect_pending:
                continue
            source.shield_lost_effect_pending = False
            for other in list(self.entities.values()):
                if (other.uid == source.uid or other.side == source.side
                        or not other.alive):
                    continue
                if distance(source.pos, other.pos) > (
                        source.shield_lost_area_radius_mt
                        + other.collision_radius_mt):
                    continue
                dealt = other.take_damage(source.shield_lost_area_damage)
                self.damage_log.append(
                    (self.now_ms, source.uid, other.uid, dealt))
                if (source.shield_lost_area_pushback_mt > 0 and other.alive
                        and not other.is_building and not other.ignore_pushback):
                    dx, dy = other.pos.x - source.pos.x, other.pos.y - source.pos.y
                    span = arena.isqrt(dx * dx + dy * dy) or 1
                    other.pos = arena.clamp_to_arena(Point(
                        other.pos.x + dx * source.shield_lost_area_pushback_mt // span,
                        other.pos.y + dy * source.shield_lost_area_pushback_mt // span))

    def _resolve_on_damage_effects(self) -> None:
        for entity in self.entities.values():
            if not entity.on_damage_effect_pending:
                continue
            entity.on_damage_effect_pending = False
            expires = self.now_ms + entity.on_damage_invulnerable_ms
            entity.invulnerable_until_ms = expires
            entity.buff_until_ms = max(entity.buff_until_ms, expires)
            entity.buff_speed_pct = entity.on_damage_speed_pct
            entity.buff_hit_speed_pct = entity.on_damage_hit_speed_pct
            if entity.on_damage_invisible:
                entity.buff_invisible_until_ms = max(
                    entity.buff_invisible_until_ms, expires)

    def _tick_transformations(self) -> None:
        """Apply client ActionChangeGameObjectData health transformations."""
        if self.unit_lookup is None:
            return
        for uid, entity in list(self.entities.items()):
            if (not entity.alive or entity.transformed
                    or entity.transform_at_hp_pct <= 0
                    or not entity.transform_character):
                continue
            if entity.hitpoints * 100 > entity.max_hitpoints * entity.transform_at_hp_pct:
                continue
            spec = self.unit_lookup(entity.transform_character)
            if spec is None:
                continue
            transformed = make_unit(uid, spec, entity.side, entity.pos, self.now_ms)
            # A transformation changes data/model, not remaining damage. Keep
            # the live health fraction and combat ownership while switching the
            # movement/building capabilities to the new client character.
            transformed.hitpoints = min(transformed.max_hitpoints,
                                        max(1, entity.hitpoints))
            transformed.deploy_remaining_ms = 0
            transformed.target_uid = entity.target_uid
            transformed.transformed = True
            self.entities[uid] = transformed

    def _spawn_area(self, source: Entity) -> None:
        """Resolve a source-declared deployment AEO exactly once.

        This is deliberately data-driven: the client’s AEO/action relationship
        names the effect and spawned character, instead of an Electro Wizard
        branch hidden in placement code.
        """
        source.spawn_area_done = True
        from .gamedata import load_buffs
        speed_pct, hit_pct, _heal = load_buffs().get(source.spawn_area_buff, (0, 0, 0))
        for target in list(self.entities.values()):
            if (target.side == source.side or not target.alive or target.untargetable
                    or distance(source.pos, target.pos) > source.spawn_area_radius_mt):
                continue
            amount = (source.spawn_area_tower_damage
                      if target.is_tower and source.spawn_area_tower_damage > 0
                      else source.spawn_area_damage)
            if target.is_tower and source.spawn_area_tower_damage <= 0:
                # Goblin Drill's emergence is an anti-swarm pop and is barred
                # from crown towers outright by `CrownTowerDamagePercent`.
                amount = amount * source.spawn_area_tower_percent // 100
            dealt = target.take_damage(amount)
            source.damage_dealt += dealt
            self.damage_log.append((self.now_ms, source.uid, target.uid, dealt))
            if source.spawn_area_buff_ms > 0 and (speed_pct or hit_pct):
                target.buff_until_ms = max(target.buff_until_ms,
                                           self.now_ms + source.spawn_area_buff_ms)
                target.buff_speed_pct = speed_pct
                target.buff_hit_speed_pct = hit_pct
                if hit_pct <= -100:
                    target.ramp_target_uid = None
                    target.ramp_started_ms = 0

    # -------------------------------------------------------------- targeting

    def _is_sniper_target(self, source: Entity, target: Entity) -> bool:
        if (source.sniper_ammo <= 0 or target.is_tower
                or not source.is_valid_target(target, self.now_ms)):
            return False
        dx = target.pos.x - source.pos.x
        dy = target.pos.y - source.pos.y
        # +1 is the bottom player, whose forward direction is decreasing Y.
        if dy * source.side >= 0:
            return False
        gap = distance(source.pos, target.pos)
        normal_reach = source.range_mt + target.collision_radius_mt
        if gap <= normal_reach:
            return False
        if (gap < source.sniper_min_range_mt
                or gap > source.sniper_max_range_mt + target.collision_radius_mt):
            return False
        return abs(dx) <= source.sniper_side_clip_mt + target.collision_radius_mt

    def _pending_damage(self, target_uid: int) -> int:
        """Damage already committed by homing shots to one target."""
        return sum(int(shot[3]) for shot in self.in_flight
                   if shot[2] == target_uid)

    def _acquire_target(self, entity: Entity) -> None:
        previous_target_uid = entity.target_uid
        if entity.taunted_by_uid and self.now_ms < entity.taunt_until_ms:
            taunter = self.get(entity.taunted_by_uid)
            if (taunter is not None and taunter.alive
                    and entity.is_valid_target(taunter, self.now_ms)):
                entity.target_uid = taunter.uid
                if self.diagnostics is not None and previous_target_uid != taunter.uid:
                    self.diagnostics.emit(
                        "target_acquired", source=entity, target=taunter,
                        value=distance(entity.pos, taunter.pos), reason="taunt",
                        state=entity.state)
                return
        elif entity.taunted_by_uid:
            entity.taunted_by_uid = 0
            entity.taunt_until_ms = 0
        current = self.get(entity.target_uid)
        keep = (
            current is not None
            and current.alive
            and entity.is_valid_target(current, self.now_ms)
            and (distance(entity.pos, current.pos)
                 <= (entity.ability_siege_range_mt if self._siege_active(entity)
                     else entity.sight_range_mt) + current.collision_radius_mt
                 or self._is_sniper_target(entity, current))
        )
        # Re-scanning every entity every tick is the single most expensive
        # thing the engine does, and a unit with no target was doing exactly
        # that. Throttle the full sweep to the retarget interval whether or not
        # a target is currently held, staggered by uid so they do not all sweep
        # on the same tick and spike one frame.
        due = (self.now_ms + entity.uid * TICK_MS) % RETARGET_INTERVAL_MS == 0
        if keep and not due:
            return
        if not keep and not due and entity.target_uid is None                 and entity.last_scan_ms and self.now_ms - entity.last_scan_ms < RETARGET_INTERVAL_MS:
            return
        entity.last_scan_ms = self.now_ms

        # Two different questions, which used to be one. What can this unit
        # *see* right now, and if the answer is nothing, where is it *going*?
        #
        # Picking the globally nearest valid target answered both at once, and
        # got the first one wrong: an Ice Spirit by the right tower would lock
        # onto a troop on the far left purely because no closer enemy existed.
        # Sight range exists precisely so that does not happen.
        best, best_d = None, None
        fallback, fallback_d = None, None
        offlane, offlane_d = None, None
        sniper, sniper_d = None, None
        # Loop-invariant, and this is the hottest loop in the engine: how far
        # the unit can see does not depend on which candidate is being looked
        # at, but it was recomputed for every one of them.
        sight = (entity.ability_siege_range_mt if self._siege_active(entity)
                 else entity.sight_range_mt)
        now_ms = self.now_ms
        own_side = entity.side
        own_pos = entity.pos
        for other in self.entities.values():
            # `is_valid_target` starts with exactly this test, but the call
            # itself is the cost: about half of everything on the field is
            # friendly, and skipping those here avoids a million method calls
            # a match without changing which units pass.
            if other.side == own_side or not other.alive:
                continue
            if not entity.is_valid_target(other, now_ms):
                continue
            if other.invisible(now_ms):
                continue          # nothing can lock onto a vanished unit
            gap = distance(own_pos, other.pos) - other.collision_radius_mt
            if gap <= sight and (best_d is None or gap < best_d):
                best, best_d = other, gap
            # Out of sight, something has to give a unit a destination, or it
            # stands still. Which something depends on what it hunts.
            #
            # A building-targeter - Hog Rider, Giant, Battle Ram - is pulled by
            # any building, and that is the whole point of dropping a Cannon in
            # the middle. Everything else walks at a crown tower and fights
            # whatever it meets on the way.
            #
            # Allowing every troop to be pulled by any building let a Skeleton
            # deployed on the right walk diagonally across the arena to an
            # Inferno Tower at the *left* bridge, because straight-line distance
            # made it marginally the nearest building. Nothing in the real game
            # does that.
            #
            # The same argument applies to a Hog Rider and it was not applied:
            # `target_only_buildings` made *any* building a fallback at *any*
            # distance, so a Hog sent down the right lane at tile (14,26)
            # turned and walked 8.5 tiles across the arena to a Cannon at
            # (3,13) - seventeen tiles away, against a sight range of 9.5.
            # Buildings pull building-targeters through sight range, which is
            # why those cards are given a longer one than everything else;
            # they do not pull from the far corner of the map. Crown towers
            # are exempt because they are not a pull, they are where the unit
            # is going when it can see nothing at all.
            #
            # Crown towers are additionally lane-committed - see
            # `arena.same_lane`. Exempting them from the sight gate above is
            # right, because a unit that can see nothing still has to be
            # walking somewhere; letting them then compete on raw distance was
            # not, because with the near princess tower already down the far
            # lane's tower is nearer than the king, and the unit crosses the
            # whole arena. The far tower stays eligible, but only once this
            # lane has nothing standing.
            pulled_by = (other.is_building if entity.target_only_buildings
                         else other.is_tower)
            if pulled_by:
                if other.is_tower:
                    if arena.same_lane(entity.pos, other.pos):
                        if fallback_d is None or gap < fallback_d:
                            fallback, fallback_d = other, gap
                    elif offlane_d is None or gap < offlane_d:
                        offlane, offlane_d = other, gap
                elif gap <= sight and (fallback_d is None or gap < fallback_d):
                    fallback, fallback_d = other, gap
            if (best is None and self._is_sniper_target(entity, other)
                    and self._pending_damage(other.uid) < other.hitpoints
                    and (sniper_d is None or gap < sniper_d)):
                sniper, sniper_d = other, gap

        if best is None:
            best = sniper or fallback or offlane
        if best is None:
            entity.target_uid = None
            # Nothing attackable, which is not the same as nowhere to go. A
            # unit barred from crown towers - the spirits carry
            # `cannot_target_towers` - found no fallback at all, because the
            # fallback is chosen inside the loop *after* `is_valid_target` has
            # already rejected every tower. So it stopped dead wherever it was
            # standing, usually a stride past the bridge, and stayed there for
            # the rest of the match.
            #
            # This is a destination, not a target: `target_uid` stays None so
            # `_attack` still refuses, and only `_move` reads it.
            entity.walk_target_uid = self._walk_destination(entity)
            if self.diagnostics is not None and previous_target_uid is not None:
                self.diagnostics.emit(
                    "target_lost", source=entity,
                    target_uid=previous_target_uid, reason="no_valid_candidate",
                    state=entity.state,
                    metadata={"walk_target_uid": entity.walk_target_uid})
            return
        entity.walk_target_uid = None
        if best.uid != entity.target_uid:
            entity.target_uid = best.uid
            gap = distance(entity.pos, best.pos)
            entity.windup_remaining_ms = (
                entity.special_load_time_ms
                if (entity.special_range_mt > 0
                    and entity.special_min_range_mt <= gap <= entity.special_range_mt)
                else entity.load_time_ms
            )
            entity.state = MOVING
            if self.diagnostics is not None:
                reason = ("visible_nearest" if best_d is not None
                          else "sniper" if sniper is best else "fallback_building")
                self.diagnostics.emit(
                    "target_acquired", source=entity, target=best,
                    value=gap, reason=reason, state=entity.state,
                    metadata={"sight_mt": sight,
                              "windup_ms": entity.windup_remaining_ms,
                              "previous_target_uid": previous_target_uid})



    def _tick_areas(self) -> None:
        """Keep hurting whatever is standing in a lingering spell.

        A Poison that only fired once on landing is a weak Fireball; the card
        is eight seconds of 36 a second, and a Tornado is a second of 60. Both
        also slow what they touch, through the same buff fields a unit's attack
        uses.
        """
        if not self.areas:
            return
        still = []
        for area in self.areas:
            spec, centre, side, expires_ms, next_tick_ms, selected_uids = area[:6]
            if self.now_ms >= expires_ms:
                continue
            if self.now_ms >= next_tick_ms:
                if getattr(spec, "volley_waves", 0):
                    remaining = area[6]
                    for entity in list(self.entities.values()):
                        if (not entity.alive or entity.side == side or entity.untargetable
                                or (entity.flying and not spec.hits_air)
                                or (not entity.flying and not spec.hits_ground)
                                or (entity.is_building and spec.ignore_buildings)
                                or distance(centre, entity.pos)
                                    > spec.radius_mt + entity.collision_radius_mt):
                            continue
                        amount = (spec.tower_damage_override // spec.volley_waves
                                  if entity.is_tower and spec.tower_damage_override
                                  else spec.damage // spec.volley_waves)
                        dealt = entity.take_damage(amount)
                        self.damage_log.append((self.now_ms, 0, entity.uid, dealt))
                    area[6] = remaining - 1
                    area[4] = self.now_ms + max(1, spec.volley_interval_ms)
                    if area[6] > 0:
                        still.append(area)
                    continue
                if getattr(spec, "sequential_targets", False):
                    seen = selected_uids if selected_uids is not None else set()
                    targets = [entity for entity in self.entities.values()
                               if entity.alive and entity.side != side
                               and not entity.untargetable and entity.uid not in seen
                               and (spec.hits_air if entity.flying else spec.hits_ground)
                               and not (spec.ignore_buildings and entity.is_building)
                               and distance(centre, entity.pos)
                                   <= spec.radius_mt + entity.collision_radius_mt]
                    targets.sort(key=lambda entity: (-entity.hitpoints, entity.uid))
                    if targets:
                        entity = targets[0]
                        seen.add(entity.uid)
                        area[5] = seen
                        dealt = entity.take_damage(spec.damage_to(entity))
                        self.damage_log.append((self.now_ms, 0, entity.uid, dealt))
                        if spec.target_buff and spec.buff_time_ms > 0:
                            from .gamedata import load_buffs
                            speed_pct, hit_pct, _ = load_buffs().get(
                                spec.target_buff, (0, 0, 0))
                            entity.buff_until_ms = max(
                                entity.buff_until_ms,
                                self.now_ms + spec.buff_time_ms)
                            entity.buff_speed_pct = speed_pct
                            entity.buff_hit_speed_pct = hit_pct
                            if hit_pct <= -100:
                                entity.ramp_target_uid = None
                                entity.ramp_started_ms = 0
                    area[4] = self.now_ms + max(1, spec.hit_frequency_ms)
                    if len(seen) < spec.target_limit:
                        still.append(area)
                    continue
                if getattr(spec, "waves", 0):
                    remaining_waves = area[6]
                    targets = [entity for entity in self.entities.values()
                               if entity.alive and entity.side != side
                               and not entity.untargetable
                               and (spec.hits_air if entity.flying else spec.hits_ground)
                               and not (spec.ignore_buildings and entity.is_building)
                               and distance(centre, entity.pos)
                                   <= spec.radius_mt + entity.collision_radius_mt]
                    count = len(targets)
                    tier = 0 if count == 1 else (1 if count <= 4 else 2)
                    for entity in targets:
                        amount = (spec.tower_damage_by_target_count[tier]
                                  if entity.is_tower
                                  else spec.damage_by_target_count[tier])
                        dealt = entity.take_damage(amount)
                        self.damage_log.append((self.now_ms, 0, entity.uid, dealt))
                    area[6] = remaining_waves - 1
                    area[4] = self.now_ms + spec.wave_interval_ms
                    if area[6] > 0:
                        still.append(area)
                    continue
                if getattr(spec, "area_spawn_character", ""):
                    # A Graveyard drips skeletons for as long as it lasts.
                    period = max(100, spec.area_spawn_period_ms or 1000)
                    if self.unit_lookup is not None:
                        unit_spec = self.unit_lookup(spec.area_spawn_character)
                        if unit_spec is not None:
                            offset = (self.now_ms // period) % 4
                            pos = arena.clamp_to_arena(Point(
                                centre.x + (offset - 2) * 400,
                                centre.y + ((offset % 2) - 1) * 400))
                            self.add(make_unit(0, unit_spec, side, pos, self.now_ms))
                    area[4] = self.now_ms + period
                    still.append(area)
                    continue
                period = max(100, spec.hit_frequency_ms or 1000)
                per_tick = spec.damage_per_second * period // 1000
                candidates = []
                for entity in list(self.entities.values()):
                    if not entity.alive or entity.untargetable:
                        continue
                    wants_own = getattr(spec, "area_only_own_troops", False)
                    if wants_own != (entity.side == side):
                        continue
                    if entity.flying and not getattr(spec, "hits_air", True):
                        continue
                    if not entity.flying and not getattr(spec, "hits_ground", True):
                        continue
                    if entity.is_building and getattr(spec, "ignore_buildings", False):
                        continue
                    if (distance(centre, entity.pos)
                            > spec.radius_mt + entity.collision_radius_mt):
                        continue
                    candidates.append(entity)
                if getattr(spec, "target_limit", 0):
                    if selected_uids is None:
                        if getattr(spec, "target_highest_hitpoints", False):
                            candidates.sort(key=lambda entity: (-entity.hitpoints,
                                                                 entity.uid))
                        selected_uids = {entity.uid for entity in
                                         candidates[:spec.target_limit]}
                        area[5] = selected_uids
                    candidates = [entity for entity in candidates
                                  if entity.uid in selected_uids]
                for entity in candidates:
                    if per_tick > 0:
                        amount = per_tick
                        if entity.is_tower:
                            if getattr(spec, "tower_damage_per_hit", 0):
                                amount = spec.tower_damage_per_hit
                            elif getattr(spec, "tower_damage_override", 0):
                                tick_count = max(1, (spec.life_duration_ms + period - 1)
                                                 // period)
                                amount = spec.tower_damage_override // tick_count
                            else:
                                amount = amount * spec.crown_tower_percent // 100
                        elif entity.is_building:
                            amount = amount * getattr(
                                spec, "building_damage_percent", 100) // 100
                        dealt = entity.take_damage(amount)
                        self.damage_log.append((self.now_ms, 0, entity.uid, dealt))
                    if (getattr(spec, "convert_character", "")
                            and not entity.immune_to(spec.name)
                            and not (entity.is_building and getattr(
                                spec, "conversion_ignore_buildings", False))):
                        entity.cursed_by_side = side
                        entity.cursed_until_ms = self.now_ms + period
                        entity.cursed_spawn = spec.convert_character
                        entity.cursed_spawn_count = max(1, spec.convert_count)
                    if spec.area_speed_pct or spec.area_hit_speed_pct:
                        linger = max(period, getattr(spec, "area_buff_linger_ms", 0))
                        entity.buff_until_ms = max(entity.buff_until_ms,
                                                   self.now_ms + linger)
                        entity.buff_speed_pct = spec.area_speed_pct
                        entity.buff_hit_speed_pct = spec.area_hit_speed_pct
                    if getattr(spec, "grounds_air", False) and entity.flying:
                        entity.grounded_until_ms = max(entity.grounded_until_ms,
                                                       self.now_ms + period)
                area[4] = self.now_ms + period
            still.append(area)
        self.areas = still


    def _bank_souls(self, dying: Entity) -> None:
        """A Skeleton King on the board collects a soul from every troop that dies.

        Either side's troop, anywhere in the arena, and he keeps them after he
        himself is gone - so a King who dies with eight banked still summons
        fourteen if his ability is spent before he falls. Ten is the cap, which
        is what turns his declared floor of six skeletons into the declared
        ceiling of sixteen.

        Towers are not troops and do not count.
        """
        if dying.is_tower:
            return
        for entity in self.entities.values():
            if (entity.ability_summon_max_count > entity.ability_summon_base_count
                    and entity.uid != dying.uid):
                cap = (entity.ability_summon_max_count
                       - entity.ability_summon_base_count)
                if entity.souls < cap:
                    entity.souls += 1

    def schedule_ability_summon(self, source: Entity) -> bool:
        """Raise the Skeleton King's skeletons in a ring around him.

        His whole card is this and the simulator did none of it: the loader
        looked for a buff, a dash or a guard on his ability, found an
        `AreaEffectObject` it had no handling for, and `can_activate_ability`
        refused him outright. A two-elixir champion ability that was simply
        not there.

        The geometry is declared: one skeleton every 250ms after a 250ms delay,
        placed between 2.5 and 3.5 tiles out, six of them plus one per banked
        soul. They are staggered rather than dropped at once because that is
        what the graveyard says and it matters - a swarm that arrives over four
        seconds can be answered mid-summon, one that arrives instantly cannot.
        """
        if not source.ability_summon_character or self.unit_lookup is None:
            return False
        spec = self.unit_lookup(source.ability_summon_character)
        if spec is None:
            return False
        count = min(source.ability_summon_max_count,
                    source.ability_summon_base_count + source.souls)
        if count <= 0:
            return False
        source.souls = 0
        low = source.ability_summon_min_radius_mt or 2500
        high = max(low, source.ability_summon_max_radius_mt or low)
        due = self.now_ms + source.ability_action_delay_ms + (
            source.ability_summon_initial_delay_ms or 0)
        interval = max(1, source.ability_summon_interval_ms or 250)
        for index in range(count):
            # Spread around the circle rather than randomly, so the summon is
            # deterministic. The client randomises the sequence; the positions
            # it draws from are this ring either way.
            angle = 2 * math.pi * index / count
            # Alternate between the inner and outer edge of the declared band,
            # so sixteen skeletons are not all fighting for one circle.
            span = high if index % 2 else low
            self.ability_summons.append([
                due + index * interval, source, spec, angle, span])
        return True

    def _tick_ability_summons(self) -> None:
        if not self.ability_summons:
            return
        pending = []
        for due, source, spec, angle, span in self.ability_summons:
            if due > self.now_ms:
                pending.append([due, source, spec, angle, span])
                continue
            centre = source.pos
            pos = arena.clamp_to_arena(Point(
                centre.x + int(span * math.cos(angle)),
                centre.y + int(span * math.sin(angle))))
            raised = self.add(make_unit(0, spec, source.side, pos, self.now_ms))
            if source.ability_summon_deploy_ms:
                raised.deploy_remaining_ms = source.ability_summon_deploy_ms
        self.ability_summons = pending

    def _tick_area_attraction(self, dt_ms: int) -> None:
        """Drag whatever is standing in a Tornado toward its centre.

        The engine had no attraction at all, which made Tornado a second of
        weak damage. Repositioning *is* the card - pulling a Hog off the tower,
        stacking a swarm for a Fireball, dragging troops onto the king - and
        none of it happened. The number is declared: `AttractPercentage` on the
        buff, 360 for Tornado, 300 for Evolved Valkyrie's spin, 250 for Wizard
        Hero's, read as a pull speed in percent of one tile per second.

        Published behaviour is "up to 3.5 tiles per second" against a declared
        3.6, and the gap is the documented resistance: a unit walking away from
        the centre keeps walking, so its own movement eats into the drag. That
        falls out of applying the pull as a displacement alongside normal
        movement rather than overriding it, so it is not modelled separately.

        Buildings and towers do not move. Mass is not modelled: `PushMassFactor`
        is not declared on any of the three attractors, and inventing one would
        be worse than leaving the pull uniform.
        """
        if not self.areas:
            return
        for area in self.areas:
            spec, centre, side = area[0], area[1], area[2]
            pull = getattr(spec, "attract_percentage", 0)
            if not pull or self.now_ms >= area[3]:
                continue
            # Percent of a tile per second, over this tick.
            step = pull * MT * dt_ms // (100 * 1000)
            if step <= 0:
                continue
            for entity in self.entities.values():
                if (not entity.alive or entity.side == side or entity.is_building
                        or entity.is_tower or entity.untargetable
                        or entity.spell_captured
                        or self.now_ms < entity.forced_move_until_ms):
                    continue
                if entity.flying and not getattr(spec, "hits_air", True):
                    continue
                if not entity.flying and not getattr(spec, "hits_ground", True):
                    continue
                gap = distance(centre, entity.pos)
                if gap > spec.radius_mt + entity.collision_radius_mt:
                    continue
                if gap == 0:
                    continue
                moved = min(step, gap)
                entity.pos = arena.clamp_to_arena(Point(
                    entity.pos.x + (centre.x - entity.pos.x) * moved // gap,
                    entity.pos.y + (centre.y - entity.pos.y) * moved // gap))

    def _reflect(self, struck: Entity, attacker: Entity) -> None:
        """An Electro Giant answers whatever hits it.

        Everything hostile within ReflectedAttackRadius takes
        ReflectedAttackDamage and a stun, not only the unit that landed the
        blow - which is why piling melee onto one is a mistake.
        """
        if struck.reflect_damage <= 0 or not struck.alive:
            return
        from .gamedata import load_buffs
        speed_pct, hit_pct, _heal = load_buffs().get(struck.reflect_buff, (0, 0, 0))
        for other in list(self.entities.values()):
            if other.side == struck.side or not other.alive or other.is_tower:
                continue
            if distance(struck.pos, other.pos) > struck.reflect_radius_mt:
                continue
            dealt = other.take_damage(struck.reflect_damage)
            self.damage_log.append((self.now_ms, struck.uid, other.uid, dealt))
            if struck.reflect_buff_ms > 0 and (speed_pct or hit_pct):
                other.buff_until_ms = max(other.buff_until_ms,
                                          self.now_ms + struck.reflect_buff_ms)
                other.buff_speed_pct = speed_pct
                other.buff_hit_speed_pct = hit_pct

    # ------------------------------------------------------------------- dash

    def _dash(self, entity: Entity, dt_ms: int) -> None:
        """Cross the gap to a target that is neither adjacent nor far away.

        A Bandit picks a target between DashMinRange and DashMaxRange, crosses
        untouchable, and lands DashDamage instead of an ordinary hit. Without
        it she was a fast melee unit, which gets the whole family of counters
        wrong: the point of the dash is that a spell aimed at her misses.
        """
        if entity.dash_max_range_mt <= 0:
            return
        target = self.get(entity.target_uid)

        if entity.dashing:
            if target is None or not target.alive:
                entity.dashing = False
                return
            reach = entity.range_mt + target.collision_radius_mt
            gap = distance(entity.pos, target.pos)
            if gap <= reach:
                # Arrived. The dash hit replaces the normal one and starts the
                # cooldown, so a Bandit cannot dash every swing.
                entity.dashing = False
                entity.dash_ready_at_ms = self.now_ms + entity.dash_cooldown_ms
                self._land(entity, target, entity.dash_damage or entity.damage)
                if entity.dash_radius_mt > 0:
                    for other in list(self.entities.values()):
                        if other.uid == target.uid or not entity.is_valid_target(other, self.now_ms):
                            continue
                        if distance(target.pos, other.pos) <= entity.dash_radius_mt:
                            entity.damage_dealt += other.take_damage(
                                entity.dash_damage or entity.damage)
                if entity.dash_pushback_mt > 0:
                    self._shove(entity.pos, entity.dash_pushback_mt, entity.side)
                return
            # still crossing, at several times walking pace
            step = max(1, entity.speed_mt_per_sec * 4 * dt_ms // 1000)
            dx, dy = target.pos.x - entity.pos.x, target.pos.y - entity.pos.y
            span = arena.isqrt(dx * dx + dy * dy) or 1
            entity.pos = arena.clamp_to_arena(
                Point(entity.pos.x + dx * step // span,
                      entity.pos.y + dy * step // span))
            return

        if self.now_ms < entity.dash_ready_at_ms or target is None or not target.alive:
            return
        gap = distance(entity.pos, target.pos)
        if entity.dash_min_range_mt <= gap <= entity.dash_max_range_mt:
            entity.dashing = True

    def _shove(self, centre: Point, force_mt: int, side: int) -> None:
        """Push enemies away from a point - a Mega Knight's landing."""
        for other in list(self.entities.values()):
            if (other.side == side or not other.alive or other.is_building
                    or other.ignore_pushback):
                continue
            dx, dy = other.pos.x - centre.x, other.pos.y - centre.y
            span = arena.isqrt(dx * dx + dy * dy)
            if span == 0 or span > force_mt * 2:
                continue
            other.pos = arena.clamp_to_arena(
                Point(other.pos.x + dx * force_mt // span,
                      other.pos.y + dy * force_mt // span))

    # --------------------------------------------------------------- attacking

    def _attack(self, entity: Entity, dt_ms: int) -> bool:
        """Returns True when the entity spent this tick attacking."""
        target = self.get(entity.target_uid)
        if target is None or not target.alive:
            return False
        gap = distance(entity.pos, target.pos)
        uses_siege = self._siege_active(entity)
        reach = ((entity.ability_siege_range_mt if uses_siege else entity.range_mt)
                 + target.collision_radius_mt)
        uses_sniper = self._is_sniper_target(entity, target)
        uses_pull = (entity.special_range_mt > 0
                     and entity.special_min_range_mt <= gap <= entity.special_range_mt
                     and entity.pull_projectile_speed_mt_per_sec > 0)
        uses_periodic_ranged = (
            entity.periodic_ranged_damage > 0
            and entity.periodic_ranged_projectile_speed_mt_per_sec > 0
            and self.now_ms >= entity.periodic_ranged_next_ms
            and not target.flying
            and entity.periodic_ranged_min_mt <= gap
            and gap <= entity.periodic_ranged_max_mt + target.collision_radius_mt)
        if (gap > reach and not uses_pull and not uses_sniper
                and not uses_periodic_ranged):
            return False
        if entity.ground_on_attack and entity.ground_character:
            self._start_grounding(entity)
            return True

        # Decrement first, then test, so a timer of exactly N ticks takes N
        # ticks. Testing first spent one extra tick per cycle: a Musketeer on a
        # 1000ms hit speed fired every 1050ms. The error is a fixed tick rather
        # than a fixed share, so it fell hardest on the fastest attackers -
        # roughly 3% off a Giant's damage but 17% off Skeletons - which is a
        # thumb on the scale in precisely the swarm-versus-tank comparisons the
        # simulator gets used for.
        if entity.attack_cooldown_ms > 0:
            entity.attack_cooldown_ms -= dt_ms
            if entity.attack_cooldown_ms > 0:
                entity.state = ATTACKING
                if self.diagnostics is not None:
                    self.diagnostics.emit(
                        "attack_timing", source=entity, target=target,
                        value=entity.attack_cooldown_ms, reason="cooldown",
                        state=entity.state, metadata={"gap_mt": gap})
                return True
        if entity.windup_remaining_ms > 0:
            entity.windup_remaining_ms -= dt_ms
            if entity.windup_remaining_ms > 0:
                entity.state = WINDUP
                if self.diagnostics is not None:
                    self.diagnostics.emit(
                        "attack_timing", source=entity, target=target,
                        value=entity.windup_remaining_ms, reason="windup",
                        state=entity.state, metadata={"gap_mt": gap})
                return True
        if self.diagnostics is not None:
            fired = ("siege" if uses_siege
                     else "periodic_ranged" if uses_periodic_ranged
                     else "pull" if uses_pull else "hit_cycle")
            self.diagnostics.emit(
                "attack_timing", source=entity, target=target, value=gap,
                reason=fired, state=entity.state,
                metadata={"reach_mt": reach, "sniper": bool(uses_sniper)})

        # A frozen unit is stopped mid-swing: -100 hit speed means the cycle
        # never completes while the buff holds.
        if entity.buffed(self.now_ms) and entity.buff_hit_speed_pct <= -100:
            entity.state = ATTACKING
            return True

        if uses_siege:
            speed = max(1, entity.ability_siege_projectile_speed_mt_per_sec)
            flight = gap * 1000 // speed
            self.siege_impacts.append([
                self.now_ms + flight, entity, target.pos,
                entity.ability_siege_damage,
                entity.ability_siege_tower_damage,
                entity.ability_siege_radius_mt])
        elif uses_periodic_ranged:
            speed = entity.periodic_ranged_projectile_speed_mt_per_sec
            flight = gap * 1000 // speed
            self.rage_spears.append([
                self.now_ms + flight, entity, target.uid,
                entity.pos, target.pos, self.now_ms,
                self.now_ms + entity.periodic_ranged_trail_delay_ms])
            cooldown = entity.periodic_ranged_cooldown_ms
            if entity.buffed(self.now_ms) and entity.buff_hit_speed_pct:
                cooldown = cooldown * 100 // max(
                    1, 100 + entity.buff_hit_speed_pct)
            entity.periodic_ranged_next_ms = self.now_ms + cooldown
        elif uses_pull:
            flight = gap * 1000 // entity.pull_projectile_speed_mt_per_sec
            self.pull_flight.append([self.now_ms + flight, entity.uid, target.uid])
        else:
            self._deal_damage(entity, target)
            if entity.attack_area_radius_mt > 0:
                self._attack_area_effect(entity)
        if entity.attack_self_pushback_mt > 0:
            dx = entity.pos.x - target.pos.x
            dy = entity.pos.y - target.pos.y
            span = arena.isqrt(dx * dx + dy * dy) or 1
            entity.pos = arena.clamp_to_arena(Point(
                entity.pos.x + dx * entity.attack_self_pushback_mt // span,
                entity.pos.y + dy * entity.attack_self_pushback_mt // span))
        if entity.kamikaze:
            # One hit and gone. Its death effects still fire, which is the
            # whole point of a Fire Spirit or a Skeleton Barrel.
            entity.hitpoints = 0
            entity.state = DEAD
            return True
        cooldown = ((entity.ability_siege_hit_speed_ms or entity.hit_speed_ms)
                    if uses_siege else entity.hit_speed_ms)
        if entity.buffed(self.now_ms) and entity.buff_hit_speed_pct:
            cooldown = cooldown * 100 // max(1, 100 + entity.buff_hit_speed_pct)
        entity.attack_cooldown_ms = cooldown
        entity.state = ATTACKING
        # `RetargetAfterAttack` is a real per-unit flag in the client data, so
        # this replaces part of the fixed 500ms sweep with the game's own rule.
        # What the flag means exactly is inferred rather than documented: the
        # reading here is "re-pick a target once this hit lands", which is why
        # splash units drift onto whatever is nearest rather than tunnelling on
        # one victim. The remaining periodic sweep still covers everything else.
        if entity.retarget_after_attack:
            entity.target_uid = None
        return True

    # A drill placed this close to a crown tower is "next to" it, and
    # resurfaces a quarter turn around it rather than in place. The client says
    # only `UseDistanceBasedPositioning = true`; this distance is the one
    # number here that no source states, so it is named rather than buried.
    DRILL_TOWER_REACH_MT = 4000

    def _tick_drill_relocation(self) -> None:
        """Evolved Goblin Drill goes back under when it is hurt enough.

        Its evolution is entirely this: at 66% and again at 33% hitpoints it
        drops out of the fight for a second, leaving goblins behind - two the
        first time, one the second - and comes back up somewhere else with its
        emergence burst. None of it happened, so the evolution was a Goblin
        Drill with an evolution slot spent on nothing.

        Everything but the destination is declared on
        `ActionGoblinDrillEvoRelocate`. Where it comes back is published
        behaviour rather than data: in the same spot, unless it was placed
        beside a crown tower, in which case it surfaces ninety degrees around
        that tower - which is what makes it awkward to answer, since whatever
        was hitting it is now on the wrong side.
        """
        for entity in list(self.entities.values()):
            if not entity.hide_hp_thresholds or not entity.alive:
                continue
            if entity.hidden_until_ms:
                if self.now_ms < entity.hidden_until_ms:
                    continue
                entity.hidden_until_ms = 0
                entity.ability_digging = False
                entity.spawn_area_done = False      # it surfaces hitting again
                continue
            if entity.hides_used >= len(entity.hide_hp_thresholds):
                continue
            threshold = entity.hide_hp_thresholds[entity.hides_used]
            if entity.hitpoints * 100 > entity.max_hitpoints * threshold:
                continue
            self._drill_go_under(entity)

    def _drill_go_under(self, entity: Entity) -> None:
        counts = entity.hide_goblin_counts
        leaving = counts[entity.hides_used] if entity.hides_used < len(counts) else 0
        if entity.hide_spawn_character and self.unit_lookup is not None:
            spec = self.unit_lookup(entity.hide_spawn_character)
            if spec is not None:
                offset = entity.hide_spawn_offset_mt or 1000
                for index in range(leaving):
                    # RelativeX of -1 and +1 tiles, as the hide groups declare.
                    side_step = offset if index % 2 else -offset
                    self.add(make_unit(
                        0, spec, entity.side,
                        arena.clamp_to_arena(Point(entity.pos.x + side_step,
                                                   entity.pos.y)),
                        self.now_ms))
        entity.hides_used += 1
        entity.hidden_until_ms = self.now_ms + (entity.hide_time_ms or 1000)
        # `ability_digging` is already what "underground and unreachable"
        # means to `untargetable`, which is exactly where the drill goes.
        entity.ability_digging = True
        entity.target_uid = None
        entity.pos = self._drill_resurface_at(entity)

    def _drill_resurface_at(self, entity: Entity) -> Point:
        """Same spot, or a quarter turn around the crown tower it is hugging."""
        towers = (arena.ENEMY_PRINCESS if entity.side > 0
                  else arena.ALLY_PRINCESS)
        for centre in towers.values():
            gap = distance(centre, entity.pos)
            if gap == 0 or gap > self.DRILL_TOWER_REACH_MT:
                continue
            # Rotate ninety degrees about the tower, keeping the same distance.
            rel_x, rel_y = entity.pos.x - centre.x, entity.pos.y - centre.y
            return arena.clamp_to_arena(
                Point(centre.x - rel_y, centre.y + rel_x))
        return entity.pos

    def resolve_drop_target(self, source: Entity) -> Optional[Entity]:
        """The closest ground enemy inside the drop radius, ties on most hitpoints.

        `default_targets_no_towers_no_flying` with
        `RESOLVER_STRATEGY_CLOSEST_TARGET` then
        `RESOLVER_STRATEGY_HIGHEST_CURR_HP`, over a 6500 circle.
        """
        best = None
        for other in self.entities.values():
            if (not other.alive or other.side == source.side or other.is_tower
                    or other.flying or other.untargetable):
                continue
            gap = distance(source.pos, other.pos)
            if gap > source.ability_drop_radius_mt:
                continue
            key = (gap, -other.hitpoints, other.uid)
            if best is None or key < best[0]:
                best = (key, other)
        return best[1] if best else None

    @staticmethod
    def paratrooper_flight_ms(span: int) -> int:
        """How long the dive takes, from the declared speed ramp.

        `BalloonHero_Skeletrooper_Speed_Up_Interval` adds 2 to a counter every
        150ms and overrides the projectile speed to
        `logX10000(max(5, rampup - 1)) / 80`. That is a formula, not a mystery,
        and integrating it is what the action audit called an "accelerated
        payload trajectory" needing calibration.

        The one real unknown is which logarithm `logX10000` means. Natural log
        lands the trooper in 0.9 to 1.5 seconds over the ability's range, which
        is what the published "after a 1-second delay" describes; base ten
        would take 1.5 to 2.7. The choice moves when it lands, never where.
        """
        travelled = 0
        rampup = 0
        elapsed = 0
        while travelled < span and elapsed < 10_000:
            elapsed += 150
            rampup += 2
            # Client speed units convert the same way every projectile does.
            speed = math.log(max(5, rampup - 1)) * 10_000 / 80 * 1000 / 60
            travelled += speed * 150 / 1000
        return max(TICK_MS, elapsed)

    def schedule_paratrooper(self, source: Entity) -> bool:
        """Drop a Skeletrooper on the nearest ground target, or straight down.

        Balloon Hero's whole ability, and it did nothing at all: the loader
        never followed an `ActionSpawn` of `ProjectileType` into the character
        its projectile carries, so two elixir bought an animation.

        With nothing in range the trooper lands under the balloon rather than
        being wasted, which is the published behaviour and also the only
        sensible reading of an ability that costs elixir up front.
        """
        if not source.ability_drop_character or self.unit_lookup is None:
            return False
        spec = self.unit_lookup(source.ability_drop_character)
        if spec is None:
            return False
        target = self.resolve_drop_target(source)
        landing = target.pos if target is not None else source.pos
        # The dive covers the height he drops from as well as the ground
        # distance, so a trooper landing directly below still falls.
        flight = self.paratrooper_flight_ms(
            distance(source.pos, landing) + source.ability_drop_height_mt)
        self.paratroopers.append([self.now_ms + flight, source, spec, landing])
        return True

    def _tick_paratroopers(self) -> None:
        if not self.paratroopers:
            return
        pending = []
        for due, source, spec, landing in self.paratroopers:
            if due > self.now_ms:
                pending.append([due, source, spec, landing])
                continue
            trooper = make_unit(0, spec, source.side,
                                arena.clamp_to_arena(landing), self.now_ms)
            # The dive was the deploy; it lands ready, and its own landing
            # burst fires through the ordinary spawn-area path.
            trooper.deploy_remaining_ms = source.ability_drop_deploy_ms
            self.add(trooper)
        self.paratroopers = pending

    def _maybe_special_attack(self, entity: Entity, target: Entity) -> None:
        """Evolved Princess's ice arrow, every third shot starting with the first.

        Her evolution is the slow field and she was firing ordinary arrows
        every time, so it was a Princess with nothing added. The field is
        declared - three tiles, 5500ms, `IceWizardSlowDown` at -30% move and
        hit speed - on the projectile of attack sequence index 1; only the
        cadence is published rather than shipped, because
        `Princess_EV1_reload_frequency` is a VARIABLE the client never assigns.

        Spawned as an ordinary lingering area so it slows whatever walks into
        it later, not only what was standing there when the arrow landed -
        which is the difference between a slow and a splash.
        """
        count = entity.special_attack_count
        entity.special_attack_count += 1
        if count % entity.special_attack_every != 0:
            return
        from .gamedata import load_buffs
        from .spells import SpellSpec
        speed_pct, hit_pct, _heal = load_buffs().get(
            entity.special_area_buff, (0, 0, 0))
        if not (speed_pct or hit_pct):
            return
        duration = entity.special_area_duration_ms or 1
        self.areas.append([
            SpellSpec(
                name=f"{entity.name}_ice_field", damage=0,
                radius_mt=entity.special_attack_radius_mt,
                radius_y_mt=entity.special_attack_radius_mt,
                crown_tower_percent=0, pushback_mt=0,
                life_duration_ms=duration,
                hit_frequency_ms=entity.special_area_hit_frequency_ms or 300,
                area_speed_pct=speed_pct,
                area_hit_speed_pct=hit_pct,
                area_buff_linger_ms=entity.special_area_buff_ms,
            ),
            target.pos, entity.side, self.now_ms + duration, self.now_ms, None])

    def _fire_parallel_arrows(self, entity: Entity, target: Entity,
                              projectile_speed: int) -> None:
        """Three arrows abreast for the seven seconds his ability lasts.

        The client declares `ProjectileCount = 2` beside the ordinary shot and
        `ProjectileDistance = 1500`, each arrow carrying Damage 19 down a
        13500 line. Nothing read it, because the declaration hangs off the
        projectile of attack sequence index 1 rather than off the ability, and
        the ability was refused outright for having no declared effect.

        Each arrow is its own piercing line, offset sideways from the aim - so
        the spread catches a wide push rather than three shots at one target,
        which is the whole reason the ability exists.

        What stays approximate is ordering along each line: arrows are resolved
        by distance rather than swept, the same treatment the ordinary pierce
        already gets.
        """
        dx, dy = target.pos.x - entity.pos.x, target.pos.y - entity.pos.y
        length = arena.isqrt(dx * dx + dy * dy) or 1
        # Perpendicular, normalised to the declared spacing.
        spacing = entity.ability_extra_projectile_spacing_mt
        off_x, off_y = -dy * spacing // length, dx * spacing // length
        radius = entity.projectile_radius_mt or 1000
        span = entity.ability_shot_range_mt or entity.projectile_range_mt
        amount = entity.ability_shot_damage or entity.damage

        lanes = [0]
        for index in range(entity.ability_extra_projectiles):
            step = index // 2 + 1
            lanes.append(step if index % 2 == 0 else -step)
        for lane in lanes:
            origin = Point(entity.pos.x + off_x * lane,
                           entity.pos.y + off_y * lane)
            for other in list(self.entities.values()):
                if not entity.is_valid_target(other, self.now_ms):
                    continue
                rel_x, rel_y = other.pos.x - origin.x, other.pos.y - origin.y
                along = (rel_x * dx + rel_y * dy) // length
                if along < 0 or along > span:
                    continue
                perpendicular = abs(rel_x * dy - rel_y * dx) // length
                if perpendicular > radius + other.collision_radius_mt:
                    continue
                flight = along * 1000 // max(1, projectile_speed)
                self.in_flight.append(
                    [self.now_ms + flight, entity, other.uid, amount])

    def _throw_boomerang(self, entity: Entity, target: Entity,
                         projectile_speed: int) -> None:
        """Executioner's axe flies out, comes back, and hurts twice.

        Both Executioner and his evolution throw the same boomerang - the
        client gives them identical geometry, `ProjectileRange = 7000` at
        Speed 550 with a 1000 radius and `PingpongVisualTime = 1500` for the
        round trip - and the simulator threw it at whatever he was aiming at,
        dealt damage once, and stopped there.

        That made a line-clearing card a single-target hit for 70. Anything
        standing behind his target took nothing, and nothing was ever hit
        twice, even though his own card screen states his damage as "70 x2"
        (`OverrideIntValue2 = 2`, `Unit = "INTEGER_TIMES_X"`).

        The axe is resolved geometrically rather than stepped: everything
        inside the corridor is found once, then each victim is scheduled for a
        hit when the axe reaches it on the way out and again when it passes on
        the way back. Out and back over seven tiles at 9166 mt/s comes to
        roughly the declared 1500ms round trip, which is two independent
        numbers agreeing.

        The evolution hits for `StrongDamage` inside `StrongDamageRange` and
        `Damage` beyond it. The client actually declares a hysteresis - strong
        below 2000 outbound, strong again below 3000 inbound - and this uses
        the single 2500 band that the card screen displays. That is a detail
        of where the boundary sits, not of whether the axe returns.
        """
        span = max(1, entity.pingpong_range_mt)
        dx, dy = target.pos.x - entity.pos.x, target.pos.y - entity.pos.y
        length = arena.isqrt(dx * dx + dy * dy) or 1
        radius = entity.pingpong_radius_mt or entity.splash_radius_mt

        for other in list(self.entities.values()):
            if not entity.is_valid_target(other, self.now_ms):
                continue
            rel_x, rel_y = other.pos.x - entity.pos.x, other.pos.y - entity.pos.y
            along = (rel_x * dx + rel_y * dy) // length
            if along < 0 or along > span:
                continue
            perpendicular = abs(rel_x * dy - rel_y * dx) // length
            if perpendicular > radius + other.collision_radius_mt:
                continue

            strong = (entity.pingpong_strong_damage > 0
                      and along <= entity.pingpong_strong_range_mt)
            amount = (entity.pingpong_strong_damage if strong
                      else entity.pingpong_damage)
            if amount <= 0:
                continue
            outbound = along * 1000 // projectile_speed
            inbound = (2 * span - along) * 1000 // projectile_speed
            for delay in (outbound, inbound):
                self.in_flight.append(
                    [self.now_ms + delay, entity, other.uid, amount])

    def _spawn_attack_attraction(self, source: Entity) -> None:
        """Evolved Valkyrie's swing drags what is near her toward her.

        Her evolution is this and nothing else: every attack spawns
        `Valkyrie_MiniTornado_EV1`, a half-second five-tile area declaring
        `AttractPercentage = 300`. The published line is "Evolved Valkyrie draws
        all enemies towards her with each swing"; in the simulator she swung and
        nothing moved.

        Spawned as a real area rather than resolved inline, so it drags for its
        declared half second instead of once, and so the declared `HitsAir` is
        what decides - the inline attack-area path skips flying units outright,
        and this tornado is documented as catching air as well as ground.

        The client says `FollowBehaviour = "FollowParent"`, so the real tornado
        tracks her as she moves. This one is pinned where she swung. Over five
        hundred milliseconds of a slow unit that is a fraction of a tile.
        """
        from .spells import SpellSpec
        duration = source.attack_area_duration_ms or 500
        self.areas.append([
            SpellSpec(
                name=f"{source.name}_attack_tornado", damage=0,
                radius_mt=source.attack_area_radius_mt,
                radius_y_mt=source.attack_area_radius_mt,
                crown_tower_percent=0, pushback_mt=0,
                life_duration_ms=duration,
                hit_frequency_ms=duration,
                attract_percentage=source.attack_area_attract_percentage,
            ),
            source.pos, source.side, self.now_ms + duration,
            self.now_ms + duration, None])

    def _attack_area_effect(self, source: Entity) -> None:
        """Resolve a source-centred AEO spawned by OnAttackAction."""
        if source.attack_area_attract_percentage > 0:
            self._spawn_attack_attraction(source)
        for other in list(self.entities.values()):
            if (other.side == source.side or not other.alive
                    or other.uid == source.uid or other.flying):
                continue
            if distance(source.pos, other.pos) > (
                    source.attack_area_radius_mt + other.collision_radius_mt):
                continue
            if source.attack_area_damage > 0:
                dealt = other.take_damage(source.attack_area_damage)
                self.damage_log.append(
                    (self.now_ms, source.uid, other.uid, dealt))
            if (source.attack_area_pushback_mt > 0 and other.alive
                    and not other.is_building and not other.ignore_pushback):
                dx, dy = other.pos.x - source.pos.x, other.pos.y - source.pos.y
                span = arena.isqrt(dx * dx + dy * dy) or 1
                other.pos = arena.clamp_to_arena(Point(
                    other.pos.x + dx * source.attack_area_pushback_mt // span,
                    other.pos.y + dy * source.attack_area_pushback_mt // span))

    def _deal_damage(self, entity: Entity, target: Entity) -> None:
        # A charging Prince lands DamageSpecial - roughly double - and the
        # charge is spent whether or not the hit killed anything.
        uses_sniper = self._is_sniper_target(entity, target)
        amount = entity.sniper_damage if uses_sniper else entity.damage
        if uses_sniper:
            entity.sniper_ammo -= 1
        if entity.buff_damage_pct:
            amount = amount * (100 + entity.buff_damage_pct) // 100
            if target.is_tower and entity.buff_tower_damage_pct > 0:
                amount = amount * entity.buff_tower_damage_pct // 100
        self._refresh_wind_area(entity)
        if (entity.far_attack_damage > 0 and entity.far_attack_min_range_mt > 0
                and distance(entity.pos, target.pos) >= entity.far_attack_min_range_mt):
            amount = entity.far_attack_damage
        # Inferno-family cards retain a beam on one target.  The source data
        # exposes the three damage stages and both dwell times; tracking that
        # shared primitive also covers Mighty Miner without hard-coded names.
        if entity.persistent_ramp_damages:
            if (entity.persistent_ramp_attack_count > 0
                    and self.now_ms - entity.persistent_ramp_last_attack_ms
                        >= entity.persistent_ramp_decay_ms):
                entity.persistent_ramp_attack_count = 0
            entity.persistent_ramp_attack_count += 1
            tier = 0
            for threshold in entity.persistent_ramp_thresholds:
                if entity.persistent_ramp_attack_count < threshold:
                    break
                tier += 1
            amount = entity.persistent_ramp_damages[
                min(tier, len(entity.persistent_ramp_damages) - 1)]
            entity.persistent_ramp_last_attack_ms = self.now_ms
        elif entity.variable_damage2 > 0 and entity.variable_damage_time1_ms > 0:
            if entity.ramp_target_uid != target.uid:
                entity.ramp_target_uid = target.uid
                entity.ramp_started_ms = self.now_ms
            elapsed = self.now_ms - entity.ramp_started_ms
            if (entity.variable_damage3 > 0
                    and elapsed >= entity.variable_damage_time1_ms + entity.variable_damage_time2_ms):
                amount = entity.variable_damage3
            elif elapsed >= entity.variable_damage_time1_ms:
                amount = entity.variable_damage2
        if entity.charging and entity.damage_special > 0:
            amount = entity.damage_special
        if target.is_tower and entity.tower_damage_pct != 100:
            amount = amount * entity.tower_damage_pct // 100
        entity.charging = False
        entity.charge_distance_mt = 0

        # A ranged attack is a projectile that has to fly. The tower's arrow
        # travels 10 tiles a second, so a shot at the edge of its 7.5 tile
        # range lands most of a second after it is loosed. Applying damage the
        # instant it is fired gave every shooter that time for free, which is
        # enough to decide whether something living on a knife edge - a lone
        # Ice Golem walking into tower fire - reaches its target or not.
        projectile_speed = (entity.sniper_projectile_speed_mt_per_sec
                            if uses_sniper else entity.projectile_speed_mt_per_sec)
        # Elite Barbarian evolution's top-level Projectile belongs only to
        # attack-sequence index 1. Index 0 is the ordinary melee strike.
        if entity.periodic_ranged_damage > 0 and not uses_sniper:
            projectile_speed = 0
        if projectile_speed > 0:
            # A ProjectileRange of one millitile is the client's contact
            # explosion primitive (Wall Breakers), not a freely flying shot.
            # Once the melee attack lands there is no trajectory to calibrate.
            if entity.projectile_range_mt == 1:
                self._land(entity, target, amount)
                return
            # Executioner and his evolution throw an axe that comes back, and
            # it hurts on both legs. See `_throw_boomerang`.
            if entity.pingpong_range_mt > 0:
                self._throw_boomerang(entity, target, projectile_speed)
                return
            # Elite Archer Hero fires in threes while his ability is up.
            if (entity.ability_extra_projectiles > 0
                    and self.now_ms < entity.ability_shots_until_ms):
                self._fire_parallel_arrows(entity, target, projectile_speed)
                return
            targets = [target]
            if entity.pierces and entity.projectile_range_mt > 0:
                # The client projectile supplies both the long travel range and
                # its narrow radius.  A pierced target must lie on the ray in
                # front of the shooter, not merely near the original victim.
                dx, dy = target.pos.x - entity.pos.x, target.pos.y - entity.pos.y
                span = arena.isqrt(dx * dx + dy * dy) or 1
                candidates = []
                for other in self.entities.values():
                    if other.uid == target.uid or not entity.is_valid_target(other, self.now_ms):
                        continue
                    rel_x, rel_y = other.pos.x - entity.pos.x, other.pos.y - entity.pos.y
                    along = (rel_x * dx + rel_y * dy) // span
                    if along < 0 or along > entity.projectile_range_mt:
                        continue
                    perpendicular = abs(rel_x * dy - rel_y * dx) // span
                    if perpendicular <= entity.projectile_radius_mt + other.collision_radius_mt:
                        candidates.append((along, other))
                candidates.sort(key=lambda item: (item[0], item[1].uid))
                targets += [other for _, other in candidates]
            for shot_target in targets:
                flight = (distance(entity.pos, shot_target.pos) * 1000
                          // projectile_speed)
            # Hold the attacker itself, not its uid. A Kamikaze unit is dead
            # before its own shot lands, and looking it up by uid then found
            # nothing and threw the shot away - which silently deleted the Ice
            # Spirit's entire contribution, damage and freeze alike.
                # A fired shot lands. In Clash Royale a projectile that has
                # left the attacker connects with what it was fired at; there
                # is no spatial miss to model. The `Homing` field distinguishes
                # how the shot is drawn and whether it can clip units on the
                # way, not whether it arrives.
                #
                # This branch used to hold non-homing launches back from
                # resolution "until a measured collision rule is available",
                # which was not conservative: it meant 25 shooters - Princess,
                # Bomber, Mortar, Firecracker, Hunter, Bowler, Elite Archer and
                # the rest - dealt no damage whatsoever. A Princess that fires
                # and never hurts anything is a far larger error than a shot
                # placed a few hundred millitiles from its true impact point.
                #
                # The launch record is still kept, because the swept-path
                # geometry genuinely is unmeasured and the action graphs that
                # depend on it still need calibrating. It is now a record of a
                # resolved shot rather than a discarded one.
                self.in_flight.append(
                    [self.now_ms + flight, entity, shot_target.uid, amount])
                if self.diagnostics is not None:
                    self.diagnostics.emit(
                        "projectile_launch", source=entity, target=shot_target,
                        value=amount,
                        reason=("homing" if entity.projectile_homing
                                else "target_snapshot"),
                        metadata={"flight_ms": flight,
                                  "arrival_ms": self.now_ms + flight,
                                  "speed_mt_per_sec": projectile_speed,
                                  "aim": (shot_target.pos.x, shot_target.pos.y)})
                if not entity.projectile_homing:
                    self.unmodelled_projectiles.append({
                        "launch_ms": self.now_ms,
                        "arrival_ms": self.now_ms + flight,
                        "source_uid": entity.uid,
                        "target_uid": shot_target.uid,
                        "start": (entity.pos.x, entity.pos.y),
                        "aim": (shot_target.pos.x, shot_target.pos.y),
                        "amount": amount,
                        "speed_mt_per_sec": projectile_speed,
                        "range_mt": entity.projectile_range_mt,
                        "radius_mt": entity.projectile_radius_mt,
                        "homing": False,
                    })
            return

        self._land(entity, target, amount)

        # `MultipleTargets` is a simultaneous beam/strike, not splash around
        # the first victim.  The client declares the count and AllTargetsHit
        # on the character (for example Electro Wizard has 2 + true).  Use
        # stable distance/uid ordering so replays are deterministic.
        if entity.all_targets_hit and entity.multiple_targets > 1:
            extras = [other for other in self.entities.values()
                      if other.uid != target.uid and entity.is_valid_target(other, self.now_ms)
                      and distance(entity.pos, other.pos)
                          <= entity.range_mt + other.collision_radius_mt]
            extras.sort(key=lambda other: (distance(entity.pos, other.pos), other.uid))
            for other in extras[:entity.multiple_targets - 1]:
                self._land(entity, other, amount)

    def _apply_buff(self, entity: Entity, target: Entity) -> None:
        """Hand the attacker's buff to whatever it just hit.

        An Ice Spirit carries Freeze on its projectile: SpeedMultiplier and
        HitSpeedMultiplier both -100 for 1100ms. Without this it was a cheap
        body that did 43 damage, which is not the card anybody plays.
        """
        if not entity.target_buff or entity.buff_time_ms <= 0:
            return
        from .gamedata import load_buffs, load_death_spawn_buffs
        speed_pct, hit_pct, heal = load_buffs().get(entity.target_buff, (0, 0, 0))
        death_spawn = load_death_spawn_buffs().get(entity.target_buff)
        if speed_pct == 0 and hit_pct == 0 and heal == 0 and not death_spawn:
            return
        target.buff_until_ms = max(target.buff_until_ms,
                                   self.now_ms + entity.buff_time_ms)
        target.buff_speed_pct = speed_pct
        target.buff_hit_speed_pct = hit_pct
        target.buff_heal_per_second = heal
        if death_spawn:
            target.cursed_by_side = entity.side
            target.cursed_until_ms = max(target.cursed_until_ms,
                                         self.now_ms + entity.buff_time_ms)
            target.cursed_spawn, target.cursed_spawn_count = death_spawn
        if hit_pct <= -100:
            # Zap and every stun reset an Inferno/Sparky-style buildup.
            target.ramp_target_uid = None
            target.ramp_started_ms = 0
            target.persistent_ramp_attack_count = 0
            target.persistent_ramp_last_attack_ms = 0

    def _land(self, entity: Entity, target: Entity, amount: int,
              chained_seen: Optional[set[int]] = None, *,
              suppress_chain: bool = False,
              apply_attack_buff: bool = True) -> None:
        # Swinging reveals a Royal Ghost: invisibility is measured from the
        # last attack, so landing one resets the clock.
        entity.last_attacked_ms = self.now_ms
        # Ronin's ActionCounter blocks one targeted ground melee hit, then
        # returns twice that exact blocked amount on the authored delayed
        # timeline. Projectile, flying, spell/deploy and independent AEO
        # damage never enters this branch and therefore cannot trigger it.
        parry_disabled = (target.spell_captured
                          or (target.buffed(self.now_ms)
                              and target.buff_speed_pct <= -100))
        if (target.parry_cooldown_ms > 0
                and self.now_ms >= target.parry_ready_at_ms
                and not parry_disabled and not entity.flying
                and entity.projectile_speed_mt_per_sec <= 0):
            target.parry_ready_at_ms = self.now_ms + target.parry_cooldown_ms
            self.parry_events.append([
                self.now_ms + target.parry_stun_delay_ms,
                self.now_ms + target.parry_damage_delay_ms,
                target, entity, amount * target.parry_damage_pct // 100,
                False])
            self.damage_log.append((self.now_ms, entity.uid, target.uid, 0))
            return
        self._reflect(target, entity)
        if apply_attack_buff:
            self._apply_buff(entity, target)
        dealt = target.take_damage(amount)
        entity.damage_dealt += dealt
        self.damage_log.append((self.now_ms, entity.uid, target.uid, dealt))
        if dealt > 0:
            self._apply_target_poison(entity, target)
            if entity.quest_hit_advance_ms > 0:
                self._advance_quest(entity, entity.quest_hit_advance_ms)
        if entity.special_attack_every > 0:
            self._maybe_special_attack(entity, target)
        if entity.uppercut_every_hits > 0:
            entity.uppercut_attack_count += 1
            if (entity.uppercut_attack_count % entity.uppercut_every_hits == 0
                    and target.alive):
                self._start_uppercut(entity, target)

        if (dealt > 0 and entity.projectile_area_damage > 0
                and entity.projectile_area_radius_mt > 0
                and entity.projectile_area_delay_ms > 0):
            self.projectile_area_events.append([
                self.now_ms + entity.projectile_area_delay_ms,
                entity, target, entity.projectile_area_damage,
                entity.projectile_area_radius_mt, entity.projectile_area_buff,
                entity.projectile_area_buff_ms,
                entity.projectile_area_hits_ground,
                entity.projectile_area_hits_air,
            ])

        # P.E.K.K.A Evolution selects a heal tier from the defeated target's
        # maximum HP. Values and boundaries are versioned from Supercell's
        # published level-11 table; the client independently exposes the same
        # 990/1990 selection conditions and 150% overheal ceiling.
        if (dealt > 0 and not target.alive and entity.kill_heal_amounts):
            tier = 0
            for threshold in entity.kill_heal_thresholds:
                if target.max_hitpoints < threshold:
                    break
                tier += 1
            tier = min(tier, len(entity.kill_heal_amounts) - 1)
            entity.buff_max_hitpoints_pct = entity.kill_heal_overheal_pct
            entity.heal(entity.kill_heal_amounts[tier])

        # Source-declared on-hit self buffs power evolved Barbarians and Bats.
        # Count only landed attacks, and refresh the effect at its threshold.
        if dealt > 0 and entity.buff_after_hits_count > 0:
            entity.buff_after_hits_landed += 1
            if entity.buff_after_hits_landed >= entity.buff_after_hits_count:
                entity.buff_after_hits_landed = 0
                entity.buff_until_ms = max(
                    entity.buff_until_ms,
                    self.now_ms + entity.buff_after_hits_time_ms)
                entity.buff_speed_pct = entity.buff_after_hits_speed_pct
                entity.buff_hit_speed_pct = entity.buff_after_hits_hit_speed_pct
                entity.buff_heal_per_second = entity.buff_after_hits_heal_per_second
                entity.buff_max_hitpoints_pct = entity.buff_after_hits_overheal_pct
                if (entity.buff_after_hits_spawn_character
                        and entity.buff_after_hits_spawn_count > 0):
                    for index in range(entity.buff_after_hits_spawn_count):
                        self.on_hit_spawn_events.append([
                            self.now_ms + entity.buff_after_hits_spawn_interval_ms * (index + 1),
                            entity.uid,
                            entity.buff_after_hits_spawn_character,
                        ])

        if entity.splash_radius_mt > 0:
            for other in self.entities.values():
                # Splash eligibility is broader than primary targeting. The
                # current Spirits cannot acquire a Crown Tower on their own,
                # but their jump still splashes one when triggered by a troop.
                if (other.uid == target.uid or other.side == entity.side
                        or not other.alive or other.untargetable
                        or not entity.can_attack(other, self.now_ms)):
                    continue
                if distance(target.pos, other.pos) <= entity.splash_radius_mt:
                    self._apply_buff(entity, other)
                    entity.damage_dealt += other.take_damage(amount)

        # Chain attacks use the client projectile's count/radius, hopping from
        # the most recently struck target and never returning to an earlier
        # victim.  Electro Dragon and Electro Spirit share this primitive;
        # their stun remains the ordinary source-declared target buff.
        if (not suppress_chain and entity.chained_hit_radius_mt > 0
                and (entity.chained_hit_count > 1 or entity.chain_unlimited)):
            self._schedule_chain(entity, target, 1, {target.uid}, [target.uid])

    # ---------------------------------------------------------------- movement

    def _walk_destination(self, entity: Entity) -> "int | None":
        """The nearest enemy building to advance on when nothing is attackable.

        Deliberately ignores `cannot_target_towers`: that rule stops a unit
        connecting, not walking. Everything else `is_valid_target` checks -
        side, alive, untargetable - still applies, because none of those give
        a unit somewhere to go either.

        A placed building only counts as a destination if the unit can see it,
        for the same reason it only counts as a pull in `_acquire_target`: a
        Cannon in the far lane is not where a unit sent down this one is
        going. Crown towers are always eligible - they are the destination of
        last resort, and in a real match every unit has one to walk at.

        The gate is therefore conditional on there being an alternative. With
        no tower standing and nothing in sight, the far building is not
        competing with the lane, it *is* the only place to go, and gating it
        unconditionally left units standing where they were deployed. That
        cannot happen in a match - a king tower is always there until the game
        ends - but it happens constantly in tests that build a bare arena, and
        a rule that only holds when the arena is fully populated is a rule
        that will be wrong somewhere else later.
        """
        sight = (entity.ability_siege_range_mt if self._siege_active(entity)
                 else entity.sight_range_mt)
        best, best_gap = None, None
        offlane, offlane_gap = None, None
        distant, distant_gap = None, None
        for other in self.entities.values():
            if (other.side == entity.side or not other.alive
                    or not (other.is_building or other.is_tower)
                    or other.untargetable):
                continue
            gap = distance(entity.pos, other.pos) - other.collision_radius_mt
            if other.is_tower:
                # Crown towers are lane-committed; buildings are not. A Cannon
                # dropped in the middle is *meant* to pull a Hog out of either
                # lane, which is why the building case is gated on sight range
                # and not on lane.
                if arena.same_lane(entity.pos, other.pos):
                    if best_gap is None or gap < best_gap:
                        best, best_gap = other, gap
                elif offlane_gap is None or gap < offlane_gap:
                    offlane, offlane_gap = other, gap
            elif gap <= sight:
                if best_gap is None or gap < best_gap:
                    best, best_gap = other, gap
            elif distant_gap is None or gap < distant_gap:
                distant, distant_gap = other, gap
        # The far lane's tower is a real destination and outranks the
        # out-of-sight-building last resort, which exists only so a unit in a
        # bare test arena is not stranded.
        chosen = best or offlane or distant
        return chosen.uid if chosen is not None else None

    def _move(self, entity: Entity, dt_ms: int) -> None:
        if entity.speed_mt_per_sec <= 0:
            entity.state = IDLE
            return
        target = self.get(entity.target_uid)
        if target is None:
            # Nothing to hit, but possibly still somewhere to be.
            target = self.get(entity.walk_target_uid)
        if target is None:
            entity.state = IDLE
            return

        goal = self._waypoint(entity, target)
        speed = entity.speed_mt_per_sec
        if entity.charging and entity.charge_speed_multiplier > 0:
            speed = speed * entity.charge_speed_multiplier // 100
        if entity.buffed(self.now_ms) and entity.buff_speed_pct:
            speed = max(0, speed * (100 + entity.buff_speed_pct) // 100)
        step = speed * dt_ms // 1000
        if step <= 0:
            return
        before_pos = entity.pos
        dx, dy = goal.x - entity.pos.x, goal.y - entity.pos.y
        gap = arena.isqrt(dx * dx + dy * dy)
        if gap == 0:
            return
        # Steer around a building that is in the way but is not what we came
        # for. Making buildings solid without this left units grinding against
        # the side of a tower for ever - a Royal Giant sat behind one and never
        # walked round it, which the real game does.
        dx, dy = self._avoid_buildings(entity, dx, dy, gap, step)
        gap = arena.isqrt(dx * dx + dy * dy) or 1
        if gap <= step:
            entity.pos = Point(entity.pos.x + dx, entity.pos.y + dy)
        else:
            entity.pos = Point(entity.pos.x + dx * step // gap,
                               entity.pos.y + dy * step // gap)
        moved_mt = distance(before_pos, entity.pos)
        entity.pos = arena.clamp_to_arena(entity.pos)
        entity.state = MOVING
        if self.diagnostics is not None and moved_mt:
            self.diagnostics.emit(
                "movement", source=entity, position=entity.pos,
                value=moved_mt, reason="waypoint",
                metadata={"before": (before_pos.x, before_pos.y),
                          "goal": (goal.x, goal.y), "step_mt": step})
        # The charge builds while the unit walks and is spent on its next hit,
        # so a Prince that is answered before it covers the distance never gets
        # the double-damage swing at all - which is the whole point of pulling
        # one off its line.
        if entity.charge_range_mt > 0 and not entity.charging:
            entity.charge_distance_mt += moved_mt
            if entity.charge_distance_mt >= entity.charge_range_mt:
                entity.charging = True
        if not entity.crossed_river and not arena.crosses_river(entity.pos, target.pos):
            entity.crossed_river = True


    def _buildings(self) -> List[Entity]:
        """Living buildings, rebuilt only when the roster changes.

        Both collision and steering want this list every tick, and walking the
        whole entity table twice per unit per tick was costing more than the
        movement it served.
        """
        stamp = len(self.entities)
        if self._buildings_stamp != stamp:
            self._buildings_cache = [e for e in self.entities.values()
                                     if e.alive and e.is_building]
            self._buildings_stamp = stamp
        return self._buildings_cache

    def _obstacles(self, entity: Entity):
        """What this unit has to walk *around* rather than through or into.

        Buildings, always - they are solid and never yield.

        Plus any enemy ground unit it is not allowed to attack. That is the
        case that used to weld a push in place: a Hog Rider targets buildings
        only, so a Skeleton standing in its lane is something it can neither
        hit nor be stopped by, and with no steering the two simply pressed
        into each other until the match ended. Measured before this existed: a
        Hog that reaches a tower in 4.6 seconds never arrived at all against
        one Skeleton, one Ice Golem or one Musketeer. A one-elixir card
        permanently stopping a win condition is not a mechanic the real game
        has, and it is the reason the trained policy defended with Ice Golem -
        in here, that worked perfectly.

        A unit that *can* attack the blocker is deliberately not steered: it
        should stop and fight, which is what a Knight meeting a Barbarian
        does. The asymmetry falls out on its own - the Skeleton can hit the
        Hog and stands its ground, the Hog cannot hit the Skeleton and walks
        round it.
        """
        now_ms = self.now_ms
        for other in self._buildings():
            yield other
        for other in self.entities.values():
            if other.side == entity.side or not other.alive:
                continue
            if other.is_building or other.is_tower or other.flying:
                continue          # buildings came from above; fliers overlap
            if entity.is_valid_target(other, now_ms):
                continue          # something we may attack is not an obstacle
            yield other

    def _avoid_buildings(self, entity: Entity, dx: int, dy: int,
                         gap: int, step: int):
        """Deflect around a blocking building, sliding along its edge.

        Not a pathfinder. It asks one question - is something solid directly in
        front of me that I am not trying to hit - and if so turns the step
        sideways so the unit rounds the corner instead of pressing into it.
        """
        # Whatever we are heading for, we do not steer around it. That is the
        # attack target normally - but a unit with nothing it may attack is
        # walking at `walk_target_uid` instead, and steering around *that* left
        # it orbiting its own destination for ever.
        going_to = {entity.target_uid, entity.walk_target_uid} - {None, 0}
        ahead_x = entity.pos.x + dx * step // gap
        ahead_y = entity.pos.y + dy * step // gap
        for other in self._obstacles(entity):
            if not other.alive:
                continue
            if other.uid in going_to:
                continue          # this is what we came for
            clearance = other.collision_radius_mt + entity.collision_radius_mt
            if distance(Point(ahead_x, ahead_y), other.pos) >= clearance:
                continue
            # Slide along the obstacle: take the perpendicular that points
            # more towards where we were going.
            ox, oy = entity.pos.x - other.pos.x, entity.pos.y - other.pos.y
            options = ((-oy, ox), (oy, -ox))

            # Commit to a side and keep it until clear of this building.
            #
            # Recomputing the choice every tick deadlocks a unit that is
            # directly behind the obstacle: both perpendiculars are exactly
            # sideways to where it wants to go, so both dot products are zero,
            # the tie-break picks one, the unit shifts a little, and next tick
            # the sign flips and it shifts back. Observed as a skeleton behind
            # our own king tower stepping its full 75 millitiles every tick and
            # covering 0.08 tiles in six seconds - moving hard and going
            # nowhere, which is exactly what it looks like in the viewer.
            if entity.avoid_uid == other.uid and entity.avoid_turn:
                index = 0 if entity.avoid_turn > 0 else 1
                return options[index]
            index = 0
            for candidate, (turn_x, turn_y) in enumerate(options):
                if turn_x * dx + turn_y * dy > 0:
                    index = candidate
                    break
            else:
                # Dead astern. Break the tie on the unit's own identity so a
                # crowd splits around the building instead of every one of them
                # queueing on the same side.
                index = entity.uid % 2
            entity.avoid_uid = other.uid
            entity.avoid_turn = 1 if index == 0 else -1
            return options[index]
        entity.avoid_uid = 0
        entity.avoid_turn = 0
        return dx, dy

    def _waypoint(self, entity: Entity, target: Entity) -> Point:
        """Where to walk next.

        Ground units follow a flow field over the tile grid, so the river and
        its two bridges are simply terrain: a unit that has to cross finds a
        bridge because it is the only way through, not because the movement
        code was told to detour to one. Fliers and river-jumpers ignore it.

        Dynamic obstacles - a Cannon dropped mid-field - are not in the field,
        because rebuilding it whenever anything is placed would cost more than
        it saves. Those are handled by the steering step in _move, which is why
        the two exist together.
        """
        if entity.flying:
            return target.pos
        # `JumpEnabled` describes the unit's attack/jump animation and river
        # interaction, not unrestricted terrain traversal. Ground units still
        # have to enter the river through a bridge; otherwise a Hog Rider or
        # Prince could cross anywhere and central buildings would lose their
        # defining pull. Only flying units ignore the bridge terrain here.
        if not arena.crosses_river(entity.pos, target.pos):
            # Same side of the river: head straight and let steering handle
            # anything solid in the way.
            return target.pos

        step = pathfind.next_step(entity.pos, target.pos)
        return step if step is not None else target.pos

    # -------------------------------------------------------------- collision

    def _separate(self, units: List[Entity]) -> None:
        """Push overlapping ground units apart, heavier units yielding less.

        Approximation: one pass of pairwise correction. The real game resolves
        this continuously and mass-weighted; the visible consequence of getting
        it wrong is units bunching where they should spread.
        """
        movers = [u for u in units if not u.is_building and not u.flying
                  and u.attached_to_uid is None]

        # Buildings and towers are solid. They were left out of separation
        # entirely, so ground troops walked straight through the king tower.
        # They never yield, so this pushes only the mover.
        def push_out_of_buildings():
            blockers = self._buildings()
            for mover in movers:
                for block in blockers:
                    min_gap = mover.collision_radius_mt + block.collision_radius_mt
                    dx, dy = mover.pos.x - block.pos.x, mover.pos.y - block.pos.y
                    gap = arena.isqrt(dx * dx + dy * dy)
                    if gap >= min_gap:
                        continue
                    if gap == 0:
                        dx, dy, gap = 1, 0, 1
                    push = min_gap - gap
                    before = mover.pos
                    mover.pos = Point(mover.pos.x + dx * push // gap,
                                      mover.pos.y + dy * push // gap)
                    if self.diagnostics is not None:
                        self.diagnostics.emit(
                            "collision", source=mover, target=block,
                            value=push, reason="building_separation",
                            metadata={"gap_mt": gap,
                                      "required_gap_mt": min_gap,
                                      "normal": (dx, dy),
                                      "before": (before.x, before.y),
                                      "after": (mover.pos.x, mover.pos.y)})
                    if self.trace_contacts:
                        self.contact_trace.append({
                            "time_ms": self.now_ms,
                            "kind": "building_contact",
                            "mover_uid": mover.uid,
                            "blocker_uid": block.uid,
                            "gap_mt": gap,
                            "required_gap_mt": min_gap,
                            "before": (before.x, before.y),
                            "after": (mover.pos.x, mover.pos.y),
                        })

        push_out_of_buildings()

        for _ in range(SEPARATION_PASSES):
            for i, a in enumerate(movers):
                for b in movers[i + 1:]:
                    # Two opposing units that had each other targeted used to be
                    # exempted from separation entirely - "let engaged units
                    # touch" - which meant a fight was two bodies occupying the
                    # same ground, sunk into one another by half a tile. The
                    # exemption is gone: nothing overlaps anything.
                    #
                    # It costs them no reach. A unit's attack range is its own
                    # range plus the *target's* collision radius, so a melee
                    # unit sitting at exactly the separation distance is still
                    # in range - which is the geometry the real game has too.
                    min_gap = a.collision_radius_mt + b.collision_radius_mt
                    dx, dy = b.pos.x - a.pos.x, b.pos.y - a.pos.y
                    gap = arena.isqrt(dx * dx + dy * dy)
                    if gap >= min_gap:
                        continue
                    if gap == 0:
                        # Exactly coincident: there is no direction to push
                        # along, so pick one. Swarm cards spawn several units
                        # on the same point, so this is the common case, not an
                        # edge case - skipping it left them stacked for ever.
                        # Direction and magnitude are kept separate here;
                        # folding them together makes the overlap compute to
                        # zero and the push silently do nothing.
                        dx, dy, norm, overlap_mt = 1, 0, 1, min_gap
                    else:
                        norm, overlap_mt = gap, min_gap - gap
                    overlap = overlap_mt * SEPARATION_STRENGTH // 100
                    total = a.mass + b.mass
                    a_share = overlap * b.mass // total
                    b_share = overlap - a_share
                    a_before, b_before = a.pos, b.pos
                    a.pos = arena.clamp_to_arena(
                        Point(a.pos.x - dx * a_share // norm, a.pos.y - dy * a_share // norm))
                    b.pos = arena.clamp_to_arena(
                        Point(b.pos.x + dx * b_share // norm, b.pos.y + dy * b_share // norm))
                    if self.diagnostics is not None:
                        self.diagnostics.emit(
                            "collision", source=a, target=b, value=overlap,
                            reason=("zero_distance_normal" if gap == 0
                                    else "troop_separation"),
                            metadata={"gap_mt": gap,
                                      "required_gap_mt": min_gap,
                                      "normal": (dx, dy),
                                      "first_before": (a_before.x, a_before.y),
                                      "first_after": (a.pos.x, a.pos.y),
                                      "second_before": (b_before.x, b_before.y),
                                      "second_after": (b.pos.x, b.pos.y)})
                    if self.trace_contacts:
                        self.contact_trace.append({
                            "time_ms": self.now_ms,
                            "kind": "troop_contact",
                            "first_uid": a.uid,
                            "second_uid": b.uid,
                            "gap_mt": gap,
                            "required_gap_mt": min_gap,
                            "resolved_overlap_mt": overlap,
                            "first_before": (a_before.x, a_before.y),
                            "first_after": (a.pos.x, a.pos.y),
                            "second_before": (b_before.x, b_before.y),
                            "second_after": (b.pos.x, b.pos.y),
                        })

        # Enforced last, because a unit pushed off another unit can land
        # inside a building. Buildings never yield, so giving them the final
        # say is what makes "nothing walks through anything" actually hold.
        push_out_of_buildings()

    def _reap(self) -> None:
        for uid, entity in list(self.entities.items()):
            if not entity.alive:
                self._resolve_death(entity)
                if self.diagnostics is not None:
                    self.diagnostics.capture_damage(self.damage_log, self.entities)
                    self.diagnostics.emit(
                        "cleanup", source=entity, position=entity.pos,
                        reason="dead_entity_removed", state=entity.state,
                        metadata={"name": entity.name})
                del self.entities[uid]

    # ------------------------------------------------------- death and spawns

    def _resolve_death(self, entity: Entity) -> None:
        """A unit's death is an event, not just a removal.

        A Golem leaves two Golemites and a blast; a Balloon drops its bomb; an
        Ice Golem explodes. Treating these as plain removals made every one of
        them a smaller card than it is, and made the defences that answer them
        look better than they are.
        """
        if entity.death_resolved:
            return
        entity.death_resolved = True
        if self.diagnostics is not None:
            self.diagnostics.emit(
                "death", source=entity, position=entity.pos,
                value=entity.hitpoints, reason="lethal_or_expired",
                state=entity.state,
                metadata={"name": entity.name,
                          "spawn_character": entity.death_spawn_character,
                          "spawn_count": entity.death_spawn_count})
        if entity.elixir_value and not entity.is_tower:
            killer = -entity.side
            self.elixir_destroyed[killer] = (
                self.elixir_destroyed.get(killer, 0) + entity.elixir_value)
        self._bank_souls(entity)
        if entity.captured_uid:
            self._release_captured(entity)
        if entity.link_receiver_on_death:
            self.link_receivers[entity.spawn_group_uid] = entity.pos

        if entity.container_drop_hp_pct > 0:
            if not entity.container_threshold_dropped:
                entity.container_threshold_dropped = True
                self._schedule_container_drop(
                    entity, entity.container_drop_threshold_offset)
            self._schedule_container_drop(
                entity, entity.container_drop_death_offset)

        if entity.last_group_death_spawn_character and self.unit_lookup is not None:
            marker = (entity.side, entity.spawn_group_uid,
                      entity.last_group_death_spawn_character)
            group_survives = any(
                member.uid != entity.uid and member.alive
                and member.spawn_group_uid == entity.spawn_group_uid
                and member.last_group_death_spawn_character
                == entity.last_group_death_spawn_character
                for member in self.entities.values())
            if not group_survives and marker not in self.resolved_last_group_spawns:
                self.resolved_last_group_spawns.add(marker)
                spec = self.unit_lookup(entity.last_group_death_spawn_character)
                if spec is not None:
                    banner = make_unit(0, spec, entity.side, entity.pos,
                                       self.now_ms)
                    added = self.add(banner)
                    added.spawn_group_uid = entity.spawn_group_uid

        if entity.group_death_kill_character:
            for member in self.entities.values():
                if (member.uid != entity.uid and member.alive
                        and member.spawn_group_uid == entity.spawn_group_uid
                        and member.name == entity.group_death_kill_character):
                    member.hitpoints = 0
                    member.state = DEAD

        if (entity.group_death_spawn_character and self.unit_lookup is not None):
            guard_alive = any(
                member.alive
                and member.spawn_group_uid == entity.spawn_group_uid
                and member.name == entity.group_required_guard_character
                for member in self.entities.values())
            if guard_alive:
                spec = self.unit_lookup(entity.group_death_spawn_character)
                if spec is not None:
                    spectral = make_unit(0, spec, entity.side, entity.pos,
                                         self.now_ms)
                    spectral.spawn_group_uid = entity.spawn_group_uid
                    self.add(spectral)

        if entity.death_damage > 0 and entity.death_damage_radius_mt > 0:
            for other in list(self.entities.values()):
                if other.uid == entity.uid or not other.alive:
                    continue
                if other.side == entity.side:
                    continue          # the blast is hostile only
                if distance(entity.pos, other.pos) <= entity.death_damage_radius_mt:
                    dealt = other.take_damage(entity.death_damage)
                    self.damage_log.append((self.now_ms, entity.uid, other.uid, dealt))
                    if (entity.death_damage_pushback_mt > 0 and other.alive
                            and not other.is_building and not other.ignore_pushback):
                        dx = other.pos.x - entity.pos.x
                        dy = other.pos.y - entity.pos.y
                        span = arena.isqrt(dx * dx + dy * dy) or 1
                        other.pos = arena.clamp_to_arena(Point(
                            other.pos.x + dx * entity.death_damage_pushback_mt // span,
                            other.pos.y + dy * entity.death_damage_pushback_mt // span))

        if entity.death_area_radius_mt > 0 and entity.death_area_duration_ms > 0:
            # Princess Evolution drops a one-hit damage AEO and a 3.5-second
            # slow field. Both values are direct edges from DeathAreaEffect.
            if entity.death_area_damage > 0:
                for other in list(self.entities.values()):
                    if (other.uid == entity.uid or not other.alive
                            or other.side == entity.side):
                        continue
                    if distance(entity.pos, other.pos) <= (
                            entity.death_area_radius_mt + other.collision_radius_mt):
                        amount = (entity.death_area_tower_damage
                                  if other.is_tower and entity.death_area_tower_damage
                                  else entity.death_area_damage)
                        dealt = other.take_damage(amount)
                        self.damage_log.append(
                            (self.now_ms, entity.uid, other.uid, dealt))
            from .spells import SpellSpec
            area_spec = SpellSpec(
                name=f"{entity.name}_death_area", damage=0,
                radius_mt=entity.death_area_radius_mt,
                radius_y_mt=entity.death_area_radius_mt,
                crown_tower_percent=100, pushback_mt=0,
                life_duration_ms=entity.death_area_duration_ms,
                hit_frequency_ms=entity.death_area_hit_frequency_ms,
                area_speed_pct=entity.death_area_speed_pct,
                area_hit_speed_pct=entity.death_area_hit_speed_pct,
                area_only_own_troops=(entity.death_area_speed_pct > 0
                                      or entity.death_area_hit_speed_pct > 0),
                area_buff_linger_ms=entity.death_area_buff_linger_ms,
            )
            self.areas.append([
                area_spec, entity.pos, entity.side,
                self.now_ms + entity.death_area_duration_ms,
                self.now_ms, None])

        # A unit that dies while cursed comes back on the curser's side, right
        # where it fell - which is the whole card, and why a curse landing on
        # the enemy king tower can leave a goblin standing there.
        if (entity.cursed_spawn and entity.cursed_by_side
                and entity.cursed_until_ms >= self.now_ms
                and entity.side != entity.cursed_by_side):
            spec = self.unit_lookup(entity.cursed_spawn) if self.unit_lookup else None
            if spec is not None:
                for _ in range(max(1, entity.cursed_spawn_count)):
                    converted = make_unit(0, spec, entity.cursed_by_side,
                                          entity.pos, now_ms=self.now_ms)
                    self.add(converted)

        if entity.death_spawn_character and entity.death_spawn_count > 0:
            self._spawn_from(entity, entity.death_spawn_character,
                             entity.death_spawn_count,
                             (0 if entity.death_spawn_at_source
                              else entity.death_spawn_radius_mt or 600))

        if entity.owner_heal_on_death > 0 and entity.spawn_owner_uid:
            owner = self.get(entity.spawn_owner_uid)
            if owner is not None and owner.alive:
                owner.buff_max_hitpoints_pct = entity.owner_heal_overheal_pct
                owner.heal(entity.owner_heal_on_death)

    def _spawn_from(self, parent: Entity, character: str, count: int,
                    radius_mt: int) -> None:
        """Put `count` copies of `character` on the board around `parent`.

        The data names spawned units in its own PascalCase - Golemite, Skeleton,
        BalloonBomb - so this needs the card table to look them up. Without a
        lookup the spawn is skipped rather than guessed at.
        """
        if self.unit_lookup is None:
            return
        spec = self.unit_lookup(character)
        if spec is None:
            return
        for index in range(count):
            if index < len(parent.death_spawn_offsets):
                offset_x, offset_y = parent.death_spawn_offsets[index]
                offset_y *= parent.side
            else:
                angle = 6.28318 * index / max(1, count)
                offset_x = int(radius_mt * math.cos(angle))
                offset_y = int(radius_mt * math.sin(angle))
            pos = arena.clamp_to_arena(
                Point(parent.pos.x + offset_x, parent.pos.y + offset_y))
            # add() allocates the uid; passing one here would be ignored, and
            # bumping the counter separately desynchronises it.
            child = make_unit(0, spec, parent.side, pos, now_ms=self.now_ms)
            if parent.death_spawn_deploy_ms > 0:
                child.deploy_remaining_ms = parent.death_spawn_deploy_ms
            child.spawn_owner_uid = parent.uid
            child.spawn_group_uid = parent.spawn_group_uid
            if (parent.owned_spawn_death_heal > 0
                    and parent.owned_spawn_death_heal_remaining > 0):
                child.owner_heal_on_death = parent.owned_spawn_death_heal
                child.owner_heal_overheal_pct = (
                    parent.owned_spawn_death_heal_overheal_pct)
                parent.owned_spawn_death_heal_remaining -= 1
            self.add(child)

    def _tick_spawners(self, dt_ms: int) -> None:
        """Huts and Witches produce a wave every SpawnPauseTime."""
        for entity in list(self.entities.values()):
            if not entity.alive or not entity.spawn_character:
                continue
            if entity.spawn_pause_ms <= 0 or entity.spawn_count <= 0:
                continue
            if entity.deploy_remaining_ms > 0:
                continue
            if (entity.hot_spawn_active
                    or self.now_ms < entity.normal_spawn_resume_ms):
                continue
            # A frozen or stunned hut stops producing, and a raged one speeds
            # up. `SpawnSpeedMultiplier` is declared on every buff that has it
            # as exactly the same number as `HitSpeedMultiplier` - -100 for
            # Stun and the freezes, 130 to 170 for the rages - so the field the
            # simulator already carries is the field the client uses, and this
            # loop simply never looked at it. A Freeze on a Tombstone stopped
            # it attacking and left it spawning skeletons regardless.
            spawn_pct = entity.buff_hit_speed_pct if entity.buffed(self.now_ms) else 0
            if spawn_pct <= -100:
                # Hold the current wave rather than losing it: the hut resumes
                # where it was once the freeze ends.
                entity.spawn_due_ms = max(entity.spawn_due_ms,
                                          self.now_ms + dt_ms)
                continue
            if entity.spawn_due_ms < 0:
                entity.spawn_due_ms = self.now_ms + (entity.spawn_start_ms
                                                     or entity.spawn_pause_ms)
                continue
            if self.now_ms >= entity.spawn_due_ms:
                if entity.spawn_forward_mt and self.unit_lookup is not None:
                    spec = self.unit_lookup(entity.spawn_character)
                    if spec is not None:
                        position = arena.clamp_to_arena(Point(
                            entity.pos.x,
                            entity.pos.y - entity.side * entity.spawn_forward_mt))
                        for _ in range(entity.spawn_count):
                            child = make_unit(0, spec, entity.side, position,
                                              self.now_ms)
                            if entity.spawn_deploy_ms:
                                child.deploy_remaining_ms = entity.spawn_deploy_ms
                            child.spawn_owner_uid = entity.uid
                            self.add(child)
                else:
                    self._spawn_from(entity, entity.spawn_character,
                                     entity.spawn_count, 900)
                if entity.spawn_after_first_character:
                    entity.spawn_character = entity.spawn_after_first_character
                    entity.spawn_after_first_character = ""
                    if entity.spawn_after_first_pause_ms > 0:
                        entity.spawn_pause_ms = entity.spawn_after_first_pause_ms
                # Rage shortens the wait in the same proportion it shortens
                # an attack.
                entity.spawn_due_ms = self.now_ms + (
                    entity.spawn_pause_ms * 100 // (100 + spawn_pct)
                    if spawn_pct else entity.spawn_pause_ms)

    def _tick_hot_spawners(self, dt_ms: int) -> None:
        """Run Evolved Furnace's attack-only alternating Fire Spirit stream."""
        if self.unit_lookup is None:
            return
        for entity in list(self.entities.values()):
            if (not entity.alive or not entity.hot_spawn_character
                    or entity.hot_spawn_interval_ms <= 0
                    or entity.deploy_remaining_ms > 0):
                continue
            target = self.get(entity.target_uid)
            engaged = bool(
                target and target.alive
                and entity.is_valid_target(target, self.now_ms)
                and distance(entity.pos, target.pos)
                    <= entity.range_mt + target.collision_radius_mt)
            if engaged:
                entity.hot_spawn_moving_ms = 0
                if not entity.hot_spawn_active:
                    entity.hot_spawn_active = True
                    entity.hot_spawn_pause_started_ms = self.now_ms
                    entity.hot_spawn_due_ms = (
                        self.now_ms + entity.hot_spawn_first_delay_ms)
            elif entity.hot_spawn_active:
                if entity.state == MOVING:
                    entity.hot_spawn_moving_ms += dt_ms
                else:
                    entity.hot_spawn_moving_ms = 0
                if entity.hot_spawn_moving_ms >= entity.hot_spawn_stop_moving_ms:
                    entity.hot_spawn_active = False
                    paused_for = max(
                        0, self.now_ms - entity.hot_spawn_pause_started_ms)
                    if entity.spawn_due_ms >= 0:
                        entity.spawn_due_ms += (
                            paused_for + entity.hot_spawn_normal_resume_ms)
                    entity.normal_spawn_resume_ms = (
                        self.now_ms + entity.hot_spawn_normal_resume_ms)
                    entity.hot_spawn_due_ms = -1
                    entity.hot_spawn_pause_started_ms = -1
                    continue
            if (not entity.hot_spawn_active
                    or self.now_ms < entity.hot_spawn_due_ms):
                continue
            spec = self.unit_lookup(entity.hot_spawn_character)
            if spec is not None:
                direction = 1 if entity.hot_spawn_alternate else -1
                position = arena.clamp_to_arena(Point(
                    entity.pos.x + direction * entity.side
                        * entity.hot_spawn_side_mt,
                    entity.pos.y + entity.side * entity.hot_spawn_behind_mt))
                child = make_unit(0, spec, entity.side, position, self.now_ms)
                if entity.hot_spawn_deploy_ms:
                    child.deploy_remaining_ms = entity.hot_spawn_deploy_ms
                child.spawn_owner_uid = entity.uid
                self.add(child)
                entity.hot_spawn_alternate = not entity.hot_spawn_alternate
            entity.hot_spawn_due_ms += entity.hot_spawn_interval_ms

    def _tick_threshold_spawners(self) -> None:
        """Run source-declared interval spawns once a health trigger fires."""
        if self.unit_lookup is None:
            return
        for entity in list(self.entities.values()):
            if (not entity.alive or entity.threshold_spawn_hp_pct <= 0
                    or not entity.threshold_spawn_character
                    or entity.threshold_spawn_interval_ms <= 0):
                continue
            if not entity.threshold_spawn_active:
                if (entity.hitpoints * 100
                        > entity.max_hitpoints * entity.threshold_spawn_hp_pct):
                    continue
                entity.threshold_spawn_active = True
                entity.threshold_spawn_due_ms = (
                    self.now_ms + entity.threshold_spawn_interval_ms)
                continue
            if self.now_ms < entity.threshold_spawn_due_ms:
                continue
            spec = self.unit_lookup(entity.threshold_spawn_character)
            if spec is not None:
                position = arena.clamp_to_arena(Point(
                    entity.pos.x,
                    entity.pos.y + entity.side * entity.threshold_spawn_behind_mt))
                self.add(make_unit(0, spec, entity.side, position, self.now_ms))
            entity.threshold_spawn_due_ms = (
                self.now_ms + entity.threshold_spawn_interval_ms)

    def _release_captured(self, cage: Entity) -> None:
        target = self.get(cage.captured_uid)
        if target is not None:
            target.spell_captured = False
            target.forced_move_until_ms = 0
            target.pos = cage.pos
            self.forced_moves = [event for event in self.forced_moves
                                 if event[0].uid != target.uid]
        cage.captured_uid = 0
        cage.capture_started = False
        cage.capture_drag_start_ms = 0
        cage.capture_due_ms = 0
        cage.capture_next_damage_ms = 0

    def _tick_captures(self) -> None:
        """Pull one ground troop into an evolved Goblin Cage and fight it."""
        for cage in list(self.entities.values()):
            if not cage.alive or cage.capture_radius_mt <= 0:
                continue
            if cage.captured_uid:
                target = self.get(cage.captured_uid)
                if target is None or not target.alive:
                    self._release_captured(cage)
                    cage.capture_cooldown_until_ms = (
                        self.now_ms + cage.capture_cooldown_ms)
                    continue
                if (not cage.capture_started
                        and self.now_ms >= cage.capture_drag_start_ms):
                    cage.capture_started = True
                    target.spell_captured = True
                    target.target_uid = None
                    target.state = IDLE
                    cage.capture_due_ms = (
                        self.now_ms + cage.capture_drag_time_ms)
                    target.forced_move_until_ms = cage.capture_due_ms
                    self.forced_moves.append([
                        target, target.pos, cage.pos, self.now_ms,
                        cage.capture_due_ms])
                if not cage.capture_started or self.now_ms < cage.capture_due_ms:
                    continue
                target.pos = cage.pos
                if cage.capture_next_damage_ms <= 0:
                    cage.capture_next_damage_ms = (
                        self.now_ms + cage.capture_hit_frequency_ms)
                if self.now_ms >= cage.capture_next_damage_ms:
                    dealt = target.take_damage(cage.capture_damage)
                    self.damage_log.append(
                        (self.now_ms, cage.uid, target.uid, dealt))
                    cage.capture_next_damage_ms += cage.capture_hit_frequency_ms
                continue
            if self.now_ms < cage.capture_cooldown_until_ms:
                continue
            candidates = [target for target in self.entities.values()
                          if target.side != cage.side and target.alive
                          and not target.flying and not target.is_building
                          and not target.is_tower and not target.untargetable
                          and distance(cage.pos, target.pos)
                              <= cage.capture_radius_mt]
            if not candidates:
                continue
            candidates.sort(key=lambda target: (
                distance(cage.pos, target.pos), target.uid))
            target = candidates[0]
            cage.captured_uid = target.uid
            cage.capture_drag_start_ms = (
                self.now_ms + cage.capture_drag_delay_ms)

    def _advance_quest(self, entity: Entity, amount_ms: int) -> None:
        if (amount_ms <= 0 or entity.ability_used
                or entity.quest_interval_ms <= 0
                or entity.quest_stacks >= entity.quest_max_stacks):
            return
        entity.quest_progress_ms += amount_ms
        while (entity.quest_progress_ms >= entity.quest_interval_ms
               and entity.quest_stacks < entity.quest_max_stacks):
            entity.quest_progress_ms -= entity.quest_interval_ms
            entity.quest_stacks += 1

    def _tick_quests(self, dt_ms: int) -> None:
        for entity in self.entities.values():
            if (not entity.active or entity.quest_interval_ms <= 0
                    or self.now_ms <= entity.spawned_at_ms
                        + entity.quest_start_delay_ms):
                continue
            self._advance_quest(entity, dt_ms)

    def _start_grounding(self, entity: Entity) -> None:
        if entity.grounding_due_ms or not entity.ground_character:
            return
        entity.grounding_due_ms = self.now_ms + max(1, entity.ground_transition_ms)
        entity.target_uid = None
        entity.state = IDLE

    def _tick_grounding(self) -> None:
        """Resolve client ActionAirToGround transitions and landing areas."""
        if self.unit_lookup is None:
            return
        for uid, entity in list(self.entities.items()):
            if not entity.alive or not entity.ground_character:
                continue
            if (not entity.grounding_due_ms and entity.ground_on_damage_hp_pct > 0
                    and entity.hitpoints * 100
                        <= entity.max_hitpoints * entity.ground_on_damage_hp_pct):
                self._start_grounding(entity)
            if not entity.grounding_due_ms or self.now_ms < entity.grounding_due_ms:
                continue
            spec = self.unit_lookup(entity.ground_character)
            if spec is None:
                continue
            grounded = make_unit(uid, spec, entity.side, entity.pos, self.now_ms)
            # ActionAirToGround owns the runtime movement layer; the grounded
            # EXT intentionally inherits the airborne character data and does
            # not redundantly clear FlyingHeight in the static table.
            grounded.flying = False
            grounded.hitpoints = min(grounded.max_hitpoints, entity.hitpoints)
            grounded.deploy_remaining_ms = 0
            grounded.damage_dealt = entity.damage_dealt
            self.entities[uid] = grounded
            for target in list(self.entities.values()):
                if (target.uid == uid or target.side == grounded.side
                        or not target.alive or target.flying or target.untargetable
                        or distance(grounded.pos, target.pos)
                            > entity.ground_landing_radius_mt
                                + target.collision_radius_mt):
                    continue
                dealt = target.take_damage(entity.ground_landing_damage)
                grounded.damage_dealt += dealt
                self.damage_log.append(
                    (self.now_ms, grounded.uid, target.uid, dealt))
