"""체력/마나/스태미나 '단일 바' 오버레이.

게임 하단 바에서 채움 비율(과 추후 '현재/최대' 수치)을 읽어, 게임 UI와 무관하게
**우리가 그린 깨끗한 가로 바**로 보여준다(미러링이 아님 — 값만 읽어 새로 그린다).
바 하나당 위젯 하나라, HP/MP/스태미나를 **각각 원하는 위치에** 따로 둘 수 있다.

버프 오버레이와 동일하게 프레임리스·투명·항상 위·드래그 이동·고정 시 클릭 통과.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

# 스탯별 기본 색(게임 바 색과 맞춤).
STAT_COLORS = {
    "hp": QColor(236, 72, 128),  # 분홍-빨강
    "mp": QColor(72, 148, 236),  # 파랑
    "sta": QColor(236, 196, 72),  # 노랑
}
STAT_LABELS = {"hp": "HP", "mp": "MP", "sta": "STA"}
_EMPTY = QColor(40, 40, 46, 205)  # 빈(소모) 트랙
_BORDER = QColor(0, 0, 0, 180)

# 100% 기준 치수(배율 적용 전)
_BAR_W = 150
_BAR_H = 16
_PAD = 4
_SHAKE_AMPLITUDE = 3
_SHAKE_BURST = 0.4
_SHAKE_REST = 1.4
WARNING_SAMPLE_MAX_AGE = 0.65


def shake_offset(elapsed: float, scale: float) -> float:
    phase = max(0.0, elapsed) % (_SHAKE_BURST + _SHAKE_REST)
    if phase >= _SHAKE_BURST:
        return 0.0
    return math.sin(phase / _SHAKE_BURST * 4 * math.pi) * _SHAKE_AMPLITUDE * scale


class StatBarOverlay(QWidget):
    moved = Signal()  # 드래그로 위치 바뀜 → 저장
    warning_interrupted = Signal()

    def __init__(self, stat_id: str, scale: float = 1.5, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Widget if parent is not None else Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._embedded = parent is not None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._stat_id = stat_id
        self._color = STAT_COLORS.get(stat_id, QColor(200, 200, 200))
        self._scale = scale
        self._ratio: float = 1.0
        self._text: str | None = None  # None이면 "NN%" 자동
        self._align = "left"  # 퍼센트/수치 가로 정렬: "left" | "center" | "right"
        self._locked = False
        self._drag_offset = None
        self._shake_margin = 0
        self._shake_offset = 0.0
        self._warning = False
        self._warning_started = 0.0
        self._warning_sample_at = 0.0
        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._warning_timer.timeout.connect(self._advance_warning)

    @property
    def base_position(self) -> QPoint:
        """Original saved window origin, excluding the transparent shake gutter."""
        return self.pos() + QPoint(self._shake_margin, 0)

    def move_base(self, pos: QPoint) -> None:
        self.move(pos - QPoint(self._shake_margin, 0))

    @property
    def warning_active(self) -> bool:
        return self._warning

    def set_warning(self, active: bool, sample_at: float = 0.0) -> None:
        if self._embedded or not active or not self.isVisible():
            self._warning = False
            self._warning_timer.stop()
            if self._shake_offset:
                self._shake_offset = 0.0
                self.update()
            return
        self._warning_sample_at = sample_at
        if not self._warning:
            self._warning = True
            self._warning_started = time.monotonic()
            self._advance_warning()

    def _advance_warning(self) -> None:
        now = time.monotonic()
        age = now - self._warning_sample_at
        if not self._warning or not self.isVisible() or age >= WARNING_SAMPLE_MAX_AGE or age < 0:
            self.set_warning(False)
            self.warning_interrupted.emit()
            return
        elapsed = now - self._warning_started
        offset = shake_offset(elapsed, self._scale)
        if offset != self._shake_offset:
            self._shake_offset = offset
            self.update()
        phase = elapsed % (_SHAKE_BURST + _SHAKE_REST)
        # No frame-rate wake-ups during the rest; fresh samples renew the lease.
        delay = 1 / 30 if phase < _SHAKE_BURST else _SHAKE_BURST + _SHAKE_REST - phase
        delay = min(delay, WARNING_SAMPLE_MAX_AGE - age)
        self._warning_timer.start(max(1, math.ceil(delay * 1000)))

    def hideEvent(self, event) -> None:
        self.set_warning(False)
        self.warning_interrupted.emit()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self.set_warning(False)
        super().closeEvent(event)

    @property
    def stat_id(self) -> str:
        return self._stat_id

    # ---- 값 ----
    def set_value(self, ratio: float, text: str | None = None) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self._text = text
        self.update()

    def set_align(self, align: str) -> None:
        """퍼센트/수치 가로 정렬: 'left' | 'center' | 'right'."""
        if align in ("left", "center", "right"):
            self._align = align
            self.update()

    # ---- 고정/이동(버프 오버레이와 동일) ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        if not self._embedded:
            set_click_through(self, locked)
        self._relayout()

    @property
    def locked(self) -> bool:
        return self._locked

    def mousePressEvent(self, event) -> None:
        if not self._embedded and not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.base_position
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
            self.move_base(target)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        was_dragging = self._drag_offset is not None
        self._drag_offset = None
        if was_dragging:
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.5, min(3.0, scale))
        self._relayout()
        if self._warning:
            self._advance_warning()

    # ---- 레이아웃 ----
    def _metrics(self) -> tuple[int, int]:
        return int(_BAR_W * self._scale), int(_BAR_H * self._scale)

    def _relayout(self) -> None:
        bw, bh = self._metrics()
        base = self.base_position
        self._shake_margin = math.ceil(_SHAKE_AMPLITUDE * self._scale)
        size = (bw + 2 * _PAD + 2 * self._shake_margin, bh + 2 * _PAD)
        if self._embedded:
            self.setFixedSize(*size)
        else:
            self.resize(*size)
            self.move_base(base)
        self.update()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        bw, bh = self._metrics()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont()
        font.setPixelSize(max(9, int(bh * 0.72)))
        font.setBold(True)
        painter.setFont(font)

        painter.save()
        painter.translate(self._shake_margin + self._shake_offset, 0)
        track = QRectF(_PAD, _PAD, bw, bh)
        radius = bh * 0.35
        # 트랙(빈 구간)
        painter.setPen(QPen(_BORDER, 1))
        painter.setBrush(_EMPTY)
        painter.drawRoundedRect(track, radius, radius)
        # 채움(둥근 트랙으로 클립해 오른쪽 끝이 각지지 않게)
        if self._ratio > 0:
            painter.save()
            path = QPainterPath()
            path.addRoundedRect(track, radius, radius)
            painter.setClipPath(path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawRect(QRectF(_PAD, _PAD, bw * self._ratio, bh))
            painter.restore()
        # 수치(외곽선 → 어떤 배경에서도 읽힘)
        txt = self._text if self._text is not None else f"{int(self._ratio * 100)}%"
        self._draw_text(painter, track, txt)
        painter.restore()

        # 고정 해제 중엔 '드래그 가능' 느낌으로 옅은 테두리(어느 바인지 라벨도).
        if not self._locked:
            painter.setPen(QPen(QColor(0, 209, 167), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(self._shake_margin, 0, -self._shake_margin - 1, -1))
        painter.end()

    def _draw_text(self, painter: QPainter, rect: QRectF, text: str) -> None:
        halign = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
        }.get(self._align, Qt.AlignmentFlag.AlignHCenter)
        align = halign | Qt.AlignmentFlag.AlignVCenter
        # 좌/우 정렬은 바 모서리에 붙지 않게 안쪽 여백을 둔다.
        pad = max(4, int(rect.height() * 0.35))
        r = rect.toRect().adjusted(pad, 0, -pad, 0)
        painter.setPen(QColor(0, 0, 0))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(r.translated(dx, dy), align, text)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(r, align, text)
