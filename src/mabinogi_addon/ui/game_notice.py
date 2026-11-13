"""② 게임 위 알림(화면 규칙 '알림 규칙') — 게임 화면 상단 정중앙 알약. 블랙박스 메시지 부품을 공용으로 일반화했다(0.48.0).

- 크기: 보통(14px, 블랙박스 그대로) / 크게(22px, 알람·타이머 — 색 테두리).
- 항상 위·포커스를 빼앗지 않음·클릭 통과·판독 캡처에서 빠짐(overlay_capture.watch).
- 여럿이 함께 뜨면 겹치지 않게 아래로 쌓는다. 블랙박스 메시지가 늘 맨 위(자리 그대로), 나머지는 뜬 순서로 그 아래.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

GAP = 6  # 쌓을 때 사이 간격(px)
# 알람 알림 색(알람 명세 2절): 시각 알람·미리 알림 주황, 타이머 민트
ALARM_COLORS = {"time": QColor("#FF9F43"), "pre": QColor("#FF9F43"), "timer": QColor("#00D1A7")}
_STACK: list["GameNotice"] = []  # 지금 떠 있는 알림(뜬 순서)

SIZES = {"normal": {"px": 14, "pad_w": 34, "pad_h": 12, "dot_x": 12, "text_x": 21},
         "large": {"px": 22, "pad_w": 52, "pad_h": 18, "dot_x": 18, "text_x": 32}}


def screen_rect_for_hwnd(hwnd):
    """게임 창이 있는 모니터의 화면 사각형(논리 좌표). 못 구하면 None — 블랙박스 메시지와 같은 자리 규칙."""
    if not hwnd:
        return None
    from ..system.blackbox_events import window_rect
    rect = window_rect(hwnd)  # 게임 창이 있는 모니터의 상단 중앙에 띄운다
    if rect is None:
        return None
    from PySide6.QtCore import QPoint
    try:
        from .dpi import to_logical
        # GetWindowRect는 물리 픽셀: 다른 오버레이처럼 논리 좌표로 바꾼 뒤 화면을 찾는다(혼합 배율 대응).
        left, top, width, height = to_logical(rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1])
        screen = QGuiApplication.screenAt(QPoint(left + width // 2, top + height // 2))
    except Exception:
        return None
    return screen.geometry() if screen is not None else None


def _base_y(screen_rect: QRect) -> int:
    return screen_rect.y() + max(24, screen_rect.height() // 14)


def _reflow() -> None:
    """같은 화면에 뜬 알림을 위에서부터 쌓는다(맨 위 우선: stack_rank가 낮은 것 → 뜬 순서)."""
    live = [n for n in _STACK if n.isVisible()]
    _STACK[:] = live
    columns: dict[tuple, int] = {}
    for notice in sorted(live, key=lambda n: (n.stack_rank, n._order)):
        sr = notice._screen_rect
        if sr is None:
            continue
        key = (sr.x(), sr.y(), sr.width(), sr.height())
        y = columns.get(key, _base_y(sr))
        notice.move(sr.x() + (sr.width() - notice.width()) // 2, y)
        columns[key] = y + notice.height() + GAP


class GameNotice(QWidget):
    _counter = 0
    stack_rank = 1  # 블랙박스 메시지는 0(늘 맨 위 — 예전 자리 그대로)

    def __init__(self, *, size: str = "large", colors: dict | None = None, show_ms: int = 5000) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        from . import overlay_capture
        overlay_capture.watch(self)  # 0.37.1: 뜰 때마다 판독 캡처에서 빼기(이 창에만 필터)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._size = SIZES[size]
        self._colors = dict(colors or {})
        self._show_ms = show_ms
        self._text, self._kind = "", next(iter(self._colors), "")
        self._screen_rect = None
        self._order = 0
        self.sticky = False  # 진행 알림은 끝날 때까지 유지(타이머 없음)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide_message)
        self._font = QFont()
        self._font.setPixelSize(self._size["px"])
        self._font.setWeight(QFont.Weight.Bold)

    def text(self) -> str:
        return self._text

    def kind(self) -> str:
        return self._kind

    def show_message(self, text, kind=None, screen_rect=None, sticky=False):
        """sticky면 끝날 때까지 유지, 아니면 show_ms 뒤 사라짐."""
        self._text, self.sticky = text, sticky
        if kind is not None:
            self._kind = kind
        metrics = QFontMetricsF(self._font)
        self.resize(round(metrics.horizontalAdvance(text) + self._size["pad_w"]),
                    round(metrics.height() + self._size["pad_h"]))
        if screen_rect is None:
            screen = QGuiApplication.primaryScreen()
            screen_rect = screen.geometry() if screen is not None else None
        self._screen_rect = screen_rect
        if screen_rect is not None:
            self.move(screen_rect.x() + (screen_rect.width() - self.width()) // 2, _base_y(screen_rect))
        from ..system.clickthrough import set_click_through
        set_click_through(self, True)
        self.update()
        if self not in _STACK:
            GameNotice._counter += 1
            self._order = GameNotice._counter
            _STACK.append(self)
        self.show()
        _reflow()
        if sticky:
            self._timer.stop()
        else:
            self._timer.start(self._show_ms)

    def hide_message(self):
        self.sticky = False
        self._timer.stop()
        self.hide()
        if self in _STACK:
            _STACK.remove(self)
        _reflow()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self in _STACK:
            _STACK.remove(self)
            _reflow()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        large = self._size is SIZES["large"]
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        accent = self._colors.get(self._kind) or next(iter(self._colors.values()), QColor("#00d1a7"))
        painter.setBrush(QColor(0, 0, 0, 165 if not large else 190))
        if large:  # 크게: 종류 색 테두리(알람 주황·타이머 민트)
            border = QColor(accent)
            border.setAlpha(210)
            painter.setPen(QPen(border, 2))
            rect = rect.adjusted(1, 1, -1, -1)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        center = QPointF(rect.x() + self._size["dot_x"], rect.center().y())
        dot = rect.height() * .22
        if large:  # 고리 점
            painter.setPen(QPen(accent, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(center, dot / 2, dot / 2)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawEllipse(center, dot / 2, dot / 2)
        metrics = QFontMetricsF(self._font)
        path = QPainterPath()
        path.addText(QPointF(rect.x() + self._size["text_x"], rect.center().y() + metrics.ascent() / 2 - metrics.descent() / 2),
                     self._font, self._text)
        painter.setPen(QPen(QColor(0, 0, 0, 220), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        painter.drawPath(path)
        painter.end()
