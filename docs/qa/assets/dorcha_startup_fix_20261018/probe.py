"""Independent recovery checks; the previous delay-observation probe stays intact."""

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_dorcha_tracking import moving, one_cv_thread, held_worker  # noqa: E402,F401
from docs.qa.assets.dorcha_startup_20261018.probe import drain, visible_five  # noqa: E402
from mabinogi_addon.ui import dorcha_search  # noqa: E402


@pytest.mark.parametrize("cost", [2.0, 8.0, 15.0])
def test_current_five_recovers_at_local_deadline_not_full_search_deadline(moving, monkeypatch, cost):
    app, tab, state, writes = moving
    worker_type = dorcha_search.DorchaSearch

    class Measured(worker_type):
        def run(self):
            super().run()
            self.elapsed = cost

    monkeypatch.setattr(dorcha_search, "DorchaSearch", Measured)
    state.game = False
    tab._tick()
    state.game = True
    tab._tick()
    state.now += cost
    drain(app, tab)
    full_deadline = tab._next_search
    assert full_deadline - state.now == pytest.approx(cost * 20)
    tab._tick()
    assert tab._tracking_lost and tab._overlay.value is None
    local_deadline = tab._next_region_probe
    full_count = state.captures.count((0, 0, 260, 180))

    visible_five(state)
    captures = len(state.captures)
    for offset in (0.2, 0.6, 1.0, 1.8, 1.999):
        state.now = local_deadline - 2 + offset
        tab._tick()
        assert tab._overlay.value is None
        assert len(state.captures) == captures and tab._search_worker is None
        assert tab._next_search == full_deadline

    state.now = local_deadline + 0.001
    tab._tick()
    assert state.now < full_deadline
    assert tab._overlay.value == 5 and not tab._tracking_lost
    assert tab._search_worker is None and tab._next_search == 0
    assert state.captures.count((0, 0, 260, 180)) == full_count
    assert not writes


def test_a_pending_full_worker_prevents_additional_local_captures(moving, monkeypatch):
    app, tab, state, writes = moving
    release = held_worker(monkeypatch)
    tab._tick()
    assert tab._tracking_lost and tab._search_worker is not None
    captures = len(state.captures)
    visible_five(state)
    state.now += 120
    for _ in range(100):
        tab._tick()
    assert len(state.captures) == captures and tab._overlay.value is None
    release.set()
    drain(app, tab)
    assert not writes


def test_local_verification_cannot_publish_a_number_that_disappeared(moving, monkeypatch):
    _, tab, state, writes = moving
    visible_five(state)
    tab._tracking_lost = True
    tab._next_search = state.now + 300
    grab = tab._grab_rect
    calls = []

    def disappear(x, y, w, h):
        calls.append((x, y, w, h))
        if (w, h) == (28, 23):
            state.frame[:] = 0
        return grab(x, y, w, h)

    monkeypatch.setattr(tab, "_grab_rect", disappear)
    tab._tick()
    assert len(calls) == 2 and tab._overlay.value is None
    assert tab._live_box is None and tab._search_worker is None and not writes


@pytest.mark.parametrize("change", ["pause", "logout", "disable", "inactive", "shutdown"])
def test_stopped_states_do_not_run_local_recovery(moving, change):
    _, tab, state, writes = moving
    visible_five(state)
    tab._ensure_overlay()
    tab._tracking_lost = True
    tab._next_search = state.now + 300
    if change == "pause":
        tab.set_paused(True)
    elif change == "logout":
        state.logged = False
    elif change == "disable":
        tab.enable.setChecked(False)
    elif change == "inactive":
        state.game = False
    else:
        tab.shutdown()
    tab._tick()
    assert not state.captures and tab._overlay.value is None
    assert tab._search_worker is None
