from contextlib import contextmanager
import weakref

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QWidget

from mabinogi_addon.system import capture_exclusion
from test_dorcha_tab import runtime


@pytest.mark.parametrize("capture_error", [False, True])
def test_failed_restore_is_retained_even_if_capture_raises(runtime, monkeypatch, capture_error):
    tab, state, _ = runtime
    widget = QWidget()
    widget.show()
    hwnd = int(widget.winId())

    @contextmanager
    def excluded(handles, box):
        assert hwnd in handles
        pending = []
        try:
            yield pending
        finally:
            pending.append((hwnd, 1))

    def capture(*args):
        if capture_error:
            raise OSError("capture failed")
        return state.frame

    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "excluding_windows", excluded)
    monkeypatch.setattr(tab, "_grab_rect", capture)
    if capture_error:
        with pytest.raises(OSError, match="capture failed"):
            tab._grab_tracking_rect(1, 2, 3, 4)
    else:
        assert tab._grab_tracking_rect(1, 2, 3, 4) is state.frame
    assert tab._capture_restore[hwnd][0]() is widget
    assert tab._capture_restore[hwnd][1] == 1
    calls = []
    monkeypatch.setattr(capture_exclusion, "restore_window", lambda *args: calls.append(args) or True)
    tab._restore_capture_windows()
    assert calls == [(hwnd, 1)] and not tab._capture_restore


@pytest.mark.parametrize("condition", ["paused", "disabled", "logged-out", "inactive", "shutdown"])
def test_pending_restore_is_retried_even_when_tracking_stops(runtime, monkeypatch, condition):
    tab, state, _ = runtime
    widget = QWidget()
    widget.show()
    hwnd = int(widget.winId())
    tab._capture_restore[hwnd] = (weakref.ref(widget), 0)
    calls = []
    recover = [False]
    monkeypatch.setattr(capture_exclusion, "restore_window",
                        lambda *args: calls.append(args) or recover[0])
    tab._restore_capture_windows()
    assert hwnd in tab._capture_restore
    recover[0] = True
    if condition == "paused":
        tab.set_paused(True)
    elif condition == "disabled":
        tab._cfg["enabled"] = False
        tab._tick()
    elif condition == "logged-out":
        state.logged = False
        tab._tick()
    elif condition == "inactive":
        state.game = False
        tab._tick()
    else:
        tab.shutdown()
    assert not tab._capture_restore
    assert calls == [(hwnd, 0), (hwnd, 0)]
    assert not state.captures


@pytest.mark.parametrize("condition", ["destroyed", "recreated-hwnd"])
def test_old_window_identity_is_not_restored_on_a_different_native_window(runtime, monkeypatch, condition):
    tab, _, _ = runtime
    widget = QWidget()
    widget.show()
    hwnd = int(widget.winId())
    tab._capture_restore[hwnd + (1 if condition == "recreated-hwnd" else 0)] = (weakref.ref(widget), 0)
    if condition == "destroyed":
        widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    monkeypatch.setattr(capture_exclusion, "restore_window",
                        lambda *args: pytest.fail("stale HWND reached native restoration"))
    tab._restore_capture_windows()
    assert not tab._capture_restore


def test_repeated_restore_failures_keep_one_original_value_without_new_timers(runtime, monkeypatch):
    tab, state, _ = runtime
    widget = QWidget()
    widget.show()
    hwnd = int(widget.winId())
    timers = len(tab.findChildren(QTimer))

    @contextmanager
    def excluded(handles, box):
        previous = 0x11 if hwnd in tab._capture_restore else 1
        pending = []
        try:
            yield pending
        finally:
            pending.append((hwnd, previous))

    monkeypatch.setattr(capture_exclusion, "available", lambda: True)
    monkeypatch.setattr(capture_exclusion, "excluding_windows", excluded)
    monkeypatch.setattr(capture_exclusion, "restore_window", lambda *args: False)
    for _ in range(100):
        tab._grab_tracking_rect(1, 2, 3, 4)
        assert len(tab._capture_restore) == 1
        assert tab._capture_restore[hwnd][1] == 1
    assert state.captures == 100
    assert len(tab.findChildren(QTimer)) == timers
    assert tab._search_worker is None
    monkeypatch.setattr(capture_exclusion, "restore_window", lambda *args: True)
    tab._restore_capture_windows()
    assert not tab._capture_restore
