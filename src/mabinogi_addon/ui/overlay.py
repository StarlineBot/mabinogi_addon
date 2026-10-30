"""버프 오버레이 (기획서 3.4 / 5.1).

프레임리스·배경 투명·항상 위·포커스 안 뺏음. 매칭된 버프를 등록 순서대로 가로로
나열하고, 지속시간 표시를 켠 버프는 아이콘 아래 남은 시간을 그린다. 남은 시간이
1분 미만(<60초)이면 숫자를 빨갛게 표시한다(점멸은 쓰지 않는다 — 산만함).
배율 50~300%(표시에만 적용). 클릭 통과는 Windows에서 system 헬퍼로 별도 적용.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..duration import format_duration

# 남은 시간이 이 값 미만이면 숫자를 빨갛게(임박 경고). 점멸 대신 색으로 알린다.
WARN_SEC = 60.0


def overlay_spec(
    entries, show_duration: dict[str, bool]
) -> list[tuple[str, str | None, bool, bool]]:
    """엔진 결과(OverlayEntry) → (buff_id, 시간 문자열|None, 임박여부, 사라짐여부) 목록.

    - 임박여부 = 남은 시간이 1분 미만(<60초)인지. True면 숫자를 빨갛게 그린다.
    - 사라짐여부 = 사라짐 경고 대상(디버프가 보스에서 떨어짐). True면 빨간 테두리+X.
    지속시간 표시를 끈 버프나 판독값 없는 버프는 시간 None(칸만 비움, 임박 False).
    """
    specs: list[tuple[str, str | None, bool, bool]] = []
    for entry in entries:
        show = show_duration.get(entry.buff_id, True)
        has_time = show and entry.remaining is not None
        text = format_duration(entry.remaining) if has_time else None
        warn = has_time and entry.remaining < WARN_SEC
        specs.append((entry.buff_id, text, warn, entry.gone))
    return specs

_ICON_BASE = 40  # 100% 기준 아이콘 변
_GAP_BASE = 3  # 아이콘 사이 간격(100% 기준)
_TEXT_BASE = 16  # 아이콘 아래 글자 칸 높이
_PAD = 6


@dataclass
class OverlayItem:
    pixmap: QPixmap  # 표시 아이콘(원본 — 그릴 때 배율 적용)
    duration_text: str | None  # None=칸만 비움(아이콘 높이 맞춤)
    warn: bool = False  # 남은 시간 1분 미만 → 숫자 빨갛게
    gone: bool = False  # 사라짐 경고: 아이콘 흐리게 + 빨간 테두리 + X(잠깐 표시)


class BuffOverlay(QWidget):
    moved = Signal()  # 드래그로 위치가 바뀜 → main이 저장

    def __init__(self, scale: float = 1.5, placeholder_name: str = "버프") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        self._name = placeholder_name  # 플레이스홀더 안내 문구용
        self._scale = scale
        self._items: list[OverlayItem] = []
        self._locked = False  # 고정=클릭 통과, 해제=드래그 이동
        self._drag_offset = None
        self._opacity = 1.0  # 창 전체 불투명도(명세 15절) — 잠금·클릭 통과와 무관하게 같은 값

    # ---- 고정/이동 ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        self.setWindowOpacity(self._opacity)  # 확장 스타일을 바꾼 뒤에도 같은 불투명도(Windows 레이어드 창)
        self._relayout()  # 해제 시 비어 있어도 위치 잡게 플레이스홀더 크기

    @property
    def locked(self) -> bool:
        return self._locked

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

    def mouseReleaseEvent(self, event) -> None:
        was_dragging = self._drag_offset is not None
        self._drag_offset = None
        if was_dragging:
            from . import grid

            grid.hide_guide()
            self.moved.emit()

    def set_opacity(self, percent: int) -> None:
        """창 전체 불투명도(%) — 20~100. 바꾸는 즉시 반영(Qt setWindowOpacity)."""
        self._opacity = max(20, min(100, int(percent))) / 100
        self.setWindowOpacity(self._opacity)

    @property
    def opacity_percent(self) -> int:
        return round(self._opacity * 100)

    def set_scale(self, scale: float) -> None:
        self._scale = max(0.5, min(3.0, scale))
        self._relayout()

    def set_items(self, items: list[OverlayItem]) -> None:
        self._items = items
        self._relayout()

    # ---- 레이아웃 ----
    def _metrics(self) -> tuple[int, int, int]:
        icon = int(_ICON_BASE * self._scale)
        gap = int(_GAP_BASE * self._scale)
        text_h = int(_TEXT_BASE * self._scale)
        return icon, gap, text_h

    def _relayout(self) -> None:
        icon, gap, text_h = self._metrics()
        n = len(self._items)
        if n == 0:
            if self._locked:
                self.resize(1, 1)  # 고정+비어있음 → 보이지 않게
            else:
                self.resize(220, 56)  # 해제 시 드래그용 플레이스홀더
            self.update()
            return
        width = n * icon + (n - 1) * gap + 2 * _PAD
        height = icon + text_h + 2 * _PAD
        self.resize(width, height)
        self.update()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        if not self._items:
            if not self._locked:
                self._paint_placeholder()
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
            # 사라짐 경고 칸도 아이콘을 또렷하게(어떤 버프/디버프였는지 보이게) 그린다.
            # 살짝만 흐리게(0.7) + 가운데 비운 모서리 X로 '떨어짐'을 표시한다.
            painter.setOpacity(0.7 if item.gone else 1.0)
            scaled = item.pixmap.scaled(
                icon,
                icon,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,  # Nearest(선명)
            )
            painter.drawPixmap(x, _PAD, scaled)
            painter.setOpacity(1.0)

            if item.gone:
                self._draw_gone(painter, QRect(x, _PAD, icon, icon))
            elif item.duration_text:
                rect = QRect(x, _PAD + icon, icon, text_h)
                # 1분 미만(warn)이면 빨강, 아니면 흰색
                self._draw_text(painter, rect, item.duration_text, warn=item.warn)
            x += icon + gap
        painter.end()

    def _paint_placeholder(self) -> None:
        """고정 해제 + 비어있을 때 드래그용 안내 박스."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        painter.setPen(QColor(0, 209, 167))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            self.rect(),
            Qt.AlignmentFlag.AlignCenter,
            f"{self._name} 오버레이\n(드래그로 이동 · 고정하면 사라짐)",
        )
        painter.end()

    def _draw_text(
        self, painter: QPainter, rect: QRect, text: str, *, warn: bool = False
    ) -> None:
        align = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        # 외곽선(검정) 후 본문 → 어떤 배경에서도 읽힘. 1분 미만이면 본문을 빨강으로.
        painter.setPen(QColor(0, 0, 0))
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            painter.drawText(rect.translated(dx, dy), align, text)
        painter.setPen(QColor(255, 80, 80) if warn else QColor(255, 255, 255))
        painter.drawText(rect, align, text)

    def _draw_gone(self, painter: QPainter, rect: QRect) -> None:
        """사라짐 경고: 빨간 테두리 + 네 모서리에만 짧은 X 자국(가운데는 비워 아이콘이
        보이게). '사라진' 느낌은 주면서 어떤 버프/디버프가 떨어졌는지 바로 알아본다."""
        w = max(2, int(rect.width() * 0.08))  # 배율 따라 선 두께
        pen = QPen(QColor(255, 60, 60), w)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        # 테두리(선 두께만큼 안쪽으로 당겨 잘림 방지)
        inset = rect.adjusted(w // 2, w // 2, -(w // 2 + 1), -(w // 2 + 1))
        painter.drawRect(inset)
        # 네 모서리에서 가운데로 짧게 그은 X 자국(가운데는 비움 → 아이콘이 보인다)
        arm = int(rect.width() * 0.28)
        for corner, dx, dy in (
            (inset.topLeft(), 1, 1),
            (inset.topRight(), -1, 1),
            (inset.bottomLeft(), 1, -1),
            (inset.bottomRight(), -1, -1),
        ):
            painter.drawLine(
                corner.x(), corner.y(), corner.x() + dx * arm, corner.y() + dy * arm
            )
