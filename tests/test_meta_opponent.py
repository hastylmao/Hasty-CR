"""The training opponent plays real ladder decks, not a copy of us.

`sim/train_ppo.py` states the problem in its own words:

    the mirror defends exactly as well as we attack, and `SimpleOpponent`
    loses 99.7% of the time. Every sweep run here has therefore answered
    "does this beat a copy of me", which is not the question.

The pieces to fix it were mostly already here - `ScriptedOpponent` pilots any
deck with style-driven heuristics, and `classify_style` exists specifically
"for decks imported from elsewhere". What was missing was decks: the pool held
five hand-written archetypes, which its own docstring admitted were "archetypes
rather than a live meta snapshot".

`scripts/sync_meta_decks.py` fills it from public Path of Legends battle logs -
real eight-card decks, ranked by how often they were actually played, with
every card the simulator can play guaranteed to appear somewhere so the agent
has at least seen it.

The pool falls back to the archetypes when nothing has been synced, so these
tests pass either way and the env never silently trains against a mirror while
claiming otherwise.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sim.env import DECK_26, ClashEnv                            # noqa: E402
from sim.gamedata import load_gamedata                           # noqa: E402
from sim.meta_decks import classify_style, deck_pool             # noqa: E402

CARDS = load_gamedata(11)
POOL = deck_pool(CARDS)


def test_there_is_a_pool_at_all():
    assert POOL, "no opponent decks; run scripts/sync_meta_decks.py"


def test_every_deck_is_eight_distinct_playable_cards():
    for name, _style, deck in POOL:
        assert len(deck) == 8, f"{name} has {len(deck)} cards"
        assert len(set(deck)) == 8, f"{name} repeats a card"
        for card in deck:
            assert CARDS.get(card) is not None, f"{name} names {card}"


def test_no_deck_appears_twice():
    keys = [tuple(sorted(deck)) for _name, _style, deck in POOL]
    assert len(keys) == len(set(keys)), "the pool contains a duplicate deck"


def test_styles_are_assigned_and_differ():
    """A pool where everything plays the same way is one opponent again."""
    styles = {style for _name, style, _deck in POOL}
    assert styles, "no styles assigned"
    assert styles <= {"cycle", "beatdown", "control"}, styles
    if len(POOL) > 5:
        assert len(styles) > 1, (
            "every deck in the pool classified the same way, so they all play "
            "alike and the pool is decoration")


def test_the_style_rule_separates_a_tank_deck_from_a_cycle_deck():
    beatdown = ["golem", "baby_dragon", "mega_minion", "lightning",
                "tornado", "barbarian_barrel", "knight", "archers"]
    beatdown = [c for c in beatdown if c in CARDS]
    if "golem" in beatdown:
        assert classify_style(CARDS, beatdown) == "beatdown"
    assert classify_style(CARDS, list(DECK_26)) in {"cycle", "control"}


# ------------------------------------------------------------------ the env

def test_the_env_refuses_meta_without_a_pool(monkeypatch):
    """Better than quietly falling back to a mirror and calling it meta."""
    monkeypatch.setattr("sim.meta_decks.deck_pool", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="deck pool"):
        ClashEnv(seed=0, opponent="meta")


def test_our_side_is_always_hog_cycle():
    """The near-term goal is a strong 2.6 pilot, not an all-cards generalist."""
    env = ClashEnv(seed=0, opponent="meta")
    env.reset(seed=0)
    ours = env.match.players[1].deck
    assert sorted(ours) == sorted(DECK_26), ours


def test_the_opponent_deck_changes_between_episodes():
    env = ClashEnv(seed=0, opponent="meta")
    seen = set()
    for episode in range(12):
        env.reset(seed=episode)
        seen.add(env.opponent_deck_name)
    if len(POOL) > 1:
        assert len(seen) > 1, (
            f"twelve episodes and one deck ({seen}); the opponent is a mirror "
            f"by another name")


def test_the_same_seed_gives_the_same_opponent():
    """A run has to be reproducible or an A/B result means nothing."""
    first = ClashEnv(seed=0, opponent="meta")
    second = ClashEnv(seed=0, opponent="meta")
    for episode in range(5):
        first.reset(seed=episode)
        second.reset(seed=episode)
        assert first.opponent_deck_name == second.opponent_deck_name


def test_the_card_table_carries_the_whole_pool():
    """Otherwise the opponent's deck resolves to nothing and it stands there."""
    env = ClashEnv(seed=0, opponent="meta")
    for _name, _style, deck in POOL:
        for card in deck:
            assert env._cards.get(card) is not None, card


def test_an_episode_against_a_meta_deck_runs_and_the_opponent_plays():
    import random
    env = ClashEnv(seed=0, opponent="meta")
    rng = random.Random(0)
    played = 0
    for episode in range(3):
        env.reset(seed=episode)
        for _ in range(400):
            mask = env.action_mask()
            legal = [i for i, ok in enumerate(mask) if ok]
            out = env.step(rng.choice(legal) if legal else 0)
            if len(out) >= 3 and out[2]:
                break
        played += sum(getattr(env.opponent, "plays", {}).values())
    assert played > 0, "the opponent never played a card in three episodes"
