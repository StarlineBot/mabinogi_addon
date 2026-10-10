"""보스 패턴 경고 오버레이 (기획서 12.5).

화면에 큰 글씨로 경고를 띄우고 수 초 후 사라진다. 검은 외곽선 + 밝은 글씨로 게임
배경 위에서도 또렷하게.

위치는 사용자가 바꿀 수 있다(다음 패턴 목록과 같은 규칙):
- 고정(평소): 배경 투명 + 클릭 통과. 경고가 올 때만 저장된 위치에 잠깐 떴다 사라진다.
- 해제(위치 조정): 샘플 경고가 계속 떠서 끌어 옮길 수 있다(미리보기 겸용). 이때는
  실제 경고가 와도 샘플을 유지한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
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

# 글씨 = 화면높이 / FONT_DIV (크면 작아짐), 최소 FONT_MIN.
_FONT_DIV = 28
_FONT_MIN = 24
_PAD_X = 16
_PAD_Y = 9
_HEADER_H = 18  # 해제 상태 상단 이동 안내
_HINT = "⠿ 끌어서 이동 · 고정하면 경고만 표시"
_SAMPLE = "고목의 페타크 85% 패턴 준비"


class PatternWarningOverlay(QWidget):
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
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._locked = True
        self._text = ""
        self._drag_offset = None
        self._font_px = self._default_font_px()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)

    @staticmethod
    def _default_font_px() -> int:
        screen = QGuiApplication.primaryScreen()
        h = screen.geometry().height() if screen is not None else 1080
        return max(_FONT_MIN, h // _FONT_DIV)

    @property
    def locked(self) -> bool:
        return self._locked

    # ---- 경고 표시(고정 상태에서만) ----
    def show_message(self, text: str, duration_ms: int = 3000) -> None:
        if not self._locked:
            return  # 위치 조정 중엔 샘플 유지
        self._text = text
        self._relayout()
        self.show()
        self.raise_()
        from ..system.clickthrough import set_click_through

        set_click_through(self, True)  # 게임 조작 막지 않게 클릭 통과
        self._timer.start(duration_ms)
        self.update()

    def _on_timeout(self) -> None:
        self._text = ""
        self.hide()

    # ---- 고정/해제 ----
    def set_locked(self, locked: bool) -> None:
        self._locked = locked
        self.setCursor(
            Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.SizeAllCursor
        )
        from ..system.clickthrough import set_click_through

        set_click_through(self, locked)
        if locked:
            self._timer.stop()
            self._text = ""
            self.hide()
        else:
            # 위치 조정 모드: 샘플을 계속 띄워 끌어 옮기게 한다(미리보기 겸용).
            self._timer.stop()
            self._text = _SAMPLE
            self._relayout()
            self.show()
            self.raise_()
        self.update()

    def _display_text(self) -> str:
        return self._text or (_SAMPLE if not self._locked else "")

    def _relayout(self) -> None:
        font = QFont()
        font.setPixelSize(self._font_px)
        font.setBold(True)
        fm = QFontMetrics(font)
        text = self._display_text()
        tw = fm.horizontalAdvance(text) if text else fm.horizontalAdvance(_SAMPLE)
        th = fm.height()
        header = 0 if self._locked else _HEADER_H
        self.resize(tw + _PAD_X * 2, th + _PAD_Y * 2 + header)

    # ---- 드래그 이동(해제 상태) ----
    def mousePressEvent(self, event) -> None:
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if not self._locked and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, _event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self.moved.emit()

    # ---- 그리기 ----
    def paintEvent(self, _event) -> None:
        text = self._display_text()
        if not text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPixelSize(self._font_px)
        font.setBold(True)
        fm = QFontMetrics(font)
        header = 0 if self._locked else _HEADER_H

        # 가독성 배경 띠(은은한 어두운 반투명)
        band = self.rect().adjusted(0, header, 0, 0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(band, 10, 10)

        if not self._locked:
            # 이동 안내 + 드래그 가능 테두리(해제 상태)
            p.setPen(QColor(0, 209, 167))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(band, 10, 10)
            hint_font = QFont()
            hint_font.setPixelSize(11)
            p.setFont(hint_font)
            p.setPen(QColor(150, 200, 190))
            p.drawText(
                _PAD_X, 0, self.width() - _PAD_X, _HEADER_H,
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                _HINT,
            )

        # 외곽선(검정) + 글씨(밝은 노랑) — 게임 위에서도 또렷
        p.setFont(font)
        baseline = header + _PAD_Y + fm.ascent()
        path = QPainterPath()
        path.addText(float(_PAD_X), float(baseline), font, text)
        p.setPen(QPen(QColor(0, 0, 0, 230), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFD54A"))
        p.drawPath(path)
        p.end()
