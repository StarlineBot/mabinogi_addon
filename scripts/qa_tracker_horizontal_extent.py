"""Measure actual horizontal control bounds, not only scrollbar policy."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit

from scripts.qa_creator_dialogue import app, window  # noqa: F401


@pytest.mark.parametrize("family", ["DejaVu Sans", "Noto Sans CJK KR", "Noto Serif CJK KR"])
def test_long_notice_keeps_right_form_controls_within_viewport(window, app, monkeypatch, family):
    w, d, _ = window
    w.setStyleSheet(w.styleSheet() + '\nQWidget {font-size:18px; font-family:"%s";}' % family)
    w.buff_tab.status_label.setText("status\n" * 80)
    monkeypatch.setattr(w, "screen", lambda: SimpleNamespace(
        availableGeometry=lambda: QRect(0, 0, 1100, 730)))
    d.refresh()
    for _ in range(10):
        app.processEvents()
    scroll = w._tracker_tabs.currentWidget()
    viewport = scroll.viewport()
    clipped = []
    controls = [control for control in w.buff_tab.form_panel.findChildren(object)
                if isinstance(control, (QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit))]
    for control in controls:
        if not control.isVisible():
            continue
        point = control.mapTo(viewport, QPoint())
        if point.x() < 0 or point.x() + control.width() > viewport.width():
            clipped.append({"type": type(control).__name__, "x": point.x(), "width": control.width()})
    state = {"family": family, "inner": scroll.widget().width(), "viewport": viewport.width(),
             "range": scroll.horizontalScrollBar().maximum(), "clipped": clipped}
    print("horizontal bounds:", state)
    assert not clipped, state
