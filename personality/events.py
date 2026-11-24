"""Gameplay events the personality reacts to.

An event says what happened, when (match ms), how sure we are, and whether it
was *confirmed* by an outcome (tower HP, a unit dying) or only *estimated*
(inferred from positions/timing). The dialogue layer may refuse to voice
low-confidence estimates; nothing here ever feeds back into the bot.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict


class K(str, Enum):
    BIG_PUSH = "big_push"                       # 1
    DEFENSE = "defense"                         # 2
    PERFECT_DEFENSE = "perfect_defense"         # 3
    POSITIVE_TRADE = "positive_trade"           # 4
    NEGATIVE_TRADE = "negative_trade"           # 5
    KITE = "kite"                               # 6
    KITE_FAIL = "kite_fail"                     # 7
    HOG_CONNECT = "hog_connect"                 # 8
    HOG_COUNTERED = "hog_countered"             # 9
    MEGA_KNIGHT = "mega_knight"                 # 10
    EXPENSIVE_COMBO = "expensive_combo"         # 11
    ENEMY_SPELL_WASTED = "enemy_spell_wasted"   # 12
    AI_SPELL_MISS = "ai_spell_miss"             # 13
    AI_BAD_PLAY = "ai_bad_play"                 # 14
    AI_TOWER_LOST = "ai_tower_lost"             # 15
    AI_TOWER_TAKEN = "ai_tower_taken"           # 16
    POCKET_UNLOCKED = "pocket_unlocked"         # 17
    OPP_LEAD = "opp_lead"                       # 18
    COMEBACK = "comeback"                       # 19
    OVERTIME = "overtime"                       # 20
    SUDDEN_DEATH = "sudden_death"               # 21
    LOW_ELIXIR_PUSH = "low_elixir_push"         # 22
    SUS_PLACEMENT = "sus_placement"             # 23
    ABOUT_TO_WIN = "about_to_win"               # 24
    LOSS = "loss"                               # 25
    WIN = "win"                                 # 26
    OPP_BM = "opp_bm"                           # 27
    ANNOYING_DECK = "annoying_deck"             # 28
    AI_IDLE = "ai_idle"                         # 29
    COUNTER = "counter"                         # 30
    # Internal, not voiced directly: lets emotion track the AI's own emotes.
    AI_BM = "ai_bm"
    MATCH_START = "match_start"


# What each detector needs. Shown in the docs and by `--capabilities`.
REQUIRES = {
    "log": {K.MEGA_KNIGHT, K.EXPENSIVE_COMBO, K.ANNOYING_DECK, K.AI_IDLE, K.AI_BAD_PLAY,
            K.SUS_PLACEMENT, K.AI_BM, K.WIN, K.LOSS, K.OVERTIME, K.SUDDEN_DEATH, K.MATCH_START},
    "frames": set(K) - {K.OPP_BM},
}
UNSUPPORTED = {K.OPP_BM: "opponent emotes are not in game memory frames or the live log; "
                         "only addable by hand in the preview tool"}


@dataclass
class Event:
    t_ms: int
    kind: K
    confidence: float = 1.0
    confirmed: bool = True
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind.value
        return d

    @staticmethod
    def from_json(d: dict) -> "Event":
        return Event(int(d["t_ms"]), K(d["kind"]), float(d.get("confidence", 1.0)),
                     bool(d.get("confirmed", True)), dict(d.get("data", {})))
