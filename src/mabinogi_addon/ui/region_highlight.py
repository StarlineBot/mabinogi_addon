"""영역 확인 하이라이트 (기획서 5.2 보조).

영역 지정 직후(또는 '영역 보기' 버튼) 실제 화면 그 자리에 **굵은 점선**으로 잡힌
영역을 잠깐 그려, 아이콘·시간 등이 영역 안에 제대로 들어왔는지 눈으로 확인하게 한다.

- 전체화면 투명 오버레이 + **클릭 통과**(게임 조작을 막지 않음)
- 포커스를 뺏지 않고(ShowWithoutActivating) 지정 시간 뒤 자동으로 닫힘
- 좌표계는 RegionSelector와 동일: 저장된 전역 좌표 → 주 화면 기준 로컬로 환산
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

_MINT = QColor(0, 224, 180)
_DARK = QColor(18, 24, 32, 235)
_WHITE = QColor(236, 239, 245)


class RegionHighlight(QWidget):
    """화면 위에 영역을 굵은 점선으로 잠깐 표시하는 클릭 통과 오버레이."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput,  # 클릭 통과(입력 안 받음)
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._rect = QRect()
        self._title = ""
        self._sub = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.close)

    def flash(
        self,
        x: int,
        y: int,
        w: int,
        h: int,
        title: str,
        sub: str = "",
        msec: int = 2000,
    ) -> None:
        """전역 좌표 (x, y, w, h) 영역을 점선으로 msec밀리초 동안 표시."""
        geo = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geo)
        # 저장된 전역 좌표 → 주 화면 로컬 좌표(RegionSelector와 동일한 환산).
        self._rect = QRect(x - geo.x(), y - geo.y(), w, h)
        self._title = title
        self._sub = sub
        self.update()
        self.show()
        self.raise_()
        if msec > 0:
            self._timer.start(msec)
        else:
            self._timer.stop()

    def paintEvent(self, _event) -> None:
        if self._rect.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        # 굵은 점선 테두리(안쪽은 비워 원래 화면이 보이게 둔다).
        pen = QPen(_MINT, 5)
        pen.setStyle(Qt.PenStyle.CustomDashLine)
        pen.setDashPattern([3.4, 2.2])  # (width 배수) 긴 선 · 짧은 공백
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawRect(self._rect)
        self._draw_label(p)

    def _draw_label(self, p: QPainter) -> None:
        """영역 위(공간 없으면 아래)에 '정답 기준' 라벨 알약을 그린다."""
        fm = p.fontMetrics()
        pad = 10
        gap = 4
        tw = fm.horizontalAdvance(self._title)
        sw = fm.horizontalAdvance(self._sub) if self._sub else 0
        box_w = max(tw, sw) + pad * 2
        line_h = fm.height()
        box_h = line_h + (line_h + gap if self._sub else 0) + pad * 2 - gap
        lx = self._rect.left()
        ly = self._rect.top() - box_h - 8
        if ly < 4:  # 위에 공간 없으면 영역 아래로
            ly = self._rect.bottom() + 8
        lx = max(4, min(lx, self.width() - box_w - 4))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_DARK)
        p.drawRoundedRect(lx, ly, box_w, box_h, 8, 8)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_MINT, 1))
        p.drawRoundedRect(lx, ly, box_w, box_h, 8, 8)

        ty = ly + pad
        p.setPen(_MINT)
        p.drawText(QRect(lx + pad, ty, box_w, line_h),
                   Qt.AlignmentFlag.AlignLeft, self._title)
        if self._sub:
            p.setPen(_WHITE)
            p.drawText(QRect(lx + pad, ty + line_h + gap, box_w, line_h),
                       Qt.AlignmentFlag.AlignLeft, self._sub)
