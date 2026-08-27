"""A small local LLM that advises the policy on intent, card and zone.

Why it is shaped this way
-------------------------
The complaint was that the bot "places something as soon as it gets enough
elixir instead of deciding what to place according to what is coming". That is
a judgement problem, and judgement is what a language model is actually good
at. Precise tile coordinates are *not* - the 4-3 Cannon tile and the Ice Golem
kite spot are web-verified geometry that a 4B model will only degrade. So the
split is:

    LLM      -> intent (defend / push / cycle / hold), which card, which lane,
                and a coarse zone
    policy   -> the exact tile for that zone, legality, elixir, and every
                safety rule

Two hard constraints on the integration:

* **It never blocks the game loop.** A call takes roughly 0.8s; the loop runs
  at about 2Hz. A worker thread keeps the newest advice on hand and the policy
  reads whatever is fresh, so a slow or dead model costs nothing but the advice.
* **It can only bias, never authorise.** Advice adjusts the score of candidates
  the rule engine already produced and considers legal. The model cannot invent
  a play, place a troop in the enemy half, or spend elixir we do not have.

Output is schema-constrained by Ollama, so the response is always valid JSON
rather than the prose a small model otherwise drifts into.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
DEFAULT_MODEL = "qwen3:4b"

# Context window for the advisor.
#
# qwen3:4b advertises 262144 tokens and Ollama loads it at 4096 by default. The
# KV cache for this architecture costs
#     36 layers x 8 KV heads x (128 + 128) x 2 bytes  =  144 KiB per token
# so 4096 tokens is 576 MiB of VRAM held permanently. The advisor's prompt is
# ~424 tokens and it generates ~40, so almost all of that is reserved for
# nothing. 2048 leaves generous headroom for a longer lesson list and a busy
# board while returning roughly 288 MiB to the GPU, which is shared with the
# emulator.
NUM_CTX = 2048

# Ollama unloads an idle model after five minutes; the first call after that
# took 31 seconds against 0.6 warm. The advisor is asynchronous so this never
# stalls the bot, but it does mean the first decisions of a match run on no
# advice at all. Keep it resident for the length of a run instead.
KEEP_ALIVE = "30m"
STATS_PATH = Path(__file__).with_name("card_stats.json")

INTENTS = ("defend", "push", "cycle", "hold")
ZONES = ("bridge", "pocket", "back", "onto_threat", "enemy_tower")

SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": list(INTENTS)},
        "card": {"type": "string"},
        "lane": {"type": "string", "enum": ["left", "right"]},
        "zone": {"type": "string", "enum": list(ZONES)},
    },
    "required": ["intent", "card", "lane", "zone"],
}

BRIEF = """You play Clash Royale Hog 2.6: cannon, fireball, hog_rider, ice_golem,
ice_spirit, musketeer, skeletons, the_log.

hog_rider is the ONLY card here that can take a tower. Every other card exists to
make sending him affordable. Defending perfectly and not sending him is a draw at
best: this deck cannot win on spell chip. If you are unsure, send hog_rider.

Send hog_rider about every 20 seconds. A 2.6 cycle returns him to hand faster than
the opponent's answer cycles back, and out-cycling their answer is the whole plan -
so a lone hog_rider on cycle is this deck's standard play, not a mistake. Leading
with ice_golem is better when you can afford both, but waiting for that is how the
match ends with three Hogs played and no damage dealt.

There are only two good reasons to hold him: a push in our half that we have not
contained yet, or knowing their answer is in hand right now. "Their elixir is not
low enough" is not one of them.

Defend for less elixir than the opponent spends, then counter-push with hog_rider
behind whatever survived. Cannon only stops ground; it cannot shoot air. Musketeer
answers air. Ice Golem kites ground melee across the arena. Only spend fireball or
the_log when it kills several units or finishes a tower.

zone meanings: bridge = at the river to attack; pocket = the defensive tile in front of
our king tower; back = behind our towers to cycle safely; onto_threat = directly on the
enemy units; enemy_tower = a spell on their tower.

