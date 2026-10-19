import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QVBoxLayout, QWidget

from test_support.scroll_visibility import assert_control_reachable


def test_all_ancestor_viewports_are_scrolled_and_checked(monkeypatch):
    app = QApplication.instance() or QApplication([])
    outer = QScrollArea()
    outer.resize(300,180)
    outer.setWidgetResizable(True)
    middle = QWidget()
    layout = QVBoxLayout(middle)
    inner = QScrollArea()
    inner.setFixedSize(240,400)
    content = QWidget()
    content.resize(220,1200)
    button = QPushButton('target',content)
    button.setGeometry(20,1100,120,30)
    inner.setWidget(content)
    layout.addWidget(inner)
    outer.setWidget(middle)
    outer.show()
    try:
        for _ in range(8): app.processEvents()
        assert_control_reachable(button,app,'nested')
        assert inner.verticalScrollBar().value() > 0
        assert outer.verticalScrollBar().value() > 0
        outer.verticalScrollBar().setValue(0)
        rect = QRect(button.mapTo(outer.viewport(),QPoint()),button.size())
        assert not outer.viewport().rect().contains(rect)
        monkeypatch.setattr(outer,'ensureWidgetVisible',lambda *args:None)
        with pytest.raises(AssertionError):
            assert_control_reachable(button,app,'outer clipped')
    finally:
        outer.close()
        outer.deleteLater()
        app.processEvents()
