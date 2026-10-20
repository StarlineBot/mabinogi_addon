"""Approved policy: exposed inactive windows work; covered/unknown targets stay silent."""

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
        dialogue, native_model, monkeypatch, condition, automatic):
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
@pytest.mark.parametrize('condition', ['opaque', 'unknown'])
def test_cover_and_unknown_composition_do_not_draw_or_make_sound(dialogue, native_model, monkeypatch, automatic, condition):
    w, app, d = dialogue
    native_model.alpha = 255
    if condition == 'unknown':
        def unknown(*args):
            raise OSError('per-pixel composition has no global alpha')
        monkeypatch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', unknown)
    calls = []
    d.sound = calls.append
    if automatic:
        d.tick()
    else:
        assert not d.request()
    assert not d.bubble.isVisible() and calls == []
    assert d.session.last_draw is None and not d.session.shown
    native_model.alpha = 0
    if condition == 'unknown':
        monkeypatch.setattr(sys.modules['win32gui'], 'GetLayeredWindowAttributes', lambda *a: (0, native_model.alpha, 2))
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
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (w.width(), w.height()), diagnostic=detail)
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
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'unknown'
    monkeypatch.setattr(gui, 'GetWindowLong', lambda *args: (_ for _ in ()).throw(OSError()))
    assert not visibility.display_available(native_model.owner, [(20, 20, 48, 48)], (800, 800), diagnostic=detail)
    assert detail['visibility'] == 'unknown'
