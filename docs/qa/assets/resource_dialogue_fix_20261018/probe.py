"""Actual Qt requests across explicit Windows API failure and recovery inputs."""

import ctypes
import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QTimer

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from scripts.qa_dialogue_transparent_occlusion import app, window, native_model  # noqa: E402,F401
from mabinogi_addon.system import dialogue_visibility as visibility  # noqa: E402

REAL_DESKTOP = visibility.desktop_unlocked
LOGGER = "mabinogi_addon.ui.creator_dialogue"


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("raises", [False, True])
def test_unrelated_cloak_failure_allows_actual_display_then_overlap_stays_safe(
        window, app, native_model, monkeypatch, caplog, automatic, raises):
    state = native_model
    state.owner = int(window.winId())
    state.client = (0, 0, window.width(), window.height())
    state.cover = (1500, 800, 1600, 900)
    original = ctypes.windll.dwmapi.DwmGetWindowAttribute
    calls = []

    def attribute(hwnd, key, pointer, size):
        calls.append(key)
        if key == 14:
            if raises:
                raise OSError("private message should stay out of logs")
            return -1
        return original(hwnd, key, pointer, size)

    monkeypatch.setattr(ctypes.windll.dwmapi, "DwmGetWindowAttribute", attribute)
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    dialogue.clock = lambda: 100.0
    dialogue.session.rng.random = lambda: 0.0
    timers = set(window.findChildren(QTimer))
    caplog.set_level(logging.INFO, logger=LOGGER)
    if automatic:
        dialogue.tick()
    else:
        dialogue.face.click()
    assert dialogue.bubble.isVisible() and dialogue.session.last_text
    assert 14 not in calls
    assert not [r for r in caplog.records if r.name == LOGGER]

    state.cover = (0, 0, 1920, 1080)
    dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    records = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1 and "window_cloak" in records[0]
    assert "other_hwnd" in records[0] and "private message" not in records[0]
    state.present = False
    dialogue.face.click()
    assert dialogue.bubble.isVisible()
    assert set(window.findChildren(QTimer)) == timers


@pytest.mark.parametrize("failure", ["OpenInputDesktop", "GetUserObjectInformationW"])
def test_actual_click_records_desktop_failure_and_recovers_without_restart(
        window, app, native_model, monkeypatch, caplog, failure):
    state = native_model
    state.owner = int(window.winId())
    state.client = (0, 0, window.width(), window.height())
    state.present = False
    failing = [True]
    closed = []

    def open_desktop(*args):
        return 0 if failing[0] and failure == "OpenInputDesktop" else 55

    def information(handle, key, name, size, needed):
        name.value = "Default"
        return not (failing[0] and failure == "GetUserObjectInformationW")

    def win_error():
        error = OSError("private message should stay out of logs")
        error.winerror = 5
        return error

    ctypes.windll.user32 = SimpleNamespace(
        OpenInputDesktop=open_desktop,
        GetUserObjectInformationW=information,
        CloseDesktop=lambda handle: closed.append(handle),
    )
    monkeypatch.setattr(ctypes, "WinError", win_error, raising=False)
    monkeypatch.setattr(visibility, "desktop_unlocked", REAL_DESKTOP)
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    caplog.set_level(logging.INFO, logger=LOGGER)
    dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    records = [r.getMessage() for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1
    assert "input_desktop" in records[0] and failure in records[0]
    assert "winerror" in records[0] and "private message" not in records[0]
    assert closed == ([] if failure == "OpenInputDesktop" else [55])
    before = len(closed)
    failing[0] = False
    dialogue.face.click()
    assert dialogue.bubble.isVisible()
    assert len(closed) == before + 2  # Request checks visibility before and after selection.
    assert all(handle == 55 for handle in closed)
