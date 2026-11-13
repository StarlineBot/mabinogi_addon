"""게임 위 알람 목록 오버레이(알람 명세 3절) — 다음 패턴 목록(upcoming_overlay)과 같은 모양·고정 규칙.

- 고정: 배경 없이 외곽선 글씨·클릭 통과(표시 전용). 해제: 반투명 상자 + `⠿ 끌어서 이동 · 고정하면 표시만`, 끌어서 이동.
- 줄: 시각 알람 `10:30  해야 할 일`(노랑), 타이머 `28분 뒤  요리 타이머`(민트), 1분 안은 빨강·초 단위(`58초 뒤`).
- 배율·불투명도는 다른 게임 위 오버레이와 같은 공통 규칙.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

_HEADER_H = 20
_PAD_X = 14
_PAD_Y = 8
_LINE_GAP = 6
_HINT = "⠿ 끌어서 이동 · 고정하면 표시만"
COLORS = {"time": QColor("#FFD54A"), "timer": QColor("#3EE6C1"), "soon": QColor("#FF6B6B")}
_SAMPLE = [("10:30", "해야 할 일", "time"), ("28분 뒤", "요리 타이머", "timer"), ("21:00", "레이드", "time")]


class AlarmListOverlay(QWidget):
    moved = Signal()

    def __init__(self, scale: int = 100, opacity: int = 100) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        from . import overlay_capture
        overlay_capture.watch(self)  # 뜰 때마다 판독 캡처에서 빼기
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._locked = False
        self._drag_offset = None
        self._lines: list[tuple[str, str, str]] = []
        self._scale = scale
        self.setWindowOpacity(max(0.3, min(1.0, opacity / 100)))
        self._relayout()

    @staticmethod
    def _base_px() -> int:
        screen = QGuiApplication.primaryScreen()
        h = screen.geometry().height() if screen is not None else 1080
        return max(18, h // 48)

    def _font(self) -> QFont:
        font = QFont()
        font.setPixelSize(max(10, round(self._base_px() * self._scale / 100)))
        font.setBold(True)
        return font

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def lines(self) -> list[tuple[str, str, str]]:
        return list(self._lines)

    def set_lines(self, lines) -> None:
        lines = [tuple(x) for x in lines]
        if lines == self._lines:
            return
        self._lines = lines
        self._relayout()

    def set_scale(self, scale: int) -> None:
        self._scale = int(scale)
        self._relayout()

    def set_opacity(self, opacity: int) -> None:
        self.setWindowOpacity(max(0.3, min(1.0, opacity / 100)))

    def _display(self):
        return self._lines if (self._lines or self._locked) else _SAMPLE

    def _columns(self, fm: QFontMetrics):
        items = self._display()
        left = max((fm.horizontalAdvance(t) for t, _n, _k in items), default=fm.horizontalAdvance("00:00"))
        right = max((fm.horizontalAdvance(n) for _t, n, _k in items), default=0)
        return items, left, right

    def _relayout(self) -> None:
        fm = QFontMetrics(self._font())
        items, left, right = self._columns(fm)
        n = max(1, len(items))
        header = 0 if self._locked else _HEADER_H
        gap = fm.horizontalAdvance("  ")
        hint = 0 if self._locked else QFontMetrics(QFont()).horizontalAdvance(_HINT) + _PAD_X
        self.resize(int(max(left + gap + right + _PAD_X * 2, hint)),
                    int(header + _PAD_Y * 2 + n * fm.height() + (n - 1) * _LINE_GAP))
        self.update()

    def set_locked(self, locked: bool) -> None:
        if locked:
            from . import grid as _grid
            _grid.owner_locked(self)
        self._locked = locked
        self.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor)
        from ..system.clickthrough import set_click_through
        set_click_through(self, locked)
        self._relayout()

    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            from . import grid
            self._snap = grid.enabled()
            self._grid_size = grid.size() if self._snap else None
            if self._snap:
                grid.show_guide(self)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            target = event.globalPosition().toPoint() - self._drag_offset
            if getattr(self, "_snap", False):
                from . import grid
                target = grid.snap(target, getattr(self, "_grid_size", None))
            self.move(target)
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            from . import grid
            grid.hide_guide()
            self.moved.emit()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font()
        fm = QFontMetrics(font)
        items, left, _right = self._columns(fm)
        if not self._locked:
            rect = self.rect().adjusted(0, 0, -1, -1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(rect, 8, 8)
            p.setPen(QColor(0, 209, 167))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 8, 8)
            hint_font = QFont()
            hint_font.setPixelSize(11)
            p.setFont(hint_font)
            p.setPen(QColor(150, 200, 190))
            p.drawText(_PAD_X, 0, self.width() - _PAD_X, _HEADER_H,
                       int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), _HINT)
        top = (0 if self._locked else _HEADER_H) + _PAD_Y
        name_x = _PAD_X + left + fm.horizontalAdvance("  ")
        for i, (when, name, kind) in enumerate(items):
            baseline = top + i * (fm.height() + _LINE_GAP) + fm.ascent()
            for x, text, fill in ((_PAD_X, when, COLORS.get(kind, COLORS["time"])), (name_x, name, QColor("white"))):
                path = QPainterPath()
                path.addText(float(x), float(baseline), font, text)
                p.setPen(QPen(QColor(0, 0, 0, 230), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawPath(path)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(fill)
                p.drawPath(path)
        p.end()
