"""본창 내부 제작자 얼굴/말풍선. 게임 오버레이와 재생기는 소유하지 않는다."""

import logging
import math
import sys
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QToolButton, QWidget

from ..creator_dialogue import DialogueSession, MAX_CHARS
from ..system.dialogue_visibility import exposed
from .dialogue_feed import DialogueFeed
from .settings_tab import LOGO_IMAGE, PROFILE_IMAGE, _circular

_log = logging.getLogger(__name__)


class SpeechBubble(QWidget):
    dismissed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.text = QLabel(self)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setStyleSheet("color:#24262a; background:transparent; font-size:13px;")
        self.text.setWordWrap(True)
        self.text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.side = "bottom"
        self.hide()

    def measure(self, message):
        if not message or len(message) > MAX_CHARS:
            return 0, 0, False
        self.text.ensurePolished()
        metrics = self.text.fontMetrics()
        width = min(290, metrics.horizontalAdvance(message) + 1)
        layout = QTextLayout(message, self.text.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        height = lines = 0
        layout.beginLayout()
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            height += line.height()
            lines += 1
            if lines > 2:
                break
        layout.endLayout()
        return width, math.ceil(height), lines <= 2

    def set_message(self, message, side="bottom"):
        width, height, fits = self.measure(message)
        if not fits:
            return False
        self.side = side
        self.text.setText(message)
        self.body_width, self.body_height = width + 20, height + 14
        left = 10 if side == "left" else 0
        self.text.setGeometry(left + 10, 7, width, height)
        self.setFixedSize(self.body_width + left, self.body_height + (10 if side == "bottom" else 0))
        self.update()
        return True

    def paintEvent(self, event):
        if not hasattr(self, "body_width"):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        left = 10 if self.side == "left" else 0
        body = QRectF(left + .5, .5, self.body_width - 1, self.body_height - 1)
        path = QPainterPath()
        path.addRoundedRect(body, 7, 7)
        tail = QPainterPath()
        if self.side == "bottom":
            x = self.width() - 24
            tail.moveTo(x - 5.6, body.bottom() - 1)
            tail.lineTo(x, self.height() - 1)
            tail.lineTo(x + 4.2, body.bottom() - 1)
        else:
            y = min(24, self.body_height / 2)
            tail.moveTo(left + 1, y - 4.9)
            tail.lineTo(1, y)
            tail.lineTo(left + 1, y + 4.2)
        tail.closeSubpath()
        p.setPen(QPen(QColor("#a8adb5"), 1))
        p.setBrush(QColor("#f4f5f6"))
        p.drawPath(path.united(tail))
        p.end()

    def mousePressEvent(self, event):
        event.accept()
        self.dismissed.emit()


class CreatorDialogue(QObject):
    def __init__(self, window, *, visibility=exposed, clock=time.monotonic, sound=None):
        super().__init__(window)
        self.window = window
        self._central = window.centralWidget()
        self.visibility = visibility
        self.clock = clock
        self.sound = sound  # 선택적 비동기 재생 콜백. 파일/재생기가 없어도 무음으로 동작.
        self.enabled = window.settings_tab.dialogue_enabled.isChecked()
        self.started = self.closed = False
        self.session_unavailable = self.suspended = False
        self.session_registered = False
        self.previous_tick = None
        self._floating_footer = False
        self.bubble = SpeechBubble(window.centralWidget())
        self.feed = DialogueFeed(self, validate=self._usable_entries)
        self.session = DialogueSession(self.feed.entries)
        self.feed.updated.connect(self._updated)
        self.footer = QWidget(window.centralWidget())
        self.footer.setFixedHeight(64)
        row = QHBoxLayout(self.footer)
        row.setContentsMargins(12, 8, 16, 8)
        row.addStretch()
        self.face = QToolButton()
        self.face.setAutoRaise(True)
        self.face.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.face.setFixedSize(48, 48)
        self.face.setIconSize(QSize(48, 48))
        image = _circular(PROFILE_IMAGE, 48, 3, "#3A0729") or _circular(LOGO_IMAGE, 48, 3, "#3A0729")
        if image is not None:
            self.face.setIcon(QIcon(image))
        self.face.setToolTip("잡담")
        self.face.clicked.connect(self.request)
        row.addWidget(self.face)
        window.centralWidget().layout().addWidget(self.footer)
        self.bubble.dismissed.connect(self.dismiss)
        self.expiry = QTimer(self)
        self.expiry.setTimerType(Qt.TimerType.PreciseTimer)
        self.expiry.setSingleShot(True)
        self.expiry.timeout.connect(self.dismiss)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.deadline = None
        window.settings_tab.creator_avatar.clicked.connect(self.request)
        window.settings_tab.dialogue_enabled.toggled.connect(self.set_enabled)
        for tabs in (window._tabs, window._tracker_tabs, window._convenience_tabs, window._pages):
            tabs.currentChanged.connect(self.refresh)
        window._tabs.widget(3).verticalScrollBar().valueChanged.connect(self._scrolled)
        window.installEventFilter(self)
        window.centralWidget().installEventFilter(self)
        self._tracker_panels = (window.buff_tab, window.debuff_tab)
        for panel in self._tracker_panels:
            panel.installEventFilter(self)
        self.refresh()

    def _updated(self, entries):
        if not self.closed:
            self.session.entries = entries

    def _shortest(self, parts):
        self.bubble.text.ensurePolished()
        metrics = self.bubble.text.fontMetrics()
        selected = [min(choices, key=metrics.horizontalAdvance) for choices in parts]
        if not "".join(selected).strip():
            alternatives = [(metrics.horizontalAdvance(value) - metrics.horizontalAdvance(selected[index]), index, value)
                            for index, choices in enumerate(parts) for value in choices if value.strip()]
            if alternatives:
                _, index, value = min(alternatives)
                selected[index] = value
        return "".join(selected)

    def _usable_entries(self, entries):
        # 조합 전체를 전개하지 않고 표시 가능한 짧은 완성 문장을 가진 항목만 받는다.
        return tuple(parts for parts in entries
                     if (text := self._shortest(parts)).strip() and self.bubble.measure(text)[2])

    def set_enabled(self, enabled):
        self.enabled = enabled
        if not enabled:
            self.dismiss()

    def _scrolled(self, *_):
        self.dismiss()

    def _footer_visible(self):
        normal = self.window._pages.currentWidget() is self.window._tabs
        return (normal and self.window._tabs.currentIndex() != 3
                and not self.window._guide_return_btn.isVisible())

    def _can_expand(self, footer, height):
        if not (footer and self.window._tabs.currentIndex() == 0
                and self.window._tracker_tabs.currentIndex() in (0, 1)):
            return False
        tab = self._tracker_panels[self.window._tracker_tabs.currentIndex()]
        if tab._columns.stacked:
            return False
        scroll = self.window._tracker_tabs.currentWidget()
        reserved = self._central.layout().indexOf(self.footer) >= 0 and not self.footer.isHidden()
        available = scroll.viewport().height() + height - self.window.height() + (64 if reserved else 0)
        needed = tab.layout().heightForWidth(scroll.viewport().width())
        if needed < 0:
            needed = tab.sizeHint().height()
        needed += 64 - tab.form_panel.layout().contentsMargins().bottom()
        return needed <= available

    def refresh(self, *_):
        self.dismiss()
        footer = self._footer_visible()
        central = self.window.centralWidget()
        layout = central.layout()
        height = 864 if footer else 800
        screen = self.window.screen()
        if screen is not None:
            frame = max(32, self.window.frameGeometry().height() - self.window.height())
            height = min(height, max(200, screen.availableGeometry().height() - frame))
        self._floating_footer = self._can_expand(footer, height)
        for tab in (self.window.buff_tab, self.window.debuff_tab):
            tab.form_panel.layout().setContentsMargins(0, 0, 0, 64 if self._floating_footer else 0)
        if self._floating_footer:
            layout.removeWidget(self.footer)
            self.footer.setFixedWidth(76)
        else:
            self.footer.setFixedWidth(central.width())
            if layout.indexOf(self.footer) < 0:
                layout.addWidget(self.footer)
        self.footer.setVisible(footer)
        if self.window.height() != height:
            self.window.setFixedHeight(height)
        if screen is not None and self.window.isVisible():
            area = screen.availableGeometry()
            self.window.move(self.window.x(), max(area.top(), min(self.window.y(), area.bottom() - height - frame + 1)))
        self._place_footer()

    def _place_footer(self):
        if self._floating_footer:
            area = self.window.centralWidget().rect()
            self.footer.move(area.width() - self.footer.width(), area.height() - self.footer.height())
            self.footer.raise_()

    def _anchor(self):
        return self.window.settings_tab.creator_avatar if self.window._tabs.currentIndex() == 3 else self.face

    def _position(self, text):
        anchor = self._anchor()
        setting = anchor is self.window.settings_tab.creator_avatar
        if not self.bubble.set_message(text, "left" if setting else "bottom"):
            return False
        point = anchor.mapTo(self.window.centralWidget(), QPoint())
        if setting:
            self.bubble.move(point.x() + 51, point.y() + (48 - self.bubble.height()) // 2)
        else:
            self.bubble.move(point.x() + 48 - self.bubble.width(), point.y() - self.bubble.height() - 3)
        return self.window.centralWidget().rect().contains(self.bubble.geometry())

    def _eligible(self):
        w = self.window
        if (self.closed or not self.enabled or self.session_unavailable or self.suspended
                or not w.isVisible() or w.isMinimized()
                or w._pages.currentWidget() is not w._tabs
                or getattr(w, "_tour", None) is not None
                or w._guide_return_btn.isVisible()
                or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None):
            return False
        if any(widget.isVisible() and type(widget).__name__ in
               {"RegionSelector", "TopEdgeSelector", "TourOverlay"}
               for widget in QApplication.topLevelWidgets()):
            return False
        anchor = self._anchor()
        if not anchor.isVisible() or not anchor.visibleRegion().contains(anchor.rect()):
            return False
        if not self._position(self.bubble.text.text() or "...방금 무슨 생각 하고 있었지?"):
            return False
        rects = []
        for widget in (anchor, self.bubble):
            point = widget.mapTo(w, QPoint())
            rects.append((point.x(), point.y(), widget.width(), widget.height()))
        try:
            return self.visibility(int(w.winId()), rects, (w.width(), w.height()))
        except Exception:
            return False

    def start(self):
        if self.started or self.closed:
            return
        self.started = True
        if sys.platform == "win32":
            try:
                import win32ts
                win32ts.WTSRegisterSessionNotification(int(self.window.winId()), 0)
                self.session_registered = True
            except Exception:
                _log.debug("세션 이벤트 등록 실패; 입력 데스크톱 폴링 유지", exc_info=True)
        self.feed.start()
        if self.window.isVisible():
            self.timer.start()

    def tick(self):
        now = self.clock()
        gap = self.previous_tick is not None and now > self.previous_tick + 5
        self.previous_tick = now
        if gap:
            self.dismiss()
            return  # 잠금/절전/이벤트 루프 지연 후 이전 말풍선을 복원하지 않는다.
        if self.deadline is not None and now >= self.deadline:
            self.dismiss()
        if not self._eligible():
            self.dismiss()
            return
        if not self.bubble.isVisible() and self.session.draw(now):
            self.request(automatic=True)

    def request(self, *, automatic=False):
        if not self._eligible():
            self.dismiss()
            return False
        text = self.session.choose(lambda value: self.bubble.measure(value)[2], fallback=self._shortest)
        if text is None:
            return False
        if not self._position(text) or not self._eligible():
            self.dismiss()
            return False
        self.bubble.show()
        self.bubble.raise_()
        now = self.clock()
        self.deadline = now + 3
        self.expiry.start(3000)
        self.session.displayed(text, now, automatic=automatic)
        if self.sound is not None:
            try:
                self.sound(text)
            except Exception:
                _log.debug("선택적 잡담 소리 재생 실패", exc_info=True)
        return True

    def dismiss(self):
        self.bubble.hide()
        self.expiry.stop()
        self.deadline = None

    def eventFilter(self, watched, event):
        if self.closed:
            return False
        kind = event.type()
        if watched is self._central:
            if kind == QEvent.Type.Resize:
                self._place_footer()
            return False
        if any(watched is panel for panel in self._tracker_panels):
            if (kind == QEvent.Type.LayoutRequest
                    and self._can_expand(self._footer_visible(), self.window.height()) != self._floating_footer):
                self.refresh()
            return False
        if kind in (QEvent.Type.Hide, QEvent.Type.WindowStateChange, QEvent.Type.Move,
                    QEvent.Type.Resize, QEvent.Type.ScreenChangeInternal):
            self.dismiss()
        if kind == QEvent.Type.Hide:
            self.timer.stop()
        elif kind == QEvent.Type.Show and not self.closed:
            self.refresh()
            if self.started:
                self.timer.start()
        if kind == QEvent.Type.ScreenChangeInternal:
            self.refresh()
        return False

    def shutdown(self):
        self.closed = True
        self.window.removeEventFilter(self)
        self._central.removeEventFilter(self)
        for panel in self._tracker_panels:
            panel.removeEventFilter(self)
        self.timer.stop()
        self.dismiss()
        self.feed.shutdown()
        if self.session_registered:
            try:
                import win32ts
                win32ts.WTSUnRegisterSessionNotification(int(self.window.winId()))
            except Exception:
                _log.debug("세션 이벤트 해제 실패", exc_info=True)
            self.session_registered = False

    def system_message(self, message, value):
        if message == 0x02B1:  # WM_WTSSESSION_CHANGE
            if value in (2, 4, 6, 7):  # disconnect/logoff/lock
                self.session_unavailable = True
            elif value in (1, 3, 8):  # connect/unlock
                self.session_unavailable = False
            self.dismiss()
        elif message == 0x0218:  # WM_POWERBROADCAST
            if value == 4:
                self.suspended = True
            elif value in (7, 18):
                self.suspended = False
            self.dismiss()
        elif message in (0x007E, 0x02E0):  # display / DPI changes
            self.dismiss()
