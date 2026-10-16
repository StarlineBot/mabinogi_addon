"""판독 실패 중에는 틱 중간에도 창을 표시하지 않아야 한다."""

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.stat_bars import read_stat_bars
from test_stat_bars_stability import pipeline


class VisibilityTrace(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.events.append((obj.stat_id, event.type().name, obj._ratio))
        return False


@pytest.fixture
def visibility(pipeline):
    tab, state, good = pipeline
    tab._ensure_overlays()
    trace = VisibilityTrace()
    for ov in tab._overlays.values():
        ov.installEventFilter(trace)
    try:
        yield tab, state, good, trace
    finally:
        for ov in tab._overlays.values():
            ov.removeEventFilter(trace)


@pytest.mark.parametrize("previously_valid", [False, True])
@pytest.mark.parametrize("kind", ["black", "partial", "uploaded", "capture-none"])
def test_invalid_frames_never_redisplay_and_recovery_sets_values_before_show(visibility, previously_valid, kind):
    tab, state, good, trace = visibility
    if previously_valid:
        tab._tick()
        assert all(ov.isVisible() for ov in tab._overlays.values())
    if kind == "black":
        state.frame = np.zeros_like(good)
    elif kind == "partial":
        state.frame = good.copy()
        state.frame[:12] = 0
    elif kind == "uploaded":
        shot = image_io.imread(Path(__file__).parent / "data/스크린샷 2026-10-16 205627.png")
        assert shot is not None and shot.shape == (1440, 2560, 3)
        state.frame = shot[1403:1435, 932:1036].copy()
    else:
        state.frame = None
    assert not read_stat_bars(state.frame, require_complete=True)
    trace.events.clear()
    for index in range(5):
        state.now = index * .2
        tab._tick()
        QApplication.processEvents()
        assert not any(ov.isVisible() for ov in tab._overlays.values())
        assert not tab._display_valid
    assert not any(event == "Show" for _, event, _ in trace.events)
    state.frame = good
    state.now = 1.2
    trace.events.clear()
    tab._tick()
    expected = {reading.stat_id: reading.ratio for reading in read_stat_bars(good, require_complete=True)}
    assert {sid: value for sid, event, value in trace.events if event == "Show"} == expected
    assert all(ov.isVisible() for ov in tab._overlays.values())
    assert not any(ov.warning_active for ov in tab._overlays.values())
    trace.events.clear()
    tab._tick()
    assert not trace.events


@pytest.mark.parametrize("action", ["show", "pause", "enable", "login", "focus", "region", "unlock"])
def test_callbacks_cannot_show_invalid_cached_bars(visibility, monkeypatch, action):
    tab, state, good, trace = visibility
    tab._tick()
    state.frame = None
    tab._tick()
    trace.events.clear()
    if action == "show":
        tab._show_checks["hp"].setChecked(False)
        tab._show_checks["hp"].setChecked(True)
    elif action == "pause":
        tab.set_paused(True)
        tab.set_paused(False)
    elif action == "enable":
        tab._on_enable(False)
        tab._on_enable(True)
    elif action == "login":
        monkeypatch.setattr(config, "load_discord_user", lambda: None)
        tab._apply_visibility()
        monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
        tab._apply_visibility()
    elif action == "focus":
        state.active = False
        tab._apply_visibility()
        state.active = True
        tab._apply_visibility()
    elif action == "region":
        monkeypatch.setattr(tab, "_flash_region", lambda: None)
        tab._on_selected(1, 2, good.shape[1], good.shape[0])
    else:
        tab._set_locked_all(False)
        tab._set_locked_all(True)
    tab._tick()
    QApplication.processEvents()
    assert not any(event == "Show" for _, event, _ in trace.events)
    assert not any(ov.isVisible() for ov in tab._overlays.values())
    state.frame = good
    tab._tick()
    assert all(ov.isVisible() for ov in tab._overlays.values())


@pytest.mark.parametrize("action", ["pause", "disable", "focus", "region"])
def test_interruption_requires_new_capture_even_if_last_frame_was_valid(visibility, monkeypatch, action):
    tab, state, good, trace = visibility
    tab._tick()
    if action == "pause":
        tab.set_paused(True)
        tab.set_paused(False)
    elif action == "disable":
        tab._on_enable(False)
        tab._on_enable(True)
    elif action == "focus":
        state.active = False
        tab._apply_visibility()
        state.active = True
        tab._apply_visibility()
    else:
        monkeypatch.setattr(tab, "_flash_region", lambda: None)
        tab._on_selected(1, 2, good.shape[1], good.shape[0])
    assert not any(ov.isVisible() for ov in tab._overlays.values())
    assert not tab._display_valid
    trace.events.clear()
    state.frame = None
    tab._tick()
    assert not any(event == "Show" for _, event, _ in trace.events)
    state.frame = good
    tab._tick()
    assert all(ov.isVisible() for ov in tab._overlays.values())


def test_valid_data_keeps_position_editing_without_more_capture(visibility, monkeypatch):
    tab, _, _, _ = visibility
    tab._tick()
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: pytest.fail("editing must not capture"))
    tab._set_locked_all(False)
    assert all(ov.isVisible() and not ov.locked for ov in tab._overlays.values())
    assert all(not ov.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
               for ov in tab._overlays.values())
