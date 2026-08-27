"""A whole battle: towers, decks, hands, elixir, the clock and the result.

Rules encoded here are the ones we verified by search earlier in the project
rather than recalled: both players start at 5 elixir and cap at 10, regeneration
is one per 2.8s, halving to 1.4s at 2:00 and about 0.9s at 4:00. A card returns
to hand only after four others have been played, which is why a cycle deck can
reach its win condition every rotation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import arena
from .arena import MT, Point, TICK_MS
from .engine import Battle
from .entities import Entity, make_tower, make_unit

START_ELIXIR = 5000            # milli-elixir, to keep the whole sim integer
MAX_ELIXIR = 10000
# One elixir every 2.8 seconds, halved at two minutes and thirded at four.
# Triple was 900ms rather than 2800/3, which is a 3.7% overpayment.
SINGLE_MS, DOUBLE_MS, TRIPLE_MS = 2800, 1400, 933
DOUBLE_AT_MS = 120_000
TRIPLE_AT_MS = 240_000
REGULAR_END_MS = 180_000
OVERTIME_END_MS = 300_000

# Tower stats, derived rather than hardcoded.
#
# These were four numbers read off a live account, with an honest comment
# saying the tower-level curve was not in the shipped files. It is now: the
# published `cards_stats_building` tables give hitpoints at every level, and
# the tower projectiles give damage at every level. Checked against those, the
# old values matched *no level at all* - princess 3346 sits between levels 10
# and 11 (3262, 3584), king 5735 between 5592 and 6144. The likeliest
# explanation is that the account had a tower troop equipped, which `sim.towers`
# now models properly.
from .towers import DEFAULT_TOWER_LEVEL, king_tower, princess_tower

_PRINCESS = princess_tower(DEFAULT_TOWER_LEVEL)
_KING = king_tower(DEFAULT_TOWER_LEVEL)

PRINCESS_HP = _PRINCESS.hitpoints
PRINCESS_DAMAGE = _PRINCESS.damage
PRINCESS_HIT_MS = _PRINCESS.hit_speed_ms
PRINCESS_RANGE = _PRINCESS.range_mt
KING_HP = _KING.hitpoints
KING_DAMAGE = _KING.damage
KING_HIT_MS = _KING.hit_speed_ms
KING_RANGE = _KING.range_mt


_LEVELLED_CACHE: dict = {}


def _levelled_cards(level: int) -> dict:
    """The whole card table rebuilt at another level, cached.

    Only Mirror needs this, and only for the one card it is copying, but the
    loader works a table at a time so the table is what gets cached.
    """
    if level not in _LEVELLED_CACHE:
        from .gamedata import load_gamedata
        _LEVELLED_CACHE[level] = load_gamedata(level=level)
    return _LEVELLED_CACHE[level]


@dataclass
class PlayerState:
    side: int
    deck: List[str]
    elixir: int = START_ELIXIR
    hand: List[str] = field(default_factory=list)
    queue: List[str] = field(default_factory=list)
    crowns: int = 0
    elixir_spent: int = 0
    # What Mirror would copy: the last card this player actually deployed.
    last_card: str = ""
    evolution_progress: Dict[str, int] = field(default_factory=dict)

    def draw(self) -> None:
        while len(self.hand) < 4 and self.queue:
            self.hand.append(self.queue.pop(0))

    def play(self, card: str) -> bool:
        """Move a card from hand to the back of the queue."""
        if card not in self.hand:
            return False
        self.hand.remove(card)
        self.queue.append(card)
        self.draw()
        return True

    @property
    def next_card(self) -> Optional[str]:
        return self.queue[0] if self.queue else None


@dataclass
class Match:
    cards: Dict[str, object]                     # name -> CardSpec
    decks: Tuple[List[str], List[str]]
    seed: int = 0
    battle: Battle = field(default_factory=Battle)
    players: Dict[int, PlayerState] = field(default_factory=dict)
    towers: Dict[int, Dict[str, Entity]] = field(default_factory=dict)
    spells: Dict[str, object] = field(default_factory=dict)
    spell_damage: Dict[int, int] = field(default_factory=dict)
    # Fractional elixir left over between ticks, so income is not truncated.
    # The level the card pool was built at, so Mirror knows what a level up is.
    level: int = 11
    _regen_carry: int = 0
    finished: bool = False
    result: Optional[str] = None
    # RL must choose when to press an ability.  Kept as an opt-in compatibility
    # mode for old scripted baselines, never the default training behaviour.
    auto_abilities: bool = False
    # side -> {base card: evolved card}. Only explicitly equipped evolutions
    # cycle; merely owning/loading a variant does not change a deck.
    evolution_slots: Dict[int, Dict[str, str]] = field(default_factory=dict)

    def __post_init__(self):
        if self.evolution_slots:
            all_level_cards = _levelled_cards(self.level)
            for mapping in self.evolution_slots.values():
                for evolved_name in mapping.values():
                    if evolved_name not in self.cards and evolved_name in all_level_cards:
                        self.cards[evolved_name] = all_level_cards[evolved_name]
        rng = random.Random(self.seed)
        # Death spawns and huts name what they produce in the data's own
        # PascalCase - Golemite, Skeleton, BalloonBomb - so the battle needs a
        # way back to a spec. Anything it cannot resolve is skipped rather than
        # guessed at, and `missing_spawns` records it so a silent hole in a
        # card's behaviour shows up instead of looking like correct play.
        self.missing_spawns = set()

        def lookup(character: str):
            from .gamedata import load_characters, to_snake_case
            key = to_snake_case(character)
            # The exact client identifier first. Going through the card table
            # first meant a companion whose name snake-cases onto a card name
            # resolved to that card's *own* unit: `RamRider` became `ram_rider`
            # became the Ram Rider card became the Ram - which declares RamRider
            # as its attachment, so `Battle.add` recursed until the stack ran
            # out. It killed about one random-deck match in fifteen.
            exact = load_characters(self.level).get(character)
            if exact is not None:
                return exact
            card = self.cards.get(key)
            if card is not None and getattr(card, "unit", None) is not None:
                return card.unit
            # Most spawned units are not cards at all, so fall back to the full
            # character table before giving up.
            character_table = load_characters()
            spec = character_table.get(character) or character_table.get(key)
            if spec is not None:
                return spec
            for other in self.cards.values():
                unit = getattr(other, "unit", None)
                if unit is not None and unit.name == key:
                    return unit
            self.missing_spawns.add(character)
            return None

        self.battle.unit_lookup = lookup
        for index, side in enumerate((1, -1)):
            deck = list(self.decks[index])
            order = deck[:]
            rng.shuffle(order)
            player = PlayerState(side=side, deck=deck, queue=order)
            player.draw()
            self.players[side] = player
            self.towers[side] = self._build_towers(side)

    def _build_towers(self, side: int) -> Dict[str, Entity]:
        anchors = arena.ALLY_PRINCESS if side > 0 else arena.ENEMY_PRINCESS
        king_pos = arena.ALLY_KING if side > 0 else arena.ENEMY_KING
        out = {}
        for lane, pos in anchors.items():
            tower = make_tower(0, side, pos, PRINCESS_HP, PRINCESS_DAMAGE,
                               PRINCESS_HIT_MS, PRINCESS_RANGE)
            out[lane] = self.battle.add(tower)
        king = make_tower(0, side, king_pos, KING_HP, KING_DAMAGE,
                          KING_HIT_MS, KING_RANGE, king=True)
        # A king tower is asleep until it is damaged or a princess falls. Until
        # then it must not shoot, so it is given nothing it considers valid.
        king.target_only_buildings = True
        out["king"] = self.battle.add(king)
        return out

    # --------------------------------------------------------------- elixir

    @property
    def elapsed_ms(self) -> int:
        return self.battle.now_ms

    def regen_ms(self) -> int:
        if self.elapsed_ms >= TRIPLE_AT_MS:
            return TRIPLE_MS
        if self.elapsed_ms >= DOUBLE_AT_MS:
            return DOUBLE_MS
        return SINGLE_MS

    def _regen(self, dt_ms: int) -> None:
        """Elixir income, carrying the remainder rather than dropping it.

        A tick is 50ms and single elixir is one per 2800ms, so the integer
        division gave 17 milli-elixir a tick where the true figure is 17.857.
        Truncating that lost nearly 5% of all income - about three elixir over
        a match, a whole extra card each - and both players being poorer than
        they should be is exactly the sort of thing that makes every simulated
        match run long.
        """
        scaled = 1000 * dt_ms + self._regen_carry
        period = self.regen_ms()
        gain = scaled // period
        self._regen_carry = scaled % period
        for player in self.players.values():
            player.elixir = min(MAX_ELIXIR, player.elixir + gain)

    # ------------------------------------------------------------ deployment

    MIRROR_LEVEL_BONUS = 1

    def mirrored(self, side: int):
        """What Mirror plays, and what it costs.

        Mirror is a rule rather than a card: it replays whatever that player
        put down last, one elixir dearer and one level higher. It needs no
        stats of its own, which is why it has no data file - the copy is just
        the original card built a level up.
        """
        player = self.players[side]
        if not player.last_card:
            return None, 0
        original = self.cards.get(player.last_card)
        if original is None:
            return None, 0
        higher = _levelled_cards(self.level + self.MIRROR_LEVEL_BONUS)
        spec = higher.get(player.last_card, original)
        return spec, original.cost + 1

    def can_play(self, side: int, card: str) -> bool:
        player = self.players[side]
        if card == "mirror":
            spec, cost = self.mirrored(side)
            return (spec is not None and card in player.hand
                    and player.elixir >= cost * 1000)
        spec = self.cards.get(card)
        return (spec is not None and card in player.hand
                and player.elixir >= spec.cost * 1000)

    def play_card(self, side: int, card: str, at: Point) -> bool:
        """Deploy a card. Returns False if it was not a legal play."""
        if not self.can_play(side, card):
            return False
        player = self.players[side]
        spec = self.cards[card]
        resolved_card = card
        mirror_cost = None
        if card == "mirror":
            resolved_card = player.last_card
            spec, mirror_cost = self.mirrored(side)
            if spec is None:
                return False
        evolved_play = False
        if card != "mirror":
            evolved_name = self.evolution_slots.get(side, {}).get(card, "")
            evolved_spec = self.cards.get(evolved_name)
            cycles = int(getattr(evolved_spec, "evolution_cycles", 0) or 0)
            if (evolved_spec is not None and cycles > 0
                    and player.evolution_progress.get(card, 0) >= cycles):
                spec = evolved_spec
                resolved_card = evolved_name
                evolved_play = True
        if card == "mirror":
            # Mirror replays the spell one level higher too. Looking up the
            # literal key "mirror" made every mirrored spell spend elixir and
            # resolve no effect at all.
            from .spells import load_spells
            spell = load_spells(self.level + self.MIRROR_LEVEL_BONUS).get(resolved_card)
        else:
            spell = self.spells.get(resolved_card)
        resolves_as_spell = ((spec.unit is None
                              and not getattr(spec, "additional_summons", ())) or
                             (spell is not None and spell.resolves_card_as_spell))
        # Spells land anywhere on the arena; only troops and buildings are
        # restricted to your own half. Gating spells by the deploy area meant
        # every Fireball aimed at a tower silently failed, so the whole chip
        # and finisher game was untestable here and offence was measured with
        # its main tool disabled.
        if resolves_as_spell:
            if not arena.in_arena(at):
                return False
            if spell is not None and spell.deploy_own_side_only:
                if ((side > 0 and at.y < arena.RIVER_Y)
                        or (side < 0 and at.y >= arena.RIVER_Y)):
                    return False
            if (spell is not None and not spell.can_place_on_water
                    and arena.RIVER_TOP < at.y < arena.RIVER_BOTTOM
                    and not arena.on_bridge(at)):
                return False
        elif getattr(spec.unit, "burrow_speed_mt_per_sec", 0) > 0:
            # A burrower goes anywhere on the board. Being able to drop a Miner
            # straight onto the far tower is the card, not a detail of it, and
            # holding it to the normal deploy area made it an ordinary troop
            # that happened to be slow.
            if not arena.in_arena(at):
                return False
        else:
            down = [lane for lane, tower in self.towers[-side].items()
                    if lane != "king" and not tower.alive]
            if not arena.deploy_area_ok(at, side, down):
                return False

        cost = mirror_cost if mirror_cost is not None else spec.cost
        player.elixir -= cost * 1000
        player.elixir_spent += cost
        player.play(card)
        # Mirror copies the last card; it does not become the last card, or a
        # second Mirror would copy itself.
        if card != "mirror":
            player.last_card = card
            if card in self.evolution_slots.get(side, {}):
                if evolved_play:
                    player.evolution_progress[card] = 0
                else:
                    player.evolution_progress[card] = (
                        player.evolution_progress.get(card, 0) + 1)

        if resolves_as_spell:
            if spell is not None:
                from .spells import cast_spell
                self.spell_damage[side] = self.spell_damage.get(side, 0) + \
                    cast_spell(self.battle, spell, at, side,
                               self.towers[side]["king"].pos)
            return True
        count = (max(1, spec.summon_number) if spec.unit is not None else 0)
        spawn_group_uid = 0
        for index in range(count):
            offset = self._formation_offset(index, count,
                                            getattr(spec, "summon_radius_mt", 0))
            pos = arena.clamp_to_arena(Point(at.x + offset.x, at.y + offset.y))
            unit = make_unit(0, spec.unit, side, pos, self.battle.now_ms)
            unit.elixir_value = (cost * 1000) // max(1, count)
            # A burrower does not appear where it was placed straight away: it
            # tunnels there from its own side, and cannot be touched on the
            # way. The further it is sent, the longer that takes - which is
            # exactly the trade a Miner on the far tower is making.
            if unit.burrow_speed_mt_per_sec > 0:
                home = arena.ALLY_KING if side > 0 else arena.ENEMY_KING
                travelled = arena.distance(home, pos)
                unit.deploy_remaining_ms += (travelled * 1000
                                             // unit.burrow_speed_mt_per_sec)
            added = self.battle.add(unit)
            if spawn_group_uid == 0:
                spawn_group_uid = added.uid
            added.spawn_group_uid = spawn_group_uid
        for extra_spec, offset_x, offset_y in getattr(
                spec, "additional_summons", ()):
            # Y offsets are authored from the bottom player's view and mirror
            # for the opposing side. X offsets are arena-absolute unless the
            # source explicitly supplies a mirrored list (the symmetric lists
            # currently produce the same result either way).
            extra_pos = arena.clamp_to_arena(Point(
                at.x + int(offset_x), at.y + int(offset_y) * side))
            extra = make_unit(0, extra_spec, side, extra_pos,
                              self.battle.now_ms)
            added = self.battle.add(extra)
            if spawn_group_uid == 0:
                spawn_group_uid = added.uid
            added.spawn_group_uid = spawn_group_uid
        secondary = getattr(spec, "secondary_unit", None)
        secondary_count = int(getattr(spec, "secondary_summon_number", 0) or 0)
        for index in range(secondary_count):
            toward = int(getattr(
                spec, "secondary_offset_toward_centre_mt", 0) or 0)
            direction = 1 if at.x < arena.WIDTH // 2 else -1
            secondary_pos = arena.clamp_to_arena(Point(
                at.x + direction * toward, at.y))
            unit = make_unit(0, secondary, side, secondary_pos,
                             self.battle.now_ms)
            unit.deploy_remaining_ms += int(getattr(
                spec, "secondary_summon_deploy_delay_ms", 0) or 0)
            added = self.battle.add(unit)
            if spawn_group_uid == 0:
                spawn_group_uid = added.uid
            added.spawn_group_uid = spawn_group_uid
        return True

    @staticmethod
    def _formation_offset(index: int, count: int, summon_radius_mt: int = 0) -> Point:
        """Spread a multi-unit card the way the card says it spreads.

        The radius was hard-coded at 350 millitiles, half what the data gives:
        Skeletons and Barbarians both carry SummonRadius 700 on their card row,
        which is a field on the spell rather than the character and so was
        never read. At half spacing three Skeletons dropped centrally clumped
        and all chased the same tower, where in a real game the formation is
        wide enough that they pick different ones - which is most of the value
        a good player gets out of the card.
        """
        if count == 1:
            return Point(0, 0)
        import math
        radius = summon_radius_mt or 700
        angle = 2 * math.pi * index / count
        return Point(int(radius * math.cos(angle)), int(radius * math.sin(angle)))

    # ------------------------------------------------------------------ tick

    def step(self, dt_ms: int = TICK_MS) -> None:
        if self.finished:
            return
        self._regen(dt_ms)
        self.battle.step(dt_ms)
        self.spell_damage = dict(self.battle.resolved_spell_damage)
        self._wake_kings()
        if self.auto_abilities:
            self._fire_abilities()
        self._check_end()


    def can_activate_ability(self, side: int, uid: int) -> bool:
        """Whether this explicit champion/hero action is presently legal.

        A card placement and a button press are separate decisions in Clash
        Royale.  The generic path is intentionally limited to abilities that
        the client represents as a self-buff; action graphs requiring a dash,
        target picker, spawn, or transformation remain unavailable rather
        than being silently auto-fired as the wrong mechanic.
        """
        entity = self.battle.get(uid)
        player = self.players.get(side)
        return bool(entity and player and entity.side == side and entity.alive
                    and entity.active
                    and ((entity.ability_max_charges > 1
                          and entity.ability_charges_used
                              < entity.ability_max_charges)
                         or (entity.ability_max_charges <= 1
                             and not entity.ability_used))
                    and self.battle.now_ms >= entity.ability_ready_at_ms
                    and (entity.ability_buff or entity.ability_area_damage > 0
                         or entity.ability_deploy_character
                         or entity.ability_level_adjustments
                         or entity.ability_taunt_radius_mt
                         or entity.ability_hurl_radius_mt
                         or entity.ability_siege_range_mt
                         or entity.ability_split_character
                         or entity.ability_reroll_range_mt
                         or entity.ability_spin_seek_radius_mt
                         or entity.ability_reinforcement_character
                         or entity.ability_transform_character
                         or entity.ability_warp_backward_mt
                         or entity.ability_warp_to_target_speed
                         or entity.ability_temporary_character
                         or entity.ability_summon_character
                         or entity.ability_extra_projectiles
                         or entity.ability_drop_character)
                    and (entity.ability_buff_ms > 0 or entity.ability_dash_range_mt > 0
                         or entity.ability_spawn_character
                         or entity.ability_area_damage > 0
                         or entity.ability_deploy_character
                         or entity.ability_lane_switch
                         or entity.ability_link_target
                         or entity.ability_level_adjustments
                         or entity.ability_hurl_radius_mt
                         or entity.ability_siege_range_mt
                         or entity.ability_split_character
                         or entity.ability_reroll_range_mt
                         or entity.ability_spin_seek_radius_mt
                         or entity.ability_reinforcement_character
                         or entity.ability_transform_character
                         or entity.ability_warp_backward_mt
                         or entity.ability_warp_to_target_speed
                         or entity.ability_temporary_character
                         or entity.ability_summon_character
                         or entity.ability_extra_projectiles
                         or entity.ability_drop_character)
                    and (entity.ability_window_ms <= 0
                         or self.battle.now_ms <= (
                             entity.spawned_at_ms + entity.ability_window_ms))
                    and player.elixir >= entity.ability_cost * 1000)

    def activate_ability(self, side: int, uid: int) -> bool:
        """Spend elixir and activate a source-declared self-buff ability."""
        if not self.can_activate_ability(side, uid):
            return False
        entity = self.battle.get(uid)
        player = self.players[side]
        from .gamedata import (load_buffs, load_buff_flags,
                               load_buff_damage_reductions)
        speed_pct, hit_pct, heal = load_buffs().get(entity.ability_buff, (0, 0, 0))
        is_dash = entity.ability_dash_range_mt > 0
        is_guard = bool(entity.ability_spawn_character)
        is_area = entity.ability_area_damage > 0
        is_deploy = bool(entity.ability_deploy_character)
        is_lane_switch = entity.ability_lane_switch
        is_link = bool(entity.ability_link_target)
        is_level_up = bool(entity.ability_level_adjustments)
        is_taunt = entity.ability_taunt_radius_mt > 0
        is_hurl = entity.ability_hurl_radius_mt > 0
        is_siege = entity.ability_siege_range_mt > 0
        is_split = bool(entity.ability_split_character)
        is_reroll = entity.ability_reroll_range_mt > 0
        is_spin = entity.ability_spin_seek_radius_mt > 0
        is_reinforcement = bool(entity.ability_reinforcement_character)
        is_transform = bool(entity.ability_transform_character)
        is_warp = entity.ability_warp_backward_mt > 0
        # A warp *onto* a resolved target, as opposed to the fixed retreat
        # above. Mega Minion Hero is the one that declares it.
        is_target_warp = entity.ability_warp_to_target_speed > 0
        is_temporary = bool(entity.ability_temporary_character)
        # Skeleton King raises his skeletons; nothing else in the game does.
        is_summon = bool(entity.ability_summon_character)
        # Elite Archer Hero's seven seconds of firing in threes.
        is_triple = entity.ability_extra_projectiles > 0
        # Balloon Hero drops a Skeletrooper onto the nearest ground target.
        is_drop = bool(entity.ability_drop_character)
        reduction = load_buff_damage_reductions().get(entity.ability_buff, 0)
        shield_pct = int(getattr(entity, "ability_shield_pct", 0) or 0)
        if not (speed_pct or hit_pct or heal or reduction or shield_pct) and not (is_dash or is_guard or is_area or is_deploy or is_lane_switch or is_link or is_level_up or is_taunt or is_hurl or is_siege or is_split or is_reroll or is_spin or is_reinforcement or is_transform or is_warp or is_target_warp or is_temporary or is_summon
                or is_triple or is_drop):
            return False
        player.elixir -= entity.ability_cost * 1000
        entity.ability_charges_used += 1
        max_charges = max(1, entity.ability_max_charges)
        entity.ability_used = entity.ability_charges_used >= max_charges
        entity.ability_ready_at_ms = (
            self.battle.now_ms + entity.ability_cooldown_ms)
        if is_drop:
            self.battle.schedule_paratrooper(entity)
        if is_triple:
            entity.ability_shots_until_ms = (
                self.battle.now_ms + entity.ability_shot_window_ms)
        if is_summon:
            if not self.battle.schedule_ability_summon(entity):
                entity.ability_charges_used -= 1
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_temporary:
            if not self.battle.schedule_temporary_form(entity):
                entity.ability_charges_used -= 1
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_target_warp:
            if not self.battle.schedule_target_warp(entity):
                entity.ability_charges_used -= 1
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_warp:
            if not self.battle.schedule_ability_warp(entity):
                entity.ability_charges_used -= 1
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_transform:
            if not self.battle.schedule_linked_transform(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_reinforcement:
            if not self.battle.schedule_reinforcements(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_spin:
            if not self.battle.schedule_spin(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_reroll:
            if not self.battle.schedule_reroll(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_split:
            if not self.battle.schedule_split(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_siege:
            if not self.battle.schedule_siege(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_hurl:
            if not self.battle.schedule_hurl(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_taunt:
            if not self.battle.schedule_taunt(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_level_up:
            if not self.battle.schedule_level_up(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_dash:
            if not self.battle.start_ability_dash_chain(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_guard:
            if not self.battle.schedule_ability_guard(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_area:
            if not self.battle.start_ability_area(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_deploy:
            if not self.battle.schedule_ability_deploy(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_lane_switch:
            if not self.battle.schedule_ability_lane_switch(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        elif is_link:
            if not self.battle.start_ability_link(entity):
                entity.ability_used = False
                player.elixir += entity.ability_cost * 1000
                return False
        else:
            buff_delay = entity.ability_buff_delay_ms
            buff_start = self.battle.now_ms + buff_delay
            buff_end = buff_start + entity.ability_buff_ms
            if buff_delay > 0:
                self.battle.delayed_self_buffs.append([
                    buff_start, buff_end, entity, speed_pct, hit_pct, heal,
                    reduction])
            else:
                entity.buff_until_ms = (
                    self.battle.now_ms + entity.ability_buff_ms
                    + (0 if entity.ability_duration_includes_cast
                       else entity.ability_cast_ms))
                entity.buff_speed_pct = speed_pct
                entity.buff_hit_speed_pct = hit_pct
                entity.buff_heal_per_second = heal
                entity.damage_reduction_pct = reduction
            entity.buff_damage_pct = entity.ability_damage_pct
            entity.buff_tower_damage_pct = entity.ability_tower_damage_pct
            if entity.ability_unkillable:
                entity.unkillable_until_ms = entity.buff_until_ms
            if entity.ability_cast_locks_actions:
                entity.control_cast_until_ms = max(
                    entity.control_cast_until_ms,
                    self.battle.now_ms + entity.ability_cast_ms)
            if entity.deflect_radius_mt > 0:
                entity.deflect_from_ms = buff_start
                entity.deflect_until_ms = buff_end
                entity.control_cast_until_ms = max(
                    entity.control_cast_until_ms, buff_end)
            if shield_pct > 0:
                entity.shield_hitpoints = (entity.shield_max_hitpoints
                                           * shield_pct // 100)
            if load_buff_flags().get(entity.ability_buff, {}).get("invisible"):
                entity.buff_invisible_until_ms = entity.buff_until_ms
        return True


    def _fire_abilities(self) -> None:
        """Use a champion's ability once it is in the fight and paid for.

        An approximation, and worth naming as one: in the real game a player
        chooses the moment, and this sim has no action for that. Firing it as
        soon as the champion is engaged and its owner can afford it is what a
        competent player mostly does with Archer Queen's rapid fire or Monk's
        deflect, and it is far closer than never using it at all. Once each,
        because the cooldown rules are not in the data we have.
        """
        for entity in list(self.battle.entities.values()):
            if not entity.alive or entity.target_uid is None:
                continue
            self.activate_ability(entity.side, entity.uid)

    def _wake_kings(self) -> None:
        for side, towers in self.towers.items():
            king = towers["king"]
            if not king.alive or not king.target_only_buildings:
                continue
            princesses = [towers[lane] for lane in ("left", "right")]
            if king.hitpoints < king.max_hitpoints or any(not t.alive for t in princesses):
                king.target_only_buildings = False

    def crowns_for(self, side: int) -> int:
        enemy = self.towers[-side]
        return sum(1 for lane in ("left", "right") if not enemy[lane].alive) + \
            (2 if not enemy["king"].alive else 0)

    def _check_end(self) -> None:
        for side in (1, -1):
            if not self.towers[side]["king"].alive:
                self.finished = True
                self.result = "top" if side > 0 else "bottom"
                return
        if self.elapsed_ms < REGULAR_END_MS:
            return
        bottom, top = self.crowns_for(1), self.crowns_for(-1)
        if self.elapsed_ms >= OVERTIME_END_MS or bottom != top:
            # Regular time ends on crowns; overtime ends on crowns, then on the
            # lowest remaining tower, which is how the real tiebreak works.
            self.finished = True
            if bottom != top:
                self.result = "bottom" if bottom > top else "top"
            else:
                self.result = self._tiebreak()

    def _tiebreak(self) -> str:
        def lowest(side: int) -> float:
            towers = [self.towers[side][lane] for lane in ("left", "right")]
            alive = [t.hp_fraction for t in towers if t.alive]
            return min(alive) if alive else 0.0
        bottom, top = lowest(1), lowest(-1)
        if abs(bottom - top) < 1e-6:
            return "draw"
        return "bottom" if bottom > top else "top"

    # ----------------------------------------------------------------- views

    def tower_fractions(self, side: int) -> Dict[str, float]:
        towers = self.towers[side]
        return {lane: towers[lane].hp_fraction for lane in ("left", "right")}

    def summary(self) -> str:
        b, t = self.tower_fractions(1), self.tower_fractions(-1)
        return (f"{b['left']:.2f}/{b['right']:.2f}-{t['left']:.2f}/{t['right']:.2f} "
                f"t={self.elapsed_ms // 1000}s result={self.result}")
