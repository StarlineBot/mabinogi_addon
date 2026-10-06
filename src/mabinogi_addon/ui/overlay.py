"""버프 오버레이 (기획서 3.4 / 5.1).

프레임리스·배경 투명·항상 위·포커스 안 뺏음. 매칭된 버프를 등록 순서대로 가로로
나열하고, 지속시간 표시를 켠 버프는 아이콘 아래 남은 시간을 그린다. 만료임박은 점멸.
배율 50~300%(표시에만 적용). 클릭 통과는 Windows에서 system 헬퍼로 별도 적용.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

_ICON_BASE = 40  # 100% 기준 아이콘 변
_GAP_BASE = 8
_TEXT_BASE = 16  # 아이콘 아래 글자 칸 높이
_PAD = 6


@dataclass
class OverlayItem:
    pixmap: QPixmap  # 표시 아이콘(원본 — 그릴 때 배율 적용)
    duration_text: str | None  # None=칸만 비움(아이콘 높이 맞춤)
    blinking: bool = False


class BuffOverlay(QWidget):
    def __init__(self, scale: float = 1.5) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._scale = scale
        self._items: list[OverlayItem] = []
        self._blink_on = True
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._toggle_blink)

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
            self.resize(1, 1)
            self._timer.stop()
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
            # 점멸: off 단계에서 반투명
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
                rect = QRect(x, _PAD + icon, icon, text_h)
                self._draw_text(painter, rect, item.duration_text)
            x += icon + gap
        painter.end()

    def _draw_text(self, painter: QPainter, rect: QRect, text: str) -> None:
        align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        # 외곽선(검정) 후 흰색 → 어떤 배경에서도 읽힘
        painter.setPen(QColor(0, 0, 0))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(rect.translated(dx, dy), align, text)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect, align, text)
