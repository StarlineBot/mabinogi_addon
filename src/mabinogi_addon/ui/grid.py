"""오버레이 격자 맞춤(스냅) 공용 유틸.

설정(general.gridSnap)이 켜져 있으면 모든 오버레이(버프·디버프·메모·미러)를 드래그로
옮길 때 좌표를 16px 격자에 맞춰 이동한다. 격자 선은 **드래그하는 동안에만** 전체 화면에
표시(클릭 통과)되고, 떼면 사라진다.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_DEFAULT_SIZE = 32  # 격자 한 칸(px) 기본값. 설정에서 조절 가능.


def enabled() -> bool:
    from .. import config

    return config.load_general_flag("gridSnap", False)


def size() -> int:
    from .. import config

    return config.load_grid_size()


def _screen_center() -> tuple[int, int]:
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return 960, 540
    c = screen.geometry().center()
    return c.x(), c.y()


def snap(point: QPoint, grid_size: int | None = None) -> QPoint:
    """좌표를 **화면 정중앙 기준** 격자에 맞춰 반올림.

    0,0이 아니라 화면 중앙을 원점으로 삼아, 격자선(가이드)과 스냅이 항상 중앙을
    지나도록 일치시킨다 → 중앙 기준선에 맞춰 오버레이를 정렬하기 쉽다.
    """
    s = grid_size or _DEFAULT_SIZE
    cx, cy = _screen_center()
    return QPoint(
        cx + round((point.x() - cx) / s) * s,
        cy + round((point.y() - cy) / s) * s,
    )


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
        self._size = _DEFAULT_SIZE

    def show_guide(self, grid_size: int) -> None:
        self._size = max(2, int(grid_size))
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.setGeometry(screen.geometry())
        self.show()
        self.raise_()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        w, h = self.width(), self.height()
        s = max(2, self._size)
        cx, cy = w // 2, h // 2
        # 일반 격자선 — 중앙을 지나도록 위상을 맞춘다(중앙 대칭).
        painter.setPen(QPen(QColor(0, 209, 167, 70), 1))
        x = cx % s
        while x < w:
            painter.drawLine(x, 0, x, h)
            x += s
        y = cy % s
        while y < h:
            painter.drawLine(0, y, w, y)
            y += s
        # 중앙 기준선(십자) — 더 밝고 두껍게.
        painter.setPen(QPen(QColor(255, 213, 74, 180), 2))
        painter.drawLine(cx, 0, cx, h)
        painter.drawLine(0, cy, w, cy)
        painter.end()


_guide: _GridGuide | None = None


def show_guide() -> None:
    global _guide
    if _guide is None:
        _guide = _GridGuide()
    _guide.show_guide(size())


def hide_guide() -> None:
    if _guide is not None:
        _guide.hide()
