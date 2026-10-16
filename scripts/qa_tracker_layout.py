"""Independent input/transition probes for the expanded tracker layout."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from scripts.qa_creator_dialogue import app, window  # noqa: F401


def settle(app):
    for _ in range(8):
        app.processEvents()


@pytest.fixture
def expanded(window, app, monkeypatch):
    w, d, now = window
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
    d.refresh()
    settle(app)
    assert d._floating_footer
    return w, d, now


@pytest.mark.parametrize("tab_index", [0, 1])
def test_lower_list_mouse_wheel_and_reorder_are_not_intercepted(expanded, app, tab_index):
    w, d, _ = expanded
    w._tracker_tabs.setCurrentIndex(tab_index)
    settle(app)
    tab = w.buff_tab if tab_index == 0 else w.debuff_tab
    items = tab.buff_list if tab_index == 0 else tab.debuff_list
    d.dismiss()
    viewport = items.viewport()
    point = QPoint(viewport.width() // 2, viewport.height() - 20)
    target = items.indexAt(point)
    assert target.isValid() and target.row() > 0
    central_point = viewport.mapTo(w.centralWidget(), point)
    hit = w.centralWidget().childAt(central_point)
    assert hit is viewport or viewport.isAncestorOf(hit)
    assert not d.footer.isAncestorOf(hit)
    QTest.mouseClick(viewport, Qt.MouseButton.LeftButton, pos=point)
    assert items.currentRow() == target.row()
    selected = items.currentItem().text()
    up = next(b for b in tab.findChildren(QPushButton) if b.text() == "\u25b2")
    down = next(b for b in tab.findChildren(QPushButton) if b.text() == "\u25bc")
    original = items.currentRow()
    QTest.mouseClick(up, Qt.MouseButton.LeftButton)
    assert items.currentRow() == original - 1 and items.currentItem().text() == selected
    QTest.mouseClick(down, Qt.MouseButton.LeftButton)
    assert items.currentRow() == original and items.currentItem().text() == selected
    bar = items.verticalScrollBar()
    bar.setValue(0)
    assert bar.maximum() > 0
    wheel = QWheelEvent(QPointF(point), QPointF(viewport.mapToGlobal(point)),
                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
    QApplication.sendEvent(viewport, wheel)
    assert bar.value() > 0


def test_bubble_close_does_not_click_an_underlying_button(expanded, app):
    w, d, _ = expanded
    assert d.request()
    settle(app)
    assert d.bubble.isVisible()
    calls = []
    button = QPushButton(w.centralWidget())
    button.setGeometry(d.bubble.geometry())
    button.clicked.connect(lambda: calls.append(True))
    button.show()
    d.bubble.raise_()
    QTest.mouseClick(d.bubble, Qt.MouseButton.LeftButton)
    assert not d.bubble.isVisible() and not calls


class LayoutEvents(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.LayoutRequest:
            self.count += 1
        return False


def test_resize_notice_mode_switches_settle_without_accumulation(expanded, app, monkeypatch):
    w, d, _ = expanded
    original_notice = w.buff_tab.status_label.text()
    # Compare repeated transitions after QLabel has delivered both layout states.
    w.buff_tab.status_label.setText("status\n" * 35)
    settle(app)
    w.buff_tab.status_label.setText(original_notice)
    settle(app)
    baseline = w.buff_tab.buff_list.height()
    rows = (w.buff_tab.buff_list.currentRow(), w.debuff_tab.debuff_list.currentRow())
    timers = len(d.findChildren(QTimer))
    observer = LayoutEvents()
    for panel in d._tracker_panels:
        panel.installEventFilter(observer)
    try:
        for index in range(24):
            area_height = 730 if index % 2 else 1100
            monkeypatch.setattr(w, "screen", lambda h=area_height: SimpleNamespace(
                availableGeometry=lambda: QRect(0, 0, 1600, h)))
            w._tracker_tabs.setCurrentIndex(index % 2)
            w.debuff_tab.method_combo.setCurrentIndex(index % 3)
            w.buff_tab.status_label.setText("status\n" * (35 if index % 4 == 1 else 0))
            d.refresh()
            settle(app)
            assert w.height() <= area_height - 32
            layout = w.centralWidget().layout()
            assert sum(layout.itemAt(i).widget() is d.footer for i in range(layout.count())) <= 1
            assert len(d.findChildren(QTimer)) == timers == 3
            settled = observer.count
            settle(app)
            assert observer.count == settled
        w.buff_tab.status_label.setText(original_notice)
        monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(
            availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
        w._tracker_tabs.setCurrentIndex(0)
        d.refresh()
        settle(app)
        assert d._floating_footer and w.buff_tab.buff_list.height() == baseline
        assert (w.buff_tab.buff_list.currentRow(), w.debuff_tab.debuff_list.currentRow()) == rows
    finally:
        for panel in d._tracker_panels:
            panel.removeEventFilter(observer)


def test_page_switch_requests_work_after_real_layout_delivery(expanded, app):
    w, d, _ = expanded
    rejected = []
    for index in range(120):
        w._tabs.setCurrentIndex(index % 3)
        if not d.request():
            rejected.append({"iteration": index, "page": index % 3,
                             "central": w.centralWidget().size().toTuple(),
                             "footer": d.footer.geometry().getRect(),
                             "bubble": d.bubble.geometry().getRect()})
        settle(app)
        assert d.request(), {"iteration": index, "rejected_before_layout": rejected[-1:]}
        d.dismiss()
    print("requests rejected before pending layout delivery:", rejected[:4], "total:", len(rejected))


@pytest.mark.parametrize("font_pixels", [9, 13, 18])
def test_small_area_decision_uses_measured_content_height(expanded, app, monkeypatch, font_pixels):
    w, d, _ = expanded
    w.setStyleSheet(w.styleSheet() + "\nQWidget {font-size: %dpx;}" % font_pixels)
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1100, 730)))
    d.refresh()
    settle(app)
    scroll = w._tracker_tabs.currentWidget()
    print("small area:", {"font_pixels": font_pixels, "floating": d._floating_footer,
                          "window_height": w.height(), "viewport_height": scroll.viewport().height(),
                          "scroll_maximum": scroll.verticalScrollBar().maximum(),
                          "footer": d.footer.geometry().getRect()})
    assert w.height() <= 698
    assert w.rect().contains(d.face.mapTo(w, d.face.rect().bottomRight()))
    if d._floating_footer:
        assert scroll.verticalScrollBar().maximum() == 0
        for index in range(w.buff_tab.form_panel.layout().count()):
            widget = w.buff_tab.form_panel.layout().itemAt(index).widget()
            if widget is not None and widget.isVisible():
                rect = QRect(widget.mapTo(w.centralWidget(), QPoint()), widget.size())
                assert not rect.intersects(d.footer.geometry()), rect.getRect()
    else:
        assert w._pages.geometry().bottom() < d.footer.y()
