"""Independent shutdown guards, repeated lifecycle and tray capture probes."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer

from mabinogi_addon import config
from mabinogi_addon.ui import main_window
from scripts.qa_setup_closed_retry import Source
from scripts.qa_setup_first_user import app, isolated, close, forbid


def events(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def enable_regions(window):
    raw = config._read_local_config()
    for key, section in (("buff", "buffTracker"), ("debuff", "debuffTracker")):
        raw[section].update(enabled=True, captureRegion={"x": 10, "y": 20, "w": 80, "h": 40})
        check = window._feature_checks[key]
        check.blockSignals(True)
        check.setChecked(True)
        check.blockSignals(False)
    config._write_local_config(raw)


@pytest.mark.parametrize("started", [False, True])
def test_import_wait_rejects_start_capture_and_first_show(app, isolated, monkeypatch, started):
    window = main_window.MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    try:
        if started:
            window.start()
        window._on_config_imported()
        enable_regions(window)
        before = isolated.read_bytes()
        monkeypatch.setattr(main_window, "create_live_source", forbid)
        monkeypatch.setattr(window.party_tab, "start_polling", forbid)
        monkeypatch.setattr(window, "_maybe_show_release_notes", forbid)
        monkeypatch.setattr(window, "_maybe_run_tour", forbid)
        for _ in range(10):
            window.start()
            window._maybe_retry_live_capture()
            window._start_buff_tracking()
            window._start_debuff_tracking()
            window._update_tracking_status()
            window._on_first_shown()
        events(850)
        assert window.buff_controller is None and window.debuff_controller is None
        assert isolated.read_bytes() == before
    finally:
        close(window)


def test_twenty_start_double_start_double_close_cycles(app, isolated, monkeypatch):
    monkeypatch.setattr(main_window, "create_live_source", forbid)
    for _ in range(20):
        window = main_window.MainWindow()
        starts = []
        monkeypatch.setattr(window.party_tab, "start_polling", lambda: starts.append(True))
        try:
            window.start()
            timer = window._status_timer
            timers = window.findChildren(QTimer)
            window.start()
            assert window._status_timer is timer
            assert window.findChildren(QTimer) == timers
            assert len(starts) == 1
            window._force_quit = True
            window.close()
            window.close()
            assert window._closing and not timer.isActive()
            enable_regions(window)
            window._update_tracking_status()
            window._start_buff_tracking()
            window._start_debuff_tracking()
            window.start()
            app.processEvents()
            assert window.buff_controller is None and window.debuff_controller is None
            # Keep the next cycle unconfigured without changing the closed UI.
            raw = config._read_local_config()
            for section in ("buffTracker", "debuffTracker"):
                raw[section]["enabled"] = False
            config._write_local_config(raw)
        finally:
            close(window)
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_tray_status_tick_starts_real_workers_but_full_close_does_not(app, isolated, monkeypatch):
    calls = []

    def source(region):
        calls.append(region)
        return Source()

    monkeypatch.setattr(main_window, "create_live_source", source)
    window = main_window.MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    monkeypatch.setattr(window, "_minimize_to_tray_enabled", lambda: True)
    try:
        window.start()
        window.close()
        assert not window._closing and not window._setup_flow.closed
        assert window._status_timer.isActive()
        enable_regions(window)
        events(850)
        assert len(calls) == 2
        assert window.buff_controller._worker.isRunning()
        assert window.debuff_controller._worker.isRunning()
        window._force_quit = True
        window.close()
        assert window._closing and not window._status_timer.isActive()
        monkeypatch.setattr(main_window, "create_live_source", forbid)
        events(850)
        window._start_buff_tracking()
        window._start_debuff_tracking()
    finally:
        close(window)
