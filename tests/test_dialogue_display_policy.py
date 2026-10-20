"""Approved policy: exposed inactive windows work; opaque covers block; unknown composition permits muted text."""

import sys

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from test_navigation import window
from scripts.qa_dialogue_transparent_occlusion import native_model
from mabinogi_addon.system import dialogue_visibility as visibility


@pytest.fixture
def dialogue(window, native_model, monkeypatch):
    w, app = window
    native_model.owner = int(w.winId())
    native_model.client = (0, 0, w.width(), w.height())
    d = w.creator_dialogue
    assert d.visibility is visibility.display_available
    d.clock = lambda: 100.0
    d.session.rng.random = lambda: 0.0

    def forbidden(*args):
        pytest.fail('dialogue must not activate a window')

    gui = sys.modules['win32gui']
    for name in ('SetForegroundWindow',):
        monkeypatch.setattr(gui, name, forbidden, raising=False)
    return w, app, d


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('location', ['footer', 'settings'])
def test_default_dialogue_displays_under_confirmed_transparency_without_changing_focus(
        dialogue, automatic, location):
    w, app, d = dialogue
    if location == 'settings':
        w._tabs.setCurrentIndex(3)
        app.processEvents()
        w._tabs.widget(3).ensureWidgetVisible(w.settings_tab.creator_avatar)
        app.processEvents()
    other = None
    if automatic:
        other = QWidget()
        editor = QLineEdit(other)
        other.show()
        other.activateWindow()
        editor.setFocus()
        app.processEvents()
        assert QApplication.activeWindow() is other
    active, focus = QApplication.activeWindow(), QApplication.focusWidget()
    timers = set(d.findChildren(QTimer))
    if automatic:
        d.tick()
    else:
        QTest.mouseClick(d._anchor(), Qt.MouseButton.LeftButton)
    assert d.bubble.isVisible()
    assert d.bubble.parentWidget() is w.centralWidget()
    assert not d.bubble.isWindow()
    assert QApplication.activeWindow() is active
    if automatic:
        assert QApplication.focusWidget() is focus
    assert d.expiry.isActive() and d.deadline == 103.0
    assert len(d.session.shown) == int(automatic)
    assert set(d.findChildren(QTimer)) == timers
    if automatic:
        d.clock = lambda: 103.0
        d.tick()
        assert not d.bubble.isVisible()
        d.clock = lambda: 104.0
        d.tick()
        assert not d.bubble.isVisible() and len(d.session.shown) == 1
    if other is not None:
        other.close()


@pytest.mark.parametrize('condition', ['locked', 'desktop_error', 'offscreen', 'minimized', 'hidden'])
@pytest.mark.parametrize('automatic', [False, True])
def test_display_boundaries_still_block_without_spending_draws(
        dialogue, native_model, main_foreground, monkeypatch, condition, automatic):
    w, _, d = dialogue
    if condition == 'locked':
        monkeypatch.setattr(visibility, 'desktop_unlocked', lambda: False)
    elif condition == 'desktop_error':
        def fail():
            raise OSError('desktop unavailable')
        monkeypatch.setattr(visibility, 'desktop_unlocked', fail)
    elif condition == 'offscreen':
        native_model.origin = (4000, 0)
    elif condition == 'minimized':
        w.showMinimized()
    elif condition == 'hidden':
        w.hide()
    if automatic:
        d.tick()
    else:
        QTest.mouseClick(d.face, Qt.MouseButton.LeftButton)
    assert not d.bubble.isVisible()
    assert d.session.last_draw is None
    assert not d.session.shown


@pytest.mark.parametrize('logical,rects,client', [
    ((0, 800), [(20, 20, 48, 48)], (0, 0, 800, 800)),
    ((800, 800), [], (0, 0, 800, 800)),
    ((800, 800), [(790, 20, 48, 48)], (0, 0, 800, 800)),
    ((800, 800), [(20, 20, 0, 48)], (0, 0, 800, 800)),
    ((800, 800), [(20, 20, 48, 48)], (0, 0, 0, 0)),
])
def test_invalid_geometry_is_not_display_available(native_model, logical, rects, client):
    native_model.client = client
    detail = {}
    assert not visibility.display_available(11, rects, logical, diagnostic=detail)
    assert detail['stage'] == 'target_geometry'


@pytest.mark.parametrize('automatic', [False, True])
def test_opaque_cover_does_not_draw_or_make_sound(dialogue, native_model, automatic):
    w, app, d = dialogue
    native_model.alpha = 255
    calls = []
    d.sound = calls.append
    if automatic:
        d.tick()
    else:
        assert not d.request()
    assert not d.bubble.isVisible() and calls == []
    assert d.session.last_draw is None and not d.session.shown
    native_model.alpha = 0
    d.tick()
    assert d.bubble.isVisible() and len(calls) == 1
    assert len(d.session.shown) == 1
    player = d._notifier
    native_model.alpha = 255
    d.clock = lambda: 101.0
    d.tick()
    assert not d.bubble.isVisible()
    assert len(d.session.shown) == 1 and len(calls) == 1
    assert d._notifier is player


