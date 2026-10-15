"""Reproduce a closed MainWindow restarting capture during later Qt events."""

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer

from mabinogi_addon import config, setup_state as state
from mabinogi_addon.ui import main_window
from scripts.qa_setup_first_user import app, isolated, close


class Source:
    def grab(self):
        return np.zeros((40, 80, 3), dtype=np.uint8)

    def close(self):
        pass


def test_closed_window_cannot_restart_capture_on_next_fixture(app, isolated, monkeypatch):
    raw = {feature.section: {"enabled": False} for feature in state.FEATURES}
    raw["buffTracker"]["enabled"] = True
    raw["warnGoneSeeded"] = True
    config._write_local_config(raw)
    captures = []

    def create_source(region):
        captures.append(region)
        return Source()

    monkeypatch.setattr(main_window, "create_live_source", create_source)
    window = main_window.MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    window.start()
    try:
        window._force_quit = True
        window.close()
        assert window._setup_flow.closed
        assert window.buff_controller is None
        assert not captures

        # A following test supplies a registered region, then processes Qt events.
        raw = config._read_local_config()
        raw["buffTracker"]["captureRegion"] = {"x": 10, "y": 20, "w": 80, "h": 40}
        config._write_local_config(raw)
        loop = QEventLoop()
        QTimer.singleShot(950, loop.quit)
        loop.exec()
        controller = window.buff_controller
        worker_running = controller is not None and controller._worker.isRunning()
        assert (len(captures), worker_running) == (0, False), (
            "closed window's status timer restarted capture", len(captures), worker_running)
    finally:
        window._status_timer.stop()
        if window.buff_controller is not None:
            window.buff_controller.stop(timeout_ms=1000)
        close(window)
