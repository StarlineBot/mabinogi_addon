"""Independent Qt expiry, repeated polling and reconstructed-position boundaries."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]/'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window

from PySide6.QtCore import QEventLoop, QTimer
from mabinogi_addon import config, feature_access
from mabinogi_addon.ui.halo_capture_section import HaloCaptureSection


def section(window, monkeypatch):
    w, app = window
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': feature_access.CREATOR_DISCORD_ID})
    s = w.boss_tab.halo_capture
    s._save_region(1229, 134, 119, 42)
    w._open_setup_feature('boss')
    w.boss_tab.pattern_tabs.setCurrentIndex(1)
    app.processEvents()
    return w, app, s


def test_countdown_expires_with_real_qt_timer_after_monitor_updates_stop(window, monkeypatch):
    _, app, s = section(window, monkeypatch)
    import mabinogi_addon.ui.halo_capture_section as module
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    s._target = (11, 22, 0, 0, 1920, 1080)
    for moment, raw in ((100, 882), (100.5, 882), (101, 881)):
        now[0] = moment
        s.set_boss_context('lenen_miir_hoehan')
        s._monitor(raw)
    assert s._countdown.isVisible() and s._countdown._timer.isActive()
    assert s._countdown._text == '다음 헤일로 00:51'
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    s._countdown._timer.timeout.connect(loop.quit)
    timeout.start(2500)
    loop.exec()
    timeout.stop()
    s._countdown._timer.timeout.disconnect(loop.quit)
    app.processEvents()
    assert not s._countdown.isVisible() and not s._countdown._timer.isActive()
    assert s._countdown._text == ''


def test_editing_polling_reuses_windows_and_timers_then_shutdown_cleans_them(window, monkeypatch):
    _, app, s = section(window, monkeypatch)
    monkeypatch.setattr(s, '_capture', lambda: None)
    s.warn_lock.click()
    s.countdown_lock.click()
    windows = set(app.topLevelWidgets())
    timers = {s._timer, s._warning._timer, s._countdown._timer}
    for _ in range(100):
        s._tick()
        app.processEvents()
        assert s._warning.isVisible() and s._countdown.isVisible()
        assert not s._warning.locked and not s._countdown.locked
    assert set(app.topLevelWidgets()) == windows
    assert {s._timer, s._warning._timer, s._countdown._timer} == timers
    s.shutdown()
    assert all(not timer.isActive() for timer in timers)
    assert not s._warning.isVisible() and not s._countdown.isVisible()


def test_saved_independent_positions_are_restored_on_new_section(window, monkeypatch):
    w, _, s = section(window, monkeypatch)
    s._warning.move(-700, 80)
    s._save_warning_position()
    s._countdown.move(-650, 150)
    s._save_countdown_position()
    before = config._read_local_config()
    replacement = HaloCaptureSection(s._watcher, s._grab, w.boss_tab)
    replacement._timer.stop()
    try:
        replacement._place_warning()
        replacement._place_countdown()
        assert (replacement._warning.x(), replacement._warning.y()) == (-700, 80)
        assert (replacement._countdown.x(), replacement._countdown.y()) == (-650, 150)
        assert replacement._warning_positioned and replacement._countdown_positioned
        assert config._read_local_config() == before
    finally:
        replacement.shutdown()
        replacement.deleteLater()
