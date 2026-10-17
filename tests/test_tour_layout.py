"""Settled layout and cancelled geometry updates must agree with the highlight."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from shiboken6 import isValid

from scripts.qa_navigation_tour_layout import test_seeded_navigation_and_tour
from test_navigation import window

pytestmark = pytest.mark.usefixtures("tuarim_width_diagnostics")


def settle(app):
    loop = QEventLoop()
    QTimer.singleShot(60, loop.quit)
    loop.exec()
    for _ in range(8):
        app.processEvents()


def test_scroll_updates_card_without_host_move_or_resize(window):
    w, app = window
    w._run_tour()
    tour = w._tour
    tour._i = 5
    tour._show_step()
    settle(app)
    old_host = w.geometry()
    scroll = w._tabs.widget(3)
    target = tour._steps[5].target
    old = tour._target_rect()
    value = scroll.verticalScrollBar().value()
    scroll.verticalScrollBar().setValue(value + 35)
    settle(app)
    assert w.geometry() == old_host
    rect = tour._target_rect()
    assert rect is not None and rect != old
    assert not rect.intersects(tour._card.geometry())
    assert target in tour._watched
    assert scroll.widget() in tour._watched
    assert not tour._layout_timer.isActive()


def test_event_burst_is_coalesced_and_idle_does_not_poll(window, monkeypatch):
    w, app = window
    w._run_tour()
    tour = w._tour
    settle(app)
    calls = []
    original = tour._place_card
    def count():
        calls.append(1)
        original()
    monkeypatch.setattr(tour, '_place_card', count)
    for _ in range(100):
        QCoreApplication.sendEvent(tour._steps[tour._i].target, QEvent(QEvent.Type.LayoutRequest))
    settle(app)
    assert len(calls) == 1
    assert not tour._layout_timer.isActive()
    settle(app)
    assert len(calls) == 1


def test_step_change_detaches_old_targets_and_uses_current_target(window):
    w, app = window
    w._run_tour()
    tour = w._tour
    tour._i = 5
    tour._show_step()
    old_target = tour._steps[5].target
    assert tour._layout_timer.isActive()
    tour._i = 3
    tour._show_step()
    settle(app)
    assert old_target not in tour._watched
    assert w.settings_tab not in tour._watched
    assert w.buff_tab.lock_btn in tour._watched
    assert not tour._target_rect().intersects(tour._card.geometry())
    assert not tour._layout_timer.isActive()


def test_hide_cancels_pending_refresh_and_reopen_has_no_old_callback(window, monkeypatch):
    w, app = window
    w._run_tour()
    old = w._tour
    old._i = 5
    old._show_step()
    assert old._layout_timer.isActive()
    calls = []
    monkeypatch.setattr(old, '_place_card', lambda: calls.append('old'))
    w.hide()
    assert old._dismissed and not old._watched
    assert not old._layout_timer.isActive()
    w.show()
    w._run_tour()
    new = w._tour
    settle(app)
    assert not calls
    assert new is not old and new.isVisible()
    assert not new._layout_timer.isActive()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not isValid(old)


def test_close_cancels_pending_refresh(window):
    w, app = window
    w._run_tour()
    tour = w._tour
    tour._i = 5
    tour._show_step()
    assert tour._layout_timer.isActive()
    w._force_quit = True
    w.close()
    assert tour._dismissed and not tour._watched
    assert not tour._layout_timer.isActive()
    settle(app)
    assert not w.isVisible() and w._tour is None
