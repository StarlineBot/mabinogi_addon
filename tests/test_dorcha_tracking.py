"""Moving UI detection with explicit game/capture boundaries, not live desktop access."""

from copy import deepcopy
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace

import numpy as np
import cv2
import pytest
from PySide6.QtTest import QTest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.ui import dorcha_tab, dorcha_search
from mabinogi_addon.detect.dorcha_anchor import assets, locate_dorcha
from scripts.qa_dorcha_moved_ui import (
    test_actual_new_number_is_readable,
    test_new_visible_ui_must_be_located,
    test_prior_fifteen_scene_still_locates_and_reads,
    test_moving_source_must_be_reacquired_for_new_requirement as original_motion_repro,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", autouse=True)
def one_cv_thread():
    previous = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(previous)


def test_original_motion_with_explicit_registered_game_boundary(monkeypatch):
    monkeypatch.setattr(dorcha_tab.DorchaTab, "_search_target", lambda self: (1, 1, 0, 0, 260, 180))
    # Use a real Qt event loop, as QApplication.exec does. QTest.qWait holds the GIL
    # in this binding and starves Python QThread.run during its 200ms waits.
    def event_loop_wait(milliseconds):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()
    monkeypatch.setattr(QTest, "qWait", event_loop_wait)
    original_motion_repro(monkeypatch)


@pytest.fixture
def moving(monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = {"dorcha": {"enabled": True, "box": dict(x=20,y=20,w=28,h=23),
                      "showTuarim": False, "tuarimAlphaReset": 1}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    writes = []
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: writes.append(a))
    state = SimpleNamespace(game=True, logged=True, now=100.0, target=(1,2,0,0,260,180), captures=[])
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id":"qa"} if state.logged else None)
    monkeypatch.setattr(dorcha_tab, "monotonic", lambda: state.now)
    monkeypatch.setattr("mabinogi_addon.ui.dpi.to_physical", lambda b: tuple(b[k] for k in ("x","y","w","h")))
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 211914.png")
    assert source is not None
    state.ornament = source[931:988,933:978].copy()
    state.frame = np.zeros((180,260,3),np.uint8)
    tab = dorcha_tab.DorchaTab(SimpleNamespace(is_game_active=lambda:state.game, is_self_active=lambda:False))
    tab._timer.stop()
    monkeypatch.setattr(tab, "_search_target", lambda: state.target)
    def grab(x,y,w,h):
        state.captures.append((x,y,w,h))
        ox,oy = state.target[2:4] if state.target is not None else (0,0)
        return state.frame[y-oy:y-oy+h,x-ox:x-ox+w].copy()
    monkeypatch.setattr(tab, "_grab_rect", grab)
    try:
        yield app,tab,state,writes
    finally:
        tab.shutdown()
        if tab._overlay is not None:
            tab._overlay.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


def drain(app,tab):
    deadline = monotonic()+5
    while tab._search_worker is not None and monotonic()<deadline:
        QTest.qWait(10)
        app.processEvents()
    assert tab._search_worker is None


def place(state,x,y):
    state.frame[:] = 0
    state.frame[y-17:y+40,x-8:x+37] = state.ornament


def test_motion_occlusion_and_reappearance_do_not_save_or_keep_stale_values(moving):
    app,tab,state,writes = moving
    original = dict(tab._region)
    place(state,20,20)
    tab._tick()
    assert tab._overlay.value == 15 and not state.captures[0][2:] == (260,180)
    for x,y in [(150,90),(60,120),(200,40)]:
        place(state,x,y)
        tab._tick()
        assert tab._overlay.value is None
        drain(app,tab)
        assert tab._overlay.value == 15 and tab._live_box == (x,y,28,23)
    state.frame[:] = 0
    tab._tick()
    drain(app,tab)
    assert tab._overlay.value is None
    place(state,100,80)
    state.now = tab._next_search + 1
    tab._tick()
    drain(app,tab)
    assert tab._overlay.value == 15
    assert tab._region == original and not writes


def test_physical_offsets_are_applied_once_and_only_to_runtime_box(moving):
    app,tab,state,writes = moving
    state.target = (1,2,-400,200,260,180)
    tab._region = dict(x=-380,y=220,w=28,h=23)
    place(state,150,90)
    tab._tick()
    drain(app,tab)
    assert tab._live_box == (-250,290,28,23)
    assert state.captures[-1] == (-250,290,28,23)
    assert tab._overlay.value == 15 and not writes


def held_worker(monkeypatch):
    release = Event()
    class Held(dorcha_search.DorchaSearch):
        def run(self):
            self.box = (150,90,28,23)
            while not self.isInterruptionRequested() and not release.wait(.01):
                pass
            self.frame = None
    monkeypatch.setattr(dorcha_search, "DorchaSearch", Held)
    return release


@pytest.mark.parametrize("change", ["pause","disable","logout","inactive","registration","target","shutdown"])
def test_late_result_never_restores_interrupted_tracking(moving,monkeypatch,change):
    app,tab,state,writes = moving
    release = held_worker(monkeypatch)
    place(state,150,90)
    tab._tick()
    assert tab._search_worker is not None
    if change == "pause": tab.set_paused(True)
    elif change == "disable": tab.enable.setChecked(False)
    elif change == "logout": state.logged = False
    elif change == "inactive": state.game = False
    elif change == "registration": tab._apply_region(25,25,28,23)
    elif change == "target": state.target = (3,4,0,0,260,180)
    else: tab.shutdown()
    release.set()
    drain(app,tab)
    if change == "logout":
        assert tab._live_box == (150,90,28,23) and tab._overlay.value == 15
        assert not writes
        tab._apply_gate()
        assert not tab.auto_find_btn.isEnabled()
        return
    assert tab._live_box is None and tab._overlay.value is None


def test_single_worker_no_queue_and_ui_event_loop_stays_responsive(moving,monkeypatch):
    app,tab,state,_ = moving
    release = held_worker(monkeypatch)
    place(state,150,90)
    tab._tick()
    worker = tab._search_worker
    for _ in range(100):
        tab._tick()
        assert tab._search_worker is worker
    QTest.qWait(10)
    assert state.captures.count((0,0,260,180)) == 1
    assert tab._overlay.value is None
    release.set()
    drain(app,tab)
    assert tab._overlay.value == 15


def test_missing_ui_has_backoff_and_recovers_only_from_current_pixels(moving,monkeypatch):
    app,tab,state,_ = moving
    release = held_worker(monkeypatch)
    place(state,150,90)
    tab._tick()
    state.frame[:] = 0
    release.set()
    drain(app,tab)
    assert tab._overlay.value is None and tab._live_box is None
    for _ in range(100):
        tab._tick()
    assert state.captures.count((0,0,260,180)) == 1
    place(state,150,90)
    state.now = tab._next_search + 1
    tab._tick()
    drain(app,tab)
    assert tab._overlay.value == 15


@pytest.mark.parametrize("target", [None,(1,2,0,0,10000,10000)])
def test_missing_or_oversized_game_target_never_captures_full_desktop(moving,target):
    _,tab,state,_ = moving
    state.target = target
    tab._tick()
    assert state.captures == ([(20,20,28,23)] if target is None else [(6,0,56,66)])
    assert tab._search_worker is None


def test_new_anchor_is_native_grayscale_and_digits_are_masked():
    source = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 234015.png")
    data = assets()
    gray = cv2.cvtColor(source[106:163,569:614], cv2.COLOR_BGR2GRAY)
    assert np.array_equal(data["anchor_alt"], cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR))
    assert not data["mask"][21:36,11:33].any()


@pytest.mark.parametrize("level", [0,100,255])
def test_uniform_background_never_locates_resource(level):
    assert locate_dorcha(np.full((180,260,3),level,np.uint8)) is None


def test_ornament_without_readable_number_and_multiple_locations_are_rejected(moving):
    _,_,state,_ = moving
    place(state,20,20)
    state.frame[90-17:90+40,150-8:150+37] = state.ornament
    assert locate_dorcha(state.frame) is None
    state.frame[:] = 0
    place(state,20,20)
    state.frame[24:39,23:45] = 0
    assert locate_dorcha(state.frame) is None


def test_cancellation_exits_before_search():
    trace = {}
    assert locate_dorcha(np.zeros((180,260,3),np.uint8), diagnostics=trace, cancelled=lambda:True) is None
    assert trace["rejection"] == "cancelled"


@pytest.mark.parametrize("stamp", ["2026-10-06 223724","2026-10-06 224732", "2026-10-12 024008", "2026-10-12 024144"])
def test_boss_row_and_background_do_not_match_dorcha(stamp):
    source = image_io.imread(ROOT / f"tests/data/스크린샷 {stamp}.png")
    assert source is not None
    assert locate_dorcha(source[1195:1283,1016:1537]) is None


def test_detector_exception_is_bounded_and_does_not_leave_worker(moving,monkeypatch):
    app,tab,state,_ = moving
    def fail(*a,**k):
        raise RuntimeError("controlled detector failure")
    monkeypatch.setattr(dorcha_search,"locate_dorcha",fail)
    tab._tick()
    drain(app,tab)
    assert tab._overlay.value is None and tab._live_box is None
    for _ in range(100):
        tab._tick()
    assert state.captures.count((0,0,260,180)) == 1


def test_full_frame_capture_failure_does_not_spawn_or_retry_each_tick(moving,monkeypatch):
    _,tab,state,_ = moving
    original = tab._grab_rect
    def fail_full(x,y,w,h):
        result = original(x,y,w,h)
        return None if (w,h) == (260,180) else result
    monkeypatch.setattr(tab,"_grab_rect",fail_full)
    for _ in range(100):
        tab._tick()
    assert state.captures.count((0,0,260,180)) == 1
    assert tab._search_worker is None and tab._overlay.value is None


@pytest.mark.parametrize("kind", ["missing","damaged"])
def test_invalid_word_assets_fail_before_expensive_search(monkeypatch,kind):
    from mabinogi_addon.detect import resource_anchor
    data = assets()
    for key in list(data):
        if key.startswith("word_0_"):
            if kind == "missing":
                del data[key]
            else:
                data[key] = np.zeros((1,1),np.uint8)
    monkeypatch.setattr(resource_anchor,"candidates",lambda *a,**k:pytest.fail("invalid references reached detector"))
    trace = {}
    assert locate_dorcha(np.zeros((180,260,3),np.uint8),templates=data,diagnostics=trace) is None
    assert trace["rejection"] == "missing_word_references"
