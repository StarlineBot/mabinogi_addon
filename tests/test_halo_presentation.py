"""Halo presentation regressions, including independent QA reproductions."""

import pytest
from PySide6.QtWidgets import QLabel

from mabinogi_addon import config, feature_access
import mabinogi_addon.ui.halo_capture_section as module
from test_navigation import window


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


@pytest.mark.parametrize('overlay_name,button_name', [('_warning','warn_lock'), ('_countdown','countdown_lock')])
def test_warning_edit_sample_survives_normal_tick_without_boss(window, monkeypatch, overlay_name, button_name):
    _, app, s = creator_section(window, monkeypatch)
    overlay = getattr(s, overlay_name)
    getattr(s, button_name).click()
    assert not overlay.locked and overlay.isVisible()
    monkeypatch.setattr(s, '_capture', lambda: None)
    for _ in range(4):
        s._tick()
        app.processEvents()
        assert not overlay.locked and overlay.isVisible()
    assert '헤일로' in overlay._text and '페타크' not in overlay._text
    s.set_boss_context('lenen_miir')
    assert overlay.isVisible()


def sync_section(window, monkeypatch):
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
    return w, app, s, now


def test_synced_countdown_remains_visible_outside_settings(window, monkeypatch):
    w, app, s, now = sync_section(window, monkeypatch)
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
    assert any('헤일로' in text and '51' in text for _, text in visible), visible
    assert s._countdown.isVisible() and s._countdown.locked
    now[0] = 102
    s.set_boss_context('lenen_miir_hoehan')
    s._monitor(880)
    assert s._countdown._text == '다음 헤일로 00:50'
    s.set_boss_context(None)
    s._monitor(None)
    assert not s._countdown.isVisible()
    assert not s._countdown._timer.isActive()


@pytest.mark.parametrize('stop_reason', ['access', 'clear', 'shutdown'])
def test_editing_overlays_are_cleaned_on_lifecycle_boundary(window, monkeypatch, stop_reason):
    _, _, s = creator_section(window, monkeypatch)
    s.warn_lock.click()
    s.countdown_lock.click()
    assert s._warning.isVisible() and s._countdown.isVisible()
    if stop_reason == 'access':
        monkeypatch.setattr(config, 'load_discord_user', lambda: None)
        s._tick()
    elif stop_reason == 'clear':
        s._persist(None)
    else:
        s.shutdown()
    for overlay in (s._warning, s._countdown):
        assert not overlay.isVisible() and not overlay._timer.isActive()


def test_countdown_position_is_independent_and_preserves_settings(window, monkeypatch):
    _, _, s = creator_section(window, monkeypatch)
    before = config._read_local_config()
    s._warning.move(30,40)
    s._save_warning_position()
    s._countdown.move(130,140)
    s._save_countdown_position()
    after = config._read_local_config()
    assert after['haloTimer']['warnPos'] == dict(x=30,y=40)
    assert after['haloTimer']['countdownPos'] == dict(x=130,y=140)
    assert {k:v for k,v in after.items() if k != 'haloTimer'} == {k:v for k,v in before.items() if k != 'haloTimer'}
    s._place_warning()
    s._place_countdown()
    assert (s._warning.x(),s._warning.y()) == (30,40)
    assert (s._countdown.x(),s._countdown.y()) == (130,140)
    assert s._warning_positioned
    assert s._countdown_positioned
    s.countdown_lock.click()
    assert not s._countdown.locked and s._warning.locked
