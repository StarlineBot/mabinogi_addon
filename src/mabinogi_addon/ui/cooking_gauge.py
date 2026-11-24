"""요리 비율 그림(docs/cooking-spec.md 5·6절) — 상세의 요리창 그림과 게임 위 비율 바.

- 상세: 게임 기본 인터페이스(하늘 유리) 요리창 그림(assets/cooking/cook_ui_reference.png)의 게이지 바
  (기준 좌표 안쪽 x 39~523, y 111~124)를 비율대로 재료 색으로 채우고, 재료 경계마다 흰 점선(바 아래 → 버튼 줄 위).
- 게임 위: 바 + 경계 점선만. 첫 크기 바 245×10px(테두리 포함), 점선은 바 위로 바 높이의 약 4배.
  끌어서 요리창 바에 맞추고(격자 맞춤 없이 1px 단위), 휠로 크기, 잠그면 클릭 통과 — 다른 오버레이와 같은 조작.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .. import cooking, paths

# 재료 색(목록 색 점과 같은 순서). 게임 바 위에서도 잘 보이는 밝은 색
COLORS = ("#EBC351", "#E3665C", "#3FC28E", "#5BA4EC", "#B381E3", "#EE9A50", "#7CD3DB")
PANEL = (18, 28, 548, 248)            # 기준 그림에서 요리창 패널(x0, y0, x1, y1)
GAUGE = (39, 109, 523, 125)           # 게이지 안쪽(x0, y0, x1, y1 — 끝 제외). 명세 5절 x 39~523·y 111~124 + 위아래 번진 줄
_BOTTOM_EDGE = (QColor(19, 27, 35), QColor(56, 81, 105))  # 게이지 바로 아래 두 줄(기준 그림 빈 곳 색)
DASH_TOP = 48                         # 버튼 줄 위(점선 시작)


def color(index: int) -> QColor:
    return QColor(COLORS[index % len(COLORS)])


def _dash_pen(width: float = 1.5) -> QPen:
    pen = QPen(QColor(255, 255, 255), width, Qt.PenStyle.CustomDashLine)
    pen.setDashPattern([3, 2])
    return pen


def detail_pixmap(dish: cooking.Dish | None) -> QPixmap:
    """요리창 패널 그림 + 비율 게이지 + 경계 점선(요리가 없으면 빈 게이지)."""
    base = QPixmap(str(paths.resource_dir() / "cooking" / "cook_ui_reference.png"))
    x0, y0, x1, y1 = PANEL
    pm = base.copy(x0, y0, x1 - x0, y1 - y0)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    gx0, gy0, gx1, gy1 = (GAUGE[0] - x0, GAUGE[1] - y0, GAUGE[2] - x0, GAUGE[3] - y0)
    width = gx1 - gx0
    p.fillRect(QRectF(gx0, gy0, width, gy1 - gy0), QColor(0, 0, 0))  # 그림에 그려진 예시 채움을 지움
    for dy, edge in enumerate(_BOTTOM_EDGE):  # 아래 테두리 줄에 번진 예시 색도 지움(채움 없는 곳의 테두리 색으로)
        p.fillRect(QRectF(gx0, gy1 + dy, width, 1), edge)
    if dish is not None:
        left = gx0
        for i, r in enumerate(cooking.ratios(dish.recipe)):
            p.fillRect(QRectF(left, gy0, width * r, gy1 - gy0), color(i))
            left += width * r
        p.setPen(_dash_pen())
        for b in cooking.boundaries(dish.recipe):
            x = gx0 + width * b
            p.drawLine(QPointF(x, DASH_TOP - y0), QPointF(x, gy1))
    p.end()
    return pm


BAR_W, BAR_H = 245, 10   # 첫 크기(테두리 포함, 실게임 측정 — 명세 6절)
DASH_FACTOR = 4          # 점선 길이 = 바 높이 × 4
SCALE_MIN, SCALE_MAX, SCALE_STEP = 0.5, 3.0, 0.05


class CookingBarOverlay(QWidget):
    """게임 위 비율 바 — 바 + 경계 점선만. 끌기(격자 없이 1px)·휠 크기·잠금(클릭 통과)."""
    moved = Signal()     # 끌어서 위치가 바뀜 → 저장
    scaled = Signal()    # 휠로 크기가 바뀜 → 저장

    def __init__(self, scale: float = 1.0, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        from . import overlay_capture
        overlay_capture.watch(self)  # 판독 캡처에서 빼기(다른 오버레이와 같음)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._dish: cooking.Dish | None = None
        self._scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        self._locked = False
        self._drag = None
        self._opacity = 0.5   # 바 불투명도(0.56.1 기본 50%) — 요리 탭이 저장값으로 바꿈
        self._relayout()

    # ---- 값 ----
    def set_opacity(self, percent: int) -> None:
        """바만 비치게(20~100 %) — 경계 점선은 그대로. setWindowOpacity는 점선까지 흐려져서 안 씀."""
        value = max(0.2, min(1.0, percent / 100))
        if value != self._opacity:
            self._opacity = value
            self.update()

    def opacity(self) -> float:
        return self._opacity

    def set_dish(self, dish: cooking.Dish | None) -> None:
        self._dish = dish
        self.update()

    @property
    def dish(self):
        return self._dish

    @property
    def scale(self) -> float:
        return self._scale

    def set_scale(self, scale: float) -> None:
        self._scale = round(max(SCALE_MIN, min(SCALE_MAX, scale)), 2)
        self._relayout()

    def bar_size(self) -> tuple[int, int]:
        return round(BAR_W * self._scale), max(2, round(BAR_H * self._scale))

    def _relayout(self) -> None:
        bw, bh = self.bar_size()
        bottom_left = self.geometry().bottomLeft()
        self.resize(bw, bh * (DASH_FACTOR + 1))
        if self.isVisible():
            self.move(bottom_left.x(), bottom_left.y() - self.height() + 1)  # 바(아래쪽) 자리를 그대로 두고 크기만
        self.update()

    # ---- 잠금·끌기·휠(다른 오버레이와 같은 조작) ----
    def set_locked(self, locked: bool) -> None:
        if locked:
            from . import grid
            grid.owner_locked(self)
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through
        set_click_through(self, locked)
        self.update()

    @property
    def dragging(self) -> bool:
        return self._drag is not None

    @property
    def locked(self) -> bool:
        return self._locked

    # 끌기는 격자 맞춤 없이 1px 단위(사용자 결정 11-19): 격자는 '화면 중앙 + 칸의 배수' 자리에만 서서 게임 요리창 바에
    # 정확히 못 맞춘다 → gridSnap 설정이 켜져 있어도 이 바만 자유 이동, 격자 안내선도 띄우지 않음(다른 오버레이는 그대로).
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag is not None:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._drag is not None:
            self._drag = None
            self.moved.emit()

    def wheelEvent(self, event) -> None:
        if self._locked:
            event.ignore()
            return
        step = SCALE_STEP if event.angleDelta().y() > 0 else -SCALE_STEP
        before = self._scale
        self.set_scale(self._scale + step)
        if self._scale != before:
            self.scaled.emit()
        event.accept()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        bw, bh = self.bar_size()
        top = self.height() - bh
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        bar = QRectF(0, top, bw, bh)
        inner = bar.adjusted(1, 1, -1, -1)
        # 바(테두리·바탕·재료 칸)만 불투명도 — 게임 게이지가 차는 게 비쳐 보이게(사용자 11-24). 경계 점선은 늘 100%.
        # 바를 한 장(불투명)으로 먼저 그린 뒤 그 장을 불투명도로 얹음 — 칸마다 따로 흐리게 하면 바탕과 겹쳐 더 진해짐
        layer = QImage(bw, bh, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        whole = QRectF(0, 0, bw, bh)
        body = whole.adjusted(1, 1, -1, -1)
        lp.fillRect(whole, QColor(20, 20, 24, 230))  # 테두리(1px)
        lp.fillRect(body, QColor(0, 0, 0, 230))
        if self._dish is not None:
            left = body.left()
            for i, r in enumerate(cooking.ratios(self._dish.recipe)):
                lp.fillRect(QRectF(left, body.top(), body.width() * r, body.height()), color(i))
                left += body.width() * r
        lp.end()
        p.setOpacity(self._opacity)
        p.drawImage(bar.topLeft(), layer)
        p.setOpacity(1.0)
        if self._dish is not None:
            p.setPen(_dash_pen(max(1.0, self._scale)))
            for b in cooking.boundaries(self._dish.recipe):
                x = round(inner.left() + inner.width() * b)
                p.drawLine(QPoint(x, 0), QPoint(x, self.height() - 1))
        if not self._locked:  # 잠금 해제 중엔 '끌 수 있음' 옅은 테두리(다른 오버레이와 같음)
            p.setPen(QPen(QColor(0, 209, 167), 1, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()
