"""보스 패턴 경고 오버레이 (기획서 12.5).

화면 정중앙에 큰 글씨로 경고를 띄우고 수 초 후 사라진다. 전체 화면을 덮는 투명·최상위
창이지만 **클릭 통과**라 게임 조작을 막지 않는다. 글씨는 검은 외곽선 + 밝은 글씨로
게임 배경 위에서도 또렷하게.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

# 경고 크기·위치(쉽게 조정). 글씨 = 화면높이 / FONT_DIV, 세로 위치 = 화면높이 * Y_FRAC.
_FONT_DIV = 28  # 클수록 작아짐 (화면높이/28 ≈ 51px@1440)
_FONT_MIN = 24
_Y_FRAC = 0.14  # 0=맨 위, 0.5=정중앙 — 상단 쪽


class PatternWarningOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, duration_ms: int = 3000) -> None:
        self._text = text
        self._fit_to_screen()
        self.show()
        self.raise_()
        from ..system.clickthrough import set_click_through

        set_click_through(self, True)  # 게임 조작 막지 않게 클릭 통과
        self._timer.start(duration_ms)
        self.update()

    def _fit_to_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def paintEvent(self, _event) -> None:
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont()
        font.setPixelSize(max(_FONT_MIN, self.height() // _FONT_DIV))
        font.setBold(True)
        p.setFont(font)
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._text)
        th = fm.height()
        cx = self.width() / 2.0
        cy = self.height() * _Y_FRAC

        # 가독성 배경 띠(은은한 어두운 반투명)
        pad_x, pad_y = 16, 9
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(
            int(cx - tw / 2 - pad_x),
            int(cy - th / 2 - pad_y),
            tw + 2 * pad_x,
            th + 2 * pad_y,
            10,
            10,
        )

        # 외곽선(검정) + 글씨(밝은 노랑) — 게임 위에서도 또렷
        path = QPainterPath()
        baseline = cy + fm.ascent() / 2.0 - fm.descent() / 2.0
        path.addText(cx - tw / 2.0, baseline, font, self._text)
        p.setPen(QPen(QColor(0, 0, 0, 230), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD54A"))
        p.drawPath(path)
        p.end()
