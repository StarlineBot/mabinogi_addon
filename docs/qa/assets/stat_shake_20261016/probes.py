"""Independent stat warning integration checks; explicit pytest entry point."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.ui import stat_bars_tab
from test_support.boundaries import ExternalBoundaries


ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "settings.json"
    read, write = config._read_local_config, config._write_local_config
    write({"statBars": {"enabled": True, "box": dict(x=0, y=0, w=104, h=32),
                        "bars": {"hp": {"pos": dict(x=-500, y=100), "locked": True,
                                         "show": True, "alert": {"on": True, "pct": 30}}}}}, path)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda value, *a, **k: write(value, path))
    state = SimpleNamespace(active=True, logged=True, boss=True, captures=0, sounds=[], offsets=[])
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"} if state.logged else None)
    frame = image_io.imread(ROOT / "tests/data/stat_bar_shots/hp021_mp100_sta100_007.png")
    assert frame is not None
    state.frame = frame
    watcher = SimpleNamespace(is_game_active=lambda: state.active, is_self_active=lambda: False)
    with ExternalBoundaries() as boundary:
        tab = stat_bars_tab.StatBarsTab(watcher)
        tab._timer.stop()
        tab.set_boss_presence_source(lambda: state.boss)
        def capture(*args):
            state.captures += 1
            return state.frame
        monkeypatch.setattr(tab, "_grab_rect", capture)
        monkeypatch.setattr(tab, "_show_preview", lambda *a: None)
        monkeypatch.setattr(tab, "_play_alert_sound", lambda: state.sounds.append(time.monotonic()))
        try:
            yield app, tab, state, path
        finally:
            tab.shutdown()
            for ov in tab._overlays.values():
                ov.close()
                ov.deleteLater()
            tab.close()
            tab.deleteLater()
            app.processEvents()
        assert not boundary.violations


def test_real_timer_repeats_two_bursts_without_extra_capture_or_sound(runtime, monkeypatch):
    app, tab, state, path = runtime
    tab._tick()
    ov = tab._overlays["hp"]
    origin = ov.base_position
    geometry = ov.geometry()
    update = ov.update
    def observe():
        state.offsets.append((time.monotonic(), ov._shake_offset))
        update()
    monkeypatch.setattr(ov, "update", observe)
    start = time.monotonic()
    pulse = QTimer()
    ticks = []
    pulse.timeout.connect(lambda: (ticks.append(1), tab._tick()))
    pulse.start(100)
    try:
        QTest.qWait(2850)
    finally:
        pulse.stop()
    assert ov.warning_active
    assert state.captures == 1 + len(ticks)
    assert len(state.sounds) == 1
    assert any(.4 < t - start < 1 and abs(x) > 1 for t, x in state.offsets)
    assert any(2.2 < t - start < 2.8 and abs(x) > 1 for t, x in state.offsets)
    assert ov.geometry() == geometry and ov.base_position == origin
    tab._save()
    assert config.load_stat_bars()["bars"]["hp"]["pos"] == {"x": -500, "y": 100}
    tab.set_paused(True)
    app.processEvents()
    assert not ov.warning_active and not ov._warning_timer.isActive()
    captures, updates = state.captures, len(state.offsets)
    QTest.qWait(150)
    assert state.captures == captures and len(state.offsets) == updates


@pytest.mark.parametrize("reason", ("capture", "inactive", "logout", "boss", "partial"))
def test_unknown_and_rapid_reentry_require_new_samples_without_sound_rearm(runtime, monkeypatch, reason):
    _, tab, state, _ = runtime
    clock = [20.0]
    monkeypatch.setattr(stat_bars_tab.time, "monotonic", lambda: clock[0])
    tab._tick()
    clock[0] += .41
    tab._tick()
    ov = tab._overlays["hp"]
    assert ov.warning_active and len(state.sounds) == 1
    original = state.frame
    if reason == "capture": state.frame = None
    elif reason == "inactive": state.active = False
    elif reason == "logout": state.logged = False
    elif reason == "boss": state.boss = False
    else: state.frame = np.zeros_like(original)
    clock[0] += .05
    tab._tick()
    assert not ov.warning_active and not ov._warning_timer.isActive()
    state.frame, state.active, state.logged, state.boss = original, True, True, True
    clock[0] += .05
    tab._tick()
    assert not ov.warning_active
    clock[0] += .41
    tab._tick()
    assert ov.warning_active and len(state.sounds) == 1


def test_repeated_real_capture_path_keeps_resources_bounded_and_legacy_settings(runtime, monkeypatch):
    _, tab, state, path = runtime
    clock = [100.0]
    monkeypatch.setattr(stat_bars_tab.time, "monotonic", lambda: clock[0])
    tab._tick()
    before = deepcopy(config._read_local_config())
    overlays = tuple(tab._overlays.values())
    for index in range(1200):
        clock[0] += .2
        tab._tick()
        if index % 20 == 10:
            tab.set_paused(True)
            assert all(not ov._warning_timer.isActive() for ov in overlays)
            tab.set_paused(False)
    assert tuple(tab._overlays.values()) == overlays
    assert state.captures == 1201
    assert len(state.sounds) == 1
    assert all(len(ov.findChildren(QTimer)) == 1 for ov in overlays)
    tab._save()
    after = config._read_local_config()
    assert after["statBars"]["box"] == before["statBars"]["box"]
    assert after["statBars"]["bars"]["hp"]["pos"] == before["statBars"]["bars"]["hp"]["pos"]
    assert overlays[0].base_position == QPoint(-500, 100)


def test_stale_warning_expires_before_rechecking_threshold(runtime, monkeypatch):
    _, tab, _, _ = runtime
    clock = [30.0]
    monkeypatch.setattr(stat_bars_tab.time, "monotonic", lambda: clock[0])
    tab._tick()
    clock[0] += .41
    tab._tick()
    ov = tab._overlays["hp"]
    assert ov.warning_active
    clock[0] += .66
    ov._advance_warning()
    assert not ov.warning_active and not ov._warning_timer.isActive()
    tab._update_visual_alerts(clock[0])
    assert not ov.warning_active and tab._visual_sample_at is None
    tab._tick()
    assert not ov.warning_active
    clock[0] += .41
    tab._tick()
    assert ov.warning_active
