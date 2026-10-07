"""투아림 리더 박스 (기획서 3.3 변형).

화면의 투아림 % 게이지 위에 올려두는 반투명 상자. 이 상자의 화면 영역을 읽어 %를
판독한다(상자 자체는 게이지를 가리지 않도록, 고정하면 완전 투명 + 클릭 통과).

- 해제: 반투명 박스 + 테두리 + 안내(드래그 이동 · 휠 크기조절). 이 안에 '숫자 두 자리'가
  들어오도록 맞춘다.
- 고정: 완전 투명 + 클릭 통과(게이지가 그대로 보이고, 그 아래 화면을 읽는다).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

_MIN = 24


class TuarimBox(QWidget):
    moved = Signal()  # 위치·크기 변경 → 저장

    def __init__(self, box: dict | None = None) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        box = box or {}
        self._locked = False
        self._drag_offset = None
        self.resize(max(_MIN, int(box.get("w", 70))), max(_MIN, int(box.get("h", 34))))
        self.move(int(box.get("x", 760)), int(box.get("y", 440)))

    @property
    def locked(self) -> bool:
        return self._locked

    def to_dict(self) -> dict:
        return {
            "x": int(self.x()),
            "y": int(self.y()),
            "w": int(self.width()),
            "h": int(self.height()),
            "locked": bool(self._locked),
        }

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self.update()

    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit()

    def wheelEvent(self, event) -> None:
        if self._locked:
            return
        step = 4 if event.angleDelta().y() > 0 else -4
        self.resize(max(_MIN, self.width() + step), max(_MIN, self.height() + step // 2))
        self.moved.emit()
        event.accept()

    def paintEvent(self, _event) -> None:
        if self._locked:
            return  # 고정: 완전 투명(게이지 가리지 않음)
        painter = QPainter(self)
        rect = self.rect().adjusted(0, 0, -1, -1)
        painter.fillRect(rect, QColor(0, 209, 167, 40))
        painter.setPen(QPen(QColor(0, 209, 167), 2))
        painter.drawRect(rect)
        painter.setPen(QColor(255, 255, 255))
        font = QFont()
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawText(
            QRect(2, 2, self.width() - 4, self.height() - 4),
            Qt.AlignmentFlag.AlignCenter,
            "투아림 %",
        )
        painter.end()
