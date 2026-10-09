"""토스트 클릭 동작(on_click) 테스트."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.toast import Toast


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _press(widget) -> None:
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5, 5),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(ev)


def test_click_runs_callback():
    _app()
    hits = []
    t = Toast("제목", "본문", on_click=lambda: hits.append(1))
    t.show_toast_window()
    assert t.cursor().shape() == Qt.CursorShape.PointingHandCursor  # 클릭 가능 표시
    _press(t)
    assert hits == [1]  # 콜백 1회 실행


def test_click_without_callback_is_safe():
    _app()
    t = Toast("제목", "본문")  # on_click 없음
    t.show_toast_window()
    _press(t)  # 예외 없이 닫혀야 함


def test_callback_exception_does_not_crash():
    _app()

    def _boom():
        raise RuntimeError("boom")

    t = Toast("제목", "본문", on_click=_boom)
    t.show_toast_window()
    _press(t)  # 콜백이 터져도 앱이 죽지 않고 닫힘
