"""Actual settings layout with sample values and isolated external boundaries."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QWidget

from test_navigation import window
from test_setup import app, settings


@pytest.mark.parametrize("large", [False, True])
def test_registered_commands_fit_the_actual_window(app, settings, window, large):
    w, _ = window
    if large:
        for widget in w.findChildren(QWidget):
            font = widget.font()
            font.setPixelSize(20)
            widget.setFont(font)
    output = Path('/tmp/region-registration-implemented')
    output.mkdir(exist_ok=True)
    for key in ('buff', 'debuff', 'boss', 'stat_bars', 'dorcha', 'skillbar'):
        w._open_setup_feature(key)
        scroll = w._combat_pages[key]
        for _ in range(4):
            app.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        buttons = [button for button in scroll.widget().findChildren(QAbstractButton)
                   if button.text() == '지정 해제' and button.isVisible()]
        assert buttons
        for button in buttons:
            scroll.ensureWidgetVisible(button)
            app.processEvents()
            rect = QRect(button.mapTo(scroll.viewport(), QPoint()), button.size())
            assert scroll.viewport().rect().contains(rect)
        scroll.verticalScrollBar().setValue(0)
        app.processEvents()
        assert w.grab().save(str(output / (key + ('-large' if large else '') + '.png')))
    w.setup_guide.stage = 1
    w._pages.setCurrentWidget(w.setup_guide)
    w.setup_guide.refresh()
    app.processEvents()
    assert w.grab().save(str(output / ('guide-large.png' if large else 'guide.png')))
