"""오버레이 격자 맞춤(스냅) 공용 유틸.

설정(general.gridSnap)이 켜져 있으면 모든 오버레이(버프·디버프·메모·미러)를 드래그로
옮길 때 좌표를 16px 격자에 맞춰 이동한다. 격자 선은 **드래그하는 동안에만** 전체 화면에
표시(클릭 통과)되고, 떼면 사라진다.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

GRID_SIZE = 16  # 격자 한 칸(px) ≈ 버프 아이콘 한 칸


def enabled() -> bool:
    from .. import config

    return config.load_general_flag("gridSnap", False)


def snap(point: QPoint, size: int = GRID_SIZE) -> QPoint:
    """좌표를 가장 가까운 격자 배수로 반올림."""
    return QPoint(round(point.x() / size) * size, round(point.y() / size) * size)


class _GridGuide(QWidget):
    """드래그 중에만 뜨는 전체 화면 격자 선(표시 전용, 클릭 통과)."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def show_guide(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(QColor(0, 209, 167, 70), 1))
        w, h = self.width(), self.height()
        for x in range(0, w, GRID_SIZE):
            painter.drawLine(x, 0, x, h)
        for y in range(0, h, GRID_SIZE):
            painter.drawLine(0, y, w, y)
        painter.end()


_guide: _GridGuide | None = None


def show_guide() -> None:
    global _guide
    if _guide is None:
        _guide = _GridGuide()
    _guide.show_guide()


def hide_guide() -> None:
    if _guide is not None:
        _guide.hide()
