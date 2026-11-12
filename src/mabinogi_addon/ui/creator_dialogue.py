"""본창 내부 제작자 얼굴/말풍선과 독립 알림음. 게임 오버레이는 변경하지 않는다."""

import logging
import math
import sys
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath, QPen, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QToolButton, QWidget

from .palette import color
from .. import config
from ..creator_dialogue import (DialogueSession, INVITE_TEXT, INVITE_URL, MAX_CHARS, TipPicker, invite_due)
from ..system.dialogue_visibility import display_available, exposed
from ..system.window_watcher import is_main_window_foreground
from .dialogue_feed import DialogueFeed
from .settings_tab import AVATAR_STYLE, LOGO_IMAGE, PROFILE_IMAGE, _circular

_log = logging.getLogger(__name__)


# 버튼이 있는 말풍선(기능 추천·디스코드 권유, 17절)은 누를 시간을 주려고 조금 더 오래 둔다.
ACTION_SECONDS = 8
_PRIMARY_STYLE = ("QPushButton{background:#1fae8c;color:white;border:none;border-radius:4px;"
                  "padding:3px 10px;font-size:12px;font-weight:bold;}QPushButton:hover{background:#18977a;}")
_SECONDARY_STYLE = ("QPushButton{background:transparent;color:#7a7f87;border:none;padding:3px 4px;font-size:12px;}"
                    "QPushButton:hover{color:#24262a;}")


