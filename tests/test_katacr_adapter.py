from types import SimpleNamespace

import numpy as np

from hastycr.adapters.katacr import (
    ARENA_CHANNELS,
    build_structured_state,
    grid_to_mumu,
)


def _det(name, x, y):
    return SimpleNamespace(
        unit=SimpleNamespace(name=name),
        position=SimpleNamespace(tile_x=x, tile_y=y),
    )


def test_grid_to_mumu_covers_expected_bounds():
    assert grid_to_mumu(0, 0) == (104, 172)
    assert grid_to_mumu(17, 31) == (970, 1455)


def test_build_structured_state_maps_cards_units_and_towers():
    number = lambda value: SimpleNamespace(number=value)
    numbers = SimpleNamespace(
        elixir=number(7), enemy_king_hp=number(1), ally_king_hp=number(1),
        left_enemy_princess_hp=number(1), right_enemy_princess_hp=number(1),
        left_ally_princess_hp=number(1), right_ally_princess_hp=number(1),
    )
    names = ["cannon", "fireball", "hog_rider", "ice_golem", "the_log"]
    state = SimpleNamespace(
        allies=[_det("musketeer", 4, 5)], enemies=[_det("mini_pekka", 13, 24)],
        cards=[SimpleNamespace(name=name) for name in names], numbers=numbers,
    )
    unit2idx = {"musketeer": 10, "mini-pekka": 11,
                "king-tower": 12, "queen-tower": 13}
    result = build_structured_state(state, unit2idx)
    assert result["arena"].shape == (32, 18, ARENA_CHANNELS)
    assert result["arena_mask"].sum() == 8
    assert result["arena"][26, 4, :2].tolist() == [10, -1]
    assert result["arena"][7, 13, :2].tolist() == [11, 1]
    assert result["cards"].tolist() == [0, 2, 3, 4, 10]
    assert int(result["elixir"]) == 7
    assert result["arena"].dtype == np.int32
