"""Taking a princess tower opens that half, and the policy can use it.

`sim.arena.deploy_area_ok` has always implemented this rule - its own
docstring says "Taking a princess tower opens the strip in front of it, which
is why a lost tower changes what the opponent can do to you". Nothing reached
it. The action mask skipped every enemy-half row before asking:

    if not spell and y < RIVER_ROW:
        continue

which reads like a free optimisation and is only true while both towers stand.
The consequence was not cosmetic. A crown is worth more than the crown: it is
worth deploying at the enemy's remaining tower for the rest of the match. With
those rows masked off, that payoff did not exist, so taking a tower scored the
same as chipping toward one - which is the shape of reward that produced a
policy taking zero crowns in sixty matches and never playing its win condition.

These tests assert the ground is actually there to be taken.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import sim.env as env_module                                      # noqa: E402
from sim import arena as sim_arena                                # noqa: E402
from sim.env import GRID_W, RIVER_ROW, TILES, ClashEnv, legal_mask  # noqa: E402


@pytest.fixture()
def env():
    made = ClashEnv(seed=0, opponent="meta")
    made.reset(seed=0)
    made.match.players[1].elixir = 10_000
    return made


def troop_grid(env, card_index: int = 0):
    """Legal cells for one hand slot, as a (32, 18) boolean grid."""
    mask = legal_mask(env.match, env._cards, 1)
    start = 1 + card_index * TILES
    return mask[start:start + TILES].reshape(-1, GRID_W)


def drop(env, lane: str):
    env.match.towers[-1][lane].hitpoints = 0
    env_module._PLACEMENT_CACHE.clear()


def troop_slot(env) -> int:
    hand = env.match.players[1].hand[:4]
    for index, card in enumerate(hand):
        if card not in env_module.SPELLS:
            return index
    pytest.skip("no troop in hand this deal")


def test_with_both_towers_up_troops_stay_on_our_half(env):
    grid = troop_grid(env, troop_slot(env))
    assert grid[:RIVER_ROW].sum() == 0, "troops are deployable in enemy half"
    assert grid[RIVER_ROW:].sum() > 0


def test_a_downed_tower_opens_a_strip_in_the_enemy_half(env):
    slot = troop_slot(env)
    before = troop_grid(env, slot)[:RIVER_ROW].sum()
    drop(env, "left")
    after = troop_grid(env, slot)[:RIVER_ROW].sum()
    assert before == 0 and after > 0, (
        f"enemy-half cells went {before} -> {after}; taking a tower should "
        f"open the ground in front of it")


def test_the_strip_is_in_front_of_the_tower_that_fell(env):
    slot = troop_slot(env)
    drop(env, "left")
    grid = troop_grid(env, slot)
    opened = [(y, x) for y in range(RIVER_ROW) for x in range(GRID_W) if grid[y, x]]
    assert opened, "nothing opened"
    centre_x = sim_arena.ENEMY_PRINCESS["left"].x / sim_arena.MT
    for _y, x in opened:
        assert abs(x - centre_x) <= 4, (
            f"opened cell at x={x} is not in front of the left tower "
            f"(centre {centre_x})")


def test_taking_the_second_tower_opens_more_ground(env):
    slot = troop_slot(env)
    drop(env, "left")
    one = troop_grid(env, slot)[:RIVER_ROW].sum()
    drop(env, "right")
    two = troop_grid(env, slot)[:RIVER_ROW].sum()
    assert two > one, f"second crown opened nothing ({one} -> {two})"


def test_a_troop_placed_in_the_opened_strip_is_actually_accepted(env):
    """The mask and the match have to agree, or the agent learns a lie."""
    slot = troop_slot(env)
    drop(env, "left")
    grid = troop_grid(env, slot)
    card = env.match.players[1].hand[slot]
    spots = [(y, x) for y in range(RIVER_ROW) for x in range(GRID_W) if grid[y, x]]
    y, x = spots[len(spots) // 2]
    action = ClashEnv.encode(slot, x, y)
    _obs, _reward, _term, _trunc, info = env.step(action)
    assert info["stats"].illegal == 0, (
        f"mask said {card} was legal at ({x},{y}) and the match refused it")
    assert info["stats"].plays == 1


def test_spells_were_always_allowed_anywhere_and_still_are(env):
    hand = env.match.players[1].hand[:4]
    for index, card in enumerate(hand):
        if card in env_module.SPELLS:
            grid = troop_grid(env, index)
            assert grid[:RIVER_ROW].sum() > 0, f"{card} cannot reach enemy half"
            break


# ------------------------------------------------------------- both directions

def test_losing_a_tower_opens_our_half_to_them(env):
    """The rule cuts both ways, and the opponent seat has to get it too.

    Easy to implement for the seat you are looking at and forget for the other
    one - and the self-play league puts a learned policy on that other seat,
    so a one-sided rule would train the agent against an opponent playing a
    different game than it is.
    """
    slot = troop_slot(env)
    env.match.players[-1].elixir = 10_000

    def their_cells_in_our_half():
        mask = legal_mask(env.match, env._cards, -1)
        total = 0
        for index, card in enumerate(env.match.players[-1].hand[:4]):
            if card in env_module.SPELLS:
                continue
            grid = mask[1 + index * TILES:1 + (index + 1) * TILES].reshape(-1, GRID_W)
            total += int(grid[:RIVER_ROW].sum())
        return total

    before = their_cells_in_our_half()
    env.match.towers[1]["left"].hitpoints = 0        # they take OUR left tower
    env_module._PLACEMENT_CACHE.clear()
    after = their_cells_in_our_half()
    assert before == 0 and after > 0, (
        f"their deployable cells in our half went {before} -> {after}; losing "
        f"a tower should cost us that ground")
    del slot


def test_the_pocket_is_the_same_size_for_both_players(env):
    """An asymmetric pocket would hand one seat of every self-play game an edge."""
    def opened(side: int, lane: str) -> int:
        fresh = ClashEnv(seed=1, opponent="meta")
        fresh.reset(seed=1)
        fresh.match.players[side].elixir = 10_000
        env_module._PLACEMENT_CACHE.clear()
        fresh.match.towers[-side][lane].hitpoints = 0
        env_module._PLACEMENT_CACHE.clear()
        grid = env_module._placeable(side, (lane,), False)
        return int(grid[:RIVER_ROW].sum())

    for lane in ("left", "right"):
        ours = opened(1, lane)
        theirs = opened(-1, lane)
        assert ours == theirs > 0, (
            f"{lane}: we open {ours} cells and they open {theirs}")


def test_the_pocket_size_is_the_named_approximation():
    """Pins the unverified constants so a change is deliberate.

    `sim.arena` documents these as an approximation and says exactly what
    measurement would settle them. If a real measurement lands, this test is
    the thing that should be updated with it - not quietly widened.
    """
    grid = env_module._placeable(1, ("left",), False)
    opened = [(y, x) for y in range(RIVER_ROW) for x in range(GRID_W) if grid[y, x]]
    assert opened
    width = len({x for _y, x in opened})
    depth = len({y for y, _x in opened})
    assert (width, depth) == (7, 10), (
        f"the pocket is now {width} wide and {depth} deep, not the documented "
        f"7x10; if this came from a live measurement, update "
        f"sim.arena.POCKET_HALF_WIDTH_MT and the note beside it")
