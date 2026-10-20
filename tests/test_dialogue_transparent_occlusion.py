"""Explicit Windows API model; not a live compositor test."""

import sys
import pytest

from scripts.qa_dialogue_transparent_occlusion import (
    app, window, native_model,
    test_visibility_respects_real_coverage_not_just_window_bounds,
    test_transparent_overlay_does_not_block_actual_dialogue,
    test_real_zero_alpha_window_does_not_occlude_dialogue,
)
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.mark.parametrize("alpha", [1, 128, 255])
def test_partial_alpha_is_still_a_cover(native_model, alpha):
    native_model.alpha = alpha
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))


def test_nonlayered_zero_alpha_is_not_ignored(native_model):
    native_model.layered = False
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))


@pytest.mark.parametrize("failure", ["unavailable", "color_key"])
def test_uncertain_or_color_key_alpha_stays_conservative(native_model, monkeypatch, failure):
    gui = sys.modules["win32gui"]
    def get_alpha(hwnd):
        if failure == "unavailable":
            raise RuntimeError("per-pixel layered window")
        return 0, 0, 1
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", get_alpha)
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800))


@pytest.mark.parametrize("raises", [False, True])
def test_unrelated_window_cloak_failure_does_not_block(native_model, monkeypatch, raises):
    import ctypes
    native_model.cover = (1500, 800, 1600, 900)
    original = ctypes.windll.dwmapi.DwmGetWindowAttribute
    calls = []
    def attribute(hwnd, key, pointer, size):
        calls.append(key)
        if key == 14:
            if raises:
                raise OSError("cloak unavailable")
            return -1
        return original(hwnd, key, pointer, size)
    monkeypatch.setattr(ctypes.windll.dwmapi, "DwmGetWindowAttribute", attribute)
    assert visibility.exposed(11, [(20,20,48,48)], (800,800))
    assert 14 not in calls


def test_overlapping_cloak_failure_is_conservative_and_diagnosed(native_model, monkeypatch):
    import ctypes
    original = ctypes.windll.dwmapi.DwmGetWindowAttribute
    def attribute(hwnd, key, pointer, size):
        return -1 if key == 14 else original(hwnd, key, pointer, size)
    monkeypatch.setattr(ctypes.windll.dwmapi, "DwmGetWindowAttribute", attribute)
    detail = {}
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800), diagnostic=detail)
    assert detail["stage"] == "window_cloak"
    assert detail["other_hwnd"] == 22
    assert detail["cloak_hresult"] == -1
    assert detail["cover"] == native_model.cover
    assert detail["targets"] == [(20,20,68,68)]


def test_opaque_blocker_diagnostic_omits_title(native_model, monkeypatch):
    native_model.alpha = 255
    gui = sys.modules["win32gui"]
    monkeypatch.setattr(gui, "GetClassName", lambda hwnd: "TestOverlay", raising=False)
    detail = {}
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800), diagnostic=detail)
    assert detail["stage"] == "occluded"
    assert detail["alpha"] == 255
    assert detail["window_class"] == "TestOverlay"
    assert not any("title" in key for key in detail)


def test_api_exception_diagnostic_and_next_call_recovery(native_model, monkeypatch):
    gui = sys.modules["win32gui"]
    original = gui.GetWindowRect
    import ctypes
    original_attribute = ctypes.windll.dwmapi.DwmGetWindowAttribute
    def attribute(hwnd, key, pointer, size):
        return -1 if key == 9 else original_attribute(hwnd, key, pointer, size)
    monkeypatch.setattr(ctypes.windll.dwmapi, "DwmGetWindowAttribute", attribute)
    def fail(hwnd):
        raise OSError(5, "private title must not be logged")
    monkeypatch.setattr(gui, "GetWindowRect", fail)
    detail = {}
    assert not visibility.exposed(11, [(20,20,48,48)], (800,800), diagnostic=detail)
    assert detail["stage"] == "window_bounds"
    assert detail["error"] == "OSError"
    assert "private" not in repr(detail)
    monkeypatch.setattr(gui, "GetWindowRect", original)
    assert visibility.exposed(11, [(20,20,48,48)], (800,800), diagnostic=detail)
    assert detail == {"stage": "exposed", "hwnd": 11}


def test_requests_log_native_failure_without_logging_automatic_polls(
        window, app, native_model, monkeypatch, caplog):
    import ctypes
    import logging
    native_model.owner = int(window.winId())
    native_model.client = (0, 0, window.width(), window.height())
    original = ctypes.windll.dwmapi.DwmGetWindowAttribute
    def attribute(hwnd, key, pointer, size):
        return -1 if key == 14 else original(hwnd, key, pointer, size)
    monkeypatch.setattr(ctypes.windll.dwmapi, "DwmGetWindowAttribute", attribute)
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    with caplog.at_level(logging.INFO):
        assert not dialogue.request()
        assert "window_cloak" in caplog.text
        assert "other_hwnd" in caplog.text
        assert "cloak_hresult" in caplog.text
        assert not dialogue.bubble.isVisible()
        caplog.clear()
        assert not dialogue.request(automatic=True)
        assert len(caplog.records) == 1
        assert 'mode=automatic' in caplog.text and 'result=display_blocked' in caplog.text
        assert 'window_cloak' in caplog.text and 'cloak_hresult' in caplog.text
        caplog.clear()
        dialogue.clock = lambda: 100.0
        for _ in range(20):
            dialogue.tick()
        assert not caplog.records
        assert not dialogue.bubble.isVisible()
