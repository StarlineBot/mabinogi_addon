"""Explicit window-region evidence, not class names or alpha flags, refines coverage."""

from types import SimpleNamespace
import sys
import pytest
from scripts.qa_dialogue_transparent_occlusion import app, window, native_model
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.fixture
def region_model(native_model, monkeypatch):
    gui = sys.modules["win32gui"]
    state = native_model
    state.alpha = 0
    state.region_kind = 3
    state.rectangles = [(1000, 1000, 1100, 1100)]
    state.live = set()
    state.next_handle = 0
    def create(*args):
        state.next_handle += 1
        state.live.add(state.next_handle)
        return state.next_handle
    def region(hwnd, handle):
        assert handle in state.live
        return state.region_kind
    def intersects(handle, rect):
        assert handle in state.live
        return any(max(rect[0], c[0]) < min(rect[2], c[2]) and
                   max(rect[1], c[1]) < min(rect[3], c[3]) for c in state.rectangles)
    monkeypatch.setattr(gui, "CreateRectRgn", create, raising=False)
    monkeypatch.setattr(gui, "GetWindowRgn", region, raising=False)
    monkeypatch.setattr(gui, "RectInRegion", intersects, raising=False)
    monkeypatch.setattr(gui, "DeleteObject", lambda handle: state.live.remove(handle), raising=False)
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", lambda hwnd: (0, 0, 0))
    return state


@pytest.mark.parametrize("kind", [1, 2, 3])
def test_shaped_window_does_not_cover_targets_outside_its_region(region_model, kind):
    region_model.region_kind = kind
    assert visibility.exposed(11, [(20, 20, 48, 48)], (800, 800))
    assert not region_model.live


@pytest.mark.parametrize("kind", [0, 4])
def test_unknown_region_stays_conservative(region_model, kind):
    region_model.region_kind = kind
    detail = {}
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail["region_type"] == kind
    assert not region_model.live


def test_overlap_with_any_part_not_only_center_blocks(region_model):
    region_model.rectangles = [(67, 67, 68, 68)]
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800))
    region_model.rectangles = [(120, 120, 121, 121)]
    assert not visibility.exposed(11, [(20, 20, 48, 48), (100, 100, 50, 50)], (800, 800))
    assert not region_model.live


def test_region_uses_window_origin_not_extended_frame(region_model, monkeypatch):
    gui = sys.modules["win32gui"]
    monkeypatch.setattr(gui, "GetWindowRect", lambda hwnd: (-200, -50, 1900, 1100))
    region_model.rectangles = [(220, 70, 221, 71)]
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800))
    assert not region_model.live


@pytest.mark.parametrize("api", ["GetWindowRgn", "GetWindowRect", "RectInRegion"])
def test_region_failure_releases_handle_and_does_not_allow(region_model, monkeypatch, api):
    def fail(*args):
        raise OSError("private message")
    monkeypatch.setattr(sys.modules["win32gui"], api, fail)
    detail = {}
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail["region_error"] == "OSError"
    assert "private" not in repr(detail)
    assert not region_model.live


def test_repeated_region_checks_have_no_handle_growth(region_model):
    for _ in range(1000):
        assert visibility.exposed(11, [(20, 20, 48, 48)], (800, 800))
        assert not region_model.live
    assert region_model.next_handle == 1000


def test_real_qt_click_with_region_hole_and_returning_cover(window, app, region_model):
    region_model.owner = int(window.winId())
    region_model.client = (0, 0, window.width(), window.height())
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    region_model.rectangles = [(1800, 900, 1900, 1000)]
    assert dialogue.request()
    assert dialogue.bubble.isVisible()
    region_model.rectangles = [(0, 0, 1920, 1080)]
    assert not dialogue.request()
    assert not dialogue.bubble.isVisible()
    assert not region_model.live


def test_process_identity_only_on_explicit_diagnostic_and_handles_close(region_model, monkeypatch):
    region_model.region_kind = 0
    handles = []
    class Handle:
        closed = False
        def Close(self):
            self.closed = True
    def open_process(*args):
        handle = Handle()
        handles.append(handle)
        return handle
    monkeypatch.setattr(sys.modules["win32api"], "OpenProcess", open_process, raising=False)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 123),
        QueryFullProcessImageName=lambda *args: r"C:\Users\private\overlay.exe"))
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800))
    assert not handles
    detail = {}
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800),
                                  diagnostic=detail, diagnose=True)
    assert detail["blocker_exe"] == "overlay.exe"
    assert detail["blocker_pid"] == 123
    assert "private" not in repr(detail)
    assert len(handles) == 1 and handles[0].closed


@pytest.mark.parametrize("failure", ["query", "pid_reused"])
def test_identity_failure_does_not_escape_or_misattribute(region_model, monkeypatch, failure):
    region_model.region_kind = 0
    closed = []
    pids = iter((123, 456))
    def query(*args):
        if failure == "query":
            raise OSError("private path")
        return r"C:\private\old.exe"
    monkeypatch.setattr(sys.modules["win32api"], "OpenProcess",
                        lambda *args: SimpleNamespace(Close=lambda: closed.append(True)), raising=False)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, next(pids)), QueryFullProcessImageName=query))
    detail = {}
    assert not visibility.exposed(11, [(20, 20, 48, 48)], (800, 800),
                                  diagnostic=detail, diagnose=True)
    assert "blocker_exe" not in detail
    assert "private" not in repr(detail)
    assert closed == [True]
    if failure == "pid_reused":
        assert "blocker_pid" not in detail and detail["identity_changed"]
    else:
        assert detail["identity_error"] == "OSError"
