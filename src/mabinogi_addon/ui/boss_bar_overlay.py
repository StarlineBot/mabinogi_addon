"""보스바 오버레이(보스바 오버레이 명세 1절, A 기본형) — 판독한 HP %로 앱이 바를 직접 그린다(미러 아님).

- 어두운 테두리 안 빨간 바, 왼쪽 이름, 오른쪽 `87 %`, 패턴 구간(등록 보스만) 노란 세로선. 20% 미만은 더 밝은 빨강.
- 못 읽는 순간: 마지막 값을 흐리게 + `…`(숨김 시각은 tracker.boss_bar_value가 정한다).
- 잠금 = 클릭 통과, 해제 = 예시 바(`보스 75 %`) + 민트 테두리로 위치 잡기. 격자 맞춤·드래그는 다른 오버레이와 같다.
- 값·모양이 바뀔 때만 다시 그린다(화면 스레드 부담 최소).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .. import perf_meter

# 기본 크기(제작자 시험 #194, 11-05): 예전 150%(540×39)를 새 100%로, 길이는 조금 더 길게 640×39.
# 글자·테두리는 예전 150% 비율 그대로(UNIT). 저장된 예전 배율은 config에서 같은 높이가 되게 환산(예전 150% → 새 100%).
BASE_W, BASE_H = 640, 39
UNIT = 1.5
QUARTER_LINE = QColor(255, 255, 255, 70)  # 25·50·75% 옅은 세로선(바 안쪽만, 노란 패턴 선·글자 아래 층)
MINT = QColor(0, 209, 167)
LOW_HP = 20
EXAMPLE = ("보스", 75, (90, 60, 30))


class BossBarOverlay(QWidget):
    moved = Signal()

    def __init__(self, scale_percent: int = 100) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        from . import overlay_capture
        overlay_capture.watch(self)  # 판독 캡처에서 상시 제외(보스 영역 위에 놓아도 자기 그림을 읽지 않게)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._state: tuple | None = None  # (이름, 값, 흐림, 패턴 구간)
        self._locked = True
        self._drag = None
        self._scale = 1.0
        self.set_scale(scale_percent)

    # ---- 내용 ----
    def set_state(self, name: str | None, value: int | None, stale: bool = False, thresholds=(),
                  frac: str | None = None) -> bool:
        """그릴 내용. 바뀌었으면 True(그때만 다시 그림). value None = 비움.
        frac = 소수 두 자리 글자('38') — 판독이 확실할 때만(없으면 정수만, 틀린 소수는 그리지 않는다)."""
        frac = frac if isinstance(frac, str) and len(frac) == 2 and frac.isdigit() else None
        state = None if value is None else (str(name or "보스"), int(value), bool(stale), tuple(int(t) for t in thresholds), frac)
        if state == self._state:
            return False
        self._state = state
        self.update()
        return True

    def state(self):
        return self._state

    def has_content(self) -> bool:
        return self._state is not None or not self._locked

    def set_scale(self, percent) -> None:
        self._scale = max(50, min(300, int(percent))) / 100
        self.resize(round(BASE_W * self._scale) + 4, round(BASE_H * self._scale) + 4)
        self.update()

    def set_opacity(self, percent) -> None:
        self.setWindowOpacity(max(30, min(100, int(percent))) / 100)

    @property
    def locked(self) -> bool:
        return self._locked

    def set_locked(self, locked: bool) -> None:
        if locked:
            from . import grid as _grid
            _grid.owner_locked(self)
        self._locked = bool(locked)
        self.setCursor(Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor)
        from ..system.clickthrough import set_click_through
        set_click_through(self, self._locked)
        self.update()

    # ---- 그리기 ----
    @perf_meter.timed("그리기·보스바")
    def paintEvent(self, _event) -> None:
        state = self._state
        example = state is None
        if example and self._locked:
            return
        name, value, stale, marks, frac = (EXAMPLE[0], EXAMPLE[1], False, EXAMPLE[2], "38") if example else state
        s = self._scale * UNIT  # 글자·테두리 배율(크기는 BASE_W·BASE_H × 배율)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if stale:
            p.setOpacity(0.5)
        outer = QRectF(2, 2, BASE_W * self._scale, BASE_H * self._scale)
        radius = 4 * s
        p.setPen(QPen(QColor(10, 10, 12), max(1.0, 1.5 * s)))
        p.setBrush(QColor(28, 28, 32, 235))
        p.drawRoundedRect(outer, radius, radius)
        inner = outer.adjusted(2 * s, 2 * s, -2 * s, -2 * s)
        fill = QRectF(inner.x(), inner.y(), inner.width() * max(0, min(100, value)) / 100, inner.height())
        if fill.width() > 0:
            grad = QLinearGradient(fill.topLeft(), fill.bottomLeft())
            if value < LOW_HP:  # 저체력은 더 밝은 빨강
                grad.setColorAt(0, QColor(255, 96, 96))
                grad.setColorAt(1, QColor(236, 52, 52))
            else:
                grad.setColorAt(0, QColor(226, 62, 62))
                grad.setColorAt(1, QColor(176, 30, 34))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(grad)
            p.drawRoundedRect(fill, 2 * s, 2 * s)
        p.setPen(QPen(QUARTER_LINE, max(1.0, 0.7 * s)))
        for q in (25, 50, 75):  # 25%마다 옅은 줄 — 바 안쪽 위~아래만
            x = inner.x() + inner.width() * q / 100
            p.drawLine(round(x), round(inner.top()), round(x), round(inner.bottom()))
        p.setPen(QPen(QColor(244, 200, 40), max(1.0, 1.6 * s)))
        for t in marks:  # 패턴 구간(등록 보스만) — 옅은 줄 위 층
            if 0 < t < 100:
                x = inner.x() + inner.width() * t / 100
                p.drawLine(round(x), round(inner.top()), round(x), round(inner.bottom()))
        font = QFont()
        font.setPixelSize(max(8, round(14 * s)))
        font.setBold(True)
        p.setFont(font)
        text_box = inner.adjusted(7 * s, 0, -7 * s, 0)
        # 오른쪽 값: 정수 크게 + 소수 작게(예: 50.38 %) — 소수를 못 읽으면 정수만
        small = QFont(font)
        small.setPixelSize(max(7, round(10 * s)))
        pieces = []  # (글자, 글꼴) 오른쪽부터
        pieces.append((" %", font))
        if frac:
            pieces.append((f".{frac}", small))
        pieces.append((f"{value}", font))
        if stale:
            pieces.append(("… ", font))
        from PySide6.QtGui import QFontMetrics
        for dx, dy, color in ((1, 1, QColor(0, 0, 0, 200)), (0, 0, QColor(255, 255, 255))):  # 글자 그림자
            p.setPen(color)
            box = text_box.translated(dx, dy)
            p.setFont(font)
            p.drawText(box, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            right = box.right()
            base = box.center().y() + QFontMetrics(font).ascent() / 2 - 1  # 큰 글자 기준선에 작은 소수를 맞춘다
            for text, f in pieces:
                p.setFont(f)
                width = QFontMetrics(f).horizontalAdvance(text)
                right -= width
                p.drawText(round(right), round(base), text)
        p.setFont(font)
        if not self._locked:
            p.setOpacity(1.0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(MINT, 1, Qt.PenStyle.DashLine))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
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
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag is not None:
            self._drag = None
            from . import grid
            grid.hide_guide()
            self.moved.emit()
