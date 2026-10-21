"""Transparent native windows must not suppress visible creator dialogue.

The API model is explicit; this is not a live Windows compositor test.
Run with PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_dialogue_transparent_occlusion.py -q --tb=short.
"""

from pathlib import Path
import ctypes
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_creator_dialogue import app, window  # noqa: E402,F401
from mabinogi_addon.system import dialogue_visibility as visibility  # noqa: E402


@pytest.fixture
def native_model(monkeypatch):
    class WindowState(SimpleNamespace):
        @property
        def blocker(self):
            return 23 if self.owner == 22 else 22

    state = WindowState(owner=11, present=True, alpha=0, layered=True,
                            visible=True, cloaked=False, cover=(0, 0, 1920, 1080),
                            origin=(0, 0), client=(0, 0, 800, 800))

    def attribute(hwnd, key, pointer, size):
        if key == 14:
            pointer._obj.value = int(state.cloaked)
        else:
            pointer._obj.left, pointer._obj.top, pointer._obj.right, pointer._obj.bottom = state.cover
        return 0

    def enumerate_windows(callback, arg):
        for hwnd in ([state.blocker, state.owner] if state.present else [state.owner]):
            if not callback(hwnd, arg):
                break

    gui = SimpleNamespace(
        IsWindowVisible=lambda hwnd: state.visible if hwnd == state.blocker else True,
        IsIconic=lambda hwnd: False,
        GetClientRect=lambda hwnd: state.client,
        ClientToScreen=lambda hwnd, point: state.origin,
        GetWindowRect=lambda hwnd: state.cover,
        GetWindowLong=lambda hwnd, key: 0x80000 if state.layered else 0,
        GetLayeredWindowAttributes=lambda hwnd: (0, state.alpha, 2),
        EnumWindows=enumerate_windows,
        CreateRectRgnIndirect=lambda rect: object(),
        GetWindowRgn=lambda *args: 0,
        DeleteObject=lambda *args: None,
    )
    monkeypatch.setattr(visibility, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(visibility, "desktop_unlocked", lambda: True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(
        dwmapi=SimpleNamespace(DwmGetWindowAttribute=attribute)), raising=False)
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(
        EnumDisplayMonitors=lambda: [(1, None, (0, 0, 1920, 1080))]))
    return state


@pytest.mark.parametrize("condition, expected", [
    ("absent", True), ("hidden", True), ("cloaked", True), ("outside", True),
    ("opaque", False), ("zero-alpha", True),
])
def test_visibility_respects_real_coverage_not_just_window_bounds(native_model, condition, expected):
    state = native_model
    if condition == "absent":
        state.present = False
    elif condition == "hidden":
        state.visible = False
    elif condition == "cloaked":
        state.cloaked = True
    elif condition == "outside":
        state.cover = (1500, 800, 1600, 900)
    elif condition == "opaque":
        state.alpha = 255
    assert visibility.exposed(11, [(20, 20, 48, 48)], (800, 800)) is expected


@pytest.mark.parametrize("mode", ["click", "automatic"])
def test_transparent_overlay_does_not_block_actual_dialogue(window, app, native_model, mode):
    state = native_model
    state.owner = int(window.winId())
    state.client = (0, 0, window.width(), window.height())
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    assert dialogue.session.entries and dialogue.enabled
    dialogue.visibility = visibility.exposed
    assert dialogue.face.isVisible()
    if mode == "click":
        dialogue.face.click()
    else:
        dialogue.clock = lambda: 100.0
        dialogue.session.rng.random = lambda: 0.0
        dialogue.tick()
    assert dialogue.bubble.isVisible()
    assert dialogue.session.last_text


def test_removing_only_the_transparent_window_restores_click(window, app, native_model):
    state = native_model
    state.owner = int(window.winId())
    state.client = (0, 0, window.width(), window.height())
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    state.present = False
    dialogue.face.click()
    assert dialogue.bubble.isVisible()


@pytest.mark.windows_integration
@pytest.mark.skipif(sys.platform != "win32", reason="Requires actual HWND/DWM/layered alpha")
def test_real_zero_alpha_window_does_not_occlude_dialogue(app):
    import uuid
    import win32api
    import win32con
    import win32gui
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget

    owner = QWidget()
    instance = win32api.GetModuleHandle(None)
    name = "DialogueZeroAlphaQA_" + uuid.uuid4().hex
    registered = False
    overlay = None
    try:
        area = app.primaryScreen().availableGeometry()
        owner.setGeometry(area.x() + 10, area.y() + 10, 200, 160)
        owner.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)
        owner.show()
        app.processEvents()
        hwnd = int(owner.winId())
        target = [(20, 20, 60, 40)]
        assert visibility.exposed(hwnd, target, (owner.width(), owner.height()))
        cls = win32gui.WNDCLASS()
        cls.hInstance, cls.lpszClassName = instance, name
        cls.lpfnWndProc = win32gui.DefWindowProc
        win32gui.RegisterClass(cls)
        registered = True
        x, y = win32gui.ClientToScreen(hwnd, (0, 0))
        _, _, width, height = win32gui.GetClientRect(hwnd)
        overlay = win32gui.CreateWindowEx(
            win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TRANSPARENT
            | win32con.WS_EX_NOACTIVATE, name, name, win32con.WS_POPUP,
            x, y, width, height, 0, 0, instance, None)
        win32gui.SetLayeredWindowAttributes(overlay, 0, 0, win32con.LWA_ALPHA)
        win32gui.SetWindowPos(overlay, win32con.HWND_TOPMOST, x, y, width, height,
                             win32con.SWP_SHOWWINDOW | win32con.SWP_NOACTIVATE)
        ctypes.windll.dwmapi.DwmFlush()
        assert win32gui.IsWindowVisible(overlay)
        assert win32gui.GetLayeredWindowAttributes(overlay)[1:] == (0, win32con.LWA_ALPHA)
        assert visibility.exposed(hwnd, target, (owner.width(), owner.height()))
    finally:
        if overlay is not None:
            win32gui.DestroyWindow(overlay)
        if registered:
            win32gui.UnregisterClass(name, instance)
        owner.close()
        owner.deleteLater()
        app.processEvents()