def test_cover_stops_only_owned_sound_on_the_existing_tick(dialogue, native_model):
    w, app, d = dialogue
    d.tick()
    player = d._notifier
    assert player._player._playing
    native_model.alpha = 255
    d.clock = lambda: 101.0
    d.tick()
    assert not d.bubble.isVisible() and not player._player._playing
    assert len(d.session.shown) == 1
    native_model.alpha = 0
    d.clock = lambda: 102.0
    d.tick()
    assert not d.bubble.isVisible() and not player._player._playing
    assert len(d.session.shown) == 1


def test_cover_elsewhere_does_not_veto_target_and_unknown_is_diagnosed(dialogue, native_model, monkeypatch):
    w, app, d = dialogue
    native_model.alpha = 255
    native_model.cover = (0, 0, 10, 10)
    assert d.request()
    detail = {}
    native_model.cover = (0, 0, 1920, 1080)
    monkeypatch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', lambda *a: (_ for _ in ()).throw(OSError()))
    assert visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (w.width(), w.height()), diagnostic=detail)
    assert detail['visibility'] == 'unknown'


def test_diagnostic_distinguishes_known_opaque_cover_from_unknown(dialogue, native_model, monkeypatch):
    gui = sys.modules['win32gui']
    monkeypatch.setattr(gui, 'CreateRectRgnIndirect', lambda rect: object(), raising=False)
    monkeypatch.setattr(gui, 'GetWindowRgn', lambda *args: 0, raising=False)
    monkeypatch.setattr(gui, 'DeleteObject', lambda *args: None, raising=False)
    native_model.alpha = 255
    detail = {}
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'occluded'
    monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *args: (_ for _ in ()).throw(OSError()))
    assert visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'unknown'
    monkeypatch.setattr(gui, 'GetWindowLong', lambda *args: (_ for _ in ()).throw(OSError()))
    assert visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'unknown'


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('evidence', ['flags-zero', 'alpha-error', 'region-error', 'color-key', 'no-redirection'])
def test_unknown_composition_attempts_text_without_sound_or_focus_change(dialogue, native_model, monkeypatch, automatic, evidence):
    w, app, d = dialogue
    gui = sys.modules['win32gui']
    native_model.alpha = 255
    if evidence == 'flags-zero':
        monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    elif evidence == 'alpha-error':
        monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (_ for _ in ()).throw(OSError()))
    elif evidence == 'region-error':
        monkeypatch.setattr(gui, 'GetWindowRgn', lambda *a: (_ for _ in ()).throw(OSError()))
    elif evidence == 'color-key':
        monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (0, 255, 3))
    else:
        monkeypatch.setattr(gui, 'GetWindowLong', lambda *a: 0x200000)
    calls = []
    d.sound = calls.append
    active, focus = QApplication.activeWindow(), QApplication.focusWidget()
    timers = set(d.findChildren(QTimer))
    if automatic:
        d.tick()
    else:
        assert d.request()
    assert d.bubble.isVisible() and calls == []
    assert d.deadline == 103.0 and d.expiry.isActive()
    assert len(d.session.shown) == int(automatic)
    assert (d.session.last_draw is not None) is automatic
    assert QApplication.activeWindow() is active and QApplication.focusWidget() is focus
    assert set(d.findChildren(QTimer)) == timers
    d.session.rng.random = lambda: 1.0  # A fresh automatic chance after manual expiry may fail.
    d.clock = lambda: 103.0
    d.tick()
    assert not d.bubble.isVisible() and calls == []
    assert len(d.session.shown) == int(automatic)


def test_unknown_composition_stops_playback_without_hiding_or_replaying_text(dialogue, native_model, monkeypatch):
    w, app, d = dialogue
    d.tick()
    player = d._notifier
    assert player._player._playing
    text = d.session.last_text
    with monkeypatch.context() as patch:
        patch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
        d.clock = lambda: 101.0
        d.tick()
        assert d.bubble.isVisible() and not player._player._playing
        assert d.session.last_text == text and len(d.session.shown) == 1
    d.clock = lambda: 102.0
    d.tick()
    assert d.bubble.isVisible() and not player._player._playing
    assert d.session.last_text == text and len(d.session.shown) == 1
    assert d.request()
    assert player._player._playing  # Only a new explicit dialogue can play again.
    assert len(d.session.shown) == 1


@pytest.mark.parametrize('order', [(22, 33), (33, 22)])
def test_unknown_window_does_not_bypass_known_opaque_window_below_it(native_model, monkeypatch, order):
    gui = sys.modules['win32gui']
    monkeypatch.setattr(gui, 'GetWindowLong', lambda hwnd, *a: 0x80000 if hwnd == 22 else 0)
    monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    monkeypatch.setattr(gui, 'EnumWindows', lambda visit, arg: [visit(hwnd, arg) for hwnd in (*order, native_model.owner)])
    detail = {}
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'occluded' and detail['other_hwnd'] == 33


