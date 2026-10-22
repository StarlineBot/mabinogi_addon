"""Minimal window startup/close with isolated settings and external devices.

Runs in Linux regression and with native Qt on the Windows build runner.
This is not execution of the packaged exe or an integration test of game APIs.
"""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from mabinogi_addon import config
from mabinogi_addon.system import autostart
from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
from mabinogi_addon.ui import main_window


@pytest.mark.parametrize("returning_user", [False, True])
def test_main_window_initializes_and_closes(returning_user, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(autostart, "reconcile", lambda value: None)
    monkeypatch.setattr(main_window, "create_window_watcher", lambda **kw: AlwaysActiveWatcher())
    monkeypatch.setattr(main_window.MainWindow, "_maybe_check_update", lambda self: None)
    if returning_user:
        config._write_local_config({"general": {"skipSetup": True, "tourShown": True,
                                                "firstUseGuideShown": True}})
    window = main_window.MainWindow()
    try:
        # Polling/network/capture are deliberately not started by this smoke check.
        window.show()
        app.processEvents()
        assert window.isVisible() and window.windowTitle()
        assert window.centralWidget() is not None
        assert not window.grab().isNull()
    finally:
        window._force_quit = True
        window.close()
    assert window._closing and not window.isVisible()
    assert window.buff_controller is None and window.debuff_controller is None
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    assert not isValid(window)
