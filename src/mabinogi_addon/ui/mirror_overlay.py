"""미러 오버레이 창 (커스텀 오버레이 / 기획서 3.6).

화면의 한 영역(소스)을 복제해 띄우는 투명·항상위 창. 공유 캡처가 매 틱 프레임을
넘겨주면 그걸 그린다. 해제 상태에서 드래그 이동, 고정 상태에서 클릭 통과(표시 전용).

읽기 전용 원칙 준수: 화면을 읽어 그리기만 하며 입력을 만들지 않는다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

_SCALE_MIN = 0.25
_SCALE_MAX = 4.0
_SCALE_STEP = 0.1


def _clamp_scale(s: float) -> float:
    return max(_SCALE_MIN, min(_SCALE_MAX, round(s, 2)))


class MirrorOverlay(QWidget):
    moved = Signal()  # 드래그로 위치 변경 → 저장

    def __init__(self, source: dict) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        # source: {x,y,w,h, name, posX?, posY?, locked?, scale?}
        self.source = dict(source)
        self._pix: QPixmap | None = None
        self._locked = False
        self._drag_offset = None

        self._base_w = max(1, int(source["w"]))
        self._base_h = max(1, int(source["h"]))
        self._scale = _clamp_scale(float(source.get("scale", 1.0)))
        self._apply_size()
        self.move(int(source.get("posX", source["x"])), int(source.get("posY", source["y"])))

    def _apply_size(self) -> None:
        self.resize(
            max(1, round(self._base_w * self._scale)),
            max(1, round(self._base_h * self._scale)),
        )

    @property
    def name(self) -> str:
        return str(self.source.get("name", ""))

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def dragging(self) -> bool:
        """드래그 이동 중인지. 매니저가 이때 캡처를 쉬어 드래그를 부드럽게 한다."""
        return self._drag_offset is not None

    def set_frame(self, image: QImage) -> None:
        self._pix = QPixmap.fromImage(image)
        self.update()

    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        # 다른 오버레이와 동일: Qt 레벨 마우스 투과도 함께 토글(해제=받음, 고정=통과).
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)  # Windows 클릭 통과
        self.update()

    def to_dict(self) -> dict:
        """프리셋/복원용 직렬화(소스 영역 + 띄운 위치 + 고정 상태)."""
        return {
            "x": int(self.source["x"]),
            "y": int(self.source["y"]),
            "w": int(self.source["w"]),
            "h": int(self.source["h"]),
            "posX": int(self.x()),
            "posY": int(self.y()),
            "locked": bool(self._locked),
            "scale": round(self._scale, 2),
            "name": self.name,
        }

    # ---- 배율(해제 상태에서 휠=크기조절, 더블클릭=100%) ----
    def wheelEvent(self, event) -> None:
        if self._locked:
            return
        step = _SCALE_STEP if event.angleDelta().y() > 0 else -_SCALE_STEP
        new = _clamp_scale(self._scale + step)
        if new != self._scale:
            self._scale = new
            self._apply_size()
            self.moved.emit()  # 크기 변경도 저장
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._locked:
            self._scale = 1.0
            self._apply_size()
            self.moved.emit()
            event.accept()

    # ---- 드래그 이동(해제 상태에서만) ----
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            from . import grid

            self._snap = grid.enabled()
            self._grid_size = grid.size() if self._snap else None
            if self._snap:
                grid.show_guide()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            if getattr(self, "_snap", False):
                from . import grid

                target = grid.snap(target, getattr(self, "_grid_size", None))
            self.move(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        if self._pix is not None:
            painter.drawPixmap(self.rect(), self._pix)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if not self._locked:
            # 해제 상태: 이동 가능 표시 테두리
            painter.setPen(QPen(QColor(0, 209, 167), 2))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()
