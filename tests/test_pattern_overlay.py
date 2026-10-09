"""패턴 경고 오버레이 스모크(구성·표시가 예외 없이 되는지)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_show_message_renders():
    _app()
    from mabinogi_addon.ui.pattern_overlay import PatternWarningOverlay

    ov = PatternWarningOverlay()
    ov.resize(800, 450)
    ov._text = "고목의 페타크 85% 진입 준비"
    pm = QPixmap(800, 450)
    pm.fill()
    ov.render(pm)  # paintEvent 예외 없이 동작
    assert ov.testAttribute(
        __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.WidgetAttribute.WA_TransparentForMouseEvents
    )
