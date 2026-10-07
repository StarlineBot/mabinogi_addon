"""버프 오버레이 (기획서 3.4 / 5.1).

프레임리스·배경 투명·항상 위·포커스 안 뺏음. 매칭된 버프를 등록 순서대로 가로로
나열하고, 지속시간 표시를 켠 버프는 아이콘 아래 남은 시간을 그린다. 만료임박은 점멸.
배율 50~300%(표시에만 적용). 클릭 통과는 Windows에서 system 헬퍼로 별도 적용.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from ..duration import format_duration


def overlay_spec(
    entries, show_duration: dict[str, bool]
) -> list[tuple[str, str | None, bool]]:
    """엔진 결과(OverlayEntry) → (buff_id, 표시할 시간 문자열|None, 점멸) 목록.

    지속시간 표시를 끈 버프나 판독값 없는 버프는 시간 None(칸만 비움).
    """
    specs: list[tuple[str, str | None, bool]] = []
    for entry in entries:
        show = show_duration.get(entry.buff_id, True)
        text = (
            format_duration(entry.remaining)
            if show and entry.remaining is not None
            else None
        )
        specs.append((entry.buff_id, text, entry.alerting))
    return specs

_ICON_BASE = 40  # 100% 기준 아이콘 변
_GAP_BASE = 3  # 아이콘 사이 간격(100% 기준)
_TEXT_BASE = 16  # 아이콘 아래 글자 칸 높이
_PAD = 6


@dataclass
class OverlayItem:
    pixmap: QPixmap  # 표시 아이콘(원본 — 그릴 때 배율 적용)
    duration_text: str | None  # None=칸만 비움(아이콘 높이 맞춤)
    blinking: bool = False


class BuffOverlay(QWidget):
    moved = Signal()  # 드래그로 위치가 바뀜 → main이 저장

    def __init__(self, scale: float = 1.5, placeholder_name: str = "버프") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._name = placeholder_name  # 플레이스홀더 안내 문구용
        self._scale = scale
        self._items: list[OverlayItem] = []
        self._blink_on = True
        self._locked = False  # 고정=클릭 통과, 해제=드래그 이동
        self._drag_offset = None
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._toggle_blink)

    # ---- 고정/이동 ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self._relayout()  # 해제 시 비어 있어도 위치 잡게 플레이스홀더 크기

    @property
    def locked(self) -> bool:
        return self._locked

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            from . import grid

            self._snap = grid.enabled()
            if self._snap:
                grid.show_guide()
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not self._locked and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            if getattr(self, "_snap", False):
                from . import grid

                target = grid.snap(target)
            self.move(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_dragging = self._drag_offset is not None
        self._drag_offset = None
        if was_dragging:
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.5, min(3.0, scale))
        self._relayout()

    def set_items(self, items: list[OverlayItem]) -> None:
        self._items = items
        self._relayout()

    # ---- 레이아웃/점멸 ----
    def _metrics(self) -> tuple[int, int, int]:
        icon = int(_ICON_BASE * self._scale)
        gap = int(_GAP_BASE * self._scale)
        text_h = int(_TEXT_BASE * self._scale)
        return icon, gap, text_h

    def _relayout(self) -> None:
        icon, gap, text_h = self._metrics()
        n = len(self._items)
        if n == 0:
            self._timer.stop()
            if self._locked:
                self.resize(1, 1)  # 고정+비어있음 → 보이지 않게
            else:
                self.resize(220, 56)  # 해제 시 드래그용 플레이스홀더
            self.update()
            return
        width = n * icon + (n - 1) * gap + 2 * _PAD
        height = icon + text_h + 2 * _PAD
        self.resize(width, height)

        if any(i.blinking for i in self._items):
            self._blink_on = True
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _toggle_blink(self) -> None:
        self._blink_on = not self._blink_on
        self.update()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:  # noqa: N802
        if not self._items:
            if not self._locked:
                self._paint_placeholder()
            return
        icon, gap, text_h = self._metrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        font = QFont()
        font.setPixelSize(max(9, int(text_h * 0.8)))
        font.setBold(True)
        painter.setFont(font)

        x = _PAD
        for item in self._items:
            # 점멸: off 단계에서 아이콘만 반투명(숫자는 항상 선명하게 읽히도록).
            painter.setOpacity(
                0.35 if (item.blinking and not self._blink_on) else 1.0
            )
            scaled = item.pixmap.scaled(
                icon,
                icon,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,  # Nearest(선명)
            )
            painter.drawPixmap(x, _PAD, scaled)

            if item.duration_text:
                painter.setOpacity(1.0)  # 숫자는 점멸과 무관하게 선명
                rect = QRect(x, _PAD + icon, icon, text_h)
                self._draw_text(painter, rect, item.duration_text)
            x += icon + gap
        painter.end()

    def _paint_placeholder(self) -> None:
        """고정 해제 + 비어있을 때 드래그용 안내 박스."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        painter.setPen(QColor(0, 209, 167))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._name} 오버레이\n(드래그로 이동 · 고정하면 사라짐)",
        )
        painter.end()

    def _draw_text(self, painter: QPainter, rect: QRect, text: str) -> None:
        align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        # 외곽선(검정) 후 흰색 → 어떤 배경에서도 읽힘
        painter.setPen(QColor(0, 0, 0))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(rect.translated(dx, dy), align, text)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, align, text)
