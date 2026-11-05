"""쿨타임 오버레이 한 줄(쿨타임 명세 10.1) — 버프 오버레이처럼 가로 한 줄, 묶음 하나를 드래그로 옮긴다.

- 칸 그림은 **DWM 썸네일**로 그 단축바 칸을 그대로 비춘다(게임 숫자 그대로, CPU 거의 0 — 9.1-3).
  썸네일을 못 쓰는 환경(맥·테스트·DWM 실패)은 관측 때 잘라 둔 그림으로 대신한다.
- 강조 칸은 원래 색 + 민트 테두리(썸네일을 테두리 안쪽으로 줄여 테두리가 보이게).
- 잠금 = 클릭 통과, 해제 = 반투명 바탕 + '끌어서 이동' + 예시 칸 3개(위치 잡기용). 격자 맞춤은 다른 오버레이와 같다.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .. import perf_meter

_log = logging.getLogger(__name__)
MINT = QColor(0, 209, 167)
ICON = 40
GAP = 4
HEADER = 16
BORDER = 3


class CooldownOverlay(QWidget):
    moved = Signal()

    def __init__(self, scale_percent: int = 100) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        from . import overlay_capture
        overlay_capture.watch(self)  # 판독 캡처에서 상시 제외(자기 자신을 원본으로 다시 찍지 않게)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._items: list[tuple[str, bool]] = []      # (칸 id, 강조)
        self._pixmaps: dict[str, QPixmap] = {}         # 썸네일 대신 쓸 그림
        self._sources: dict[str, tuple[int, int, int, int]] = {}  # 칸 id → 원본 물리 사각형
        self._thumbs: dict = {}
        self._hwnd = 0
        self._locked = True
        self._drag = None
        self._scale = 1.0
        self.set_scale(scale_percent)

    # ---- 내용 ----
    def set_sources(self, sources: dict) -> None:
        self._sources = {k: tuple(v) for k, v in sources.items()}

    def set_game_window(self, hwnd: int) -> None:
        if hwnd != self._hwnd:
            self._clear_thumbs()
            self._hwnd = hwnd or 0
        self._sync_thumbs()

    def set_items(self, items: list[tuple[str, bool]], pixmaps: dict | None = None) -> None:
        """줄 내용 — 바뀐 경우에만 다시 배치·그린다(화면 스레드 부담 최소)."""
        if pixmaps:
            self._pixmaps.update(pixmaps)
        items = [(str(a), bool(b)) for a, b in items]
        if items == self._items and not pixmaps:
            return
        self._items = items
        self._relayout()

    def items(self) -> list[tuple[str, bool]]:
        return list(self._items)

    def set_scale(self, percent) -> None:
        self._scale = max(50, min(300, int(percent))) / 100
        self._relayout()

    def set_opacity(self, percent) -> None:
        self.setWindowOpacity(max(30, min(100, int(percent))) / 100)

    @property
    def locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        if locked:  # 끄던 중 고정되면 격자 안내선도 바로 숨긴다(공용)
            from . import grid as _grid
            _grid.owner_locked(self)
        self._locked = bool(locked)
        self.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor)
        from ..system.clickthrough import set_click_through
        set_click_through(self, self._locked)
        self._relayout()

    # ---- 배치 ----
    def _cells(self):
        """보여 줄 칸: 잠금 해제 중이고 비어 있으면 예시 3칸(위치 잡기용)."""
        if self._items or self._locked:
            return [(sid, hi, False) for sid, hi in self._items]
        return [(f"예시{i}", False, True) for i in range(3)]

    def _rects(self):
        size, gap = round(ICON * self._scale), round(GAP * self._scale)
        top = 0 if self._locked else HEADER
        return [QRect(2 + i * (size + gap), top + 2, size, size) for i in range(len(self._cells()))]

    def _relayout(self) -> None:
        rects = self._rects()
        size = round(ICON * self._scale)
        width = (rects[-1].right() + 3) if rects else size + 4
        height = (0 if self._locked else HEADER) + size + 4
        self.resize(max(width, 40 if not self._locked else 1), height)
        self._sync_thumbs()
        self.update()

    # ---- DWM 썸네일(9.1-3) ----
    def _sync_thumbs(self) -> None:
        from ..system import dwm_thumbnail
        if not self._hwnd or not dwm_thumbnail.available() or not self.isVisible():
            self._clear_thumbs()
            return
        wr = dwm_thumbnail.window_rect(self._hwnd)
        if wr is None:
            self._clear_thumbs()
            return
        wanted = {}
        for (sid, hi, example), rect in zip(self._cells(), self._rects()):
            src = self._sources.get(sid)
            if example or src is None:
                continue
            inset = BORDER if hi else 0
            dest = (rect.x() + inset, rect.y() + inset, rect.width() - 2 * inset, rect.height() - 2 * inset)
            x, y, w, h = src
            wanted[sid] = ((x - wr[0], y - wr[1], x - wr[0] + w, y - wr[1] + h), dest)
        for sid in [s for s in self._thumbs if s not in wanted]:
            self._thumbs.pop(sid).unregister()
        for sid, (src_rel, dest) in wanted.items():
            thumb = self._thumbs.get(sid)
            if thumb is None:
                thumb = dwm_thumbnail.Thumbnail()
                if not thumb.register(int(self.winId()), int(self._hwnd)):
                    continue
                self._thumbs[sid] = thumb
            thumb.update(src_rel, dest)

    def _clear_thumbs(self) -> None:
        for thumb in self._thumbs.values():
            thumb.unregister()
        self._thumbs.clear()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_thumbs()

    def hideEvent(self, event) -> None:
        self._clear_thumbs()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        self._clear_thumbs()
        super().closeEvent(event)

    # ---- 그리기 ----
    @perf_meter.timed("그리기·쿨타임")
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._locked:
            p.fillRect(self.rect().adjusted(0, 0, -1, -1), QColor(0, 0, 0, 120))
            p.setPen(MINT)
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
            f = QFont()
            f.setPixelSize(10)
            p.setFont(f)
            p.setPen(QColor(150, 200, 190))
            p.drawText(QRect(4, 0, self.width() - 4, HEADER), Qt.AlignmentFlag.AlignVCenter, "⠿ 쿨타임")
        for (sid, hi, example), rect in zip(self._cells(), self._rects()):
            if example:
                p.setPen(QPen(QColor(200, 200, 200, 160), 1, Qt.PenStyle.DashLine))
                p.setBrush(QColor(60, 60, 60, 150))
                p.drawRect(rect)
                continue
            if sid not in self._thumbs:  # 썸네일이 없으면 잘라 둔 그림으로
                pix = self._pixmaps.get(sid)
                if pix is not None:
                    inner = rect.adjusted(BORDER, BORDER, -BORDER, -BORDER) if hi else rect
                    p.drawPixmap(inner, pix)
            if hi:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(MINT, BORDER))
                p.drawRect(rect.adjusted(1, 1, -2, -2))
        p.end()

    # ---- 드래그(격자 맞춤 공용) ----
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            from . import grid
            self._snap = grid.enabled()
            self._grid_size = grid.size() if self._snap else None
            if self._snap:
                grid.show_guide(self)
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag is not None:
            target = event.globalPosition().toPoint() - self._drag
            if getattr(self, "_snap", False):
                from . import grid
                target = grid.snap(target, getattr(self, "_grid_size", None))
            self.move(target)
            self._sync_thumbs()
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag is not None:
            self._drag = None
            from . import grid
            grid.hide_guide()
            self.moved.emit()