Answer with the single best action right now."""


@dataclass
class Advice:
    intent: str
    card: str
    lane: str
    zone: str
    at: float
    latency: float = 0.0

    def fresh(self, now: float, max_age: float) -> bool:
        return (now - self.at) <= max_age


LESSONS_PATH = Path(__file__).with_name("lessons.md")
MAX_LESSON_CHARS = 900


def _load_stats() -> Dict[str, dict]:
    try:
        return json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_lessons() -> str:
    """Lessons written from measured outcomes, capped.

    Capped because this text is prepended to every decision: an unbounded list
    would slow the loop, and a model handed fifty rules follows none of them.
    """
    try:
        lines = [
            line for line in LESSONS_PATH.read_text(encoding="utf-8").splitlines()
            if line.startswith("- ")
        ]
    except Exception:
        return ""
    if not lines:
        return ""
    return "\n".join(lines)[:MAX_LESSON_CHARS]


class Advisor:
    """Background LLM advisor. Safe to construct even if Ollama is not running."""

    def __init__(self, model: str = DEFAULT_MODEL, url: str = OLLAMA_URL,
                 timeout: float = 6.0, min_interval: float = 0.8):
        self.model = model
        self.url = url
        self.timeout = timeout
        self.min_interval = min_interval
        self.stats = _load_stats()
        self.lessons = load_lessons()

        self._lock = threading.Lock()
        self._snapshot: Optional[dict] = None
        self._advice: Optional[Advice] = None
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self.calls = 0
        self.failures = 0
        self.last_error = ""

    # -------------------------------------------------------------- lifecycle

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(target=self._run, name="advisor", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                snapshot = self._snapshot
                self._snapshot = None
            if snapshot is None:
                time.sleep(0.1)
                continue
            started = time.monotonic()
            advice = self._ask(snapshot)
            if advice is not None:
                advice.latency = time.monotonic() - started
                with self._lock:
                    self._advice = advice
            time.sleep(self.min_interval)

    # ---------------------------------------------------------------- public

    def submit(self, snapshot: dict) -> None:
        """Hand the worker the latest state. Never blocks."""
        with self._lock:
            self._snapshot = snapshot

    def latest(self) -> Optional[Advice]:
        with self._lock:
            return self._advice

    # --------------------------------------------------------------- prompt

    def describe_unit(self, name: str) -> str:
        """One compact line of verified stats, so the model is not guessing."""
        stats = self.stats.get(name)
        if not stats:
            return name
        bits = [name]
        targets = stats.get("targets")
        if targets:
            bits.append(str(targets))
        if stats.get("attack_type") == "splash":
            bits.append("splash")
        if stats.get("cost"):
            bits.append(f"{stats['cost']}el")
        role = stats.get("role")
        if role:
            bits.append(str(role))
        return " ".join(bits)

    def build_prompt(self, snapshot: dict) -> str:
        enemies = snapshot.get("enemies", [])
        enemy_lines = [
            f"  - {self.describe_unit(e['name'])} at lane {e['lane']}, "
            f"{e['depth']} tiles into our half"
            for e in enemies[:6]
        ] or ["  - none"]
        learned = (
            f"\nWhat this bot has learned from its own past matches:\n{self.lessons}\n"
            if self.lessons else ""
        )
        return (
            f"{BRIEF}\n{learned}\n"
            f"Our elixir: {snapshot['elixir']:.1f}\n"
            f"Estimated enemy elixir: {snapshot['enemy_elixir']:.1f}\n"
            f"Elixir speed: x{snapshot['multiplier']:.0f}   Time: {snapshot['elapsed']}s\n"
            f"Our towers L/R: {snapshot['ally_hp'][0]:.2f}/{snapshot['ally_hp'][1]:.2f}   "
            f"Their towers L/R: {snapshot['enemy_hp'][0]:.2f}/{snapshot['enemy_hp'][1]:.2f}\n"
            f"Cards we can play now: {', '.join(snapshot['hand']) or 'none'}\n"
            f"Enemy units on or near our half:\n" + "\n".join(enemy_lines) + "\n"
        )

    # ------------------------------------------------------------------ call

    def _ask(self, snapshot: dict) -> Optional[Advice]:
        payload = json.dumps({
            "model": self.model,
            "prompt": self.build_prompt(snapshot),
            "stream": False,
            "think": False,
            "format": SCHEMA,
            "keep_alive": KEEP_ALIVE,
            "options": {"num_predict": 80, "temperature": 0.0, "num_ctx": NUM_CTX},
        }).encode("utf-8")
        request = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            self.calls += 1
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(body.get("response", "{}"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            self.failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return None

        intent = str(parsed.get("intent", "")).lower()
        zone = str(parsed.get("zone", "")).lower()
        lane = str(parsed.get("lane", "")).lower()
        if intent not in INTENTS or zone not in ZONES or lane not in ("left", "right"):
            self.failures += 1
            self.last_error = f"unusable advice: {parsed}"[:200]
            return None
        return Advice(
            intent=intent,
            card=str(parsed.get("card", "")).lower().replace("-", "_"),
            lane=lane,
            zone=zone,
            at=time.monotonic(),
        )


def snapshot_from(obs, hand_names: List[str]) -> dict:
    """Build the compact state the prompt needs from an Observation."""
    from . import arena
    return {
        "elixir": obs.elixir,
        "enemy_elixir": getattr(obs, "enemy_elixir", 5.0),
        "multiplier": obs.multiplier,
        "elapsed": int(obs.elapsed),
        "ally_hp": [obs.ally_hp["left"], obs.ally_hp["right"]],
        "enemy_hp": [obs.enemy_hp["left"], obs.enemy_hp["right"]],
        "hand": hand_names,
        "enemies": [
            {
                "name": track.name,
                "lane": arena.side_of(track.cell.x),
                "depth": int(max(0, track.cell.y - arena.RIVER_Y)),
            }
            for track in obs.threats[:6]
        ],
    }
