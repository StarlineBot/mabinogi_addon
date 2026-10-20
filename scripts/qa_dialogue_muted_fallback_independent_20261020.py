"""Independent Z-order, last-check and bounded-resource checks for muted fallback.

Run with PYTHONPATH=src:.:tests QT_QPA_PLATFORM=offscreen python -m pytest
scripts/qa_dialogue_muted_fallback_independent_20261020.py -q --tb=short.
Win32 behavior is modeled; this is not real compositor or audio-device evidence.
"""

from itertools import permutations
import sys

import pytest
from PySide6.QtCore import QTimer

from scripts.qa_dialogue_transparent_occlusion import native_model  # noqa: F401
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: F401
from test_navigation import window  # noqa: F401
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("order", list(permutations((22, 33, 44))))
def test_unknown_and_clear_windows_never_hide_later_opaque_evidence(native_model, monkeypatch, order):
    gui = sys.modules["win32gui"]
    monkeypatch.setattr(gui, "GetWindowLong", lambda hwnd, key: 0 if hwnd == 33 else 0x80000)

    def alpha(hwnd):
        if hwnd == 22:
            raise OSError("unknown per-pixel alpha")
        return (0, 0, 2)

    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", alpha)
    monkeypatch.setattr(gui, "EnumWindows", lambda visit, arg: [visit(h, arg) for h in (*order, native_model.owner)])
    detail = {}
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail["visibility"] == "occluded" and detail["other_hwnd"] == 33


@pytest.mark.parametrize("last_unknown", [False, True])
def test_final_native_check_controls_new_sound(window, native_model, monkeypatch, last_unknown):
    w, app = window
    native_model.owner = int(w.winId())
    native_model.client = (0, 0, w.width(), w.height())
    calls = []

    def alpha(hwnd):
        calls.append(hwnd)
        unknown = last_unknown if len(calls) > 1 else not last_unknown
        return (0, 0, 0 if unknown else 2)

    monkeypatch.setattr(sys.modules["win32gui"], "GetLayeredWindowAttributes", alpha)
    d = w.creator_dialogue
    d.timer.stop()
    w.settings_tab.dialogue_sound_enabled.setChecked(True)
    sounds = []
    d.sound = sounds.append
    assert d.request() and d.bubble.isVisible()
    assert len(calls) == 2
    assert len(sounds) == int(not last_unknown)
    d.dismiss()
    app.processEvents()


def test_repeated_unknown_checks_release_regions_without_adding_timers(window, native_model, monkeypatch):
    w, app = window
    native_model.owner = int(w.winId())
    native_model.client = (0, 0, w.width(), w.height())
    gui = sys.modules["win32gui"]
    live, created = set(), []

    def create(rect):
        handle = object()
        live.add(handle)
        created.append(handle)
        return handle

    monkeypatch.setattr(gui, "CreateRectRgnIndirect", create)
    monkeypatch.setattr(gui, "DeleteObject", live.remove)
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", lambda hwnd: (0, 0, 0))
    d = w.creator_dialogue
    d.timer.stop()
    timers = set(d.findChildren(QTimer))
    for _ in range(1000):
        assert d._eligible() and not d._sound_allowed
        assert not live
    assert len(created) == 1000
    assert set(d.findChildren(QTimer)) == timers
    d.dismiss()
    app.processEvents()
