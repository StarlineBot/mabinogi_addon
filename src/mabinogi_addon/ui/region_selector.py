"""영역 지정 오버레이 (기획서 5.2).

전체화면 반투명 위에서 드래그로 사각형을 그려 영역(실제 화면 픽셀)을 고른다.
ESC로 취소. 선택 완료 시 selected(x, y, w, h) 시그널.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RegionSelector(QWidget):
    selected = Signal(int, int, int, int)  # 화면 픽셀 x, y, w, h
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        # 주 화면 전체 덮기(위젯 로컬 좌표 = 화면 좌표 + screen.topLeft())
        self._screen_geo = QGuiApplication.primaryScreen().geometry()
        self.setGeometry(self._screen_geo)

        self._origin: QPoint | None = None
        self._rect = QRect()

    def start(self) -> None:
        self._origin = None
        self._rect = QRect()
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._rect = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._rect = QRect(self._origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._origin is None:
            return
        rect = self._rect
        self.close()
        if rect.width() >= 4 and rect.height() >= 4:
            self.selected.emit(
                self._screen_geo.x() + rect.x(),
                self._screen_geo.y() + rect.y(),
                rect.width(),
                rect.height(),
            )
        else:
            self.cancelled.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            self.cancelled.emit()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))  # 전체 어둡게
        if not self._rect.isNull():
            # 선택 영역은 비워서(원래 화면 보이게) + 테두리
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear
            )
            painter.fillRect(self._rect, Qt.GlobalColor.transparent)
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceOver
            )
            painter.setPen(QPen(QColor(0, 209, 167), 2))
            painter.drawRect(self._rect)
            label = f"{self._rect.width()} × {self._rect.height()}"
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(self._rect.adjusted(4, 4, 0, 0), 0, label)
