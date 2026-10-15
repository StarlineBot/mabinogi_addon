"""탭을 추가하지 않는 사용 준비 화면. 후보 확인은 기존 화면 위에서 진행한다."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from .. import config
from ..setup_state import FEATURES, enabled, missing, section


CHOICE_TEXT = {
    "buff": "버프가 끝나기 전에 알림을 받고 싶어요",
    "debuff": "보스에게 아직 걸지 않은 디버프를 확인하고 싶어요",
    "tuarim": "투아림이 차면 알림을 받고 싶어요",
    "boss": "보스 패턴이 다가오면 알림을 받고 싶어요",
    "stat_bars": "체력·마나·스태미나를 보기 편한 곳에 표시하고 싶어요",
    "skillbar": "단축바를 원하는 위치에서 보고 싶어요",
    "custom": "게임 화면 일부를 다른 위치에도 띄우고 싶어요",
    "memo": "게임을 보면서 메모를 확인하고 싶어요",
}


def _label(text, *, bold=False):
    label = QLabel(text)
    label.setWordWrap(True)
    if bold:
        label.setStyleSheet("font-weight:600;")
    return label


class SetupPage(QWidget):
    feature_changed = Signal(str, bool)
    open_feature = Signal(str)
    register_game = Signal()
    login_requested = Signal()
    run_requested = Signal()
    leave_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(7)
        header = QHBoxLayout()
        title = _label("사용 준비", bold=True)
        title.setStyleSheet("font-size:20px; font-weight:600;")
        header.addWidget(title, 1)
        self.run_btn = QPushButton("자동설정")
        self.run_btn.setToolTip("사용할 기능 중 미등록 영역만 순서대로 찾습니다. Discord 로그인 후 사용할 수 있습니다.")
        self.run_btn.clicked.connect(self.run_requested.emit)
        self.leave_btn = QPushButton("트래커로 이동")
        self.leave_btn.clicked.connect(self.leave_requested.emit)
        header.addWidget(self.leave_btn)
        layout.addLayout(header)
        layout.addWidget(_label("게임창 등록 → 기능 선택 → 자동설정 → 영역 확인\n"
                                "찾은 영역을 승인하면 등록하고 다음 항목으로 넘어갑니다."))

        self.game_row = QWidget()
        row = QHBoxLayout(self.game_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.game_status = _label("")
        row.addWidget(self.game_status, 1)
        self.game_btn = QPushButton("게임창 등록 시작")
        self.game_btn.setToolTip("버튼을 누른 뒤 3초 안에 게임창을 선택하세요.")
        self.game_btn.clicked.connect(self.register_game.emit)
        row.addWidget(self.game_btn)
        layout.addWidget(self.game_row)

        layout.addWidget(_label("사용할 기능", bold=True))
        layout.addWidget(_label("사용할 기능만 선택하세요. 선택한 기능에 필요한 설정을 안내합니다."))
        self.selection = QScrollArea()
        self.selection.setWidgetResizable(True)
        self.selection.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        choices = QWidget()
        choose = QVBoxLayout(choices)
        choose.setContentsMargins(10, 0, 10, 0)
        choose.setSpacing(0)
        self.checks = {}
        for feature in FEATURES:
            check = QCheckBox(CHOICE_TEXT[feature.key] + " - " + feature.name
                              + (" (베타)" if feature.beta else ""))
            check.toggled.connect(lambda value, key=feature.key: self.feature_changed.emit(key, value))
            check.setFixedHeight(max(30, check.sizeHint().height() + 8))
            self.checks[feature.key] = check
            choose.addWidget(check)
        choose.addStretch(1)
        self.selection.setWidget(choices)
        self.selection.setFixedHeight(9 * check.height() // 2 + 2 * self.selection.frameWidth())
        layout.addWidget(self.selection)
        self.run_btn.setMinimumHeight(34)
        layout.addWidget(self.run_btn)
        beta_row = QHBoxLayout()
        self.beta_note = _label("")
        beta_row.addWidget(self.beta_note, 1)
        self.login_btn = QPushButton("Discord 로그인")
        self.login_btn.setToolTip("설정의 Discord 계정으로 이동합니다. 로그인은 직접 시작할 수 있습니다.")
        self.login_btn.clicked.connect(self.login_requested.emit)
        beta_row.addWidget(self.login_btn)
        layout.addLayout(beta_row)

        self.need_title = _label("설정 필요", bold=True)
        self.done_title = _label("등록된 설정", bold=True)
        self.unused_title = _label("사용 안 함", bold=True)
        self.groups = {}
        for key, title in (("need", self.need_title), ("done", self.done_title), ("unused", self.unused_title)):
            layout.addWidget(title)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            content = QWidget()
            rows = QVBoxLayout(content)
            rows.setContentsMargins(10, 0, 10, 0)
            rows.setSpacing(0)
            rows.addStretch(1)
            scroll.setWidget(content)
            scroll.setMinimumHeight(55)
            layout.addWidget(scroll, 1)
            self.groups[key] = (scroll, rows)
        self.feature_rows = {}
        for feature in FEATURES:
            widget = QWidget()
            line = QHBoxLayout(widget)
            line.setContentsMargins(0, 3, 0, 3)
            name = QLabel(feature.name)
            name.setMinimumWidth(125)
            line.addWidget(name)
            status = _label("")
            line.addWidget(status, 1)
            button = QPushButton("개별 설정")
            button.clicked.connect(lambda _=False, key=feature.key: self.open_feature.emit(key))
            line.addWidget(button)
            self.feature_rows[feature.key] = (widget, status, button)
            self.groups["unused"][1].insertWidget(0, widget)

        self.progress = _label("")
        layout.addWidget(self.progress)
        footer = QHBoxLayout()
        self.skip = QCheckBox("시작할 때 이 화면 다시 보지 않기")
        self.skip.setChecked(config.load_general_flag("skipSetup"))
        self.skip.toggled.connect(lambda value: config.save_general_flag("skipSetup", value))
        footer.addWidget(self.skip)
        footer.addStretch(1)
        self.stop_btn = QPushButton("중단")
        self.stop_btn.clicked.connect(self.cancel_requested.emit)
        self.stop_btn.hide()
        footer.addWidget(self.stop_btn)
        layout.addLayout(footer)
        self.refresh()

    def refresh(self):
        raw = config._read_local_config()
        logged_in = config.load_discord_user() is not None
        self.beta_note.setText("자동설정은 테스트 중인 베타 기능입니다. "
                               + ("직접 지정도 가능합니다." if logged_in else
                                  "Discord 로그인 후 먼저 사용해 볼 수 있어요. 직접 지정은 로그인 없이 가능합니다.\n"
                                  "기능 자체가 베타인 체력바·단축바는 로그인이 필요합니다."))
        self.login_btn.setVisible(not logged_in)
        self.login_btn.setEnabled(not self.busy)
        self.game_status.setText("등록된 게임: " + str(section(raw, "general").get("gameExe"))
                                 if section(raw, "general").get("gameExe") else "게임창 등록 필요")
        need, done, unused = [], [], []
        for feature in FEATURES:
            check = self.checks[feature.key]
            check.blockSignals(True)
            check.setChecked(enabled(feature.key, raw))
            check.blockSignals(False)
            check.setEnabled(not self.busy and (logged_in or not feature.beta or check.isChecked()))
            check.setToolTip("기능 자체가 베타인 항목은 로그인이 필요합니다." if feature.beta else "")
            widget, status, button = self.feature_rows[feature.key]
            is_enabled = enabled(feature.key, raw)
            needed = missing(feature.key, raw)
            status.setText("사용 안 함" if not is_enabled else (
                "영역 등록됨" if not needed else "영역 미등록" + (
                    " · 보스 체력바 표시 필요" if feature.key in ("boss", "debuff") else
                    " · 직접 지정 필요" if not feature.automatic else "")))
            button.setEnabled(not self.busy)
            (unused if not is_enabled else need if needed else done).append(widget)
        for key, widgets in (("need", need), ("done", done), ("unused", unused)):
            rows = self.groups[key][1]
            for index, widget in enumerate(widgets):
                rows.insertWidget(index, widget)
            scroll = self.groups[key][0]
            scroll.setVisible(bool(widgets))
        self.need_title.setText(f"설정 필요 · {len(need)}")
        self.done_title.setText(f"등록된 설정 · {len(done)}")
        self.need_title.setVisible(bool(need))
        self.done_title.setVisible(bool(done))
        self.unused_title.setVisible(bool(unused))
        if not any(enabled(feature.key, raw) for feature in FEATURES) and not self.busy:
            self.progress.setText("사용할 기능을 선택하세요.")
        elif self.progress.text() == "사용할 기능을 선택하세요.":
            self.progress.clear()

    def set_busy(self, busy):
        self.busy = busy
        self.run_btn.setEnabled(not busy)
        self.leave_btn.setEnabled(not busy)
        self.game_btn.setEnabled(not busy)
        self.stop_btn.setVisible(busy)
        self.refresh()
