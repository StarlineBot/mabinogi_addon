"""첫 사용 안내 v3(docs/first-use-v3-spec.md 2절) — 1 시작 · 2 쓸 기능 켜기 · 3 준비 끝.

위치는 앱이 알아서 찾으므로(자동 찾기 — 모든 사용자 항상 켬) 영역 지정 단계가 없다. 2단계 스위치는 **홈과 같은 값**이고,
화면을 읽는 8개 줄은 스위치 왼쪽에 찾기 상태를 보인다(D5). 새 설치에만 처음 한 번 띄운다(4절).

화면만 맡는다: 스위치 값·찾기 상태는 state_fn이 주고, 바꾸면 feature_toggled로 알린다(앱이 홈과 같은 경로로 저장).
게임 창은 windows_fn(열린 창 목록)에서 마비노기 창이 **하나면 자동 연결**, 여러 개면 고르기, 없으면 '켜 주세요'(D6).
"""
from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
                               QStackedWidget, QVBoxLayout, QWidget)

from .palette import color
from .widgets import switch

GAME_HINTS = ("마비노기", "mabinogi")
STEPS = ("시작", "쓸 기능 켜기", "둘러보기")

# (홈 줄 키, 이름, 한 줄 설명) — 2.2절 표
COMBAT = (("buff", "버프", "버프가 끝나기 전에 알려줘요"),
          ("debuff", "디버프", "보스에게 아직 안 걸린 디버프를 보여줘요"),
          ("boss", "보스 패턴 알림", "보스 패턴이 다가오면 알려줘요"),
          ("halo", "1분 헤일로", "믿음의 균열 헤일로 전에 알려줘요"),
          ("tuarim", "투아림 알림", "정한 비율에 도달하면 알려줘요"))
SCREEN = (("stat_bars", "체력바", "생명력·마나·스태미나를 보기 편한 곳에"),
          ("dorcha", "도르카 표시", "도르카 수치를 보기 편한 곳에"),
          ("skillbar", "단축바", "단축바를 보기 편한 곳에"))
OTHERS = (("opt", "게임 최적화", "게임 우선순위·CPU 배치로 끊김 줄이기"),
          ("fps", "게임 위 정보", "FPS·현재 시각을 게임 위에"),
          ("cursor", "마우스 커서", "커서를 잘 보이게 표시"),
          ("blackbox", "최근 영상 보관", "방금 장면을 저장할 수 있게 보관"))
READ_KEYS = tuple(k for k, *_ in COMBAT + SCREEN)  # 화면을 읽는 8개 — 찾기 상태 표시
NAMES = {k: n for k, n, _ in COMBAT + SCREEN + OTHERS}

WELCOME = ("이 앱은 게임 화면을 읽기만 해요. 버프 목록·단축바·체력바 같은 위치는 앱이 알아서 찾아요.\n"
           "영역을 직접 지정할 필요 없이, 다음 화면에서 쓰고 싶은 기능만 켜면 끝이에요.")
TIPS = ("캐릭터로 접속해 있으면 화면에 보이는 UI부터 찾아요. 처음 찾는 동안 잠깐 CPU를 더 써요.",
        "보스 체력바·전투 시간은 화면에 처음 나타날 때 찾아요.",
        "게임 안에서 창을 옮겨도 다시 찾아요. 잘못 찾으면 각 기능 화면에서 직접 맞출 수 있어요.")


def game_windows(windows) -> list[tuple[str, str]]:
    """열린 창 (제목, exe) 중 마비노기 창."""
    return [(t, e) for t, e in windows if any(h in f"{t} {e}".lower() for h in GAME_HINTS)]