class SpeechBubble(QWidget):
    dismissed = Signal()
    action = Signal(str)  # 말풍선 버튼(보러 가기·참가하기·괜찮아요)

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
        self.buttons = []
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

    def set_message(self, message, side="bottom", buttons=()):
        """buttons = [(키, 글자, 강조)] — 문장 아래 한 줄(17.1·17.2). 누르면 action(키)."""
        width, height, fits = self.measure(message)
        if not fits:
            return False
        spec = (message, side, tuple(buttons))
        if spec == getattr(self, "_spec", None):
            return True  # 같은 내용(1초마다 노출 확인) — 버튼을 다시 만들지 않는다
        self._spec = spec
        self.side = side
        self.text.setText(message)
        for button in self.buttons:  # 바로 숨기고 떼어 낸다(deleteLater는 이벤트 루프가 돌아야 지워짐)
            button.hide()
            button.setParent(None)
            button.deleteLater()
        self.buttons = []
        left = 10 if side == "left" else 0
        row_width = row_height = 0
        for key, label, primary in buttons:
            button = QPushButton(label, self)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(_PRIMARY_STYLE if primary else _SECONDARY_STYLE)
            button.clicked.connect(lambda _=False, key=key: self.action.emit(key))
            button.adjustSize()
            self.buttons.append(button)
            row_width += button.width() + (6 if row_width else 0)
            row_height = max(row_height, button.height())
        inner = max(width, row_width)
        self.body_width = inner + 20
        self.body_height = height + 14 + (row_height + 6 if self.buttons else 0)
        self.text.setGeometry(left + 10, 7, width, height)
        x = left + 10
        for button in self.buttons:
            button.move(x, 7 + height + 6)
            button.show()
            x += button.width() + 6
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
    def __init__(self, window, *, visibility=display_available, clock=time.monotonic, sound=None,
                 wall=time.time, open_url=None):
        super().__init__(window)
        self.window = window
        self._central = window.centralWidget()
        self.visibility = visibility
        self.clock = clock
        self.wall = wall  # 날짜·권유 주기(17.2)는 벽시계로
        self.open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self._buttons = ()  # 지금 말풍선의 버튼(노출 확인 때 그대로 다시 배치)
        self.current_extra = None  # 지금 말풍선이 기능 추천·권유면 ('tip', Tip) / ('invite', None)
        self._notifier = None
        self._sound_allowed = False
        self._sound_reason = "display_blocked"
        self._audio_stage = "not_requested"
        self._visibility_state = "unavailable"
        self._foreground_detail = {}
        self.sound = sound if sound is not None else self._play_sound
        self.enabled = window.settings_tab.dialogue_enabled.isChecked()
        self.started = self.closed = False
        self.session_unavailable = self.suspended = False
        self.session_registered = False
        self.previous_tick = None
        self._floating_footer = False
        self.bubble = SpeechBubble(window.centralWidget())
        self.feed = DialogueFeed(self, validate=self._usable_entries, validate_tips=self._usable_tips)
        self.session = DialogueSession(self.feed.entries)
        self.picker = TipPicker(self.feed.tips, rng=self.session.rng)
        self.feed.updated.connect(self._updated)
        self.footer = QWidget(window.centralWidget())
        self.footer.setFixedHeight(64)
        row = QHBoxLayout(self.footer)
        row.setContentsMargins(12, 8, 16, 8)
        row.addStretch()
        self.face = QToolButton()
        self.face.setAutoRaise(True)
        self.face.setStyleSheet(AVATAR_STYLE)
        self.face.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.face.setFixedSize(48, 48)
        self.face.setIconSize(QSize(48, 48))
        image = _circular(PROFILE_IMAGE, 48, 3, color('brand')) or _circular(LOGO_IMAGE, 48, 3, color('brand'))
        if image is not None:
            self.face.setIcon(QIcon(image))
        self.face.setToolTip("잡담")
        self.face.clicked.connect(self.request)
        row.addWidget(self.face)
        window.centralWidget().layout().addWidget(self.footer)
        self.bubble.dismissed.connect(self.dismiss)
        self.bubble.action.connect(self._on_action)
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
        window.settings_tab.dialogue_sound_enabled.toggled.connect(self.set_sound_enabled)
        for tabs in (window._tabs, window._tracker_tabs, window._convenience_tabs, window._pages):
            tabs.currentChanged.connect(self.refresh)
        window._settings_scroll.verticalScrollBar().valueChanged.connect(self._scrolled)
        window.installEventFilter(self)
        window.centralWidget().installEventFilter(self)
        self._tracker_panels = (window.buff_tab, window.debuff_tab)
        for panel in self._tracker_panels:
            panel.installEventFilter(self)
        self.refresh()

    def _updated(self, entries):
        if not self.closed:
            self.session.entries = entries
            self.picker.tips = self.feed.tips

    def _usable_tips(self, tips):
        # 말풍선 두 줄 안에 들어가는 문장이 있는 추천만(17.4 — 넘치면 그 항목 건너뜀)
        return tuple(tip for tip in tips
                     if (text := self._shortest(tip.parts)).strip() and self.bubble.measure(text)[2])

    # ---- 기능 추천·디스코드 권유(17절) ----
    def _today(self):
        return time.strftime("%Y-%m-%d", time.localtime(self.wall()))

    def _pick_extra(self):
        """대사를 띄우기로 정해졌을 때 약 25%로 일반 대사 대신 권유·기능 추천(같은 날 겹치지 않게)."""
        now, today = self.wall(), self._today()
        invite = config.load_discord_invite()
        shown = invite.get("shownAt")
        invite_today = isinstance(shown, (int, float)) and time.strftime(
            "%Y-%m-%d", time.localtime(shown)) == today
        tip_today = config.load_dialogue_tip_day() == today
        unused_fn = getattr(self.window, "unused_tip_features", None)
        try:
            unused = set(unused_fn()) if unused_fn is not None else set()
        except Exception:  # noqa: BLE001 — 판정 실패면 추천 없이 일반 대사
            _log.debug("안 쓰는 기능 판정 실패", exc_info=True)
            unused = set()
        return self.picker.pick(unused, invite_ok=invite_due(invite, now) and not tip_today,
                                tip_ok=not invite_today)

    def _extra_message(self, extra):
        if extra[0] == "invite":
            return INVITE_TEXT, [("join", "참가하기", True), ("decline", "괜찮아요", False)]
        tip = extra[1]
        text = "".join(self.session.rng.choice(choices) for choices in tip.parts)
        if not self.bubble.measure(text)[2]:
            text = self._shortest(tip.parts)
        return text, [("tip:" + tip.feature, tip.button, True)]

    def _extra_shown(self, extra):
        try:
            if extra[0] == "invite":
                config.save_discord_invite(shownAt=self.wall())
            else:
                self.picker.shown(extra[1])
                config.save_dialogue_tip_day(self._today())
        except OSError:
            _log.debug("잡담 추천 기록 저장 실패", exc_info=True)

    def _on_action(self, key):
        self.current_extra = None
        self.dismiss()
        try:
            if key == "join":
                self.open_url(INVITE_URL)
                config.save_discord_invite(joined=True)
            elif key == "decline":
                config.save_discord_invite(declinedAt=self.wall())
            elif key.startswith("tip:"):
                opener = getattr(self.window, "open_tip_feature", None)
                if opener is not None:
                    opener(key[4:])
        except OSError:
            _log.debug("잡담 버튼 기록 저장 실패", exc_info=True)
        _log.info("제작자 잡담 버튼: %s", key)

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
        if self._home():
            self.refresh()

    def _play_sound(self, text):
        from .notifier import CREATOR_DIALOGUE_SOUND_FILE, SoundNotifier

        self._audio_stage = "asset_check"
        if not CREATOR_DIALOGUE_SOUND_FILE.exists():
            self._audio_stage = "missing_asset"
            return False
        if self._notifier is None:
            self._audio_stage = "player_preparation"
            self._notifier = SoundNotifier(
                {"dialogue": CREATOR_DIALOGUE_SOUND_FILE}, parent=self, volume=0.5
            )
        if self._notifier._player is None:
            self._audio_stage = "backend_unavailable"
            return False
        self._audio_stage = "play_request"
        result = self._notifier.play("dialogue")
        self._audio_stage = "submitted" if result else "not_submitted"
        return result

    def set_sound_enabled(self, enabled):
        if not enabled and self._notifier is not None:
            self._notifier.stop()

    def _scrolled(self, *_):
        self.dismiss()

    def _home(self):
        visible = getattr(self.window, "home_visible", None)
        return bool(visible and visible())

    def _footer_visible(self):
        if self._home():
            # 홈(탐색 구조 명세 12.4): 잡담이 켜져 있으면 창 864, 캐릭터는 다른 탭과 같은 아래 오른쪽. 꺼져 있으면 800.
            return bool(self.enabled)
        normal = self.window._pages.currentWidget() is self.window._tabs
        # 설정 탭은 위치가 아니라 위젯으로 판단(블랙박스·최적화 탭이 생기면 순서가 밀린다)
        return normal and self.window._tabs.currentWidget() is not self.window._settings_scroll

    def _can_expand(self, footer, height):
        if self._home():
            return bool(footer)  # 홈은 창 전체를 덮으므로 캐릭터를 그 위에 띄운다
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
            tab.form_panel.layout().setContentsMargins(0, 0, 0, 64 if self._floating_footer and not self._home() else 0)
        if self._floating_footer:
            layout.removeWidget(self.footer)
            self.footer.setFixedWidth(76)
        else:
            # Let the layout follow width changes. A fixed snapshot taken during
            # header/column reflow can otherwise pin the central widget too wide.
            self.footer.setMinimumWidth(0)
            self.footer.setMaximumWidth(16777215)
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
        return (self.window.settings_tab.creator_avatar
                if self.window._tabs.currentWidget() is self.window._settings_scroll and not self._home() else self.face)

    def _position(self, text, buttons=()):
        anchor = self._anchor()
        setting = anchor is self.window.settings_tab.creator_avatar
        if not self.bubble.set_message(text, "left" if setting else "bottom", buttons):
            return False
        point = anchor.mapTo(self.window.centralWidget(), QPoint())
        if setting:
            self.bubble.move(point.x() + 51, point.y() + (48 - self.bubble.height()) // 2)
        else:
            self.bubble.move(point.x() + 48 - self.bubble.width(), point.y() - self.bubble.height() - 3)
        return self.window.centralWidget().rect().contains(self.bubble.geometry())

    def _eligible(self, *, diagnose=False):
        self._sound_allowed = False
        self._sound_reason = "display_blocked"
        self._visibility_state = "unavailable"
        self._foreground_detail = {}
        w = self.window
        self._ineligible_reason = "창/설정/세션 또는 모달 상태"
        if (self.closed or not self.enabled or self.session_unavailable or self.suspended
                or not w.isVisible() or w.isMinimized()
                or w._pages.currentWidget() is not w._tabs
                or getattr(w, "_tour", None) is not None
                or QApplication.activeModalWidget() is not None
                or QApplication.activePopupWidget() is not None):
            return False
        if any(widget.isVisible() and type(widget).__name__ in
               {"RegionSelector", "TopEdgeSelector", "TourOverlay"}
               for widget in QApplication.topLevelWidgets()):
            self._ineligible_reason = "영역 지정 또는 투어 진행 중"
            return False
        anchor = self._anchor()
        if not anchor.isVisible() or not anchor.visibleRegion().contains(anchor.rect()):
            self._ineligible_reason = "제작자 얼굴이 가려짐"
            return False
        if not self._position(self.bubble.text.text() or "...방금 무슨 생각 하고 있었지?", self._buttons):
            self._ineligible_reason = "말풍선 배치 공간 부족"
            return False
        rects = []
        for widget in (anchor, self.bubble):
            point = widget.mapTo(w, QPoint())
            rects.append((point.x(), point.y(), widget.width(), widget.height()))
        try:
            detail = {}
            if self.visibility in (display_available, exposed):
                visible = self.visibility(int(w.winId()), rects, (w.width(), w.height()),
                                          diagnostic=detail, diagnose=diagnose)
            else:
                visible = self.visibility(int(w.winId()), rects, (w.width(), w.height()))
            self._visibility_state = detail.get("visibility", "exposed" if visible else "blocked")
            if visible and self._visibility_state == "unknown":
                self._sound_allowed = is_main_window_foreground(int(w.winId()), diagnostic=self._foreground_detail)
                self._sound_reason = "main_foreground" if self._sound_allowed else "unknown_without_main_foreground"
            elif visible:
                self._sound_allowed = True
                self._sound_reason = "exposed"
            if visible and not self._sound_allowed and self._notifier is not None:
                self._notifier.stop()
            self._ineligible_reason = "" if visible else "Windows 잠금/창/화면 또는 API 확인 불가"
            if not visible and detail:
                self._ineligible_reason += " " + repr(detail)
            return visible
        except Exception as exc:
            self._ineligible_reason = "노출 판정 예외: " + type(exc).__name__
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
        self._audio_stage = "not_requested"
        if not self._eligible(diagnose=not automatic):
            self._log_request(automatic, "display_blocked")
            self.dismiss()
            return False
        extra = self._pick_extra()
        buttons = ()
        if extra is not None:
            text, buttons = self._extra_message(extra)
        else:
            text = self.session.choose(lambda value: self.bubble.measure(value)[2], fallback=self._shortest)
        if text is None:
            self._log_request(automatic, "no_text")
            return False
        self._buttons = tuple(buttons)  # 아래 두 번째 노출 확인도 같은 버튼으로 배치
        if not self._position(text, buttons):
            self._log_request(automatic, "no_space")
            self.dismiss()
            return False
        if not self._eligible(diagnose=not automatic):
            self._log_request(automatic, "display_blocked")
            self.dismiss()
            return False
        self.bubble.show()
        self.bubble.raise_()
        now = self.clock()
        seconds = ACTION_SECONDS if buttons else 3
        self.deadline = now + seconds
        self.expiry.start(seconds * 1000)
        self.session.displayed(text, now, automatic=automatic)
        self.current_extra = extra
        if extra is not None:
            self._extra_shown(extra)
        outcome = "muted"
        if not self.window.settings_tab.dialogue_sound_enabled.isChecked():
            outcome = "sound_disabled"
        elif self._sound_allowed and self.sound is not None:
            try:
                self._audio_stage = "callback"
                outcome = "unavailable" if self.sound(text) is False else "requested"
            except Exception:
                outcome = "failed"
                _log.debug("선택적 잡담 소리 재생 실패", exc_info=True)
        self._log_request(automatic, outcome)
        return True

    def _log_request(self, automatic, outcome):
        # One record per actual request, never per eligibility/timer poll. No
        # dialogue text, external titles, paths or screen contents are collected.
        reason = {"no_space": "말풍선 배치 공간 부족", "no_text": "선택 가능한 대사 없음",
                  "display_blocked": self._ineligible_reason}.get(outcome, "")
        _log.info("제작자 잡담 요청: mode=%s visibility=%s foreground=%s sound_allowed=%s reason=%s audio_stage=%s result=%s foreground_error=%s %s (유효 대사 %d개)",
                  "automatic" if automatic else "click", self._visibility_state,
                  self._foreground_detail.get("foreground", "not_required"),
                  self._sound_allowed, self._sound_reason, self._audio_stage, outcome,
                  self._foreground_detail.get("foreground_error", "none"), reason, len(self.session.entries))

    def dismiss(self):
        if self._notifier is not None:
            self._notifier.stop()
        self._buttons = ()
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
