"""A saved rectangle can recover during costly full-search cooldown, with context."""

import pytest

from test_dorcha_tracking import moving, one_cv_thread
from docs.qa.assets.dorcha_startup_20261018.probe import drain, visible_five
from mabinogi_addon.ui import dorcha_search


@pytest.mark.parametrize("elapsed", [0.1, 2.0, 8.0, 15.0])
def test_readable_registered_region_recovers_without_another_full_search(moving, monkeypatch, elapsed):
    app, tab, state, writes = moving
    original = dict(tab._region)
    worker_type = dorcha_search.DorchaSearch

    class CostControlledSearch(worker_type):
        def run(self):
            super().run()
            self.elapsed = elapsed

    monkeypatch.setattr(dorcha_search, "DorchaSearch", CostControlledSearch)
    tab._tick()
    state.now += elapsed
    drain(app, tab)
    assert tab._tracking_lost and tab._overlay.value is None
    full_count = state.captures.count((0, 0, 260, 180))
    visible_five(state)
    state.now += 2.01
    tab._tick()
    assert tab._overlay.value == 5 and not tab._tracking_lost
    assert tab._search_worker is None and tab._next_search == 0
    assert state.captures.count((0, 0, 260, 180)) == full_count
    assert tab._region == original and not writes


def test_failed_local_probe_is_throttled_and_does_not_accept_digits_alone(moving, monkeypatch):
    app, tab, state, writes = moving
    tab._tick()
    drain(app, tab)
    tab._next_search = state.now + 300
    visible_five(state)
    state.frame[:20] = 0
    state.frame[43:] = 0
    state.now += 2.01
    tab._tick()
    assert tab._overlay.value is None and tab._tracking_lost
    captures = len(state.captures)
    monkeypatch.setattr(tab, "_search_target", lambda: pytest.fail("Target lookup on every lost tick"))
    for _ in range(100):
        tab._tick()
    assert len(state.captures) == captures
    assert tab._search_worker is None and not writes


@pytest.mark.parametrize("region", [dict(x=0, y=0, w=200, h=180), dict(x=250, y=170, w=28, h=23)])
def test_local_recovery_never_captures_large_or_outside_registered_hints(moving, region):
    _, tab, state, writes = moving
    tab._tracking_lost = True
    tab._region = region
    tab._next_search = state.now + 300
    tab._tick()
    assert state.captures == []
    assert tab._overlay.value is None and tab._search_worker is None and not writes


def test_target_change_during_local_capture_rejects_recovery(moving, monkeypatch):
    _, tab, state, writes = moving
    visible_five(state)
    tab._tracking_lost = True
    tab._next_search = state.now + 300
    original = tab._grab_rect

    def changed(*args):
        frame = original(*args)
        state.target = (8, 9, 0, 0, 260, 180)
        return frame

    monkeypatch.setattr(tab, "_grab_rect", changed)
    tab._tick()
    assert tab._tracking_lost and tab._overlay.value is None
    assert tab._search_worker is None and not writes