def status_text(key: str, place: str | None) -> tuple[str, str] | None:
    """2단계 찾기 상태(문구, 색 이름) — 게임 UI가 안 보이는 동안은 '게임에 접속하면 찾아요'('못 찾음'으로 보이지 않게)."""
    if place is None:
        return None
    if place in ("found", "user", "v1"):
        return "위치 찾음", "ok"
    if place == "wait" or (place in ("missing", "searching") and key in ("debuff", "boss", "halo")):
        return ("전투 시간 보이면 찾아요" if key == "halo" else "보스 나오면 찾아요"), "muted"
    if place == "hidden":
        return "게임에 접속하면 찾아요", "muted"
    if place == "searching":
        return "찾는 중", "muted"
    return "화면에 보이면 찾아요", "muted"


def _label(text, *, size=None, role="text", bold=False, wrap=True):
    lbl = QLabel(text)
    lbl.setWordWrap(wrap)
    css = "" if role == "text" else f"color:{color(role)};"  # 본문 글자는 테마 기본색
    if size:
        css += f" font-size:{size}px;"
    if bold:
        css += " font-weight:700;"
    lbl.setStyleSheet(css)
    return lbl


class _Row(QWidget):
    toggled = Signal(str, bool)

    def __init__(self, key, name, desc, with_status):
        super().__init__()
        self.key = key
        line = QHBoxLayout(self)
        line.setContentsMargins(0, 3, 0, 3)
        line.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(_label(name, bold=True))
        self.desc = _label(desc, size=11, role="muted")
        text.addWidget(self.desc)
        line.addLayout(text, 1)
        self.status = QLabel("")
        self.status.setTextFormat(Qt.TextFormat.RichText)
        self.status.setVisible(with_status)
        line.addWidget(self.status, 0, Qt.AlignmentFlag.AlignVCenter)
        self.switch = switch("")
        self.switch.setAccessibleName(name)
        self.switch.toggled.connect(lambda on: self.toggled.emit(self.key, on))
        line.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_state(self, on: bool, status: tuple[str, str] | None) -> None:
        if self.switch.isChecked() != bool(on):
            self.switch.blockSignals(True)
            self.switch.setChecked(bool(on))
            self.switch.blockSignals(False)
            self.switch.update()
        if status is not None:
            text, tone = status
            c = color(tone)
            html = f'<span style="color:{c}">●</span><span style="color:{c}; font-size:11px">&nbsp;{escape(text)}</span>'
            if self.status.text() != html:
                self.status.setText(html)


