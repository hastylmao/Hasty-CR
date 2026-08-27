from sim.watch import area_display_fields


def test_watcher_accepts_lingering_area_scheduler_state():
    base = ["void", "centre", 1, 4000, 100]
    assert area_display_fields(base) == tuple(base)
    assert area_display_fields(base + [None]) == tuple(base)
    assert area_display_fields(base + [None, 3]) == tuple(base)
