"""Measure what each play actually achieved, then learn from it.

This is the honest version of "the AI realises its interaction lost". There is
no gradient and no neural network - it is a contextual bandit over
(situation, card) pairs, which is the right tool when decisions are discrete,
feedback is delayed by a few seconds, and the whole thing has to run inside a
2Hz loop on the same machine as the emulator.

How a play is scored
--------------------
When a card is played we snapshot the situation: which enemy units were on our
half, the lane, how big the push was, and the tower HP on both sides. A few
seconds later that episode is resolved:

    reward = enemy elixir killed
           + tower damage we dealt   (weighted - this is how the deck wins)
           - the elixir we spent
           - tower damage we took    (weighted - this is how the deck loses)

A card that trades up gets a positive number, a card thrown away gets a
negative one, and the bot stops needing to be told which is which.

Two things come out of it:

* `learned.json` - mean reward per (situation, card), read by the policy and
  added to that candidate's score, scaled by how much evidence there is.
* `matchups.json` - per (our card, their unit): how often it killed the thing
  it was played against and how the elixir trade went. This is the legible
  table - "Skeletons answered a Musketeer and traded up 3 elixir" - and it is
  what the LLM is given to write lessons from.

Deliberately conservative: an episode is only counted when we can actually
observe the outcome, confidence scales with sample count, and the learned bias
is clamped so a handful of lucky samples cannot override the hand-written
strategy rules.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BRAIN_DIR = Path(__file__).resolve().parent
LEARNED_PATH = BRAIN_DIR / "learned.json"
MATCHUPS_PATH = BRAIN_DIR / "matchups.json"
EPISODES_PATH = BRAIN_DIR.parents[1] / "tmp" / "live" / "episodes.jsonl"

# How long to wait before judging a play. A defence resolves quickly - the
# units either died or they did not. An attack does not: the Hog is deployed at
# the bridge, walks for about five seconds, and only then starts hitting the
# tower. Judging it at seven seconds scored the win condition at **-3.8 over
# ten samples**, which would have taught the bot to stop playing Hog Rider
# altogether. The window has to outlast the walk.
RESOLVE_SECONDS = 7.0
ATTACK_RESOLVE_SECONDS = 13.0
ATTACK_FAMILIES = ("hog", "finish")


def resolve_window(situation: str) -> float:
    family = situation.split("|")[0]
    return ATTACK_RESOLVE_SECONDS if family in ATTACK_FAMILIES else RESOLVE_SECONDS
MAX_EPISODE_LINES = 20000      # keep the log bounded on a machine short on disk

# What a whole princess tower is worth, in elixir.
#
# The first calibration used 14, which quietly undervalued the win condition: a
# Hog that connected for 9% of a tower scored 0.09 x 14 = 1.2 against a cost of
# 4, so *chip damage always looked like a loss* and the bandit would have
# learned to stop chipping. A match is roughly 130-180 elixir of play and three
# towers decide it, so a tower is worth tens of elixir, not fourteen.
#
# Taking is weighted above dealing on purpose: 2.6's own guidance is that the
# deck wins by not losing towers, so a point of damage to us should hurt more
# than the same point dealt to them.
TOWER_DEALT_WEIGHT = 35.0
TOWER_TAKEN_WEIGHT = 45.0
CONFIDENCE_K = 4.0             # samples needed before a mean is taken seriously


def threat_bucket(score: float) -> str:
    if score <= 0:
        return "none"
    if score < 8:
        return "small"
    if score < 18:
        return "medium"
    return "big"


def situation_key(weight_key: str, threat_score: float, air: bool, contained: bool) -> str:
    """Coarse enough to generalise, specific enough to be actionable."""
    family = weight_key.split("_")[0]          # defend / hog / cycle / spell / finish
    parts = [family, threat_bucket(threat_score)]
    if air:
        parts.append("air")
    if contained:
        parts.append("contained")
    return "|".join(parts)


# A play is only credited against units it plausibly engaged. Pairing every
# play with every unit on the field produced nonsense like "hog_rider vs
# ice_golem: 100% kill rate" - the Hog never fought it, an Ice Golem simply
# happened to be on screen at the time.
ENGAGE_RADIUS = 7.0
ENGAGING_FAMILIES = ("defend", "spell", "finish")


@dataclass
class Episode:
    at: float
    card: str
    cost: float
    tag: str
    situation: str
    lane: str
    enemy_units: List[str]
    enemy_ids: List[int]
    ally_hp: float
    enemy_hp: float
    engaged: List[str] = field(default_factory=list)   # units this play answered
    resolved: bool = False
    reward: float = 0.0
    killed: List[str] = field(default_factory=list)


class ExperienceBook:
    def __init__(self, learned_path: Path | None = None,
                 matchups_path: Path | None = None):
        self.learned_path = Path(learned_path or LEARNED_PATH)
        self.matchups_path = Path(matchups_path or MATCHUPS_PATH)
        self.pending: List[Episode] = []
        self.completed: List[Episode] = []
        # situation -> card -> [count, mean_reward]
        self.learned: Dict[str, Dict[str, List[float]]] = defaultdict(dict)
        # "our_card vs their_unit" -> counters
        self.matchups: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"n": 0.0, "killed": 0.0, "reward": 0.0}
        )
        self.load()

    # ------------------------------------------------------------------ io

    def load(self) -> None:
        try:
            raw = json.loads(self.learned_path.read_text(encoding="utf-8"))
            for situation, cards in raw.items():
                if isinstance(cards, dict):
                    self.learned[situation] = {
                        card: list(value) for card, value in cards.items()
                        if isinstance(value, list) and len(value) == 2
                    }
        except Exception:
            pass
        try:
            raw = json.loads(self.matchups_path.read_text(encoding="utf-8"))
            for key, value in raw.items():
                if isinstance(value, dict):
                    self.matchups[key].update(value)
        except Exception:
            pass

    def save(self) -> None:
        self.learned_path.write_text(
            json.dumps({s: c for s, c in self.learned.items() if c}, indent=1),
            encoding="utf-8",
        )
        self.matchups_path.write_text(
            json.dumps(dict(self.matchups), indent=1), encoding="utf-8"
        )

    def append_log(self, episode: Episode) -> None:
        try:
            EPISODES_PATH.parent.mkdir(parents=True, exist_ok=True)
            with EPISODES_PATH.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "at": round(episode.at, 1), "card": episode.card,
                    "tag": episode.tag, "situation": episode.situation,
                    "lane": episode.lane, "vs": episode.enemy_units,
                    "killed": episode.killed, "reward": round(episode.reward, 2),
                }) + "\n")
        except OSError:
            pass

    # -------------------------------------------------------------- record

    def record(self, card: str, cost: float, tag: str, situation: str, lane: str,
               enemy_units: List[str], enemy_ids: List[int],
               ally_hp: float, enemy_hp: float, now: float,
               engaged: Optional[List[str]] = None) -> None:
        self.pending.append(Episode(
            at=now, card=card, cost=float(cost), tag=tag, situation=situation,
            lane=lane, enemy_units=list(enemy_units), enemy_ids=list(enemy_ids),
            ally_hp=ally_hp, enemy_hp=enemy_hp,
            engaged=list(engaged if engaged is not None else enemy_units),
        ))

    def resolve(self, now: float, live_ids: set, ally_hp: float,
                enemy_hp: float, unit_cost) -> List[Episode]:
        """Judge any episode whose window has elapsed. Returns the resolved ones."""
        done: List[Episode] = []
        for episode in list(self.pending):
            if now - episode.at < resolve_window(episode.situation):
                continue
            self.pending.remove(episode)

            killed = [
                name for name, track_id in zip(episode.enemy_units, episode.enemy_ids)
                if track_id not in live_ids
            ]
            killed_elixir = sum(unit_cost(name) for name in killed)
            dealt = max(0.0, episode.enemy_hp - enemy_hp)
            taken = max(0.0, episode.ally_hp - ally_hp)
            
            # A tower dropping to exactly 0.0 from > 25% in 7s is almost certainly a glitch.
            if enemy_hp == 0.0 and dealt > 0.25:
                dealt = 0.0
            elif dealt >= 0.60:
                dealt = 0.0
                
            if ally_hp == 0.0 and taken > 0.25:
                taken = 0.0
            elif taken >= 0.60:
                taken = 0.0

            episode.killed = killed
            episode.reward = (
                killed_elixir
                + TOWER_DEALT_WEIGHT * dealt
                - episode.cost
                - TOWER_TAKEN_WEIGHT * taken
            )
            episode.resolved = True
            self._absorb(episode)
            self.append_log(episode)
            done.append(episode)
            self.completed.append(episode)
        return done

    def _absorb(self, episode: Episode) -> None:
        table = self.learned[episode.situation]
        count, mean = table.get(episode.card, [0.0, 0.0])
        count += 1
        mean += (episode.reward - mean) / count       # running mean
        table[episode.card] = [count, mean]

        for unit in episode.engaged:
            key = f"{episode.card} vs {unit}"
            row = self.matchups[key]
            row["n"] += 1
            row["killed"] += 1.0 if unit in episode.killed else 0.0
            row["reward"] += episode.reward

    # --------------------------------------------------------------- query

    def bias(self, situation: str, card: str, scale: float, limit: float) -> float:
        """Learned adjustment for this (situation, card), damped by evidence."""
        entry = self.learned.get(situation, {}).get(card)
        if not entry:
            return 0.0
        count, mean = entry
        confidence = count / (count + CONFIDENCE_K)
        return max(-limit, min(limit, mean * scale * confidence))

    def top_matchups(self, minimum: int = 3) -> List[Tuple[str, dict]]:
        rows = [
            (key, dict(value, mean_reward=value["reward"] / max(1.0, value["n"]),
                       kill_rate=value["killed"] / max(1.0, value["n"])))
            for key, value in self.matchups.items() if value["n"] >= minimum
        ]
        rows.sort(key=lambda item: item[1]["mean_reward"])
        return rows

    def trim_log(self) -> None:
        try:
            if not EPISODES_PATH.exists():
                return
            lines = EPISODES_PATH.read_text(encoding="utf-8").splitlines()
            if len(lines) > MAX_EPISODE_LINES:
                EPISODES_PATH.write_text(
                    "\n".join(lines[-MAX_EPISODE_LINES:]) + "\n", encoding="utf-8"
                )
        except OSError:
            pass
