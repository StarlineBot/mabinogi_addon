"""Independent reproductions for halo editing and in-game countdown requirements."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests'))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window

from PySide6.QtWidgets import QLabel
from mabinogi_addon import config, feature_access
import mabinogi_addon.ui.halo_capture_section as module


def creator_section(window, monkeypatch):
    w, app = window
    monkeypatch.setattr(config, 'load_discord_user', lambda: {'id': feature_access.CREATOR_DISCORD_ID})
    s = w.boss_tab.halo_capture
    s._save_region(1229, 134, 119, 42)
    s._refresh()
    w._open_setup_feature('boss')
    w.boss_tab.pattern_tabs.setCurrentIndex(1)
    app.processEvents()
    return w, app, s


def test_warning_edit_sample_survives_normal_tick_without_boss(window, monkeypatch):
    _, app, s = creator_section(window, monkeypatch)
    s.warn_lock.click()
    assert not s._warning.locked and s._warning.isVisible()
    monkeypatch.setattr(s, '_capture', lambda: None)
    s._tick()
    app.processEvents()
    assert not s._warning.locked
    assert s._warning.isVisible(), 'normal polling hides the unlocked halo position-edit sample'


def test_synced_countdown_remains_visible_outside_settings(window, monkeypatch):
    w, app, s = creator_section(window, monkeypatch)
    monkeypatch.setattr(s._watcher, 'is_game_active', lambda: True)
    monkeypatch.setattr(s._watcher, 'is_self_active', lambda: False)
    now = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    s._target = (11, 22, 0, 0, 1920, 1080)
    for moment, raw in ((100, 882), (100.5, 882), (101, 881)):
        now[0] = moment
        s.set_boss_context('lenen_miir_hoehan')
        s._monitor(raw)
    assert s._clock.anchor == (881, 101)
    assert '00:51' in s.state.text()
    assert not s._warning.isVisible()
    w.hide()
    app.processEvents()
    assert not s.state.isVisible()
    visible = []
    for widget in app.topLevelWidgets():
        if widget is w or not widget.isVisible():
            continue
        text = str(getattr(widget, '_text', ''))
        text += ' '.join(label.text() for label in widget.findChildren(QLabel))
        visible.append((type(widget).__name__, text))
    assert any('헤일로' in text and '51' in text for _, text in visible), (
        'synchronized countdown is only in the hidden settings label; visible windows: '+repr(visible))