@pytest.mark.parametrize('failure', ['owner-missing', 'enumeration-error', 'cloak-error'])
def test_unknown_cover_does_not_bypass_failed_owner_or_native_boundaries(native_model, monkeypatch, failure):
    gui = sys.modules['win32gui']
    monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    def enumerate_windows(visit, arg):
        visit(22, arg)
        if failure == 'enumeration-error':
            raise OSError('enumeration failed')
        if failure != 'owner-missing':
            visit(native_model.owner, arg)
    monkeypatch.setattr(gui, 'EnumWindows', enumerate_windows)
    if failure == 'cloak-error':
        import ctypes
        old = ctypes.windll.dwmapi.DwmGetWindowAttribute
        monkeypatch.setattr(ctypes.windll.dwmapi, 'DwmGetWindowAttribute', lambda hwnd, key, ptr, size: -1 if key == 14 else old(hwnd, key, ptr, size))
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800))


@pytest.fixture
def main_foreground(dialogue, monkeypatch):
    import os
    from types import SimpleNamespace
    from mabinogi_addon.system import window_watcher
    w, app, d = dialogue
    state = SimpleNamespace(hwnd=int(w.winId()))
    gui = sys.modules['win32gui']
    monkeypatch.setattr(window_watcher, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(gui, 'GetForegroundWindow', lambda: state.hwnd, raising=False)
    monkeypatch.setattr(gui, 'IsWindow', lambda hwnd: bool(hwnd), raising=False)
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, os.getpid())))
    return state


@pytest.mark.parametrize('automatic', [False, True])
@pytest.mark.parametrize('cover', ['clear', 'unknown', 'opaque'])
@pytest.mark.parametrize('foreground', ['main', 'overlay', 'unavailable'])
def test_sound_uses_cover_and_exact_main_foreground(dialogue, native_model, main_foreground, monkeypatch, automatic, cover, foreground):
    w, app, d = dialogue
    gui = sys.modules['win32gui']
    if cover == 'unknown':
        monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    else:
        native_model.alpha = 255 if cover == 'opaque' else 0
    main_foreground.hwnd = int(w.winId()) if foreground == 'main' else 33 if foreground == 'overlay' else 0
    calls = []
    d.sound = calls.append
    focus = QApplication.focusWidget()
    if automatic:
        d.tick()
    else:
        assert d.request() is (cover != 'opaque')
    assert d.bubble.isVisible() is (cover != 'opaque')
    assert len(calls) == int(cover == 'clear' or (cover == 'unknown' and foreground == 'main'))
    assert len(d.session.shown) == int(automatic and cover != 'opaque')
    assert QApplication.focusWidget() is focus


def test_unknown_sound_stops_on_main_deactivation_and_does_not_resume(dialogue, native_model, main_foreground, monkeypatch):
    w, app, d = dialogue
    monkeypatch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    d.tick()
    player = d._notifier
    assert player._player._playing and player._audio._volume == 0.5
    main_foreground.hwnd = 33
    d.clock = lambda: 101.0
    d.tick()
    assert d.bubble.isVisible() and not player._player._playing
    main_foreground.hwnd = int(w.winId())
    d.clock = lambda: 102.0
    d.tick()
    assert not player._player._playing and len(d.session.shown) == 1
    assert d.request() and player._player._playing
    assert len(d.session.shown) == 1
    w.settings_tab.dialogue_sound_enabled.setChecked(False)
    assert d.request() and not player._player._playing
    w.settings_tab.dialogue_sound_enabled.setChecked(True)
    assert not player._player._playing
    for timestamp in range(103, 221):
        d.clock = lambda t=timestamp: float(t)
        d.tick()
    assert player._player._playing and len(d.session.shown) == 2


@pytest.mark.parametrize('last_main', [False, True])
def test_final_foreground_read_controls_sound_before_display(dialogue, main_foreground, monkeypatch, last_main):
    w, app, d = dialogue
    gui = sys.modules['win32gui']
    reads = []
    def alpha(*args):
        reads.append(1)
        main = last_main if len(reads) > 1 else not last_main
        main_foreground.hwnd = int(w.winId()) if main else 33
        return 0, 0, 0
    monkeypatch.setattr(gui, 'GetLayeredWindowAttributes', alpha)
    calls = []
    d.sound = calls.append
    assert d.request() and len(reads) == 2
    assert len(calls) == int(last_main)


def test_request_diagnostics_distinguish_muting_and_audio_submission_without_poll_logs(dialogue, main_foreground, monkeypatch, caplog):
    import logging
    w, app, d = dialogue
    monkeypatch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', lambda *a: (0, 0, 0))
    caplog.set_level(logging.INFO, logger='mabinogi_addon.ui.creator_dialogue')
    main_foreground.hwnd = 33
    for _ in range(50):
        assert d._eligible()
    assert not caplog.records
    assert d.request()
    assert 'visibility=unknown' in caplog.text and 'result=muted' in caplog.text
    assert 'foreground=other' in caplog.text
    caplog.clear()
    main_foreground.hwnd = int(w.winId())
    assert d.request()
    assert 'foreground=main' in caplog.text and 'audio_stage=submitted' in caplog.text
    assert 'result=requested' in caplog.text
