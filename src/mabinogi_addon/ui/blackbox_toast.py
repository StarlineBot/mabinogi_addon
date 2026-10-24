"""블랙박스 저장 반응을 게임 화면 위에 잠깐 보여주는 오버레이(블랙박스 명세 11.1).

항상 위·포커스를 빼앗지 않음·클릭 통과. 기본 위치는 게임 창이 있는 화면의 상단 중앙이며 약 3초 뒤 사라진다.
완료 문구는 실제 파일 검증을 마친 저장 결과에서만 띄운다(3절). 게임 창만 캡처하므로 녹화에는 원칙상 찍히지 않는다.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

SHOW_MS = 3000
_COLORS = {'pending': QColor('#00d1a7'), 'done': QColor('#2ecc71'), 'failed': QColor('#ff8a65')}


def format_duration(us) -> str:
    seconds = max(0, int(us or 0) // 1_000_000)
    minutes, seconds = divmod(seconds, 60)
    return f'{minutes}분 {seconds}초' if minutes else f'{seconds}초'


class BlackboxToast(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._text, self._kind = '', 'pending'
        self.sticky = False  # 진행 알림은 저장이 끝날 때까지 유지(타이머 없음)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._font = QFont()
        self._font.setPixelSize(14)  # 0.14.2 사용자 확정(A안): 작게, 볼드 유지
        self._font.setWeight(QFont.Weight.Bold)

    def text(self) -> str:
        return self._text

    def kind(self) -> str:
        return self._kind

    def show_message(self, text, kind='pending', screen_rect=None, sticky=False):
        """kind: pending(진행) · done(완료) · failed(거부·실패). sticky면 끝날 때까지 유지, 아니면 SHOW_MS 뒤 사라짐."""
        self._text, self._kind, self.sticky = text, kind, sticky
        metrics = QFontMetricsF(self._font)
        self.resize(round(metrics.horizontalAdvance(text) + 34), round(metrics.height() + 12))
        if screen_rect is None:
            screen = QGuiApplication.primaryScreen()
            screen_rect = screen.geometry() if screen is not None else None
        if screen_rect is not None:
            self.move(screen_rect.x() + (screen_rect.width() - self.width()) // 2,
                      screen_rect.y() + max(24, screen_rect.height() // 14))
        from ..system.clickthrough import set_click_through
        set_click_through(self, True)
        self.update()
        self.show()
        if sticky:
            self._timer.stop()
        else:
            self._timer.start(SHOW_MS)

    def hide_message(self):
        self.sticky = False
        self._timer.stop()
        self.hide()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 165))
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        accent = _COLORS.get(self._kind, _COLORS['pending'])
        painter.setBrush(accent)
        dot = rect.height() * .22
        painter.drawEllipse(QPointF(rect.x() + 12, rect.center().y()), dot / 2, dot / 2)
        metrics = QFontMetricsF(self._font)
        path = QPainterPath()
        path.addText(QPointF(rect.x() + 21, rect.center().y() + metrics.ascent() / 2 - metrics.descent() / 2),
                     self._font, self._text)
        painter.setPen(QPen(QColor(0, 0, 0, 220), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('white'))
        painter.drawPath(path)
        painter.end()
