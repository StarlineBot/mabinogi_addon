"""A stacked form needs scrolling only when its measured content overflows."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit, QWidget

from scripts.qa_creator_dialogue import app, window  # noqa: F401


def settle(app):
    for _ in range(12):
        app.processEvents()


@pytest.mark.parametrize("index", [0, 1])
def test_stacked_controls_are_accessible_with_or_without_vertical_overflow(window, app, monkeypatch, index):
    w, d, _ = window
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1600, 1100)))
    w._tracker_tabs.setCurrentIndex(index)
    w.setStyleSheet(w.styleSheet() + "\nQWidget {font-size:9px;}")
    d.refresh()
    settle(app)
    tab = (w.buff_tab, w.debuff_tab)[index]
    scroll = w._tracker_tabs.currentWidget()
    left = tab._columns.itemAt(0).widget()
    right = tab.form_panel
    original = left.minimumWidth(), right.minimumWidth(), tab.status_label.text()
    baseline = tab._columns.stacked, d._floating_footer
    try:
        left.setMinimumWidth(518)
        right.setMinimumWidth(404)
        for overflow in (False, True, False):
            tab.status_label.setText("status\n" * 80 if overflow else original[2])
            settle(app)
            assert tab._columns.stacked and not d._floating_footer
            assert scroll.widget().width() == scroll.viewport().width()
            maximum = scroll.verticalScrollBar().maximum()
            needed = tab.layout().heightForWidth(scroll.viewport().width())
            print("stacked visibility:", {"tab": index, "long_notice": overflow,
                                        "needed": needed, "viewport": scroll.viewport().height(),
                                        "scroll_maximum": maximum})
            if overflow:
                assert needed > scroll.viewport().height() and maximum > 0
            controls = [control for control in right.findChildren(QWidget)
                        if isinstance(control, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit))
                        and control.isVisible()]
            assert controls
            for control in controls:
                scroll.ensureWidgetVisible(control, 50, 50)
                settle(app)
                rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
                assert scroll.viewport().rect().contains(rect), {
                    "control": type(control).__name__, "rect": rect.getRect(),
                    "viewport": scroll.viewport().rect().getRect(), "maximum": maximum,
                }
            scroll.verticalScrollBar().setValue(0)
    finally:
        left.setMinimumWidth(original[0])
        right.setMinimumWidth(original[1])
        tab.status_label.setText(original[2])
        settle(app)
        assert (tab._columns.stacked, d._floating_footer) == baseline
