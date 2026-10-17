"""Collect every combat page's geometry before reporting any width failure."""

from pathlib import PureWindowsPath
import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QWidget
from test_navigation import window

pytestmark = pytest.mark.usefixtures('tuarim_width_diagnostics')


@pytest.mark.parametrize('area',[(0,0,900,1000),(0,0,800,600),(-1600,120,900,700)])
def test_all_pages_and_controls_large_font(window,monkeypatch,area):
    w,app = window
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen,'availableGeometry',lambda self:QRect(*area))
    monkeypatch.setattr(screen,'geometry',lambda self:QRect(*area))
    path = PureWindowsPath('C:/Users/runneradmin/AppData/Local/Temp/pytest-of-runneradmin/pytest-0/test_seeded_navigation_and_tou3/app/data')/('긴경로'*35)/'수집 폴더'
    for tab in (w.tuarim_tab,w.boss_tab,w.stat_bars_tab):
        tab._shot_dir = path
        tab._update_collect_label()
    for widget in w.findChildren(QWidget):
        font = widget.font(); font.setPixelSize(20); widget.setFont(font)
    failures = []
    for key,scroll in w._combat_pages.items():
        w._open_setup_feature(key)
        for _ in range(10): app.processEvents()
        extent = scroll.horizontalScrollBar().maximum()
        if extent:
            failures.append((key,'horizontal_range',extent,scroll.viewport().width(),scroll.widget().minimumSizeHint().width()))
        for widget in scroll.widget().findChildren(QAbstractButton):
            if not widget.isVisible(): continue
            scroll.ensureWidgetVisible(widget)
            for _ in range(4): app.processEvents()
            rect = QRect(widget.mapTo(scroll.viewport(),QPoint()),widget.size())
            if not scroll.viewport().rect().contains(rect):
                failures.append((key,widget.text(),str(rect),str(scroll.viewport().rect())))
    assert not failures, failures
