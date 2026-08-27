"""The Hog 2.6 decision engine.

Design notes
------------
The previous engine was a *modifier*: a learned checkpoint proposed a card and
a tile, and a shim layer patched or vetoed it.  Across sixty logged matches
that produced 11 crowns for and 90 against, and in the last three blocks the
shim vetoed 723 decisions while allowing 428 - the bot spent most of the match
declining to act.  This engine decides on its own terms instead.

It is a candidate generator plus a scorer, not an if/else ladder:

  * every rule that has an opinion emits one or more `Candidate` actions,
  * each candidate carries a feature vector,
  * a weight vector in `config.json` turns features into a score,
  * the highest-scoring legal candidate is played.

That structure is what makes the bot tunable between blocks (edit weights, not
control flow) and what a fitted model can later replace without touching any
rule: swap `score_candidate` for a learned function and the rest still works.

Placement constants come from current 2.6 guidance, verified by web search
rather than recalled: Cannon at the 4-3 tile (four from the river, three from
the centre line), Ice Golem kited one tile past the centre into the opposite
lane, Musketeer placed deep and never at the bridge, Skeletons used to
surround, Log and Fireball only on cards that reach a value threshold, and a
cheap card cycled at the back whenever elixir would otherwise cap.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import arena
from .arena import Cell
from . import advisor as advisor_mod
from . import push
from .cards import CardClassifier
from . import experience
from .economy import EnemyEconomy
from .hand import HandTracker
from . import spellinfo
from .knowledge import BOOK
from .opponent import OpponentModel
from .tracker import Track, Tracker

CONFIG_PATH = Path(__file__).with_name("config.json")

SPELLS = frozenset({"fireball", "the_log"})
OUR_DECK = frozenset({
    "cannon", "fireball", "hog_rider", "ice_golem", "ice_spirit",
    "musketeer", "skeletons", "the_log",
})
COSTS = {
    "cannon": 3, "fireball": 4, "hog_rider": 4, "ice_golem": 2,
    "ice_spirit": 1, "musketeer": 4, "skeletons": 1, "the_log": 2,
}


@dataclass
class Candidate:
    card: str
    slot: int              # 0-based hand slot
    x: int
    y: int
    tag: str
    weight_key: str
    features: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0

    @property
    def cost(self) -> int:
        return COSTS.get(self.card, 4)


def _tower_total(hp: Dict[str, float]) -> float:
    """Total remaining princess-tower HP, as a sum rather than a minimum.

    Using the minimum hid every point of damage after the first tower fell: it
    was already 0.0 and could not go lower, so once we took a tower, further
    Hog damage to the other one registered as nothing and every subsequent Hog
    scored as a pure four-elixir loss. That is how the win condition ended up
    with a negative mean reward in a match we were winning.
    """
    return sum(hp.values()) if hp else 2.0


@dataclass
class Observation:
    elixir: float
    elapsed: float
    multiplier: float
    hand: Dict[str, int]              # card name -> 0-based ready slot
    tracks: List[Track]
    threats: List[Track]              # enemies at or past the river
    incoming: List[Track]             # enemies still on their half, advancing
    allies: List[Cell]
    ally_names: frozenset[str]
    ally_hp: Dict[str, float]
    enemy_hp: Dict[str, float]
    threat_elixir: float
    threat_score: float
    threat_lane: str
    enemy_elixir: float
    air_threat: bool
    serious: bool                     # threat worth spending a card on
    contained: bool                   # our units are already on top of the push
    now: float


class Brain:
    def __init__(self, config_path: Path | None = None, use_advisor: bool = False,
                 learn: bool = True):
        self.config_path = Path(config_path or CONFIG_PATH)
        self.book = experience.ExperienceBook() if learn else None
        self.advisor = None
        if use_advisor:
            self.advisor = advisor_mod.Advisor()
            self.advisor.start()
        self.config: Dict = {}
        self.config_mtime = 0.0
        self.reload_config()
        self.tracker = Tracker()
        self.hand_tracker = HandTracker()
        self.classifier = CardClassifier(sorted(OUR_DECK))
        self.reset()

    # ------------------------------------------------------------------ setup

    def reload_config(self) -> bool:
        """Re-read config.json if it changed on disk.

        The review loop tunes weights between blocks; picking the change up
        live means a restart is never required just to change a number.
        """
        path = self.config_path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            # `config.json` is runtime state - the tuner rewrites it between
            # blocks - so it is not tracked, and a fresh clone does not have
            # one. The shipped defaults sit beside it as `config.example.json`.
            # Without this the brain ran on an empty config and every weight
            # silently fell back to zero, which looks like a bad policy rather
            # than a missing file.
            path = self.config_path.with_name(
                self.config_path.stem + ".example" + self.config_path.suffix)
            try:
                mtime = path.stat().st_mtime
            except OSError:
                return False
        if mtime == self.config_mtime and self.config:
            return False
        try:
            self.config = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            if self.config:
                return False
            raise
        self.config_mtime = mtime
        return True

    def reset(self) -> None:
        """Clear per-match memory.  Called at the start of every battle."""
        self.tracker.reset()
        self.hand_tracker.reset()
        self.classifier_overrides = 0
        self.enemy = EnemyEconomy()
        self.opponent = OpponentModel()
        self.plan = None
        self.advice_used = 0
        if getattr(self, "book", None) is not None:
            # Anything still awaiting judgement belongs to the match that just
            # ended. Carried into the next one it would be scored against a
            # fresh opponent's tower HP, which is not an outcome of that play.
            self.book.pending.clear()
        self.last_obs: Optional[Observation] = None
        self.last_play_at = 0.0
        self.last_card_at: Dict[str, float] = {}
        self.last_play_index: Dict[str, int] = {}
        self.hog_sent_at = 0.0
        self.match_started_at = 0.0
        # The opening attack lane must not be a constant.  Both fields used to
        # reset to "right", and with the towers level, no enemy defenders on the
        # board and no back placement seen yet, `_attack_lane` falls all the way
        # through to its final tie-break - "left" if the last Hog went right.
        # So the first attack of every match was the left lane, deterministically:
        # 26 of 26 logged match openings went left and not one went right.  The
        # opponent gets a free read on a lane we announce before the match has
        # started, counterpushes into it, and the left princess tower was the one
        # that died in 25 of the last 25 matches - usually inside 45 seconds.
        # Alternating the seed per match costs nothing and removes the tell.
        self.match_index = getattr(self, "match_index", 0) + 1
        opening_seed = "right" if self.match_index % 2 else "left"
        self.hog_lane = opening_seed
        self.last_hog_lane = opening_seed
        self.committed_elixir = 0.0
        self.cards_this_push = 0
        self.commit_started = 0.0
        self.last_serious_at = -99.0
        self.last_cycle_at = -99.0
        self.last_fallback_at = -99.0
        self.enemy_spend_at = 0.0
        self.enemy_back_placement_lane: Optional[str] = None
        self.plays = 0
        self.play_counts: Dict[str, int] = {}
        self.hp_history = {
            "ally_left": [], "ally_right": [],
            "enemy_left": [], "enemy_right": []
        }

    def cfg(self, key: str, default=None):
        return self.config.get(key, default)

    def weight(self, key: str) -> float:
        return float(self.config.get("weights", {}).get(key, 0.0))

    # ------------------------------------------------------------ observation

    def observe(self, state, elapsed: float, now: Optional[float] = None,
                frame=None) -> Observation:
        now = time.monotonic() if now is None else now
        if not self.match_started_at:
            # "Overdue" is measured from the start of the match, not from the
            # epoch.  A freshly reset Brain would otherwise be infinitely
            # overdue and open every match with a lone Hog, which is not this
            # deck's opening - the first Hog is due one cycle in.
            #
            # This is a separate clock from `hog_sent_at` on purpose.  Seeding
            # that one instead reads as "a Hog was just sent", which trips
            # `hog_repeat_seconds` and blocks the push entirely.
            self.match_started_at = now
        detections = []
        for enemy in state.enemies:
            cell = arena.to_grid(enemy.position.tile_x, enemy.position.tile_y)
            detections.append((str(enemy.unit.name), cell))
        tracks = self.tracker.update(detections, now)

        # Charge the opponent for anything appearing for the first time, then
        # let their bar refill.  Knowing roughly what they can afford is what
        # turns "send the Hog whenever I can pay for it" into "send the Hog
        # when they cannot answer it".
        multiplier = self._multiplier(elapsed)
        # The same first-sighting list feeds the cycle model, so both use the
        # already-filtered deploys rather than raw re-sightings.
        fresh = [t.name for t in tracks if t.hits == 1 and t.cell.y <= 17.0]
        self.opponent.observe(fresh, now)
        self.enemy.tick(now, multiplier)
        self.enemy.observe_spawns(
            [(t.name, BOOK.cost(t.name), t.cell.y) for t in tracks if t.hits == 1], now,
            visible=[t.name for t in tracks],
        )

        allies = [
            arena.to_grid(a.position.tile_x, a.position.tile_y) for a in state.allies
        ]
        ally_names = frozenset(str(a.unit.name) for a in state.allies)

        # Smooth the hand before trusting it.  A single frame's classification
        # is unreliable enough to make the runner tap the wrong slot - see
        # brain/hand.py for the captured evidence.
        raw = [state.cards[slot + 1].name for slot in range(4)]
        # Second opinion. The replacement classifier abstains when two cards
        # are too close to call. We previously fell back to the upstream detector
        # here, but the upstream detector is noisy and caused 299 hand flips.
        # Passing None lets the hand tracker's voting system hold the previous
        # confident value.
        if frame is not None and self.classifier.ready:
            scored = self.classifier.classify_hand_scored(frame)
            # A hand is four *distinct* cards: the deck holds one copy of each
            # and a card only returns after four others are played, so two slots
            # naming the same card means one of them is misread. Settling it
            # matters more than it sounds. The hand below is built with
            # setdefault, so a duplicate does not merely add a wrong card, it
            # silently *hides* the real card sitting in the losing slot - which
            # is why Musketeer, Fireball and Log each sat under 6% of plays
            # while the three cheap cards took 54%, a split an eight-card cycle
            # cannot produce. Keep the stronger correlation; the loser abstains
            # so the tracker holds its last confident value.
            keep: Dict[str, int] = {}
            for slot, (name, score) in enumerate(scored):
                if name is None:
                    continue
                winner = keep.get(name)
                if winner is None or score > scored[winner][1]:
                    keep[name] = slot
            for slot, (name, _score) in enumerate(scored):
                if name is None or keep.get(name) != slot:
                    raw[slot] = None
                    continue
                if raw[slot] != name:
                    self.classifier_overrides += 1
                raw[slot] = name
        stable = self.hand_tracker.update(raw)
        ready = {slot for slot in getattr(state, "ready", ()) if 0 <= slot < 4}
        hand: Dict[str, int] = {}
        for slot, name in stable.items():
            if slot in ready and name != "blank":
                hand.setdefault(name, slot)

        lead = float(self.cfg("predict_seconds", 1.4))
        threats, incoming = [], []
        for track in tracks:
            props = BOOK.get(track.name)
            if props["building"] and track.cell.y < arena.RIVER_Y:
                continue  # their defensive buildings are not a threat to us
            future = track.predict(lead)
            if track.cell.y >= arena.RIVER_Y or future.y >= arena.RIVER_Y:
                threats.append(track)
            elif track.cell.y >= 10 and track.vy > 0.15:
                incoming.append(track)

        threat_elixir = sum(BOOK.cost(t.name) for t in threats)
        threat_score = 0.0
        left_threat = 0.0
        for track in threats:
            depth = max(0.0, track.cell.y - arena.RIVER_Y) / 16.0
            ts = BOOK.threat(track.name) * (
                1.0 + float(self.cfg("threat_depth_bonus", 0.35)) * depth
            )
            threat_score += ts
            if arena.side_of(track.cell.x) == "left":
                left_threat += ts
        lane = "left" if left_threat > (threat_score / 2) else "right"
        air_threat = any(
            BOOK.is_air(t.name) and BOOK.threat(t.name) >= 3 for t in threats
        )
        # A stray Skeleton wandering over the bridge is not a push.  Without
        # this gate every tick found "a threat", the defensive rules outbid
        # everything, and the bot spent its whole elixir bar on nothing: 39 of
        # 42 plays in the first live match were defensive, Hog share 7%.
        serious = threat_score >= float(self.cfg("defend_min_threat", 5.0))
        # "Contained" means the answer is already on the field.  2.6's whole
        # game plan is to send the Hog *while* the defence plays out, so the
        # bot must be able to tell a push it is losing from one it has covered.
        if threats:
            centre = arena.centroid([t.cell for t in threats])
            radius = float(self.cfg("defend_cover_radius", 5.0))
            contained = any(arena.distance(a, centre) <= radius for a in allies)
        else:
            contained = True

        def get_hp(key, raw):
            history = self.hp_history[key]
            history.append(raw)
            if len(history) > 3:
                history.pop(0)
            if len(history) == 3:
                return sorted(history)[1]
            return history[-1]

        numbers = state.numbers
        return Observation(
            elixir=float(numbers.elixir.number),
            elapsed=float(elapsed),
            multiplier=multiplier,
            hand=hand,
            tracks=tracks,
            threats=threats,
            incoming=incoming,
            allies=allies,
            ally_names=ally_names,
            ally_hp={
                "left": get_hp("ally_left", float(numbers.left_ally_princess_hp.number)),
                "right": get_hp("ally_right", float(numbers.right_ally_princess_hp.number)),
            },
            enemy_hp={
                "left": get_hp("enemy_left", float(numbers.left_enemy_princess_hp.number)),
                "right": get_hp("enemy_right", float(numbers.right_enemy_princess_hp.number)),
            },
            threat_elixir=threat_elixir,
            threat_score=threat_score,
            threat_lane=lane,
            enemy_elixir=self.enemy.elixir,
            air_threat=air_threat,
            serious=serious,
            contained=contained,
            now=now,
        )

    def _emergency(self, obs: Observation) -> bool:
        """A push this deep is past the point of budgeting.

        Whatever the elixir arithmetic says, letting units walk into the tower
        unanswered because a cap was reached loses more than the cards would.

        Deep is not the same as dangerous, though, and this used to ask only how
        far in something was. A single Skeleton that walked to the tower scored
        1.15 and still opened the emergency door, which bypasses `serious` for
        the whole defence block and arms the last-resort branch below: 8 of 26
        `defend_fallback_*` plays across ten live matches answered a threat
        scoring 1, spending an Ice Golem or Skeletons on a unit the tower kills
        for free. The floor only has to separate that from a real one, and the
        depth bonus in `threat_score` spreads them wide - a lone Mini P.E.K.K.A.
        at the same depth scores 4.6, a Miner 6.9, and three Skeletons together
        clear 3 on their own, which is when they are worth a card.
        """
        if obs.threat_score < float(self.cfg("emergency_min_threat", 3.0)):
            return False
        depth = float(self.cfg("emergency_depth", 21))
        return any(t.cell.y >= depth for t in obs.threats)

    def _defend_clamp(self, x, y):
        """Keep defensive placements inside the pocket the towers cover.

        Predicted intercepts are extrapolated from noisy detections, so without
        this a single bad velocity estimate parks Skeletons in the corner at
        (17, 27) where they do nothing at all."""
        xr = self.cfg("defend_x_range", [2, 15])
        yr = self.cfg("defend_y_range", [17, 26])
        return arena.clamp(
            max(int(xr[0]), min(int(xr[1]), round(x))),
            max(int(yr[0]), min(int(yr[1]), round(y))),
        )

    def _multiplier(self, elapsed: float) -> float:
        if elapsed >= float(self.cfg("triple_elixir_second", 180)):
            return 3.0
        if elapsed >= float(self.cfg("double_elixir_second", 120)):
            return 2.0
        return 1.0

    # -------------------------------------------------------------- placement

    def _outranges_cannon(self, name: str) -> bool:
        """Would this unit shoot the Cannon from outside the Cannon's reach?

        Cannon reaches 5.5 tiles and a Musketeer 6.0, so a Cannon answering a
        Musketeer is destroyed without ever firing - reported from watching it
        play, and confirmed against the extracted card data. An Archer at 5.0
        does walk into range, so the test is reach, not "is it ranged". Units
        with no range data read as unknown and stay pullable.
        """
        reach = BOOK.get(name).get("range")
        mine = BOOK.get("cannon").get("range")
        return bool(reach and mine and reach > mine)

    def _clear_of_enemies(self, x: int, y: int, obs: Observation) -> Tuple[int, int]:
        """Pull a building back until it is not deploying on top of a unit.

        Nothing here is instant: a Cannon takes a full second to activate, and
        one dropped among the troops it is meant to stop absorbs free hits while
        doing nothing. Step it back toward our tower until it has room, and stop
        before it drifts out of the pocket the towers cover.
        """
        clearance = float(self.cfg("cannon_deploy_clearance", 2.5))
        ground = [t for t in obs.threats if not BOOK.is_air(t.name)]
        if not ground:
            return arena.clamp(x, y)
        limit = int(self.cfg("defend_y_range", [17, 26])[1])
        while y <= limit:
            # Only step back from units that are approaching the cannon, not
            # units that are already deeper than it.
            approaching = [t for t in ground if t.cell.y <= y + 0.5]
            if not approaching:
                break
            nearest = min(abs(t.cell.x - x) + abs(t.cell.y - y) for t in approaching)
            if nearest >= clearance:
                break
            y += 1
        return arena.clamp(x, min(y, limit))

    def cannon_spot(self, lane: str) -> Tuple[int, int]:
        """The 4-3 pull tile: four rows below the river, three columns in from
        the princess tower toward the centre.

        Web-verified Aug 2026: "4-3" means four tiles from the river and three
        from the *Crown Tower*, and the count is identical in both lanes. Our
        towers sit at x=3 and x=14, so the tiles are 6 and 11.

        This used to measure the offset from `CENTRE_X` (8.5) and round, which
        gave 6 on the left - right by coincidence, since 3 + 3 = 6 - but 12 on
        the right, a tile wider than its own mirror and *four* from the right
        tower rather than three. It also silently pushed the Musketeer, whose
        spot is derived from this one, onto x=9 in both lanes. Over 4000 logged
        episodes every right-lane tag scored below its left-lane twin
        (defend_cannon_43: -0.63 right vs -0.05 left; defend_musketeer: -2.83
        vs -1.85). Derive the left tile from the tower - integer arithmetic, so
        tuning the offset cannot land on a .5 and hit banker's rounding - and
        mirror it for the right.
        """
        y = arena.RIVER_Y + int(self.cfg("cannon_from_river", 4))
        offset = int(self.cfg("cannon_from_centre", 3))
        x = arena.ALLY_PRINCESS["left"][0] + offset
        if lane != "left":
            x = arena.mirror_x(x)
        return arena.clamp(x, y)

    def kite_spot(self, lane: str) -> Tuple[int, int]:
        """Ice Golem one tile past the centre into the *opposite* lane, which
        turns every kitable melee unit and walks it under both towers."""
        # Same mirroring rule as `cannon_spot`: build the left-lane tile, then
        # reflect it. `round(CENTRE_X - offset)` put the right-lane kite on x=8,
        # only half a column off centre against x=10 for the left.
        offset = int(self.cfg("kite_offset_from_centre", 1))
        x = int(arena.CENTRE_X + 0.5) + offset
        if lane != "left":
            x = arena.mirror_x(x)
        return arena.clamp(x, int(self.cfg("kite_y", 20)))

    def musketeer_spot(self, lane: str, threat_cell: Cell) -> Tuple[int, int]:
        """Deep, behind the fight, and spaced away from the Cannon so a single
        Fireball cannot take both."""
        y = int(round(min(
            float(self.cfg("musketeer_max_depth", 26)),
            max(float(self.cfg("musketeer_min_depth", 21)), threat_cell.y + 5),
        )))
        cannon_x, _ = self.cannon_spot(lane)
        spacing = int(self.cfg("musketeer_spacing_from_cannon", 3))
        x = cannon_x + spacing if lane == "left" else cannon_x - spacing
        return arena.clamp(round(x), y)

    def hog_spot(self, lane: str) -> Tuple[int, int]:
        y = int(self.cfg("hog_bridge_y", 17))
        if self.cfg("hog_use_bridge_column", True):
            x = arena.BRIDGE_X[lane]
        else:
            x = arena.ALLY_PRINCESS[lane][0]
        return arena.clamp(x, y)

    # -------------------------------------------------------------- decisions

    def decide(self, state, elapsed: float, now: Optional[float] = None, frame=None):
        """Return a `Candidate` to play, or None to bank elixir."""
        self.reload_config()
        obs = self.observe(state, elapsed, now, frame)
        self.last_obs = obs
        self._age_commitment(obs)
        self._resolve_experience(obs)

        candidates: List[Candidate] = []
        candidates += self._finisher(obs)
        candidates += self._defence(obs)
        candidates += self._offence(obs)
        candidates += self._spell_value(obs)
        candidates += self._cycle(obs)

        for c in candidates:
            if c.card == "the_log" and c.y < arena.RIVER_Y:
                c.y = arena.RIVER_Y

        legal = [c for c in candidates if self._legal(c, obs)]
        if not legal:
            # Nothing proposed anything. That is fine for a second or two and
            # indefensible for seventeen, which is what it reached live: three
            # elixir gates raised independently by three agents left a band
            # around 4-8 elixir where no generator fires at all, and the bot
            # stood still while the opponent built a push. Measured at 278 idle
            # ticks and a 13-23s silent stretch in every match.
            #
            # This runs only when the legal set is empty, so it can never
            # outbid a real decision - it is a floor, not a preference.
            legal = [c for c in self._anti_idle(obs) if self._legal(c, obs)]
        if not legal:
            return None
        advice = self._consult_advisor(obs)
        for candidate in legal:
            candidate.score = self.score_candidate(candidate, obs)
            candidate.score += self._advice_bonus(candidate, advice, obs)
            candidate.score += self._learned_bonus(candidate, obs)
        legal.sort(key=lambda c: c.score, reverse=True)
        best = legal[0]
        if best.score <= 0:
            return None
        return best

    def confirm(self, candidate: Candidate, obs_now: Optional[float] = None) -> None:
        """Record that `candidate` was actually played.

        Called by the runner only after both taps land, so a blocked or
        vetoed action never poisons the cooldown or commitment state.
        """
        now = time.monotonic() if obs_now is None else obs_now
        self.last_play_at = now
        self.last_card_at[candidate.card] = now
        self.last_play_index[candidate.card] = self.plays
        self.plays += 1
        self.play_counts[candidate.card] = self.play_counts.get(candidate.card, 0) + 1
        self.hand_tracker.confirm_played(candidate.slot)

        obs = self.last_obs
        if self.book is not None and obs is not None:
            # Only credit this play against units it could plausibly have
            # fought: near where it landed, and only for card families that
            # actually engage. A Hog sent at the bridge is not "beating" the
            # Ice Golem defending the other lane.
            family = candidate.weight_key.split("_")[0]
            if family in experience.ENGAGING_FAMILIES:
                engaged = [
                    t.name for t in obs.threats
                    if arena.distance(t.cell, (candidate.x, candidate.y))
                    <= experience.ENGAGE_RADIUS
                ]
            else:
                engaged = []
            # Snapshot what this play was answering, so the outcome a few
            # seconds from now can be attributed to it.
            self.book.record(
                card=candidate.card, cost=candidate.cost, tag=candidate.tag,
                situation=self.situation_of(candidate, obs),
                lane="left" if candidate.x < arena.CENTRE_X else "right",
                enemy_units=[t.name for t in obs.threats],
                enemy_ids=[
                    track_id for track_id, track in self.tracker.tracks.items()
                    if track in obs.threats
                ],
                ally_hp=_tower_total(obs.ally_hp),
                enemy_hp=_tower_total(obs.enemy_hp),
                now=now, engaged=engaged,
            )
        # accumulated votes are now stale.
        self.hand_tracker.confirm_played(candidate.slot)
        if candidate.weight_key in ("cycle", "cycle_to_hog"):
            self.last_cycle_at = now
        if candidate.weight_key == "defend_fallback":
            self.last_fallback_at = now
        if self.plan is not None and candidate.weight_key.startswith("hog"):
            self.plan.advance(now)
        if candidate.card == "hog_rider":
            self.hog_sent_at = now
            self.hog_lane = "left" if candidate.x < arena.CENTRE_X else "right"
            self.last_hog_lane = self.hog_lane
        if candidate.weight_key.startswith("defend"):
            self.committed_elixir += candidate.cost
            self.cards_this_push += 1

    def _age_commitment(self, obs: Observation) -> None:
        """The budget resets when the push is actually over, not on a timer.

        A timer-based reset let a long push refill the budget every few seconds,
        which is the same as having no budget at all.
        """
        if obs.serious:
            self.last_serious_at = obs.now
            return
        # Unit detection flickers: a push reads as "not serious" for a single
        # frame whenever two detections drop out, and an instant reset handed
        # the budget straight back.  Observed live as `spent=0` on defensive
        # plays against a threat score of 24 - the cap was never binding.
        if obs.now - self.last_serious_at > float(self.cfg("commit_clear_seconds", 2.5)):
            self.committed_elixir = 0.0
            self.cards_this_push = 0
            self.commit_started = obs.now

    # ------------------------------------------------------------------ rules

    def _finisher(self, obs: Observation) -> List[Candidate]:
        """Fireball a princess tower that is one spell from falling.

        Guarded by "no live threat", because trading the only Fireball for a
        tower while a push is walking in loses more than it gains.
        """
        if obs.serious or "fireball" not in obs.hand:
            return []
        alive = {s: hp for s, hp in obs.enemy_hp.items() if hp > 0.0}
        if not alive:
            return []
        side = min(alive, key=alive.get)
        hp = alive[side]
        x, y = arena.ENEMY_PRINCESS[side]

        # A Fireball removes 5.2% of a tower, not 15%. Firing at the old
        # threshold spent four elixir to leave the tower alive at ~10%.
        # A Hog already swinging counts toward the total, which is what lets
        # this finish at 8% rather than waiting for 5%.
        inbound = 0.0
        if obs.now - self.hog_sent_at <= float(self.cfg("hog_inbound_seconds", 6.0)):
            inbound = float(self.cfg("hog_inbound_tower_fraction", 0.06))
        if spellinfo.can_finish("fireball", hp, inbound):
            return [Candidate(
                card="fireball", slot=obs.hand["fireball"], x=x, y=y,
                tag=f"finish_{side}_{hp:.3f}", weight_key="finish_tower",
            )]

        # Otherwise chip. 5.2% for four elixir is small but it decides close
        # games, and the deck has no other use for a spare Fireball when there
        # is nothing on the field to answer. Log is deliberately excluded: at
        # 1.05% per cast it is a quarter of the damage per elixir and it is the
        # only answer to a ground swarm.
        # Only on an empty board. The Fireball is also the deck's answer to a
        # support cluster, so spending it on 5% of a tower while units are
        # massing on their side trades the answer away right before it is
        # needed. `serious` alone is not enough of a guard - it only counts
        # threats already past the river.
        if obs.tracks:
            return []
        if spellinfo.worth_chipping("fireball", obs.elixir, COSTS["fireball"],
                                    obs.multiplier,
                                    float(self.cfg("chip_spare_elixir", 8.0))):
            return [Candidate(
                card="fireball", slot=obs.hand["fireball"], x=x, y=y,
                tag=f"chip_{side}_{hp:.2f}", weight_key="chip_tower",
            )]
        return []

    def _defence(self, obs: Observation) -> List[Candidate]:
        if not obs.threats or (not obs.serious and not self._emergency(obs)):
            return []
        out: List[Candidate] = []
        lane = obs.threat_lane
        lead = float(self.cfg("predict_seconds", 1.4))
        # Lead the push: answer where it will be, not where it was.
        predicted = [t.predict(lead) for t in obs.threats]
        centre = arena.centroid(predicted)
        deepest = max(predicted, key=lambda c: c.y)

        air = [t for t in obs.threats if BOOK.is_air(t.name)]
        # Kite only genuine heavies.  At a threshold of 4 the Ice Golem was
        # spent kiting cheap ground units 4.5 times a match, so it was never in
        # hand to lead the Hog - which is its other, more important job.
        kite_floor = float(self.cfg("kite_min_threat", 6))
        kitable = [t for t in obs.threats
                   if BOOK.kitable(t.name) and BOOK.threat(t.name) >= kite_floor
                   and t.name != "royal_recruit"]
        big = [t for t in obs.threats if BOOK.get(t.name)["win_con"] or BOOK.get(t.name)["tank"]]
        swarm_cells = [
            t.predict(lead) for t in obs.threats
            if not BOOK.is_air(t.name) and (BOOK.get(t.name)["swarm"] or BOOK.dies_to("the_log", t.name))
        ]

        # 1. Air first: the Cannon cannot shoot it, so answering air with a
        #    Cannon is a wasted three elixir and a lost tower.
        if air:
            if "musketeer" in obs.hand:
                mx, my = self.musketeer_spot(lane, deepest)
                out.append(Candidate("musketeer", obs.hand["musketeer"], mx, my,
                                     f"defend_air_musketeer_{lane}", "defend_air"))
            # Ice Spirit only stalls air; it does not kill a Balloon or a
            # Baby Dragon.  Offering it as a headline air answer meant a one
            # elixir card was repeatedly "answering" a five elixir threat.
            # But a stall beats doing nothing: if no real anti-air is in hand,
            # it is the best available answer rather than a bad one.  A fixed
            # threshold alone left the bot silent against air with Ice Spirit
            # sitting in hand.
            air_weight = sum(BOOK.threat(t.name) for t in air)
            if "ice_spirit" in obs.hand and air_weight <= float(self.cfg("ice_spirit_max_air_threat", 5)):
                sx, sy = self._clear_of_enemies(*self._defend_clamp(centre.x, centre.y), obs)
                out.append(Candidate("ice_spirit", obs.hand["ice_spirit"], sx, sy,
                                     "defend_air_ice_spirit", "defend_air_weak"))
            if "fireball" in obs.hand:
                killable = [c for t, c in zip(obs.threats, predicted)
                            if not BOOK.get(t.name).get("tank", False) and t.name != "skeleton"]
                cluster = arena.densest_cluster(killable, float(self.cfg("fireball_radius", 2.6)), 2)
                if cluster is not None:
                    cell, count = cluster
                    out.append(Candidate("fireball", obs.hand["fireball"],
                                         round(cell.x), round(cell.y),
                                         f"defend_air_fireball_x{count}", "defend_spell"))

        # 2. Ground swarm walking at the tower: The Log is the cheapest answer.
        if "the_log" in obs.hand and len(swarm_cells) >= int(self.cfg("log_min_units", 3)):
            cluster = arena.densest_cluster(swarm_cells, float(self.cfg("log_radius", 2.2)),
                                            int(self.cfg("log_min_units", 3)))
            if cluster is not None:
                cell, count = cluster
                if count >= int(self.cfg("log_min_units", 3)):
                    out.append(Candidate("the_log", obs.hand["the_log"],
                                         round(cell.x), min(31, round(cell.y) + 1),
                                         f"defend_log_x{count}", "defend_swarm"))

        # 3. Fireball a support cluster.  Judged by the elixir it kills, not by
        #    a unit count: a Musketeer and a Mega Minion together are seven
        #    elixir and well worth four, but they are only two units and a
        #    count-of-three rule left the bot with no answer at all.
        if "fireball" in obs.hand:
            named = [(t.name, c) for t, c in zip(obs.threats, predicted)
                     if not BOOK.get(t.name).get("tank", False) and not BOOK.get(t.name).get("win_con", False) and t.name != "skeleton"]
            killable = [c for _, c in named]
            radius = float(self.cfg("fireball_radius", 2.6))
            cluster = arena.densest_cluster(killable, radius, 1)
            if cluster is not None:
                cell, count = cluster
                value = self._cluster_value(named, cell, radius)
                if (count >= int(self.cfg("fireball_min_units", 3))
                        or value >= float(self.cfg("spell_min_value_elixir", 4))):
                    out.append(Candidate("fireball", obs.hand["fireball"],
                                         round(cell.x), round(cell.y),
                                         f"defend_fireball_x{count}_e{value:.0f}",
                                         "defend_spell"))

        # 4. Kite a melee heavy across the arena with Ice Golem.  This is the
        #    single highest-value defensive technique the deck has.
        if kitable and "ice_golem" in obs.hand:
            kx, ky = self.kite_spot(lane)
            out.append(Candidate("ice_golem", obs.hand["ice_golem"], kx, ky,
                                 f"defend_kite_{lane}", "defend_kite"))

        # 5. Cannon pulls anything that targets buildings, and tanks a ground
        #    push while both princess towers work.  Never against pure air.
        cannon_targets = [t for t in obs.threats if not BOOK.is_air(t.name) or BOOK.get(t.name).get("win_con", False)]
        # A Cannon earns its elixir by pulling something that must walk into its
        # range. Against attackers that outrange it there is nothing to pull and
        # it is a three-elixir gift, so it is offered only when at least one
        # threat will actually close the distance.
        pullable = [t for t in cannon_targets if not self._outranges_cannon(t.name)]
        if pullable and sum(BOOK.threat(t.name) for t in pullable) >= float(self.cfg("cannon_min_threat", 5.0)) and "cannon" in obs.hand:
            if "cannon" not in obs.ally_names:
                cx, cy = self._clear_of_enemies(*self.cannon_spot(lane), obs)
                out.append(Candidate("cannon", obs.hand["cannon"], cx, cy,
                                     f"defend_cannon_43_{lane}", "defend_cannon"))

        # 6. Skeletons surround a ground attacker for one elixir.
        singles = [
            (t, c) for t, c in zip(obs.threats, predicted)
            if not BOOK.is_air(t.name) and not BOOK.get(t.name)["swarm"]
            and t.name != "royal_recruit"
        ]
        if singles and "skeletons" in obs.hand:
            _, cell = max(singles, key=lambda sc: sc[1].y)
            offset = int(self.cfg("skeleton_surround_offset", 1))
            sx, sy = self._defend_clamp(cell.x, cell.y + offset)
            weight = "defend_single"
            if any(t.name in ("pekka", "mini_pekka") for t, _ in singles):
                weight = "defend_outranged"
            out.append(Candidate("skeletons", obs.hand["skeletons"], sx, sy,
                                 "defend_skeletons_surround", weight))

        # 6.5. Ice Spirit stalls ground units.  The freeze is only 1.1 seconds,
        #      so this is support, not an answer - the guides use it to hold a
        #      lone Musketeer or Wizard still *and then surround with
        #      Skeletons*, which is what actually kills it.  Offered ungated it
        #      became the single most-played tag in block 73 (19 of 154 plays),
        #      and the log says 88 of ~160 stalls were against exactly one
        #      unit, where rule 6 already had a one-elixir answer that kills.
        #      Both carry weight_key "defend_single", so the stall was winning
        #      those bids on tie-break and spending the setup card without the
        #      follow-up.  So: against a lone attacker, defer to the Skeletons
        #      when they are in hand.  When they are not, the stall is still
        #      the best cheap thing available and stays on offer.
        lone_ground = len(singles) == 1
        stall_deferred = lone_ground and "skeletons" in obs.hand
        if "ice_spirit" in obs.hand and not air and not stall_deferred:
            sx, sy = self._clear_of_enemies(*self._defend_clamp(centre.x, centre.y), obs)
            weight = "defend_single"
            out.append(Candidate("ice_spirit", obs.hand["ice_spirit"], sx, sy,
                                 "defend_stall_ice_spirit", weight))

        # 7. Ranged support with nothing better: Musketeer, deep.
        #
        # Against a push made of units that outrange our short answers, the
        # Musketeer is not "nothing better" - it is the only thing that works.
        # Measured in the simulator, one attacking Musketeer leaks 880 tower
        # damage past a Cannon, Skeletons, an Ice Spirit or an Ice Golem alike,
        # and zero past our Musketeer; a Wizard leaks 284 past everything else.
        # Those cheap answers are not weak here, they are irrelevant, so the
        # Musketeer gets its own weight rather than competing on equal terms.
        if "musketeer" in obs.hand and not air and (obs.serious or self._emergency(obs)):
            mx, my = self.musketeer_spot(lane, deepest)
            ground = [t for t in obs.threats if not BOOK.is_air(t.name)]
            outranged = [t for t in ground if self._outranges_cannon(t.name)]
            if ground and len(outranged) * 2 >= len(ground):
                out.append(Candidate("musketeer", obs.hand["musketeer"], mx, my,
                                     f"defend_outranged_{lane}", "defend_outranged"))
            else:
                out.append(Candidate("musketeer", obs.hand["musketeer"], mx, my,
                                     f"defend_musketeer_{lane}", "defend_ranged"))

        # 8. Last resort so a big push is never met with nothing at all.  Gated
        #    well above the ordinary defence bar: spending a card here when the
        #    proper answer simply is not in hand is how the deck bleeds elixir.
        # Last resort, on two conditions only: something is about to connect,
        # or air is coming and nothing above produced an answer to it.
        #
        # Gating on a big threat *number* instead meant the bot dumped its last
        # one or two elixir on a push still crossing the bridge and had nothing
        # left when it arrived - eight of twenty-one plays in a live match.
        # Predicting "a better card is in hand" does not work either: Fireball
        # looks like an air answer but kills neither Musketeer nor Mega Minion
        # at equal level (verified), so it produces no candidate and the bot
        # stood there holding an Ice Spirit it had talked itself out of.
        # One last resort per push, not three.  The rule fires again on the very
        # next tick because the card it just spent has left the hand, so a single
        # push drew Ice Golem, then Skeletons, then Ice Spirit three seconds
        # apart: 113 of 513 plays across fifteen matches were this branch, and
        # the bot idled at two or three elixir 89% of the time as a result.  The
        # gap keeps the safety net for a push that is genuinely unanswered while
        # stopping it from emptying the bar into one that already ate a card.
        recent_fallback = obs.now - self.last_fallback_at < float(
            self.cfg("fallback_min_gap_seconds", 4.0))
        if not any(self._legal(c, obs) for c in out) and not recent_fallback and (self._emergency(obs) or (air and obs.serious)):
            # Against air, only offer cards that can actually shoot it. The old
            # air order was ("ice_spirit", "ice_golem", "skeletons") and two of
            # those three are ground-targeting: Ice Golem is a building-targeting
            # ground troop and Skeletons are ground-targeting melee (both
            # verified against the card wiki, and both already flagged
            # `hits_air: false` in units.json). With no Ice Spirit in hand the
            # branch dropped the Hog's tank in front of a Minion Horde it could
            # not touch - 32 of 56 fallback plays across 25 matches were
            # `defend_fallback_ice_golem`, more than the ground-first Skeletons
            # at 17, which is only possible if the air branch is the source.
            # If nothing in hand hits air, playing nothing is the cheaper error.
            fallback_order = ("ice_spirit", "ice_golem", "skeletons")
            if air:
                fallback_order = tuple(n for n in fallback_order if BOOK.hits_air(n))
            else:
                fallback_order = ("skeletons", "ice_spirit", "ice_golem")
            for name in fallback_order:
                if name in obs.hand:
                    fx, fy = self._defend_clamp(centre.x, centre.y)
                    out.append(Candidate(name, obs.hand[name], fx, fy,
                                         f"defend_fallback_{name}", "defend_fallback"))
                    break
        return out

    def _offence(self, obs: Observation) -> List[Candidate]:
        """Execute a push plan, or start one when the moment is right.

        The old version emitted a Hog whenever one was affordable and no push
        was incoming.  That is what produced the lone Hog walking into a full
        elixir bar.  Now a push is committed to as a unit: we only start one we
        can pay for in full, and a bare Hog is reserved for the case where the
        opponent demonstrably cannot answer it.
        """
        out: List[Candidate] = []

        if push.expired(self.plan, obs.now):
            self.plan = None
        # A push into a serious threat we have not contained is not a push,
        # it is giving away the game.
        if self.plan is not None and obs.serious and not obs.contained:
            self.plan.abandoned = True
            self.plan = None

        if self.plan is None:
            self.plan = self._choose_plan(obs)

        if self.plan is not None and self.plan.ready(obs.now):
            step = self.plan.current
            slot = obs.hand.get(step.card)
            # An optional step we cannot pay for is dropped, not waited on. Left
            # blocking, a missing Ice Spirit would hold the whole plan open until
            # it expired and stop the next push from starting.
            if (slot is None or obs.elixir < COSTS.get(step.card, 4)) and step.optional:
                self.plan.skip(obs.now)
                step = self.plan.current
                slot = obs.hand.get(step.card) if step else None
            if step is not None and slot is not None:
                hx, hy = self.hog_spot(self.plan.lane)
                if step.role == "support":
                    hy = min(31, hy + 2)      # behind the Hog, not in front
                elif step.role == "freeze":
                    # Same column as the Hog and level with the bridge, so the
                    # Spirit walks the same line and reaches the defender rather
                    # than trailing a couple of tiles behind it. Troops cannot be
                    # placed in the enemy half, so this is as far forward as the
                    # freeze can start.
                    hy = max(arena.RIVER_Y, hy - 1)
                out.append(Candidate(
                    step.card, slot, hx, hy,
                    f"push_{self.plan.name}_{step.role}_{self.plan.lane}",
                    "hog_punish" if self.plan.name == "punish"
                    else "hog_counterpush" if self.plan.name == "counterpush"
                    else "hog_push",
                ))
        return out

    def _choose_plan(self, obs: Observation):
        """Pick a push, or None to keep banking.

        Ordered by how likely the Hog is to connect, which is the only thing
        that scores in this deck.
        """
        if "hog_rider" not in obs.hand:
            return None
        if obs.now - self.hog_sent_at < float(self.cfg("hog_repeat_seconds", 6.0)):
            return None
        if obs.serious and not obs.contained:
            return None

        lane = self._attack_lane(obs)
        reserve = float(self.cfg("push_reserve_elixir", 1))

        # 0. The default push, tried before any of the lone-Hog paths below.
        #    Block 125 sent 37 Hogs and every one of them was naked: the tags
        #    were all probe/punish/counterpush and `push_golem_hog` appeared
        #    zero times, for 0.10 tower damage per match.  The cause was
        #    ordering, not judgement - the punish path sits on
        #    `opponent.answer_ready()`, which is false often enough that it
        #    claimed nearly every Hog before the Golem push was ever reached.
        #
        #    The guides are unambiguous that Golem-then-Hog is the default and
        #    the lone Hog is the exception, so the ladder now matches: if the
        #    tank is in hand and we can pay for the pair, tank it.  Everything
        #    below is unchanged and still catches the case where we cannot -
        #    at under seven elixir this falls straight through to punish.
        plan = push.build_plan("golem_hog", lane, obs.hand, obs.now)
        if plan and obs.elixir >= plan.total_cost + reserve:
            return plan

        # 2. A defence that is holding has already drained them.
        #    Pulled above punish so we don't return None and block a valid counterpush.
        if self.committed_elixir > 0 and obs.contained:
            cp_plan = push.build_plan("counterpush", lane, obs.hand, obs.now)
            # Only the Hog has to be affordable now; the support step waits.
            if cp_plan and obs.elixir >= COSTS["hog_rider"]:
                return cp_plan

        # 1. They just committed real elixir somewhere: send it now, alone,
        #    before they regenerate.  Keyed on spend we actually observed, not
        #    on the drifting running estimate, which read "empty" nearly always
        #    and turned every moment into a lone-Hog punish.
        # 0. Their answer to a Hog is provably not in hand - it is fewer than
        #    four of their deploys ago, so it cannot have cycled back. This is a
        #    far more reliable signal than the inferred elixir bar, because a Hog
        #    is stopped by a specific card rather than by elixir, and it only
        #    claims the confident direction (see brain/opponent.py).
        big_commit = float(self.cfg("punish_min_recent_spend", 5))
        if not self.opponent.answer_ready() or self.enemy.recent_spend(obs.now) >= big_commit:
            punish_plan = push.build_plan("punish", lane, obs.hand, obs.now)
            if punish_plan and obs.elixir >= punish_plan.total_cost:
                return punish_plan

        # 4. No Golem in hand. A lone Hog is still fine when we are rich enough
        #    that losing the trade does not also lose the tower.
        #
        #    In double and triple elixir that bar comes down: elixir refills in
        #    1.4s or 0.9s instead of 2.8s, so holding a full bar back costs far
        #    more than it protects. 2.6 turns aggressive in overtime and the bot
        #    was still budgeting as if it were the first minute.
        probe_floor = float(self.cfg("probe_min_elixir", 8))
        if obs.multiplier >= 3.0:
            probe_floor -= float(self.cfg("overtime_probe_discount", 3))
        elif obs.multiplier >= 2.0:
            probe_floor -= float(self.cfg("double_probe_discount", 2))
        if obs.elixir >= probe_floor:
            return push.build_plan("probe", lane, obs.hand, obs.now)
        return None

    def _attack_lane(self, obs: Observation) -> str:
        """Attack the weaker tower; if they are level, punish the lane the
        opponent just committed away from, otherwise alternate."""
        left, right = obs.enemy_hp["left"], obs.enemy_hp["right"]
        if left <= 0.0 and right > 0.0:
            return "right"
        if right <= 0.0 and left > 0.0:
            return "left"
        if abs(left - right) >= 0.12:
            return "left" if left < right else "right"

        # Attack the lane their defence is not in. Their surviving units sitting
        # on their own half are defenders, and a Hog sent at the lane they are
        # already committed to is a Hog into a prepared answer - which is most of
        # why a lone Hog "doesn't get much damage in". Lane choice was previously
        # decided by tower HP and simple alternation, ignoring the board.
        defenders = [t for t in obs.tracks if t.cell.y < arena.RIVER_Y]
        if defenders:
            on_left = sum(1 for t in defenders if t.cell.x < arena.CENTRE_X)
            on_right = len(defenders) - on_left
            if abs(on_left - on_right) >= int(self.cfg("lane_defender_margin", 2)):
                return "right" if on_left > on_right else "left"

        if self.enemy_back_placement_lane:
            return "right" if self.enemy_back_placement_lane == "left" else "left"
        return "left" if self.last_hog_lane == "right" else "right"

    def _punish_window(self, obs: Observation) -> bool:
        """True when the opponent has just invested behind their towers, which
        is the moment a Hog is most likely to connect."""
        for track in obs.tracks:
            props = BOOK.get(track.name)
            if track.cell.y <= 8 and props["cost"] >= 5 and not props["building"]:
                self.enemy_back_placement_lane = arena.side_of(track.cell.x)
                self.enemy_spend_at = obs.now
                return True
        return obs.now - self.enemy_spend_at <= 5.0

    def _cluster_value(self, named_cells, cell, radius: float) -> float:
        """Elixir the opponent loses if a spell lands here.

        Counting *units* was not enough: three Skeletons are three units and
        nearly zero elixir, and the bot was throwing a four-elixir Fireball at
        them.  Spawned units carry cost 0 in the unit table precisely so this
        sum stays honest."""
        return sum(
            BOOK.cost(name) for name, c in named_cells
            if arena.distance(c, cell) <= radius
        )

    def _spell_value(self, obs: Observation) -> List[Candidate]:
        """Spells outside a defence, only on a cluster big enough to be worth
        the elixir.  The old policy fired Fireball at whatever the checkpoint
        pointed at, which is the "randomly fireballs" behaviour."""
        out: List[Candidate] = []
        cells_by_name = [(t.name, t.cell) for t in obs.tracks]
        if not cells_by_name:
            return out

        if "fireball" in obs.hand:
            killable = [c for n, c in cells_by_name if not BOOK.get(n).get("tank", False) and n != "skeleton"]
            cluster = arena.densest_cluster(
                killable, float(self.cfg("fireball_radius", 2.6)),
                2,
            )
            if cluster is not None:
                cell, count = cluster
                value = self._cluster_value(cells_by_name, cell,
                                            float(self.cfg("fireball_radius", 2.6)))
                if value >= float(self.cfg("spell_min_value_elixir", 4)):
                    out.append(Candidate("fireball", obs.hand["fireball"],
                                         round(cell.x), round(cell.y),
                                         f"value_fireball_x{count}_e{value:.0f}",
                                         "spell_value"))
                cluster = None if value < float(self.cfg("spell_min_value_elixir", 4)) else cluster
            if cluster is None:
                # A single expensive support unit is also fair Fireball value.
                for name, cell in cells_by_name:
                    props = BOOK.get(name)
                    # Only worth it if the unit is actually coming at us, or if
                    # the splash also lands on their tower.  Otherwise the bot
                    # spends its defensive Fireball on a support unit parked in
                    # their own back corner.
                    approaching = cell.y >= arena.RIVER_Y - 2
                    on_tower = any(
                        arena.distance(cell, tower) <= float(self.cfg("fireball_radius", 2.6))
                        for tower in arena.ENEMY_PRINCESS.values()
                    )
                    if not (approaching or on_tower):
                        continue
                    if (props["cost"] >= int(self.cfg("fireball_min_value_cost", 4))
                            and not props.get("tank", False)
                            and not props.get("win_con", False)):
                        out.append(Candidate("fireball", obs.hand["fireball"],
                                             round(cell.x), round(cell.y),
                                             f"value_fireball_{name}", "spell_value"))
                        break

        if "the_log" in obs.hand:
            max_reach = arena.RIVER_Y - int(self.cfg("log_max_y_from_river", 4))
            killable_named = [
                (n, c) for n, c in cells_by_name
                if BOOK.dies_to("the_log", n) and c.y >= max_reach
            ]
            killable = [c for n, c in killable_named]
            cluster = arena.densest_cluster(
                killable, float(self.cfg("log_radius", 2.2)),
                int(self.cfg("log_min_units", 3)),
            )
            if cluster is not None:
                cell, count = cluster
                if count >= int(self.cfg("log_min_units", 3)):
                    value = self._cluster_value(killable_named, cell,
                                                float(self.cfg("log_radius", 2.2)))
                    if value >= float(self.cfg("log_min_value_elixir", 3)):
                        out.append(Candidate("the_log", obs.hand["the_log"],
                                             round(cell.x), min(31, round(cell.y) + 1),
                                             f"value_log_x{count}_e{value:.0f}", "spell_value"))
        return out

    def _anti_idle(self, obs: Observation) -> List[Candidate]:
        """Last resort: play the cheapest sensible card rather than stand still.

        Deliberately dumb and deliberately last. It fires only when every other
        generator produced nothing and we have been idle past
        `max_idle_seconds`, so it cannot compete with a real play; it exists so
        that a combination of thresholds nobody checked together cannot freeze
        the bot. The Hog is excluded - he is the win condition, not filler - and
        a spell goes at the weaker enemy tower rather than our own back line,
        where it would be pure waste.
        """
        # Measured from the last play *or* the start of the match, whichever is
        # later. A fresh Brain has last_play_at = 0, which would otherwise read
        # as infinitely idle and fire on the opening tick.
        since = max(self.last_play_at, self.match_started_at)
        if obs.now - since < float(self.cfg("max_idle_seconds", 6.0)):
            return []
        spot = arena.clamp(*self.cfg("cycle_spot", [9, 27]))
        # Filler must not spend the elixir the win condition is waiting on. With
        # the Hog in hand at five elixir, playing a one-cost card leaves four and
        # the Hog stays home - the floor would be curing idleness by delaying the
        # only card that scores.
        reserve = 0.0
        if "hog_rider" in obs.hand:
            if obs.serious and not obs.contained:
                reserve = float(self.cfg("hog_min_elixir_defending", 8.0))
            elif obs.serious:
                reserve = float(self.cfg("hog_min_elixir_contained", 6.0))
            else:
                reserve = float(self.cfg("probe_min_elixir", 7.0))
                if obs.multiplier >= 3.0:
                    reserve -= float(self.cfg("overtime_probe_discount", 3.0))
                elif obs.multiplier >= 2.0:
                    reserve -= float(self.cfg("double_probe_discount", 2.0))
        # Same tie-break `_cycle` already applies: at cost 2 the Ice Golem ties
        # with the Log, and filler should spend the Log first. The Golem is the
        # Hog's tank, and 15 `idle_cycle_ice_golem` plays across 25 matches each
        # dropped it at our own back line while a Golem-Hog push was affordable.
        #
        # The filler reads its own exclusion list rather than sharing
        # `cycle_unblock_exclude`, because the two paths now want different
        # answers for the Ice Golem. `_cycle_unblock` is the documented
        # last-resort valve of `_comment_cycle_cards` - once `the_log` joined
        # the shared list the Golem became the only card that path can still
        # play, so excluding it there would make the valve dead code. The
        # filler has no such role: it fires at any elixir and dumped the Golem
        # at (9,31) 20 times in 20 matches. Defaults to the shared list so
        # removing the key restores the old behaviour exactly.
        skip = set(self.cfg("anti_idle_exclude",
                            self.cfg("cycle_unblock_exclude",
                                     ["hog_rider", "cannon", "fireball", "musketeer"])))
        def anti_idle_key(n):
            c = COSTS.get(n, 4)
            if n == "ice_golem": c = 5
            if n in skip: c += 10
            return c

        for name in sorted(obs.hand, key=anti_idle_key):
            cost = COSTS.get(name, 4)
            if name == "hog_rider" or cost > obs.elixir:
                continue
            if reserve and obs.elixir - cost < reserve:
                continue
            if name == "cannon":
                continue
            if name in SPELLS:
                # `_chip` already refuses to chip with the Log, and the reason
                # applies here too: web-verified Aug 2026, the Log does 13% of
                # its damage to a Crown Tower against the Fireball's 25%, off a
                # smaller base, and it is this deck's only answer to a ground
                # swarm. Filler must not trade it away. Measured over 4000
                # episodes `idle_chip_the_log` was the worst thing the current
                # policy does at volume: 116 plays, mean -1.98, -230 total,
                # against -1.2 to -1.4 for dropping a cheap troop instead.
                # Skipping it here falls through to the next card in the sort.
                if name not in set(self.cfg("idle_chip_spells", ["fireball"])):
                    continue
                side = min(obs.enemy_hp, key=obs.enemy_hp.get) if obs.enemy_hp else "left"
                tx, ty = arena.ENEMY_PRINCESS[side]
                if name == "the_log":
                    ty = max(ty, arena.RIVER_Y)
                return [Candidate(name, obs.hand[name], tx, ty,
                                  f"idle_chip_{name}_{side}", "cycle")]
            if name in skip:
                continue
            return [Candidate(name, obs.hand[name], spot[0], spot[1],
                              f"idle_cycle_{name}", "cycle")]
        return []

    def _cycle(self, obs: Observation) -> List[Candidate]:
        """Cycling is the deck, not a fallback."""
        spot = arena.clamp(*self.cfg("cycle_spot", [9, 27]))
        order = self.cfg("cycle_cards", ["skeletons", "ice_spirit", "ice_golem"])
        cheap = [n for n in order if n in obs.hand]

        cycled_recently = obs.now - self.last_cycle_at < float(self.cfg("cycle_min_gap_seconds", 2.5))

        if cheap and obs.elixir >= float(self.cfg("cycle_elixir", 8.5)) and not cycled_recently:
            return [Candidate(cheap[0], obs.hand[cheap[0]], spot[0], spot[1],
                              f"cycle_{cheap[0]}", "cycle")]

        # Cycling fast is the point, but two cards inside one second is not
        # cycling, it is dumping: the live log caught two Ice Spirits at t=0 and
        # t=1 with a full bar and nothing to answer.
        if "hog_rider" in obs.hand or (obs.serious and not obs.contained) or cycled_recently:
            return []

        if cheap and obs.elixir >= float(self.cfg("cycle_to_hog_elixir", 5)):
            return [Candidate(cheap[0], obs.hand[cheap[0]], spot[0], spot[1],
                              f"cycle_to_hog_{cheap[0]}", "cycle_to_hog")]

        # Cycle-blocked: no Hog and no cheap card, so the hand is the expensive
        # cards and nothing can advance.  Measured across 42 matches, Musketeer,
        # Fireball and Log were each under 5% of plays while the four cheap
        # cards made up 78% - the bot was sitting on the expensive cards and so
        # could never rotate back to its win condition.  At high elixir the
        # cheapest available card is worth playing purely to unblock the cycle.
        if obs.elixir < float(self.cfg("cycle_any_elixir", 8)):
            return []
        # The win condition, the building and the two 4-cost answers are never
        # cycle chaff.  Musketeer joined the list on the block-153 evidence:
        # `cycle_unblock_musketeer` fired 7 times, 29% of all 24 Musketeers in
        # the block, every one of them dropped at (9,31) behind the king tower
        # where it does nothing and is then not in hand for the next air push.
        # It was reached because the sort key ranks ice_golem as cost 5 to keep
        # it last, so the 4-cost Musketeer sorted *ahead* of the 2-cost Golem -
        # which contradicts `_comment_cycle_cards`, whose stated design is that
        # the Golem is the unblock card of last resort once we are rich enough
        # that losing it costs nothing.  Skipping it restores that intent.
        skip = set(self.cfg("cycle_unblock_exclude",
                            ["hog_rider", "cannon", "fireball", "musketeer"]))
        for name in sorted(obs.hand, key=lambda n: (COSTS.get(n, 4) if n != "ice_golem" else 5)):
            if name in skip:
                continue
            if name in SPELLS:
                # A spell dropped at our own back line is pure waste; thrown at
                # the weaker enemy tower it at least buys chip damage.
                side = min(obs.enemy_hp, key=obs.enemy_hp.get) if obs.enemy_hp else "left"
                tx, ty = arena.ENEMY_PRINCESS[side]
                if name == "the_log":
                    ty = max(ty, arena.RIVER_Y)
                return [Candidate(name, obs.hand[name], tx, ty,
                                  f"cycle_chip_{name}_{side}", "cycle_to_hog")]
            return [Candidate(name, obs.hand[name], spot[0], spot[1],
                              f"cycle_unblock_{name}", "cycle_to_hog")]
        return []

    # ------------------------------------------------------------- learning

    def situation_of(self, candidate: Candidate, obs: Observation) -> str:
        return experience.situation_key(
            candidate.weight_key, obs.threat_score, obs.air_threat, obs.contained
        )

    def _learned_bonus(self, candidate: Candidate, obs: Observation) -> float:
        """What experience says about playing this card in this situation.

        Clamped and damped by sample count on purpose: a few lucky episodes
        must not be able to overrule a hand-written rule that came from the
        actual 2.6 guides.
        """
        if self.book is None:
            return 0.0
        return self.book.bias(
            self.situation_of(candidate, obs),
            candidate.card,
            float(self.cfg("learning_scale", 1.2)),
            float(self.cfg("learning_limit", 14.0)),
        )

    def _resolve_experience(self, obs: Observation) -> None:
        if self.book is None:
            return
        live = set(self.tracker.tracks.keys())
        self.book.resolve(
            obs.now, live, _tower_total(obs.ally_hp), _tower_total(obs.enemy_hp),
            BOOK.cost,
        )

    # -------------------------------------------------------------- advisor

    def _consult_advisor(self, obs: Observation):
        """Hand the model the current state and take whatever it last said.

        Deliberately non-blocking: the loop runs at about 2Hz and a call costs
        roughly 0.8s, so waiting would halve the bot's reaction speed to buy an
        opinion that is barely staler if we simply read the previous one.
        """
        if self.advisor is None:
            return None
        try:
            self.advisor.submit(advisor_mod.snapshot_from(obs, sorted(obs.hand)))
            advice = self.advisor.latest()
        except Exception:
            return None
        if advice is None:
            return None
        max_age = float(self.cfg("advice_max_age_seconds", 3.0))
        if not advice.fresh(obs.now, max_age):
            return None
        self.advice_used += 1
        return advice

    def _advice_bonus(self, candidate: Candidate, advice, obs: Observation) -> float:
        """Nudge, never decide.

        The model only reweights options the rule engine already produced and
        already judged legal, so a hallucinated card or a nonsensical tile
        cannot reach the emulator.
        """
        if advice is None:
            return 0.0
        weight = float(self.cfg("advice_weight", 18.0))
        bonus = 0.0
        family = candidate.weight_key

        if advice.intent == "defend" and family.startswith("defend"):
            bonus += weight
        elif advice.intent == "push" and family.startswith("hog"):
            bonus += weight
        elif advice.intent == "cycle" and family in ("cycle", "cycle_to_hog"):
            bonus += weight
        elif advice.intent == "hold" and family in ("cycle", "spell_value"):
            bonus -= weight

        if advice.card and candidate.card == advice.card:
            bonus += weight * 0.5
        # Lane agreement only counts for attacking; defence must answer the
        # lane the push is actually in, whatever the model says.
        if family.startswith("hog"):
            lane = "left" if candidate.x < arena.CENTRE_X else "right"
            if lane == advice.lane:
                bonus += weight * 0.25
        return bonus

    # ------------------------------------------------------------- scoring

    def score_candidate(self, candidate: Candidate, obs: Observation) -> float:
        """Feature-weighted score.  Kept linear and explicit so the review
        loop can reason about, and edit, why one action beat another."""
        base = self.weight(candidate.weight_key)
        features = {
            "threat": obs.threat_score,
            "surplus": max(0.0, obs.elixir - candidate.cost),
            "depth": max((t.cell.y for t in obs.threats), default=0.0) - arena.RIVER_Y,
        }
        score = base

        if candidate.weight_key.startswith("defend"):
            score += self.weight("threat_scale") * features["threat"]
            score += self.weight("depth_scale") * max(0.0, features["depth"])
            if obs.now - self.last_card_at.get(candidate.card, -99) < 2.0:
                score += self.weight("unanswered_penalty") * 0.5
            # Our units are already on this push.  Adding more defence is
            # over-committing, and over-committing is how a cycle deck loses:
            # the elixir difference is supposed to become a counter-push.
            # This replaces the blunt hard cap, which cut defence off entirely
            # and cost 10 crowns to 3 over ten matches.
            if obs.contained:
                score += self.weight("contained_defence_penalty")
        else:
            score += self.weight("elixir_surplus_scale") * features["surplus"]
            # Keep elixir back for a push we still have to answer - but not for
            # one our units are already handling.  Counter-pushing at low elixir
            # off a contained defence is the deck's core play, not a risk.
            if obs.serious and not obs.contained:
                reserve = float(self.cfg("reserve_elixir_when_threatened", 3))
                if obs.elixir - candidate.cost < reserve:
                    score += self.weight("unanswered_penalty")
            if candidate.card == "hog_rider":
                score += 2.0 * obs.multiplier
                # Chip the tower that is closest to falling.
                target = min(obs.enemy_hp.values()) if obs.enemy_hp else 1.0
                score += 6.0 * (1.0 - target)

        candidate.features = features
        return score

    # ------------------------------------------------------------- legality

    def _legal(self, candidate: Candidate, obs: Observation) -> bool:
        if candidate.card not in OUR_DECK:
            return False
        if not 0 <= candidate.slot < 4:
            return False
        if obs.hand.get(candidate.card) != candidate.slot:
            return False
        if candidate.card in self.last_play_index:
            if self.plays - self.last_play_index[candidate.card] < 4:
                return False
        if obs.elixir < candidate.cost:
            return False
        candidate.x, candidate.y = arena.clamp(candidate.x, candidate.y)
        if candidate.card not in SPELLS and candidate.y < arena.RIVER_Y:
            return False
        if obs.now - self.last_play_at < float(self.cfg("min_seconds_between_plays", 0.55)):
            return False
        # Hold elixir for the win condition.  The deck's damage all comes from
        # Hog Rider, so when he is in hand and affordable-soon, spending the
        # last few elixir on a cycle card or an optional spell is spending the
        # push.  Real defence, the finisher, and the Hog himself are exempt.
        # `defend_fallback` is deliberately NOT optional.  It was, and the
        # result was a deadlock: a 24-threat push walking in while the bot held
        # five elixir for a Hog it could not afford to play either.  Holding
        # elixir is only ever correct instead of *optional* spending.
        OPTIONAL = {"cycle", "spell_value", "hog_support"}
        if candidate.weight_key in OPTIONAL and "hog_rider" in obs.hand:
            floor = float(self.cfg("hog_min_elixir_single", 5))
            if obs.elixir - candidate.cost < floor:
                return False

        if candidate.card == "hog_rider":
            if obs.serious and not obs.contained:
                floor = float(self.cfg("hog_min_elixir_defending", 8))
            elif obs.contained:
                floor = float(self.cfg("hog_min_elixir_contained", 6))
            elif obs.multiplier >= 2.0:
                floor = float(self.cfg("hog_min_elixir_double", 7))
            else:
                floor = float(self.cfg("hog_min_elixir_single", 5))
            if obs.elixir < floor:
                return False

        # Hard elixir budget per push.  2.6 wins by defending for *less* than the
        # opponent spent and counter-pushing with the difference; answering a
        # four-elixir push with five cheap cards is how the bot ended a match at
        # one elixir having never sent a Hog.  A soft score penalty was not
        # enough here - the threat bonus simply outbid it every tick.
        if candidate.weight_key.startswith("defend") and not self._emergency(obs):
            # Size the budget by how dangerous the push is, not only by what it
            # cost them.  A five-unit push of spawned units costs almost no
            # elixir but still takes a tower, and a cost-only budget locked the
            # bot out of defending it entirely - caught live as 17 seconds of
            # IDLE at threat 35 with a Cannon in hand.
            budget = max(
                float(self.cfg("defend_min_budget", 4.0)),
                obs.threat_elixir * float(self.cfg("defend_elixir_ratio", 1.1)),
                obs.threat_score * float(self.cfg("defend_threat_to_elixir", 0.35)),
            )
            if self.committed_elixir + candidate.cost > budget:
                return False
            cap = max(
                int(self.cfg("defend_max_cards_per_push", 3)),
                int(obs.threat_score // float(self.cfg("threat_per_extra_card", 10))),
            )
            if self.cards_this_push >= cap:
                return False

        return True

    # ------------------------------------------------------------- reporting

    def summary(self) -> str:
        if not self.plays:
            return "plays=0"
        parts = " ".join(
            f"{name}={count}" for name, count in
            sorted(self.play_counts.items(), key=lambda kv: -kv[1])
        )
        hog = self.play_counts.get("hog_rider", 0)
        return f"plays={self.plays} hog_share={100.0 * hog / self.plays:.0f}% {parts}"