class FirstUseGuide(QWidget):
    feature_toggled = Signal(str, bool)  # 홈 줄 키, 켬 — 홈 스위치와 같은 경로로 저장
    game_connected = Signal(str)         # 고른·자동 연결한 마비노기 창 exe
    later = Signal()                     # 1단계 '나중에 하기'
    finished = Signal(bool)              # 3단계: True = 앱 둘러보기 시작

    def __init__(self, *, state_fn=None, windows_fn=None, game_fn=None, parent=None):
        """state_fn() → {홈 줄 키: (켬, place)} (place = autofind_regions.place 값 또는 None),
        windows_fn() → [(제목, exe)], game_fn() → 등록된 게임 exe 또는 None."""
        super().__init__(parent)
        self._state_fn = state_fn or (lambda: {})
        self._windows_fn = windows_fn or (lambda: [])
        self._game_fn = game_fn or (lambda: None)
        self.page = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 18, 28, 18)
        outer.setSpacing(10)
        self.trail = QLabel("")
        self.trail.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(self.trail)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._start_page())
        self.stack.addWidget(self._features_page())
        self.stack.addWidget(self._ready_page())
        footer = QHBoxLayout()
        self.back_btn = QPushButton("이전")
        self.back_btn.clicked.connect(lambda: self.go(self.page - 1))
        self.later_btn = QPushButton("나중에 하기")
        self.later_btn.clicked.connect(self.later.emit)
        footer.addWidget(self.back_btn)
        footer.addWidget(self.later_btn)
        footer.addStretch(1)
        self.skip_tour_btn = QPushButton("둘러보기 없이 시작")
        self.skip_tour_btn.clicked.connect(lambda: self.finished.emit(False))
        footer.addWidget(self.skip_tour_btn)
        self.next_btn = QPushButton("다음")
        self.next_btn.setDefault(True)
        self.next_btn.setObjectName("firstUseNext")
        self.next_btn.setStyleSheet(f"QPushButton#firstUseNext {{ background:{color('accent')}; color:{color('on-accent')};"
                                    " border:none; border-radius:6px; padding:7px 18px; font-weight:700; }")
        self.next_btn.clicked.connect(self._next)
        footer.addWidget(self.next_btn)
        outer.addLayout(footer)
        self._timer = QTimer(self)
        self._timer.setInterval(1500)  # 창 목록·찾기 상태(가벼운 화면 일만)
        self._timer.timeout.connect(self.refresh)
        self.go(0)

    # ---- 1 시작 ----------------------------------------------------------------------------
    def _start_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_label("마비노기 애드온에 오신 걸 환영해요", size=22, bold=True))
        v.addWidget(_label(WELCOME, role="muted"))
        box = QFrame()
        box.setObjectName("firstUseGame")
        box.setStyleSheet(f"#firstUseGame {{ border:1px solid {color('muted')}; border-radius:8px; }}")
        g = QVBoxLayout(box)
        g.setContentsMargins(14, 10, 14, 10)
        self.game_status = QLabel("")
        self.game_status.setTextFormat(Qt.TextFormat.RichText)
        self.game_status.setWordWrap(True)
        g.addWidget(self.game_status)
        pick = QHBoxLayout()
        self.game_pick = QComboBox()
        self.game_pick.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.game_pick_btn = QPushButton("이 창으로 연결")
        self.game_pick_btn.clicked.connect(self._pick_game)
        pick.addWidget(self.game_pick, 1)
        pick.addWidget(self.game_pick_btn)
        self.game_pick_row = QWidget()
        self.game_pick_row.setLayout(pick)
        pick.setContentsMargins(0, 0, 0, 0)
        g.addWidget(self.game_pick_row)
        v.addWidget(box)
        v.addSpacing(4)
        v.addWidget(_label("알아 두면 좋아요", bold=True))
        for tip in TIPS:
            v.addWidget(_label("· " + tip, size=12, role="muted"))
        v.addStretch(1)
        return page

    # ---- 2 쓸 기능 켜기 ----------------------------------------------------------------------
    def _features_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        v.addWidget(_label("쓰고 싶은 기능만 켜세요", size=22, bold=True))
        v.addWidget(_label("켜 둔 기능만 동작해요. 위치는 앱이 알아서 찾으니 켜기만 하면 돼요. "
                           "나중에 홈에서 언제든 바꿀 수 있어요.", role="muted"))
        cols = QHBoxLayout()
        cols.setSpacing(28)
        self.rows: dict[str, _Row] = {}

        def column(groups):
            col = QVBoxLayout()
            col.setSpacing(2)
            for n, (title, items) in enumerate(groups):
                if n:
                    col.addSpacing(14)
                col.addWidget(_label(title, size=12, role="ok", bold=True))
                for key, name, desc in items:
                    row = _Row(key, name, desc, key in READ_KEYS)
                    row.toggled.connect(self.feature_toggled.emit)
                    self.rows[key] = row
                    col.addWidget(row)
            col.addStretch(1)
            cols.addLayout(col, 1)
        column((("전투 보조", COMBAT),))
        column((("화면에 띄우기", SCREEN), ("그 밖에", OTHERS)))
        v.addLayout(cols)
        v.addWidget(_label("커스텀 오버레이·메모처럼 직접 고르는 기능은 다음 둘러보기에서 소개해요.", size=12, role="muted"))
        v.addStretch(1)
        return page

    # ---- 3 준비 끝 -----------------------------------------------------------------------------
    def _ready_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        v.addWidget(_label("준비 끝!", size=22, bold=True))
        self.ready_list = _label("")
        v.addWidget(self.ready_list)
        v.addWidget(_label("게임 화면에 보이면 앱이 위치를 찾고 바로 동작해요.", role="muted"))
        v.addStretch(1)
        v.addWidget(_label("둘러보기는 설정 › 일반에서 언제든 다시 볼 수 있어요.", size=12, role="muted"))
        return page

    # ---- 진행 -------------------------------------------------------------------------------------
    def start(self) -> None:
        self.go(0)
        self._auto_connect()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def go(self, page: int) -> None:
        self.page = max(0, min(2, page))
        self.stack.setCurrentIndex(self.page)
        parts = []
        for i, name in enumerate(STEPS):
            if i < self.page:
                parts.append(f'<span style="color:{color("ok")}">✓ {name}</span>')
            elif i == self.page:
                parts.append(f'<b style="color:{color("accent")}">{i + 1} {name}</b>')
            else:
                parts.append(f'<span style="color:{color("muted")}">{i + 1} {name}</span>')
        self.trail.setText(f'&nbsp;<span style="color:{color("muted")}">—</span>&nbsp; '.join(parts))
        self.back_btn.setVisible(self.page > 0)
        self.later_btn.setVisible(self.page == 0)
        self.skip_tour_btn.setVisible(self.page == 2)
        self.next_btn.setText("앱 둘러보기 시작" if self.page == 2 else "다음")
        self.refresh()

    def _next(self) -> None:
        if self.page == 2:
            self.finished.emit(True)
        else:
            self.go(self.page + 1)

    def refresh(self) -> None:
        self._refresh_game()
        try:
            state = self._state_fn() or {}
        except Exception:  # noqa: BLE001 — 표시 갱신 실패가 안내를 막지 않게
            state = {}
        for key, row in self.rows.items():
            on, place = state.get(key, (False, None))
            row.set_state(on, status_text(key, place) if key in READ_KEYS else None)
        chosen = [NAMES[k] for k in self.rows if state.get(k, (False,))[0]]
        self.ready_list.setText(("켠 기능: " + " · ".join(chosen)) if chosen
                                else "아직 켠 기능이 없어요 — 홈에서 언제든 켤 수 있어요")

    # ---- 게임 창(D6) ----------------------------------------------------------------------------
    def _matches(self):
        try:
            return game_windows(self._windows_fn() or [])
        except Exception:  # noqa: BLE001
            return []

    def _auto_connect(self) -> None:
        """마비노기 창이 하나면 자동 연결(이미 같은 창이면 그대로)."""
        if self._game_fn():
            return
        found = self._matches()
        if len(found) == 1:
            self.game_connected.emit(found[0][1])

    def _pick_game(self) -> None:
        exe = self.game_pick.currentData()
        if exe:
            self.game_connected.emit(exe)
            self.refresh()

    def _refresh_game(self) -> None:
        found = self._matches()
        game = self._game_fn()
        if not game and len(found) == 1:
            self.game_connected.emit(found[0][1])
            game = self._game_fn()
        title = next((t for t, e in found if e == game), None)
        ok, warn = color("ok"), color("warn")
        if game:
            name = escape(title or str(game))
            self.game_status.setText(f'<span style="color:{ok}">●</span> 마비노기 창을 찾았어요 — {name}')
        elif len(found) > 1:
            self.game_status.setText(f'<span style="color:{warn}">●</span> 마비노기 창이 여러 개예요 — 쓸 창을 골라 주세요')
        else:
            self.game_status.setText(f'<span style="color:{warn}">●</span> 마비노기를 켜 주세요 — 켜면 자동으로 연결돼요')
        many = not game and len(found) > 1
        self.game_pick_row.setVisible(many)
        if many:
            items = [(f"{t} ({e})", e) for t, e in found]
            if [(self.game_pick.itemText(i), self.game_pick.itemData(i)) for i in range(self.game_pick.count())] != items:
                self.game_pick.clear()
                for text, exe in items:
                    self.game_pick.addItem(text, exe)

