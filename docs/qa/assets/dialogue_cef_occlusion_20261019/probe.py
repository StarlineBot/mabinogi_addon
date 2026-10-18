"""Replay observed flags-zero coverage; passing means reproduction, not resolution."""

import logging
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from scripts.qa_dialogue_transparent_occlusion import app, window, native_model  # noqa: E402,F401
from mabinogi_addon.system import dialogue_visibility as visibility  # noqa: E402


@pytest.fixture
def observed(native_model, monkeypatch):
    state = native_model
    state.cover = (0, 0, 2559, 1440)
    state.flags = 0
    gui = sys.modules["win32gui"]
    monkeypatch.setattr(gui, "GetLayeredWindowAttributes", lambda hwnd: (0, 0, state.flags))
    monkeypatch.setattr(gui, "GetClassName", lambda hwnd: "CEF-OSC-WIDGET", raising=False)
    monkeypatch.setattr(sys.modules["win32api"], "EnumDisplayMonitors",
                        lambda: [(1, None, (0, 0, 2560, 1440))])
    return state


@pytest.mark.parametrize("rects", [
    [(418, 312, 48, 48), (469, 320, 205, 31)],
    [(1128, 1029, 48, 48), (981, 985, 195, 41)],
])
@pytest.mark.parametrize("flags", [0, 2])
def test_logged_targets_follow_the_alpha_flags_branch(observed, flags, rects):
    observed.client = (0, 0, 2560, 1440)
    observed.flags = flags
    detail = {}
    assert visibility.exposed(observed.owner, rects, (2560, 1440), diagnostic=detail) is (flags == 2)
    if flags == 0:
        assert detail["stage"] == "occluded"
        assert detail["cover"] == observed.cover
        assert detail["alpha"] == detail["alpha_flags"] == 0
        assert detail["window_class"] == "CEF-OSC-WIDGET"
        assert detail["bounds_hresult"] == detail["cloak_hresult"] == 0


@pytest.mark.parametrize("automatic", [False, True])
def test_same_flags_zero_blocks_actual_qt_request_and_only_removing_cover_recovers(
        window, app, observed, caplog, automatic):
    observed.owner = int(window.winId())
    observed.client = (0, 0, window.width(), window.height())
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    dialogue.clock = lambda: 100.0
    dialogue.session.rng.random = lambda: 0.0
    assert dialogue.enabled and dialogue.session.entries
    logger = "mabinogi_addon.ui.creator_dialogue"
    caplog.set_level(logging.INFO, logger=logger)
    if automatic:
        dialogue.tick()
    else:
        dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    assert not dialogue.session.last_text
    records = [r.getMessage() for r in caplog.records if r.name == logger]
    assert len(records) == (0 if automatic else 1)
    if records:
        assert "CEF-OSC-WIDGET" in records[0] and "'alpha_flags': 0" in records[0]
    # Boundary control only: this does not ask the user to close another app.
    observed.present = False
    dialogue.face.click()
    assert dialogue.bubble.isVisible() and dialogue.session.last_text
