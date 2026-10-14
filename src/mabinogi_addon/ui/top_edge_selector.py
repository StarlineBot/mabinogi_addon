"""자동 찾기 결과의 '위 경계'만 조절하는 오버레이 (버프 영역 전용).

버프 목록은 아래로 늘어나므로 **아래=화면 끝**이 고정이고, 좌/우(너비)는 자동 찾기 값이
적절하다. 남는 건 **위 경계**뿐 — 상단 고정(즐겨찾기) 버프를 빼도록 사용자가 '목록 맨 위'를
한 번 찍게 한다. 마우스를 움직이면 위 경계선이 따라오고, 클릭하면 확정(Enter=자동값 그대로,
ESC=취소). 좌표계는 RegionSelector/RegionHighlight와 동일(주 화면 기준 로컬 ↔ 전역).
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_MINT = QColor(0, 224, 180)
_DIM = QColor(0, 0, 0, 110)  # 위 경계 바깥(제외 영역)을 살짝 덮어 강조
_DARK = QColor(18, 24, 32, 235)
_WHITE = QColor(236, 239, 245)


class TopEdgeSelector(QWidget):
    """좌·우·아래는 고정하고 '위 경계'만 마우스로 맞추는 전체화면 오버레이."""

    selected = Signal(int, int, int, int)  # 확정 (x, y, w, h) 전역 좌표
    cancelled = Signal()

    def __init__(self, x: int, w: int, initial_top: int) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self._geo = QGuiApplication.primaryScreen().geometry()
        self._x = int(x - self._geo.x())  # 전역 → 주 화면 로컬
        self._w = int(w)
        self._bottom = int(self._geo.height())  # 아래 = 화면 끝(불변)
        self._top = max(0, min(int(initial_top - self._geo.y()), self._bottom - 10))
        self._auto_top = self._top  # 자동값(Enter로 그대로 확정 — 마우스 이동에 안 흔들림)

    def start(self) -> None:
        self.setGeometry(self._geo)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    def set_top_for_preview(self, y: int) -> None:
        """오프스크린 렌더/테스트용: 위 경계 위치를 직접 지정."""
        self._top = max(0, min(int(y), self._bottom - 10))
        self.update()

    def mouseMoveEvent(self, event) -> None:
        self._top = max(0, min(int(event.position().y()), self._bottom - 10))
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._commit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit_auto()  # Enter = 자동값 그대로(마우스 이동값 아님)

    def _commit(self) -> None:
        """현재 위 경계(마우스로 맞춘 값)로 확정 — 클릭."""
        self._emit(self._top)

    def _commit_auto(self) -> None:
        """자동값으로 확정 — Enter(마우스를 움직였어도 자동 찾기 값 그대로)."""
        self._emit(self._auto_top)

    def _emit(self, top: int) -> None:
        gx = self._x + self._geo.x()
        gy = top + self._geo.y()
        self.selected.emit(int(gx), int(gy), int(self._w), int(self._bottom - top))
        self.close()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # **전체를 아주 옅게 칠한다** — 투명(alpha 0) 픽셀은 Windows에서 클릭·마우스 이동이
        # 그대로 게임으로 통과해, 오버레이가 입력을 못 받는다(RegionSelector와 같은 처리).
        # alpha>0이면 전 영역이 히트테스트에 걸려 클릭/드래그가 오버레이로 들어온다.
        p.fillRect(self.rect(), QColor(0, 0, 0, 12))
        # 위 경계 '바깥'(제외되는 상단 고정 영역)을 더 덮어 '여기는 안 읽음'을 보여준다.
        if self._top > 0:
            p.fillRect(self._x, 0, self._w, self._top, _DIM)
        # 선택 박스(좌·우 고정, 아래=화면 끝, 위=현재 경계) 점선.
        pen = QPen(_MINT, 3)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3.4, 2.2])
        p.setPen(pen)
        p.drawRect(self._x, self._top, self._w, self._bottom - self._top - 1)
        # 위 경계선은 실선 + 좌우로 조금 더 길게(잡는 선 강조).
        p.setPen(QPen(_MINT, 4))
        p.drawLine(self._x - 12, self._top, self._x + self._w + 12, self._top)
        self._draw_hint(p)

    def _draw_hint(self, p: QPainter) -> None:
        title = "버프 목록의 '맨 위'를 클릭하세요 (상단 고정 버프는 빼기)"
        sub = "클릭=여기로 지정 · Enter=자동값 그대로 · ESC=취소 · 아래는 화면 끝까지"
        fm = p.fontMetrics()
        pad = 10
        gap = 4
        box_w = max(fm.horizontalAdvance(title), fm.horizontalAdvance(sub)) + pad * 2
        line_h = fm.height()
        box_h = line_h * 2 + gap + pad * 2
        # 목록을 가리지 않게 박스 '오른쪽'에 둔다(오른쪽 공간 없으면 왼쪽).
        lx = self._x + self._w + 16
        if lx + box_w > self.width() - 8:
            lx = self._x - box_w - 16
        lx = max(8, lx)
        ly = max(8, min(self._top, self._bottom - box_h - 8))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_DARK)
        p.drawRoundedRect(lx, ly, box_w, box_h, 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_MINT, 1))
        p.drawRoundedRect(lx, ly, box_w, box_h, 8, 8)
        p.setPen(_MINT)
        p.drawText(QRect(lx + pad, ly + pad, box_w, line_h),
                   Qt.AlignmentFlag.AlignLeft, title)
        p.setPen(_WHITE)
        p.drawText(QRect(lx + pad, ly + pad + line_h + gap, box_w, line_h),
                   Qt.AlignmentFlag.AlignLeft, sub)
