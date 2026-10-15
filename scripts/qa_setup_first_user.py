"""Independent first-user setup probes; invoke explicitly with the audio boundary."""

from copy import deepcopy
from pathlib import Path
import os
import runpy
import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, setup_state as state, version
from mabinogi_addon.ui import setup_flow
from mabinogi_addon.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    path = tmp_path / "first user settings" / "config.json"
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", path)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a, **k: None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(version, "__version__", "0.0.0")
    return path


def close(window):
    tour = getattr(window, "_tour", None)
    if tour is not None and tour.isVisible():
        tour._finish()
    window._force_quit = True
    window.close()
    window.deleteLater()


def forbid(*args, **kwargs):
    raise AssertionError("unexpected capture, authentication or settings write")


def test_actual_new_user_start_and_tour(app, isolated, monkeypatch):
    assert not isolated.exists()
    window = MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    try:
        window.start()
        window.move(0, 0)
        window.show()
        app.processEvents()
        assert window._pages.currentWidget() is window.setup_page
        assert window.buff_controller is None and window.debuff_controller is None
        assert not window.buff_overlay.isVisible() and not window.debuff_overlay.isVisible()
        assert not window.memo_overlay.isVisible()
        assert not any(check.isChecked() for check in window._feature_checks.values())
        assert not any(check.isChecked() for check in window.setup_page.checks.values())
        assert state.pending() == []
        tour = window._tour
        assert tour.isVisible() and tour._steps[0].target is window.setup_page.selection
        for _ in range(len(tour._steps)):
            tour._next.click()
            app.processEvents()
        assert not tour.isVisible()
        out = Path("/tmp/setup-first-user-qa")
        out.mkdir(exist_ok=True)
        window.grab().save(str(out / "actual-main.png"))
        assert window.rect().contains(window.setup_page.skip.mapTo(
            window, window.setup_page.skip.rect().bottomRight()))
    finally:
        close(window)


@pytest.mark.parametrize("key", [feature.key for feature in state.FEATURES])
def test_each_feature_selection_survives_restart(app, isolated, monkeypatch, key):
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "QA"})
    window = MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    try:
        window.start()
        window.setup_page.checks[key].click()
        assert window._feature_checks[key].isChecked()
        assert {f.key for f in state.FEATURES if state.enabled(f.key)} == {key}
        window._feature_checks[key].setChecked(False)
        assert not window.setup_page.checks[key].isChecked()
        window.setup_page.checks[key].click()
    finally:
        close(window)
    saved = deepcopy(config._read_local_config())
    window = MainWindow()
    try:
        assert config._read_local_config() == saved
        assert {f.key for f in state.FEATURES if window._feature_checks[f.key].isChecked()} == {key}
        assert {f.key for f in state.FEATURES if window.setup_page.checks[f.key].isChecked()} == {key}
        assert window._pages.currentWidget() is window.setup_page
    finally:
        close(window)


@pytest.mark.parametrize("contents", [b"", b"{}", b"{broken", b'{"memo":{"text":"qa","locked":true}}'])
def test_existing_main_and_backup_bytes_are_untouched(isolated, contents):
    isolated.parent.mkdir(parents=True)
    isolated.write_bytes(contents)
    backup = isolated.with_name(isolated.name + ".bak")
    original_backup = b'{"buffTracker":{"enabled":true},"general":{"skipSetup":true}}'
    backup.write_bytes(original_backup)
    state.initialize_new_user()
    assert isolated.read_bytes() == contents
    assert backup.read_bytes() == original_backup


def test_backup_only_is_not_a_new_user(isolated):
    isolated.parent.mkdir(parents=True)
    backup = isolated.with_name(isolated.name + ".bak")
    original = b'{"memo":{"enabled":true,"text":"qa"}}'
    backup.write_bytes(original)
    state.initialize_new_user()
    assert not isolated.exists()
    assert backup.read_bytes() == original
    assert state.enabled("memo")


def test_actual_existing_user_construction_preserves_settings(app, isolated):
    raw = {feature.section: {"enabled": index % 2 == 0}
           for index, feature in enumerate(state.FEATURES)}
    raw.update({"warnGoneSeeded": True,
                "general": {"gameExe": "Client.exe", "tourShown": True, "skipSetup": True},
                "memo": {"enabled": True, "text": "qa memo", "locked": True, "fontSize": 18},
                "memoTracker": {"captureRegion": {"x": 10, "y": 20, "w": 150, "h": 80}},
                "unknownLegacy": {"keep": [1, 2, 3]}})
    raw["customOverlay"]["presets"] = {"qa": [{"x": 10, "y": 20, "w": 60, "h": 40}]}
    config._write_local_config(raw)
    before = isolated.read_bytes()
    window = MainWindow()
    try:
        assert isolated.read_bytes() == before
        assert window._pages.currentWidget() is window._tabs
        for feature in state.FEATURES:
            expected = raw[feature.section]["enabled"]
            assert window._feature_checks[feature.key].isChecked() is expected
            assert window.setup_page.checks[feature.key].isChecked() is expected
    finally:
        close(window)


