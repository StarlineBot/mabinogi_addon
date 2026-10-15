"""Independent setup regression probes; run explicitly, not default collection."""

from copy import deepcopy

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, setup_state as state, autofind_diagnostics as diag
from mabinogi_addon.ui.custom_overlay_tab import CustomOverlayTab
from mabinogi_addon.ui.main_window import MainWindow
from mabinogi_addon.ui import screen_grab


BOX = {"x": 10, "y": 20, "w": 80, "h": 40,
       "posX": 300, "posY": 300, "locked": False, "name": "qa"}


class Watcher:
    def is_game_active(self):
        return True

    def is_self_active(self):
        return False


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch, tmp_path):
    path = tmp_path / "qa config.json"
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    raw = {feature.section: {"enabled": False} for feature in state.FEATURES}
    raw["general"] = {"gameExe": "Client.exe", "skipSetup": False}
    config._write_local_config(raw)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "QA"})
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    return path


def update(section, **values):
    raw = config._read_local_config()
    raw.setdefault(section, {}).update(deepcopy(values))
    config._write_local_config(raw)


@pytest.mark.parametrize("operation", ["startup", "add", "load"])
def test_disabled_custom_overlays_stay_hidden(app, settings, operation):
    update("customOverlay", enabled=False, presets={"qa": [BOX]},
           autoPreset="qa" if operation == "startup" else None)
    tab = CustomOverlayTab(Watcher())
    try:
        assert not tab.enable.isChecked()
        if operation == "add":
            tab._on_selected(10, 20, 80, 40)
        elif operation == "load":
            tab._mgr.load(config.load_custom_presets()["qa"])
        overlays = tab._mgr.overlays()
        assert len(overlays) == 1
        assert tab._mgr._paused
        for _ in range(5):
            tab._mgr._tick()
            app.processEvents()
        assert not any(overlay.isVisible() for overlay in overlays)
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()


def test_fully_configured_user_keeps_existing_start_screen(app, settings):
    # U-02: all enabled required regions are registered, no explicit opt-out needed.
    update("tuarim", enabled=True, box={"x": 10, "y": 20, "w": 42, "h": 16})
    assert state.pending() == []
    window = MainWindow()
    try:
        assert window._pages.currentWidget() is window._tabs
    finally:
        window._force_quit = True
        window.close()
        window.deleteLater()


def test_tray_close_during_capture_stays_hidden(app, settings, monkeypatch):
    update("tuarim", enabled=True)
    window = MainWindow()
    monkeypatch.setattr(window, "_minimize_to_tray_enabled", lambda: True)
    monkeypatch.setattr(screen_grab, "_grab_game_window",
                        lambda: (np.zeros((80, 120, 3), np.uint8), 0, 0))
    monkeypatch.setattr(screen_grab, "_save_debug_frame", lambda *a: None)
    monkeypatch.setattr("time.sleep", lambda *a: None)
    storage = diag.DiagnosticStore(settings.parent / "diagnostics")
    monkeypatch.setattr(diag, "store", lambda: storage)
    window.show()
    app.processEvents()
    QTimer.singleShot(0, window.close)
    try:
        window._setup_flow.run()
        assert window._setup_flow.cancelled
        assert not window._setup_flow.closed
        assert not window.isVisible()
    finally:
        storage.io.close()
        window._force_quit = True
        window.close()
        window.deleteLater()


def test_normal_custom_toggle_hides_existing_window(app, settings):
    update("customOverlay", enabled=True)
    tab = CustomOverlayTab(Watcher())
    try:
        tab._on_selected(10, 20, 80, 40)
        overlays = tab._mgr.overlays()
        assert len(overlays) == 1 and overlays[0].isVisible()
        tab.enable.setChecked(False)
        tab._mgr._tick()
        assert not overlays[0].isVisible()
        tab.enable.setChecked(True)
        assert not tab._mgr._paused
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
