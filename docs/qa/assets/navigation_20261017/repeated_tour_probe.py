"""Repeated cancellation of queued tour geometry work must leave no stale tour."""

from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from shiboken6 import isValid

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window


@pytest.mark.parametrize("exit_mode", ["skip", "hide", "replace"])
def test_repeated_pending_refresh_is_cancelled(window, exit_mode):
    host, app = window
    baseline_timers = set(host.findChildren(QTimer))
    for _ in range(30):
        host._run_tour()
        old = host._tour
        old._i = 5
        old._show_step()
        assert old._layout_timer.isActive()
        calls = []
        old._place_card = lambda: calls.append("stale")
        if exit_mode == "skip":
            old._skip.click()
        elif exit_mode == "hide":
            host.hide()
            host.show()
        else:
            host._run_tour()
            assert host._tour is not old
            host.hide()
            host.show()
        assert old._dismissed and not old._watched
        assert not old._layout_timer.isActive()
        loop = QEventLoop()
        QTimer.singleShot(5, loop.quit)
        loop.exec()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        assert calls == []
        assert not isValid(old)
        assert host._tour is None and host.isVisible()
        assert not any(type(widget).__name__ == "TourOverlay" for widget in app.topLevelWidgets())
        assert set(host.findChildren(QTimer)) == baseline_timers