def test_empty_selection_is_read_only_and_does_not_capture(app, isolated, monkeypatch):
    window = MainWindow()
    before = isolated.read_bytes()
    try:
        with monkeypatch.context() as boundary:
            boundary.setattr(setup_flow, "capture_for_autofind", forbid)
            boundary.setattr(setup_flow, "perform_autofind", forbid)
            boundary.setattr(config, "load_discord_user", forbid)
            boundary.setattr(config, "_write_local_config", forbid)
            window.setup_page.run_btn.click()
            assert window.setup_page.progress.text() == "사용할 기능을 선택하세요."
            assert isolated.read_bytes() == before
            assert not window.setup_page.busy and window._setup_flow.future is None
    finally:
        close(window)


def test_login_navigation_repeatedly_keeps_settings_and_no_auth(app, isolated):
    window = MainWindow()
    try:
        window._booting = False
        raw = config._read_local_config()
        raw.setdefault("general", {})["tourShown"] = True
        config._write_local_config(raw)
        window.show()
        app.processEvents()
        before = isolated.read_bytes()
        for _ in range(50):
            window.setup_page.login_btn.click()
            app.processEvents()
            assert window._pages.currentWidget() is window._tabs
            scroll = window._tabs.currentWidget()
            button = window.settings_tab._login_btn
            assert scroll.viewport().rect().contains(button.mapTo(scroll.viewport(), button.rect().center()))
            assert window.settings_tab._login_thread is None
            window.settings_tab.reopen_setup.emit()
            assert window._pages.currentWidget() is window.setup_page
        assert isolated.read_bytes() == before
    finally:
        close(window)


@pytest.mark.parametrize("logged_in", [False, True])
def test_actual_main_scroll_geometry_and_access(app, isolated, monkeypatch, logged_in):
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "QA"} if logged_in else None)
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        tour = getattr(window, "_tour", None)
        if tour is not None:
            tour._finish()
        page = window.setup_page
        assert page.login_btn.isVisible() is (not logged_in)
        assert page.selection.horizontalScrollBar().maximum() == 0
        rows = list(page.checks.values())
        viewport = page.selection.viewport()
        assert rows[0].mapTo(viewport, QPoint(0, 0)).y() == 0
        assert rows[3].mapTo(viewport, rows[3].rect().bottomRight()).y() < viewport.height()
        fifth_y = rows[4].mapTo(viewport, QPoint(0, 0)).y()
        assert fifth_y < viewport.height() < fifth_y + rows[4].height()
        page.selection.verticalScrollBar().setValue(page.selection.verticalScrollBar().maximum())
        app.processEvents()
        for row in rows:
            assert row.sizeHint().width() <= row.width()
        assert viewport.rect().contains(rows[-1].mapTo(viewport, rows[-1].rect().bottomRight()))
        assert page.checks["stat_bars"].isEnabled() is logged_in
    finally:
        close(window)


def test_shutdown_blocked_capture_with_explicit_child_audio_boundary():
    scenario = runpy.run_path("tests/test_lifecycle.py")["_SCENARIOS"]["shutdown_blocked"]
    target = "from mabinogi_addon.ui.main_window import MainWindow"
    assert scenario.count(target) == 1
    # Importing pytest changes closeEvent's process-exit branch, so do not use
    # the parent fixture inside this standalone shutdown process.
    boundary = ("from PySide6.QtCore import QObject\n"
                "from mabinogi_addon.ui.notifier import SoundNotifier\n"
                "def _no_native_audio(self, sounds, parent=None, volume=1.0):\n"
                "    QObject.__init__(self, parent)\n"
                "    self._sounds = dict(sounds)\n"
                "    self._player = self._audio = None\n"
                "SoundNotifier.__init__ = _no_native_audio\n")
    proc = subprocess.run([sys.executable, "-c", scenario.replace(target, boundary + target)],
                          env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
                          capture_output=True, timeout=15)
    assert proc.returncode == 0, proc.stderr[-3000:]
