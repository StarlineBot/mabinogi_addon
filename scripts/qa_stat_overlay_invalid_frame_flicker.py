"""Unresolved visibility ordering regression. Run explicitly with pytest."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.stat_bars import read_stat_bars
from mabinogi_addon.ui.stat_bars_tab import StatBarsTab


ROOT = Path(__file__).resolve().parents[1]


class VisibilityTrace(QObject):
    def __init__(self):
        super().__init__()
        self.events = []

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.Show, QEvent.Type.Hide):
            self.events.append((obj.stat_id, event.type().name))
        return False


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.json"
    read, write = config._read_local_config, config._write_local_config
    write({"statBars": {"enabled": True, "box": dict(x=932, y=1403, w=104, h=32)}}, path)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda value, *a, **k: write(value, path))
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    state = SimpleNamespace(frame=None, captures=0, active=True)
    tab = StatBarsTab(SimpleNamespace(is_game_active=lambda: state.active,
                                     is_self_active=lambda: False))
    tab._timer.stop()
    for values in tab._bars_cfg.values():
        values["alert"]["on"] = False
    tab.set_boss_presence_source(lambda: False)
    def capture(*args):
        state.captures += 1
        return state.frame
    monkeypatch.setattr(tab, "_grab_rect", capture)
    monkeypatch.setattr(tab, "_show_preview", lambda *a: None)
    monkeypatch.setattr(tab, "_play_alert_sound", lambda: pytest.fail("unexpected sound"))
    tab._ensure_overlays()
    trace = VisibilityTrace()
    for overlay in tab._overlays.values():
        overlay.installEventFilter(trace)
    good = image_io.imread(ROOT / "tests/data/stat_bar_shots/hp021_mp100_sta100_007.png")
    assert good is not None and len(read_stat_bars(good, require_complete=True)) == 3
    try:
        yield app, tab, state, trace, good
    finally:
        tab.shutdown()
        for overlay in tab._overlays.values():
            overlay.removeEventFilter(trace)
            overlay.close()
            overlay.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("previously_valid", (False, True), ids=("startup", "after-valid"))
@pytest.mark.parametrize("kind", ("black", "partial", "uploaded-native-roi", "capture-none"))
def test_invalid_input_must_not_show_before_hiding(runtime, previously_valid, kind):
    app, tab, state, trace, good = runtime
    if previously_valid:
        state.frame = good
        tab._tick()
        app.processEvents()
        assert all(overlay.isVisible() for overlay in tab._overlays.values())
    if kind == "black":
        state.frame = np.zeros_like(good)
    elif kind == "partial":
        state.frame = good.copy()
        state.frame[:12] = 0
    elif kind == "uploaded-native-roi":
        screenshot = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-16 205627.png")
        assert screenshot is not None and screenshot.shape == (1440, 2560, 3)
        # Native-pixel replay, not a claim about the original session's DPI transform.
        state.frame = screenshot[1403:1435, 932:1036].copy()
    else:
        state.frame = None
    assert not read_stat_bars(state.frame, require_complete=True)
    trace.events.clear()
    captures = state.captures
    visible_after = []
    for _ in range(4):
        tab._tick()
        app.processEvents()
        visible_after.append([overlay.isVisible() for overlay in tab._overlays.values()])
    assert state.captures == captures + 4
    assert not any(event == "Show" for _, event in trace.events), {
        "events": trace.events, "end_states": visible_after,
    }
    assert not any(any(values) for values in visible_after)


def test_valid_frames_remain_visible_without_repeated_show_events(runtime):
    app, tab, state, trace, good = runtime
    state.frame = good
    tab._tick()
    app.processEvents()
    assert all(overlay.isVisible() for overlay in tab._overlays.values())
    trace.events.clear()
    for _ in range(4):
        tab._tick()
        app.processEvents()
    assert not trace.events
    assert all(overlay.isVisible() for overlay in tab._overlays.values())


def test_inactive_frames_remain_hidden(runtime):
    app, tab, state, trace, good = runtime
    state.active = False
    state.frame = good
    for _ in range(4):
        tab._tick()
        app.processEvents()
    assert not trace.events and state.captures == 0
    assert not any(overlay.isVisible() for overlay in tab._overlays.values())
