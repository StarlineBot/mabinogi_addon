"""Tracked numeric pixels are authoritative only inside their current game context."""

import pytest

from mabinogi_addon import image_io
from scripts.qa_dorcha_stale_game_roi import test_moved_game_must_invalidate_outside_live_roi
from test_dorcha_tracking import ROOT, moving, place, drain, held_worker


@pytest.mark.parametrize("change", ["hwnd","pid","move","resize","missing"])
def test_context_change_never_reads_old_digits_even_inside_overlapping_game(moving,change):
    app,tab,state,writes = moving
    place(state,20,20)
    tab._tick()
    assert tab._overlay.value == 15 and tab._live_target == state.target
    state.captures.clear()
    targets = {
        "hwnd":(3,2,0,0,260,180), "pid":(1,3,0,0,260,180),
        "move":(1,2,10,5,260,180), "resize":(1,2,0,0,220,160), "missing":None,
    }
    state.target = targets[change]
    place(state,150,90)
    zero = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-09 185117.png")
    assert zero is not None
    state.frame[90:113,150:178] = zero[892:915,716:744]
    state.frame[20:43,20:48] = state.ornament[17:40,8:36]
    tab._tick()
    assert tab._overlay.value is None and tab._tracking_lost
    assert (20,20,28,23) not in state.captures
    drain(app,tab)
    if change == "missing":
        for _ in range(10):
            tab._tick()
        assert tab._overlay.value is None and not state.captures
        state.target = (3,4,0,0,260,180)
        state.now = tab._next_search+1
        tab._tick()
        drain(app,tab)
    assert tab._overlay.value == 0 and tab._live_target == state.target
    assert not tab._tracking_lost and not writes


def test_new_worker_is_not_cancelled_on_each_tick_while_old_roi_is_outside_game(moving,monkeypatch):
    app,tab,state,_ = moving
    place(state,20,20)
    tab._tick()
    release = held_worker(monkeypatch)
    state.target = (1,2,300,0,260,180)
    place(state,150,90)
    tab._tick()
    worker = tab._search_worker
    assert worker is not None and tab._tracking_lost
    epoch = tab._search_epoch
    for _ in range(100):
        tab._tick()
        assert tab._search_worker is worker
        assert not worker.isInterruptionRequested()
        assert tab._search_epoch == epoch
    release.set()
    drain(app,tab)
    assert tab._live_box == (450,90,28,23) and tab._overlay.value == 15


def test_context_changes_during_capture_never_publish_captured_old_value(moving,monkeypatch):
    app,tab,state,_ = moving
    place(state,20,20)
    original = tab._grab_rect
    switched = False
    def grab(x,y,w,h):
        nonlocal switched
        frame = original(x,y,w,h)
        if not switched:
            switched = True
            state.target = (8,9,0,0,260,180)
            place(state,150,90)
        return frame
    monkeypatch.setattr(tab,"_grab_rect",grab)
    tab._tick()
    assert tab._overlay.value is None and tab._tracking_lost
    drain(app,tab)
    assert tab._overlay.value == 15 and tab._live_box == (150,90,28,23)
    assert tab._live_target == (8,9,0,0,260,180)


def test_stable_game_reuses_roi_without_full_frame_search(moving):
    _,tab,state,_ = moving
    place(state,20,20)
    for _ in range(100):
        tab._tick()
    assert state.captures == [(6,0,56,66)]+[(20,20,28,23)]*100
    assert tab._search_worker is None and tab._overlay.value == 15


def test_registered_roi_outside_current_game_is_not_read(moving):
    app,tab,state,_ = moving
    tab._region = dict(x=-100,y=-100,w=28,h=23)
    place(state,150,90)
    tab._tick()
    assert (-100,-100,28,23) not in state.captures
    drain(app,tab)
    assert tab._live_box == (150,90,28,23) and tab._overlay.value == 15
