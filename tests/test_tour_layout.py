"""Settled layout and cancelled geometry updates must agree with the highlight."""

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
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


@pytest.mark.parametrize('from_guide', [False, True])
@pytest.mark.parametrize('font_profile', ['default', 'korean', 'large'])
def test_tour_text_and_buttons_fit_through_real_forward_and_back_clicks(
        window, from_guide, font_profile):
    w, app = window
    w._run_tour(from_guide=from_guide)
    tour = w._tour
    original_font, original_style = QFont(tour.font()), tour.styleSheet()
    if font_profile != 'default':
        font = QFont(tour.font())
        font.setFamily('Noto Sans CJK KR')
        if font_profile == 'large':
            font.setPixelSize(20)
            tour.setStyleSheet(tour.styleSheet() + '\n'
                              '#tourTitle { font-size:24px; } '
                              '#tourBody { font-size:20px; } '
                              '#tourStep { font-size:18px; }')
        tour.setFont(font)
    count = len(tour._steps)
    traversal = list(range(count)) + list(reversed(range(count - 1)))
    for position, index in enumerate(traversal):
        settle(app)
        assert tour._i == index
        assert tour._step_lbl.text() == f'{index + 1} / {count}'
        for label in (tour._title, tour._body):
            assert label.heightForWidth(label.contentsRect().width()) <= label.contentsRect().height()
        label = tour._step_lbl
        assert label.fontMetrics().horizontalAdvance(label.text()) <= label.contentsRect().width()
        assert tour.rect().contains(tour._card.geometry())
        target = tour._target_rect()
        assert target is None or not target.intersects(tour._card.geometry())
        for button in (tour._prev, tour._skip, tour._next):
            if button.isVisible():
                assert button.width() >= button.sizeHint().width()
                assert button.height() >= button.sizeHint().height()
                point = button.mapTo(tour, button.rect().center())
                assert tour.childAt(point) is button
        assert not tour._layout_timer.isActive()
        if position < len(traversal) - 1:
            button = tour._next if position < count - 1 else tour._prev
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    if font_profile == 'large':
        large_height = tour._card.height()
        tour.setStyleSheet(original_style)
        tour.setFont(original_font)
        settle(app)
        assert tour._card.height() < large_height
        for label in (tour._title, tour._body):
            assert label.heightForWidth(label.contentsRect().width()) <= label.contentsRect().height()


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
