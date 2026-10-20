"""Source-run loading screen, matching the bootloader layout without replacing it."""

from __future__ import annotations

import logging
import random
import unicodedata

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from .. import paths
from ..startup_content import MESSAGES

_log = logging.getLogger("mabinogi_addon.startup")


class Splash(QWidget):
    """Shared fixed layout; only normal startup creates a dialogue timer."""

    def __init__(self, *, typing: bool = True, status: str = "") -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setFixedSize(440, 240)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._background = QPixmap(str(paths.resource_dir() / "startup_background.png"))
        self.msg = QLabel(self)
        self.msg.setGeometry(24, 198, 392, 34)
        self.msg.setWordWrap(True)
        self.msg.setTextFormat(Qt.TextFormat.PlainText)
        self.msg.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        font = QFont("Malgun Gothic")
        font.setPixelSize(13)
        self.msg.setFont(font)
        self.msg.setStyleSheet("color:#e5e7eb; background:transparent;")
        self._timer = None
        self._mode = "status"
        if not typing:
            self._safe_show(status)
            return
        self._messages = tuple(
            unicodedata.normalize("NFC", message.strip())
            for message in MESSAGES
            if isinstance(message, str) and message.strip()
        )
        self._previous = None
        self._text = ""
        self._index = 0
        self._mode = "dialogue"
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._choose()
        if self._mode == "dialogue":
            self._timer.start(60)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._background)

    def _show_text(self, text: str) -> None:
        # Keep the shared slots fixed even with prerelease/build version suffixes.
        font = self.msg.font()
        for pixels in range(13, 8, -1):
            font.setPixelSize(pixels)
            bounds = QFontMetrics(font).boundingRect(
                self.msg.rect(), int(Qt.TextFlag.TextWordWrap), text
            )
            if (
                bounds.width() <= self.msg.width()
                and bounds.height() <= self.msg.height()
            ):
                break
        self.msg.setFont(font)
        self.msg.setText(text)

    def _safe_show(self, text: str) -> None:
        try:
            self._show_text(text)
        except Exception:
            if self._timer is not None:
                self._timer.stop()
            self._mode = "fallback"
            _log.info("시작 대사 표시 실패(기본 문구 사용)", exc_info=True)
            try:
                self._show_text("시작하는 중")
            except Exception:
                pass

    def _choose(self) -> None:
        if not self._messages:
            self._mode = "fallback"
            self._safe_show("시작하는 중")
            return
        options = [text for text in self._messages if text != self._previous]
        self._text = random.choice(options or self._messages)
        self._previous = self._text
        self._index = 0
        self._safe_show("")

    def _tick(self) -> None:
        # A queued timeout after a status/close must not overwrite that state.
        if self._mode != "dialogue":
            return
        if self._index == len(self._text):
            self._choose()
        else:
            self._index += 1
            self._safe_show(self._text[: self._index])
        if self._mode == "dialogue":
            self._timer.start(2000 if self._index == len(self._text) else 60)

    def step(self, pct: int, msg: str | None = None) -> None:
        if self._mode == "closed":
            return
        if msg:
            if self._timer is not None:
                self._timer.stop()
            self._mode = "status"
            self._safe_show(msg)
        elif self._mode == "status" and self._timer is not None:
            self._mode = "dialogue"
            self._choose()
            if self._mode == "dialogue":
                self._timer.start(60)
        # Internal stages neither pick another dialogue nor restart its timer.
        QApplication.processEvents()

    def closeEvent(self, event) -> None:
        self._mode = "closed"
        if self._timer is not None:
            self._timer.stop()
        super().closeEvent(event)

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
