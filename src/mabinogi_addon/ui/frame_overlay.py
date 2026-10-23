"""게임 위 FPS·추가 지표 오버레이 (FPS 명세 8.1 B안 + 8.4 1안).

배경 판 없이 항목을 가로로 나열한다. 항목마다 이름은 위에 작게(민트), 값은 아래에 크고 굵게(흰색).
검은 외곽선은 글자 **아래**에 먼저 그려 획을 깎지 않고, 옅은 그림자를 더한다. 단위(%, GB)는 값 옆에 작게.
메모 오버레이 재사용(글자 위 외곽선 → 획이 가늘어 보임)을 대신하는 전용 그리기다.
기존 규칙 유지: 항상 위·포커스 안 뺏음, 고정 시 투명 + 클릭 통과, 해제 시 반투명 박스를 끌어 이동.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

MINT = QColor('#00d1a7')
_HEADER_H = 18  # 해제 상태의 이동 안내 줄


def _font(px, weight):
    font = QFont()
    font.setPixelSize(max(6, round(px)))
    font.setWeight(weight)
    return font


class FrameOverlay(QWidget):
    moved = Signal()

    def __init__(self, scale_percent: int = 100) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._locked = False
        self._drag_offset = None
        self._items = [('FPS', '—', '')]
        self._scale = 1.0
        self.set_scale(scale_percent)

    # ---- 내용 ----
    def set_items(self, items):
        """[(이름, 값, 단위)]. 숨긴 항목은 넘기지 않으면 자리를 비우지 않고 당겨 붙는다."""
        items = [(str(n), str(v), str(u or '')) for n, v, u in items]
        if items != self._items:
            self._items = items
            self._relayout()

    def items(self):
        return list(self._items)

    def set_scale(self, percent) -> None:
        self._scale = max(50, min(300, int(percent))) / 100
        self._relayout()

    # 배율 100%에서 값 약 30px(Black), 이름 11px, 단위 13px.
    def _fonts(self):
        s = self._scale
        return (_font(11 * s, QFont.Weight.Bold), _font(30 * s, QFont.Weight.Black), _font(13 * s, QFont.Weight.Bold))

    def _layout(self):
        """항목별 (이름 x, 값 x, 단위 x, 폭)과 전체 크기를 계산한다."""
        name_font, value_font, unit_font = self._fonts()
        nm, vm, um = QFontMetricsF(name_font), QFontMetricsF(value_font), QFontMetricsF(unit_font)
        pad, gap = 8 * self._scale, 18 * self._scale
        x, boxes = pad, []
        for name, value, unit in self._items:
            value_w = vm.horizontalAdvance(value)
            unit_w = um.horizontalAdvance(unit) + (2 * self._scale if unit else 0)
            width = max(nm.horizontalAdvance(name), value_w + unit_w)
            boxes.append((x, value_w, width))
            x += width + gap
        top = _HEADER_H if not self._locked else 0
        height = top + pad + nm.height() + vm.ascent() + vm.descent() + pad
        width = max(x - gap + pad, 40)
        return boxes, top, (nm, vm, um), width, height

    def _relayout(self):
        _boxes, _top, _metrics, width, height = self._layout()
        self.resize(round(width), round(height))
        self.update()

    # ---- 고정(클릭 통과) ----
    @property
    def locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        self.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor)
        from ..system.clickthrough import set_click_through
        set_click_through(self, self._locked)
        self._relayout()

    # ---- 그리기 ----
    def _draw_text(self, painter, font, color, x, baseline, text):
        path = QPainterPath()
        path.addText(QPointF(x, baseline), font, text)
        size = font.pixelSize()
        painter.setBrush(QColor(0, 0, 0, 90))  # 옅은 그림자
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(path.translated(max(1.0, size * .04), max(1.0, size * .06)))
        # 외곽선을 먼저 그린 뒤 채움을 위에 덮어, 외곽선이 획 바깥쪽에만 남게 한다.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 230), max(1.5, size * .14), Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        boxes, top, (nm, vm, _um), _w, _h = self._layout()
        if not self._locked:
            rect = self.rect().adjusted(0, 0, -1, -1)
            painter.fillRect(rect, QColor(0, 0, 0, 120))
            painter.setPen(MINT)
            painter.drawRect(rect)
            painter.setPen(QColor(150, 200, 190))
            painter.setFont(_font(10, QFont.Weight.Normal))
            painter.drawText(QRect(6, 0, self.width() - 6, _HEADER_H),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, '⠿ 끌어서 이동')
        name_font, value_font, unit_font = self._fonts()
        pad = 8 * self._scale
        name_base = top + pad + nm.ascent()
        value_base = top + pad + nm.height() + vm.ascent()
        for (x, value_w, _width), (name, value, unit) in zip(boxes, self._items):
            self._draw_text(painter, name_font, MINT, x, name_base, name)
            self._draw_text(painter, value_font, QColor('white'), x, value_base, value)
            if unit:
                self._draw_text(painter, unit_font, QColor('white'), x + value_w + 2 * self._scale, value_base, unit)
        painter.end()

    # ---- 드래그 이동 ----
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit()
