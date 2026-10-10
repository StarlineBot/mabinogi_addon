"""다음 패턴 목록 오버레이 (기획서 12 · 보조).

보스 패턴 경고의 보조 패널. 화면 왼쪽에 '앞으로 올 패턴 %'를 세로로 나열해 뭐가
다가오는지 미리 보여준다. 각 패턴의 준비(5% 전) 알림이 뜨면 그 %는 목록에서 빠진다
(목록 갱신은 BossTab이 트래커의 upcoming()으로 매 프레임 넣어 준다).

메모/버프 오버레이와 같은 고정 규칙:
- 해제: 반투명 검은 박스(테두리·헤더). 끌어서 이동. 앱 위에서도 보여 위치 지정 가능.
- 고정: 배경 투명 + 클릭 통과(표시 전용). 밝은 글씨 + 검은 외곽선으로 게임 위에서도
  또렷. 남은 패턴이 없으면 숨는다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

_HEADER_H = 20  # 해제 상태 상단 헤더(이동 안내)
_PAD_X = 14
_PAD_Y = 8
_LINE_GAP = 6
_HINT = "⠿ 끌어서 이동 · 고정하면 표시만"
# 해제 상태에서 목록이 비어도 위치를 잡게 보여줄 샘플.
_SAMPLE = [90, 60, 30]


class UpcomingPatternsOverlay(QWidget):
    moved = Signal()  # 드래그로 위치가 바뀜 → 저장

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._locked = False
        self._drag_offset = None
        self._items: list[int] = []
        self._font_px = self._default_font_px()
        self._relayout()

    @staticmethod
    def _default_font_px() -> int:
        screen = QGuiApplication.primaryScreen()
        h = screen.geometry().height() if screen is not None else 1080
        return max(18, h // 48)

    @property
    def locked(self) -> bool:
        return self._locked

    @property
    def items(self) -> list[int]:
        return list(self._items)

    # ---- 내용 ----
    def set_items(self, items: list[int]) -> None:
        items = [int(x) for x in items]
        if items == self._items:
            return
        self._items = items
        self._relayout()

    def _display_items(self) -> list[int]:
        # 해제 + 비어 있음 → 샘플로 위치 지정 가능하게.
        if not self._items and not self._locked:
            return _SAMPLE
        return self._items

    def _relayout(self) -> None:
        font = QFont()
        font.setPixelSize(self._font_px)
        font.setBold(True)
        fm = QFontMetrics(font)
        items = self._display_items()
        line_h = fm.height()
        texts = [f"{t}%" for t in items]
        tw = max((fm.horizontalAdvance(s) for s in texts), default=fm.horizontalAdvance("00%"))
        n = max(1, len(items))
        header = 0 if self._locked else _HEADER_H
        w = tw + _PAD_X * 2
        h = header + _PAD_Y * 2 + n * line_h + (n - 1) * _LINE_GAP
        self.resize(int(w), int(h))
        self.update()

    # ---- 고정(클릭 통과) ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self._relayout()

    # ---- 드래그 이동(격자 스냅은 메모/버프 오버레이와 동일) ----
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

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        items = self._display_items()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(self._font_px)
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        line_h = fm.height()

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
            p.drawText(
                int(_PAD_X),
                0,
                self.width() - _PAD_X,
                _HEADER_H,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                _HINT,
            )
            p.setFont(font)

        top = (0 if self._locked else _HEADER_H) + _PAD_Y
        for i, t in enumerate(items):
            baseline = top + i * (line_h + _LINE_GAP) + fm.ascent()
            path = QPainterPath()
            path.addText(float(_PAD_X), float(baseline), font, f"{t}%")
            p.setPen(QPen(QColor(0, 0, 0, 230), 3))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#FFD54A"))
            p.drawPath(path)
        p.end()
