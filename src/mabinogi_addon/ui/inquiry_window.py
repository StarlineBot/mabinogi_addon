"""문의하기 창(문의 자동 진단 명세 6.2·6.3 — 목업 docs/assets/inquiry-unified-20261105/).

앱 크기(790×800)의 새 창, 첫 사용 안내와 같은 틀(제목·단계 표시·아래 버튼 줄).
- 1단계 `문의 종류`: 분할 버튼 `문제 신고 / 기능 요청 / 기타`.
  문제 신고 → `어디가 이상한가요?` 카드 6개 + `지금은 재현하기 어려워요 — 자료 없이 쓸게요` + `자료 모으기 시작`.
  기능 요청·기타 → 제목·내용 → `보내기`(단계 `문의 종류 → 보내기`).
- 2단계 `자료 모으기`: 영역 카드는 최대 60초·20장·8MiB(변경 프레임만, 초당 1장), 그 밖은 5초 뒤 게임 1장(strict).
  창은 접히고 게임 위에 진행 표시(클릭 통과·판독 캡처 제외)만 뜬다. 앱으로 돌아오면 진행·`수집 취소`·`여기까지 모으기`·최근 자료.
- 3단계 `확인하고 보내기`: 제목(자동)·내용, 첨부 썸네일(✕·모두 지우기·크게 보기), `함께 보내는 정보` 펼쳐 보기, `문의 보내기`.
  ZIP 하나(이미지·로그·진단 요약·본문 전체·info.json)를 웹훅으로 — 실패하면 같은 회차 ID로 `다시 보내기`.

수집 캡처(mss)와 PNG 쓰기·ZIP 만들기·전송은 작업 스레드, 위젯·게임 1장 캡처(우리 창을 숨겨야 함)는 화면 스레드.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import logging
import socket
import time
import urllib.error

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from .. import config, image_io
from .. import inquiry_session as inq
from .palette import color

_log = logging.getLogger(__name__)
WIDTH, HEIGHT = 790, 800
SEND_TIMEOUT = 60.0  # 큰 첨부(최대 8MiB) — 작업 스레드라 화면은 멈추지 않는다


def _label(text="", *, size=12, bold=False, muted=False, wrap=True):
    label = QLabel(text)
    label.setWordWrap(wrap)
    style = f"font-size:{size}px;" + (" font-weight:700;" if bold else "") + (f" color:{color('muted')};" if muted else "")
    label.setStyleSheet(style)
    return label


def _accent_button(text):
    button = QPushButton(text)
    button.setStyleSheet(f"QPushButton {{ background:{color('accent')}; color:{color('on-accent')}; font-weight:600;"
                         " padding:5px 16px; border-radius:6px; }"
                         f"QPushButton:disabled {{ background:palette(mid); color:{color('muted')}; }}")
    return button


def _human_bytes(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB" if n >= 100 * 1024 else f"{max(1, round(n / 1024))}KB"


class _Segments(QWidget):
    """문의 종류 분할 버튼(마우스 커서 모양 선택과 같은 모양)."""

    changed = Signal(str)

    def __init__(self, items):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = {}
        qss = ("QPushButton { border:1px solid palette(mid); padding:5px 12px; border-radius:0px; }"
               f"QPushButton:checked {{ background:{color('accent')}; color:{color('on-accent')};"
               f" border-color:{color('accent')}; font-weight:700; }}")
        for name in items:
            b = QPushButton(name)
            b.setCheckable(True)
            b.setStyleSheet(qss)
            b.clicked.connect(lambda _=False, n=name: self.changed.emit(n))
            self.group.addButton(b)
            self.buttons[name] = b
            row.addWidget(b)
        row.addStretch(1)

    def set_value(self, name):
        self.buttons[name].setChecked(True)


class CardButton(QPushButton):
    """`어디가 이상한가요?` 카드: 제목(굵게) + 한 줄 설명. 고르면 강조색 테두리."""

    def __init__(self, card: inq.Card):
        super().__init__()
        self.card = card
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(76)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(6)
        title = _label(card.title, size=14, bold=True, wrap=False)
        text = card.desc
        if card.key == "cooldown" and not inq.has_cooldown_slots():
            text += " 등록한 칸이 없어요 — 위쪽 단축바 영역으로 대신 모아요."
        desc = _label(text, size=11, muted=True)
        for w in (title, desc):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            v.addWidget(w)
        self.setStyleSheet(
            "QPushButton { border:1px solid palette(mid); border-radius:6px; background:palette(base); text-align:left; }"
            f"QPushButton:checked {{ border:2px solid {color('accent')}; }}"
            f"QPushButton:hover {{ border-color:{color('accent')}; }}")


class Thumb(QFrame):
    """첨부 썸네일: 그림(누르면 크게) + 이름 + ✕."""

    removed = Signal(object)
    opened = Signal(object)

    def __init__(self, item: inq.Attachment, pixmap: QPixmap | None, *, removable=True, width=172):
        super().__init__()
        self.item = item
        self.setObjectName("inqThumb")
        self.setStyleSheet("#inqThumb { border:1px solid palette(mid); border-radius:4px; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)
        pic = QLabel()
        pic.setFixedSize(width - 10, 28 if item.kind == "image" else 28)
        pic.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        if pixmap is not None:
            pic.setPixmap(pixmap.scaled(pic.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                        Qt.TransformationMode.SmoothTransformation).copy(0, 0, pic.width(), pic.height()))
            pic.setCursor(Qt.CursorShape.PointingHandCursor)
            pic.mousePressEvent = lambda _e: self.opened.emit(self.item)
        else:
            pic.setText("ZIP · 자동 찾기 기록")
            pic.setStyleSheet(f"color:{color('muted')}; font-size:11px;")
        v.addWidget(pic)
        row = QHBoxLayout()
        row.setSpacing(4)
        name = _label(item.label, size=11, muted=True, wrap=False)
        row.addWidget(name, 1)
        if removable:
            x = QPushButton("✕")
            x.setFixedSize(22, 20)
            x.setToolTip("이 자료 지우기")
            x.clicked.connect(lambda: self.removed.emit(self.item))
            row.addWidget(x)
        v.addLayout(row)
        self.setFixedWidth(width)


class InquiryChip(QWidget):
    """게임 위 작은 진행 표시 — 클릭 통과·판독 캡처 제외라 누를 수 있는 것을 넣지 않는다(6.2 4항)."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput)
        from . import overlay_capture
        overlay_capture.watch(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._text = ""
        self._font = QFont()
        self._font.setPixelSize(13)

    def set_text(self, text):
        if text != self._text:
            self._text = text
            from PySide6.QtGui import QFontMetrics
            w = QFontMetrics(self._font).horizontalAdvance(text) + 44
            self.resize(w, 30)
            self.update()

    def place(self, screen_rect: QRect):
        self.move(screen_rect.right() - self.width() - 24, screen_rect.top() + 24)

    def showEvent(self, event):
        super().showEvent(event)
        from ..system.clickthrough import set_click_through
        set_click_through(self, True)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(color("accent", dark=True)))
        p.setBrush(QColor(16, 22, 30, 225))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 8, 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color("ok", dark=True)))
        p.drawEllipse(12, 10, 10, 10)
        p.setPen(QColor("#e5e7eb"))
        p.setFont(self._font)
        p.drawText(self.rect().adjusted(30, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        p.end()


class InquiryWindow(QWidget):
    """문의하기(새 창). 한 번에 회차 하나 — 메인 창이 인스턴스 하나를 들고 다시 열면 앞으로 가져온다."""

    _frame_saved = Signal(object, object)   # (회차, Attachment|None)
    _job_done = Signal(object, object)      # (콜백, 결과)
    _sent = Signal(str, str)                # (결과 ok|fail|unknown, 메시지)

    def __init__(self, watcher=None, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("문의하기")
        self.resize(WIDTH, HEIGHT)
        self.setMinimumSize(WIDTH, 640)
        self._watcher = watcher
        self.category = inq.BUG
        self.card: inq.Card | None = None
        self.session: inq.Session | None = None
        self._no_data = False
        self._collecting = False
        self._elapsed = 0.0
        self._last_tick: float | None = None
        self._rects: list[tuple[str, tuple[int, int, int, int]]] = []
        self._pending = False
        self._countdown = 0
        self._sending = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inquiry")
        self._frame_saved.connect(self._on_frame_saved)
        self._job_done.connect(lambda fn, result: fn(result))
        self._sent.connect(self._on_sent)
        self.chip = InquiryChip()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(_label("문의하기", size=20, bold=True, wrap=False))
        top.addStretch(1)
        self.steps = QLabel()
        self.steps.setTextFormat(Qt.TextFormat.RichText)
        top.addWidget(self.steps)
        outer.addLayout(top)
        self.reply_hint = _label(self._reply_text(), size=11, muted=True)
        outer.addWidget(self.reply_hint)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.page_kind = self._build_kind_page()
        self.page_collect = self._build_collect_page()
        self.page_confirm = self._build_confirm_page()
        for page in (self.page_kind, self.page_collect, self.page_confirm):
            self.stack.addWidget(page)
        self.status = _label("", size=12)
        outer.addWidget(self.status)
        bottom = QHBoxLayout()
        self.back_btn = QPushButton("이전")
        self.back_btn.clicked.connect(self._back)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.close)
        bottom.addWidget(self.back_btn)
        bottom.addWidget(self.cancel_btn)
        bottom.addStretch(1)
        self.next_btn = _accent_button("자료 모으기 시작")
        self.next_btn.clicked.connect(self._next)
        bottom.addWidget(self.next_btn)
        outer.addLayout(bottom)
        self.kind.set_value(self.category)
        self._show_kind()

    # ---- 공통 ---------------------------------------------------------------------------------
    @staticmethod
    def _reply_text():
        from .. import feature_access
        user = feature_access.current_user()
        if user:
            return f"답변은 디스코드 계정({user.get('name')})으로 드려요. 보내기 전까지는 아무것도 전송하지 않아요."
        return "로그인하지 않으면 답변을 디스코드로 받을 수 없어요(설정 탭에서 로그인). 보내기 전까지는 아무것도 전송하지 않아요."

    def _set_steps(self, names, current):
        parts = []
        for i, name in enumerate(names):
            parts.append(f"<span style='color:{color('accent')}; font-weight:700'>{name}</span>" if i == current else name)
        self.steps.setText(" → ".join(parts))

    def _set_status(self, text, tone=None):
        self.status.setText(text)
        self.status.setStyleSheet("font-size:12px;" + (f" color:{color(tone)};" if tone else ""))

    def _bug_steps(self, current):
        self._set_steps(("문의 종류", "자료 모으기", "확인하고 보내기"), current)

    # ---- 1단계: 문의 종류 ---------------------------------------------------------------------
    def _build_kind_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)
        row = QHBoxLayout()
        row.addWidget(_label("문의 종류", wrap=False))
        self.kind = _Segments(inq.CATEGORIES)
        self.kind.changed.connect(self._on_kind)
        row.addWidget(self.kind, 1)
        v.addLayout(row)
        # 문제 신고: 카드 6개
        self.bug_box = QWidget()
        b = QVBoxLayout(self.bug_box)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(8)
        b.addWidget(_label("어디가 이상한가요?", size=12))
        b.addWidget(_label("고르면 그 기능의 자료를 자동으로 모아요. 게임 닉네임·채팅이 찍힐 수 있어요. "
                           "보내기 전에 확인하고 지울 수 있어요.", size=11, muted=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.cards = QButtonGroup(self)
        self.card_buttons: dict[str, CardButton] = {}
        for i, card in enumerate(inq.CARDS):
            button = CardButton(card)
            button.clicked.connect(lambda _=False, c=card: self._pick(c))
            self.cards.addButton(button)
            self.card_buttons[card.key] = button
            grid.addWidget(button, i // 2, i % 2)
        b.addLayout(grid)
        self.no_data_link = QPushButton("지금은 재현하기 어려워요 — 자료 없이 쓸게요")
        self.no_data_link.setFlat(True)
        self.no_data_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.no_data_link.setStyleSheet(f"QPushButton {{ color:{color('accent')}; text-decoration:underline; border:none;"
                                        " text-align:left; padding:0; }")
        self.no_data_link.clicked.connect(self._without_data)
        b.addWidget(self.no_data_link, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.bug_box)
        # 기능 요청·기타: 제목·내용
        self.text_box = QWidget()
        t = QVBoxLayout(self.text_box)
        t.setContentsMargins(0, 0, 0, 0)
        t.setSpacing(8)
        t.addWidget(_label("기능 요청과 기타 문의는 화면 자료 없이 글만 보내요.", size=11, muted=True))
        t.addWidget(_label("제목"))
        self.text_title = QLineEdit()
        self.text_title.setPlaceholderText("문의 제목")
        t.addWidget(self.text_title)
        t.addWidget(_label("내용"))
        self.text_body = QTextEdit()
        self.text_body.setPlaceholderText("문의 내용을 적어 주세요")
        self.text_body.setMinimumHeight(260)
        t.addWidget(self.text_body)
        v.addWidget(self.text_box)
        v.addStretch(1)
        return page

    def _on_kind(self, name):
        if self._collecting or self._pending:
            self.kind.set_value(self.category)
            return
        self.category = name
        self._show_kind()

    def _pick(self, card):
        self.card = card
        self.next_btn.setEnabled(True)

    def _show_kind(self):
        self.stack.setCurrentWidget(self.page_kind)
        bug = self.category == inq.BUG
        self.bug_box.setVisible(bug)
        self.text_box.setVisible(not bug)
        self.back_btn.hide()
        self.cancel_btn.show()
        if bug:
            self._bug_steps(0)
            self.next_btn.setText("자료 모으기 시작")
            self.next_btn.setEnabled(self.card is not None)
        else:
            self._set_steps(("문의 종류", "보내기"), 0)
            self.next_btn.setText("보내기")
            self.next_btn.setEnabled(True)
        self._set_status("")

    def _without_data(self):
        """지금 재현하기 어려워요 — 화면 없이 확인 화면으로(로그·진단 요약은 붙는다)."""
        self._discard_session()
        self._no_data = True
        self.session = inq.Session(self.card)
        self.session.notes.append("자료 없이 보냄(지금은 재현하기 어려움)")
        self._show_confirm()

    # ---- 2단계: 자료 모으기 ---------------------------------------------------------------------
    def _build_collect_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)
        self.collect_ask = _label("", size=13)
        self.collect_detail = _label("", size=12)
        v.addWidget(self.collect_ask)
        v.addWidget(self.collect_detail)
        box = QFrame()
        box.setObjectName("inqProgress")
        box.setStyleSheet("#inqProgress { border:1px solid palette(mid); border-radius:6px; }")
        p = QVBoxLayout(box)
        p.setContentsMargins(14, 12, 14, 12)
        p.setSpacing(8)
        self.progress_text = QLabel()
        self.progress_text.setTextFormat(Qt.TextFormat.RichText)
        p.addWidget(self.progress_text)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.setStyleSheet(f"QProgressBar {{ background:palette(mid); border:none; border-radius:4px; }}"
                                    f"QProgressBar::chunk {{ background:{color('ok')}; border-radius:4px; }}")
        p.addWidget(self.progress)
        self.progress_note = _label("60초 또는 20장이 되면 자동으로 끝나요. 아직 보내지 않았어요.", size=11, muted=True)
        p.addWidget(self.progress_note)
        row = QHBoxLayout()
        self.stop_cancel = QPushButton("수집 취소")
        self.stop_cancel.clicked.connect(self._cancel_collect)
        self.stop_keep = QPushButton("여기까지 모으기")
        self.stop_keep.clicked.connect(self._finish_collect)
        row.addWidget(self.stop_cancel)
        row.addStretch(1)
        row.addWidget(self.stop_keep)
        p.addLayout(row)
        v.addWidget(box)
        v.addWidget(_label("최근에 모인 자료", size=12))
        self.recent = QHBoxLayout()
        self.recent.setSpacing(8)
        self.recent.addStretch(1)
        v.addLayout(self.recent)
        v.addStretch(1)
        return page

    def _start_collect(self):
        card = self.card
        if card is None:
            return
        self._discard_session()
        self._no_data = False
        self.session = inq.Session(card)
        self.session.started = datetime.now()
        self.stack.setCurrentWidget(self.page_collect)
        self._bug_steps(1)
        self.collect_ask.setText(card.ask)
        self.collect_detail.setText(card.detail)
        self.back_btn.show()
        self.cancel_btn.hide()
        self.next_btn.setText("확인하고 보내기")
        self._clear_recent()
        self._elapsed, self._last_tick, self._next_grab = 0.0, None, 0.0
        if card.key == "cooldown":
            inq.attach_cooldown(self.session)  # 칸 목록·아이콘(수집 끝에 app.log 쿨타임 줄)
        if card.mode == "collect":
            from .dpi import to_physical
            self._rects = []
            for name in card.regions:
                box = inq.region_of(name)
                if box is None:
                    self.session.notes.append(f"{inq.REGION_LABELS[name]} 위치 없음(못 찾음·미지정)")
                    continue
                self._rects.append((name, to_physical(box)))
            if not self._rects:  # 영역이 하나도 없으면 미리 알린 대로 게임 1장으로
                self._begin_countdown("위치를 아직 못 찾아 5초 뒤 게임 화면 1장을 찍어요.")
                return
            self._collecting = True
            self.progress_note.setText("60초 또는 20장이 되면 자동으로 끝나요. 아직 보내지 않았어요.")
            self.stop_keep.show()
        else:
            self._begin_countdown(None)
            return
        self._refresh_progress()
        self._timer.start()
        self._collapse()

    def _begin_countdown(self, note):
        if note:
            self.session.notes.append(note)
        self._pending = True
        self._countdown = inq.COUNTDOWN
        self.stop_keep.hide()
        self._refresh_progress()
        self._timer.start()
        self._collapse()

    def _collapse(self):
        """게임을 앞으로 두게 창을 접는다(별도 시작 클릭 없음)."""
        if self.isVisible():
            self.showMinimized()

    def _game_active(self):
        if self._watcher is None:
            return True
        try:
            return bool(self._watcher.is_game_active())
        except Exception:  # noqa: BLE001
            return False

    def _tick(self):
        now = time.monotonic()
        dt = 0.0 if self._last_tick is None else now - self._last_tick
        self._last_tick = now
        if self._pending:
            self._countdown -= dt
            if self._countdown <= 0:
                self._pending = False
                self._timer.stop()
                self._one_shot()
                return
            self._refresh_progress()
            return
        if not self._collecting:
            return
        active = self._game_active()
        if active:  # 게임이 앞에 없으면 일시정지(같은 회차에서 이어서)
            self._elapsed += dt
            if now >= self._next_grab:  # 캡처는 초당 1번(저장은 바뀐 프레임만)
                self._next_grab = now + inq.MIN_INTERVAL
                session = self.session
                for name, rect in self._rects:
                    self._executor.submit(self._grab_save, session, name, rect)
        if self._elapsed >= inq.LIMIT_SECONDS or self.session.full():
            self._finish_collect()
            return
        self._refresh_progress(paused=not active)

    def _grab_save(self, session, name, rect):
        frame = inq.grab_physical(rect)
        item = session.add_frame(name, frame) if frame is not None else None
        self._frame_saved.emit(session, item)

    def _on_frame_saved(self, session, item):
        if session is not self.session or item is None:
            return
        self._add_recent(item)
        self._refresh_progress()

    def _refresh_progress(self, paused=False):
        s = self.session
        if s is None:
            return
        if self._pending:
            left = max(0, int(self._countdown + 0.99))
            text = f"게임 화면을 맨 앞에 두세요 · {left}초 뒤 찍어요"
            self.progress.setValue(int(100 * (inq.COUNTDOWN - max(0.0, self._countdown)) / inq.COUNTDOWN))
            self.progress_text.setText(f"<span style='color:{color('ok')}'>● 준비 중</span> · {left}초")
            self.chip.set_text(f"문의 자료 준비 중 · {left}초 뒤 게임 화면을 찍어요")
        else:
            secs = min(inq.LIMIT_SECONDS, int(self._elapsed))
            state = "잠시 멈춤(게임이 앞에 없음)" if paused else "자료 모으는 중"
            tone = color("warn") if paused else color("ok")
            self.progress_text.setText(f"<span style='color:{tone}'>● {state}</span> · {secs} / {inq.LIMIT_SECONDS}초 · "
                                       f"{len(s.images)}장 · {_human_bytes(s.total_bytes)}")
            self.progress.setValue(int(100 * max(secs / inq.LIMIT_SECONDS, len(s.images) / inq.LIMIT_FRAMES)))
            text = f"문의 자료 모으는 중 · {secs}/{inq.LIMIT_SECONDS}초 · {len(s.images)}장 · 끝나면 앱에서 확인해요"
            self.chip.set_text(text)
        self._sync_chip()

    def _sync_chip(self):
        show = (self._collecting or self._pending) and self.isMinimized() and self._game_active()
        if show:
            screen = QApplication.primaryScreen()
            if screen is not None:
                self.chip.place(screen.geometry())
            self.chip.show()
        else:
            self.chip.hide()

    def _one_shot(self):
        """버프·디버프 영역(카드가 그럴 때) + 게임 1장(strict — 바탕화면 대체 금지). 우리 창을 숨겨야 해 화면 스레드."""
        s, card = self.session, self.card
        self.chip.hide()
        try:
            if card is not None and card.mode == "snapshot":
                from .dpi import to_physical
                for name in card.regions:
                    box = inq.region_of(name)
                    if box is None:
                        s.notes.append(f"{inq.REGION_LABELS[name]} 위치 없음(못 찾음·미지정)")
                        continue
                    frame = inq.grab_physical(to_physical(box))
                    if frame is not None:
                        s.add_frame(name, frame, force=True)
            self._capture_game(s)
        finally:
            s.ended = datetime.now()
        if card is not None and card.mode == "autofind":
            self._set_status("자동 찾기 기록을 붙이는 중…")
            self._executor.submit(self._attach_autofind, s)
            return
        self._collected()

    def _capture_game(self, s):
        if not self._game_active():
            s.notes.append("게임 화면을 찾지 못했어요(게임이 앞에 없음)")
            return
        try:
            from .screen_grab import capture_for_autofind
            frame, _x, _y = capture_for_autofind(require_game=True, strict_game=True)
        except Exception as exc:  # noqa: BLE001 — 캡처 불가면 이미지 없이
            _log.warning("문의 게임 화면 캡처 실패: %r", exc)
            frame = None
        if frame is None:
            s.notes.append("게임 화면을 찾지 못했어요(캡처 안 됨)")
            return
        s.add_frame("game", frame, force=True)

    def _attach_autofind(self, s):
        from .. import autofind_diagnostics as ad
        try:
            records = ad.store().recent()[:3]
            for i, record in enumerate(records, 1):
                target = s.folder / f"autofind_{i}.zip"
                ad.store().export(record, target)
                s.add_file(target, target.name, f"자동 찾기 기록 {i}")
            if not records:
                s.notes.append("자동 찾기 기록이 없어요")
        except Exception as exc:  # noqa: BLE001
            s.notes.append(f"자동 찾기 기록을 붙이지 못했어요: {type(exc).__name__}")
        self._job_done.emit(lambda _r: self._collected(), None)

    def _finish_collect(self):
        """자동 종료·여기까지 모으기 — 0장이면 미리 알린 대로 게임 1장으로(남은 준비 시간 안에서만)."""
        if not self._collecting:
            return
        self._collecting = False
        self._timer.stop()
        self._executor.submit(lambda: None).result(timeout=5)  # 진행 중 저장을 기다린다(늦은 결과는 회차로 걸러짐)
        QApplication.processEvents()
        if not self.session.images:
            self.session.notes.append("영역 자료가 모이지 않아 게임 화면 1장으로 대신함")
            self._capture_game(self.session)
        if self.card is not None and self.card.key == "cooldown":
            inq.finish_cooldown(self.session)
        self.session.ended = datetime.now()
        self._collected()

    def _collected(self):
        self.chip.hide()
        self._set_status("")
        self._show_confirm()
        if self.isMinimized():  # 강제로 창을 띄우지 않고 작업 표시줄만 알린다
            QApplication.alert(self)

    def _cancel_collect(self):
        self._stop_all()
        self._discard_session()
        self._show_kind()

    def _stop_all(self):
        self._collecting = self._pending = False
        self._timer.stop()
        self.chip.hide()

    def _clear_recent(self):
        while self.recent.count() > 1:
            item = self.recent.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

    def _add_recent(self, item):
        thumb = Thumb(item, self._pixmap(item), removable=False)
        self.recent.insertWidget(0, thumb)
        while self.recent.count() > 5:  # 최근 4장
            old = self.recent.takeAt(self.recent.count() - 2)
            if old.widget() is not None:
                old.widget().hide()
                old.widget().deleteLater()

    # ---- 3단계: 확인하고 보내기 -----------------------------------------------------------------
    def _build_confirm_page(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 0, 0)
        v.setSpacing(8)
        v.addWidget(_label("제목"))
        self.title_edit = QLineEdit()
        v.addWidget(self.title_edit)
        v.addWidget(_label("어떤 상황이었나요?"))
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("기대한 동작과 실제 동작을 적어 주세요. 예) 70% 근처에서 알림 / 실제: 60% 아래에서 알림")
        self.body_edit.setFixedHeight(110)
        v.addWidget(self.body_edit)
        head = QHBoxLayout()
        self.attach_title = QLabel()
        self.attach_title.setTextFormat(Qt.TextFormat.RichText)
        head.addWidget(self.attach_title, 1)
        self.clear_btn = QPushButton("모두 지우기")
        self.clear_btn.clicked.connect(self._clear_all)
        head.addWidget(self.clear_btn)
        v.addLayout(head)
        self.thumb_grid = QGridLayout()
        self.thumb_grid.setHorizontalSpacing(8)
        self.thumb_grid.setVerticalSpacing(8)
        holder = QWidget()
        holder.setLayout(self.thumb_grid)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(holder)
        self.thumb_scroll = scroll
        v.addWidget(scroll)
        self.info_toggle = QPushButton()
        self.info_toggle.setFlat(True)
        self.info_toggle.setCheckable(True)
        self.info_toggle.setStyleSheet("QPushButton { border:none; text-align:left; padding:0; }")
        self.info_toggle.toggled.connect(self._toggle_info)
        v.addWidget(self.info_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.info_text = QTextEdit()
        self.info_text.setReadOnly(True)
        self.info_text.setFixedHeight(150)
        self.info_text.hide()
        v.addWidget(self.info_text)
        v.addWidget(_label("사진은 크게 눌러 확인할 수 있어요. 게임 닉네임·채팅이 보이면 지워 주세요.", size=11, muted=True))
        v.addStretch(1)
        return page

    def _show_confirm(self):
        self.stack.setCurrentWidget(self.page_confirm)
        self._bug_steps(2)
        self.back_btn.show()
        self.cancel_btn.show()
        self.next_btn.setText("문의 보내기")
        self.next_btn.setEnabled(True)
        if not self.title_edit.text().strip() and self.card is not None:
            self.title_edit.setText(f"{self.card.title} 문제")
        self.info_toggle.setChecked(False)
        self._update_info_toggle()
        self._render_thumbs()

    def _update_info_toggle(self):
        arrow = "▾" if self.info_toggle.isChecked() else "▸"
        self.info_toggle.setText(f"{arrow} 함께 보내는 정보: 앱 버전 · Windows · 해상도 · 기능 설정 요약 · 최근 로그  "
                                 f"{'접기' if self.info_toggle.isChecked() else '펼쳐 보기'}")

    def _toggle_info(self, on):
        self._update_info_toggle()
        if on:
            self.info_text.setPlainText(self._summary_text(full_logs=False))
        self.info_text.setVisible(on)

    def _summary_text(self, *, full_logs):
        from ..diagnostics import header_text
        from ..logbuffer import recent_logs
        logs = recent_logs()
        lines = [header_text()]
        if self.session is not None and self.session.notes:
            lines += ["", "===== 진단 요약 =====", *self.session.notes]
        if full_logs:
            lines += ["", "===== 최근 로그 =====", logs]
        else:
            lines += ["", f"최근 로그 {len(logs.splitlines())}줄(ZIP 안 logs.txt)"]
        return "\n".join(lines)

    def _render_thumbs(self):
        while self.thumb_grid.count():
            item = self.thumb_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        s = self.session
        items = list(s.attachments) if s is not None else []
        for i, item in enumerate(items):
            thumb = Thumb(item, self._pixmap(item))
            thumb.removed.connect(self._remove)
            thumb.opened.connect(self._open_big)
            self.thumb_grid.addWidget(thumb, i // 4, i % 4)
        images = len(s.images) if s is not None else 0
        files = len(items) - images
        total = s.total_bytes if s is not None else 0
        parts = [f"이미지 {images}장"] + ([f"자동 찾기 기록 {files}개"] if files else []) + ["로그", "진단 요약", f"합계 {_human_bytes(total + 50_000)}"]
        self.attach_title.setText(f"<b>첨부</b>&nbsp;&nbsp;<span style='color:{color('muted')}'>{' · '.join(parts)}</span>")
        self.clear_btn.setVisible(bool(items))
        self.thumb_scroll.setVisible(bool(items))
        rows = (len(items) + 3) // 4
        self.thumb_scroll.setFixedHeight(min(rows, 4) * 70 + 6)  # 4줄(16장)까지 한눈에, 그 넘으면 스크롤

    def _pixmap(self, item):
        if item.kind != "image":
            return None
        frame = image_io.imread(item.path)
        if frame is None:
            return None
        rgb = frame[:, :, ::-1].copy()
        h, w = rgb.shape[:2]
        return QPixmap.fromImage(QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888))

    def _remove(self, item):
        if self.session is not None:
            self.session.remove(item)
        self._render_thumbs()

    def _clear_all(self):
        if self.session is not None:
            self.session.clear()
        self._render_thumbs()

    def _open_big(self, item):
        pixmap = self._pixmap(item)
        if pixmap is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(item.label)
        layout = QVBoxLayout(dialog)
        label = QLabel()
        screen = self.screen().availableGeometry() if self.screen() else QRect(0, 0, 1600, 900)
        label.setPixmap(pixmap.scaled(QSize(int(screen.width() * 0.8), int(screen.height() * 0.8)),
                                      Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        if pixmap.width() > screen.width() * 0.8 else pixmap)
        layout.addWidget(label)
        dialog.exec()

    # ---- 버튼 ---------------------------------------------------------------------------------
    def _next(self):
        page = self.stack.currentWidget()
        if page is self.page_kind:
            if self.category == inq.BUG:
                self._start_collect()
            else:
                self._send_text()
        elif page is self.page_collect:
            if self._collecting:
                self._finish_collect()
            elif not self._pending:
                self._show_confirm()
        else:
            self._send_bug()

    def _back(self):
        page = self.stack.currentWidget()
        if page is self.page_collect:
            self._cancel_collect()
        elif page is self.page_confirm:
            if self._sending:
                return
            self._discard_session()  # 다시 모으면 이전 회차 이미지는 지운다(입력 내용은 유지)
            self._show_kind()

    # ---- 보내기 -------------------------------------------------------------------------------
    def _send_text(self):
        title, body = self.text_title.text().strip(), self.text_body.toPlainText().strip()
        if not title or not body:
            self._set_status("제목과 내용을 모두 입력해 주세요.", "danger")
            return
        self._send(title, body, attachment=None, session_id=None)

    def _send_bug(self):
        title, body = self.title_edit.text().strip(), self.body_edit.toPlainText().strip()
        if not title or not body:
            self._set_status("제목과 어떤 상황이었는지를 적어 주세요.", "danger")
            return
        s = self.session or inq.Session(self.card)
        self.session = s
        who = inq.sender()
        logs = self._summary_text(full_logs=True)
        try:
            name, data = s.build_zip(category=self.category, who=who, title=title, content=body, logs=logs)
        except ValueError as exc:
            self._set_status(str(exc), "danger")
            return
        self._send(title, body, attachment=(name, data, "application/zip"), session_id=s.id)

    def _send(self, title, body, *, attachment, session_id):
        webhook = config.get_inquiry_webhook_url()
        if not webhook:
            self._set_status("문의 채널이 설정되지 않았어요(웹훅 미등록).", "danger")
            return
        who = inq.sender()
        sid = session_id or (self.session.id if self.session else None) or __import__("uuid").uuid4().hex
        header = inq.header_line(who, sid, self.category, self.card if self.category == inq.BUG else None)
        self._sending = True
        for b in (self.next_btn, self.back_btn, self.cancel_btn):
            b.setEnabled(False)
        self._set_status("보내는 중…")
        self._executor.submit(self._send_worker, webhook, title, body, header, attachment, who)

    def _send_worker(self, webhook, title, body, header, attachment, who):
        from ..inquiry import send_inquiry
        try:
            send_inquiry(webhook, title, body, category=self.category, user_id=who["discord_id"], header=header,
                         attachment=attachment, timeout=SEND_TIMEOUT)
            self._sent.emit("ok", "")
        except (socket.timeout, TimeoutError) as exc:
            self._sent.emit("unknown", str(exc))
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                self._sent.emit("unknown", str(exc))
            else:
                self._sent.emit("fail", str(exc))
        except Exception as exc:  # noqa: BLE001
            self._sent.emit("fail", str(exc))

    def _on_sent(self, result, message):
        self._sending = False
        for b in (self.next_btn, self.back_btn, self.cancel_btn):
            b.setEnabled(True)
        if result == "ok":
            from .toast import show_toast
            show_toast("문의", "보내기 완료 — 소중한 의견 감사해요!")
            self._discard_session()
            self._finished = True
            self.close()
            return
        self.next_btn.setText("다시 보내기")  # 같은 회차 ID로 — 재수집 없음
        if result == "unknown":
            self._set_status("전송 여부를 확인하지 못했어요. 문의 채널을 확인한 뒤 다시 보내거나 닫아 주세요.", "warn")
        else:
            self._set_status(f"보내지 못했어요: {message}", "danger")

    # ---- 정리 ---------------------------------------------------------------------------------
    def _discard_session(self):
        if self.session is not None:
            self.session.cleanup()
            self.session = None

    def closeEvent(self, event):
        if self._sending:
            event.ignore()
            return
        self._stop_all()
        self._discard_session()
        self.chip.close()
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_chip()

    def shutdown(self):
        self._stop_all()
        self._discard_session()
        self.chip.close()
        self._executor.shutdown(wait=False, cancel_futures=True)
