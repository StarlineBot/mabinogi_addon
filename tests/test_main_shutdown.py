"""완전 종료 후 캡처 재시작 방지와 트레이 추적 유지."""

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, setup_state
from mabinogi_addon.system import autostart
from mabinogi_addon.ui import main_window


@pytest.fixture
def window(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "설정.json"
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "reconcile", lambda value: None)
    monkeypatch.setattr(main_window.MainWindow, "_maybe_check_update", lambda *a: None)
    raw = {feature.section: {"enabled": False} for feature in setup_state.FEATURES}
    raw["warnGoneSeeded"] = True
    config._write_local_config(raw)
    window = main_window.MainWindow()
    starts = []
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: starts.append(True))
    yield window, starts
    window._force_quit = True
    window.close()
    window.deleteLater()
    app.processEvents()


def provide_regions():
    raw = config._read_local_config()
    for name in ("buffTracker", "debuffTracker"):
        raw[name].update(enabled=True, captureRegion={"x": 10, "y": 20, "w": 80, "h": 40})
    config._write_local_config(raw)


def test_full_close_stops_timer_and_rejects_late_callbacks(window, monkeypatch):
    window, starts = window
    window.start()
    timer = window._status_timer
    window._force_quit = True
    window.close()
    assert window._closing and not timer.isActive()
    provide_regions()
    monkeypatch.setattr(main_window, "create_live_source", lambda *a: pytest.fail("closed window created capture"))
    window._maybe_retry_live_capture()
    window._start_buff_tracking()
    window._start_debuff_tracking()
    window._update_tracking_status()
    window._on_first_shown()
    window.start()
    loop = QEventLoop()
    QTimer.singleShot(900, loop.quit)
    loop.exec()
    assert window.buff_controller is None and window.debuff_controller is None
    assert window._status_timer is timer and not timer.isActive()
    assert len(starts) == 1


def test_start_is_idempotent(window):
    window, starts = window
    window.start()
    timer = window._status_timer
    window.start()
    assert window._status_timer is timer and timer.isActive()
    assert len(starts) == 1


def test_tray_hide_keeps_status_and_capture_retry_alive(window, monkeypatch):
    window, _ = window
    window.start()
    monkeypatch.setattr(window, "_minimize_to_tray_enabled", lambda: True)
    window.close()
    assert not window._closing and not window._setup_flow.closed
    assert window._status_timer.isActive()
    provide_regions()
    calls = []
    def unavailable(region):
        calls.append(region)
        raise ImportError("capture backend unavailable")
    monkeypatch.setattr(main_window, "create_live_source", unavailable)
    window._maybe_retry_live_capture()
    assert calls
