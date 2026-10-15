"""단계별 첫 사용 안내. 저장된 사용 설정과 기존 자동찾기를 공유한다."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import config
from ..setup_state import BY_KEY, enabled, missing, section
from .setup_page import CHOICE_TEXT, _label


STAGES = ((), ("buff", "debuff", "boss"), ("tuarim", "stat_bars", "skillbar"))
GUIDE_KEYS = STAGES[1] + STAGES[2]


class SetupGuide(QWidget):
    feature_changed = Signal(str, bool)
    register_game = Signal()
    run_requested = Signal()
    cancel_requested = Signal()
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.busy = False
        self.active = False
        self.stage = 0
        self.outcomes = {}
        self.deferred = set()
        self.first_run = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(7)
        self.step_label = _label("")
        layout.addWidget(self.step_label)
        self.title = _label("", bold=True)
        self.title.setStyleSheet("font-size:20px; font-weight:600;")
        layout.addWidget(self.title)
        self.description = _label("")
        layout.addWidget(self.description)

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
        self.game_space = QWidget()
        layout.addWidget(self.game_space, 1)

        self.selection = QScrollArea()
        self.selection.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(10, 0, 10, 0)
        rows.setSpacing(0)
        self.checks, self.feature_rows, self.statuses = {}, {}, {}
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            check = QCheckBox(CHOICE_TEXT[key] + " - " + feature.name + (" (베타)" if feature.beta else ""))
            check.toggled.connect(lambda value, key=key: self.feature_changed.emit(key, value))
            check.setFixedHeight(max(30, check.sizeHint().height() + 8))
            rows.addWidget(check)
            self.checks[key] = check
        rows.addStretch(1)
        self.selection.setWidget(content)
        self.selection.setFixedHeight(3 * check.height() + 2 * self.selection.frameWidth())
        layout.addWidget(self.selection)
        self.run_btn = QPushButton("자동설정")
        self.run_btn.setMinimumHeight(34)
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)
        self.groups = {}
        for key, name in (("need", "설정 필요"), ("done", "등록된 설정"), ("unused", "사용 안 함")):
            title = _label(name, bold=True)
            layout.addWidget(title)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setMinimumHeight(40)
            content = QWidget()
            lines = QVBoxLayout(content)
            lines.setContentsMargins(10, 0, 10, 0)
            lines.setSpacing(0)
            lines.addStretch(1)
            scroll.setWidget(content)
            layout.addWidget(scroll, 1)
            self.groups[key] = (title, scroll, lines)
        for key in GUIDE_KEYS:
            widget = QWidget()
            line = QHBoxLayout(widget)
            line.setContentsMargins(0, 4, 0, 4)
            name = _label(BY_KEY[key].name)
            name.setMinimumWidth(125)
            line.addWidget(name)
            status = _label("")
            line.addWidget(status, 1)
            self.feature_rows[key], self.statuses[key] = widget, status
            self.groups["unused"][2].insertWidget(0, widget)

        self.progress = _label("")
        self.progress_area = QScrollArea()
        self.progress_area.setWidgetResizable(True)
        self.progress_area.setFrameShape(QFrame.Shape.NoFrame)
        self.progress_area.setWidget(self.progress)
        self.progress_area.setFixedHeight(85)
        layout.addWidget(self.progress_area)
        self.skip = QCheckBox("시작할 때 이 화면 다시 보지 않기")
        self.skip.toggled.connect(lambda value: config.save_general_flag("skipSetup", value))
        layout.addWidget(self.skip)
        footer = QHBoxLayout()
        self.back_btn = QPushButton("이전")
        self.back_btn.clicked.connect(lambda: self.move(-1))
        footer.addWidget(self.back_btn)
        self.later_btn = QPushButton("나중에 설정")
        self.later_btn.clicked.connect(self.defer)
        footer.addWidget(self.later_btn)
        footer.addStretch(1)
        self.stop_btn = QPushButton("중단")
        self.stop_btn.clicked.connect(self.cancel_requested.emit)
        footer.addWidget(self.stop_btn)
        self.next_btn = QPushButton("다음")
        self.next_btn.clicked.connect(lambda: self.move(1))
        footer.addWidget(self.next_btn)
        layout.addLayout(footer)
        self.refresh()

    @property
    def feature_keys(self):
        return STAGES[self.stage]

    def reset(self, *, first_run=False):
        if self.busy:
            return
        self.active = True
        self.first_run = first_run
        self.stage = 0
        self.outcomes.clear()
        self.deferred.clear()
        self.progress.clear()
        self.refresh()

    def move(self, delta):
        if self.busy:
            return
        if self.stage == 2 and delta > 0:
            self.finish()
            return
        self.stage = max(0, min(2, self.stage + delta))
        self.progress.clear()
        self.refresh()

    def defer(self):
        if not self.busy:
            self.deferred.update(self.feature_keys)
            self.move(1)

    def finish(self):
        if not self.busy:
            self.active = False
            self.finished.emit()

    def record_result(self, key, status):
        self.outcomes[key] = status
        self.refresh()

    def status_text(self, key, raw):
        if not enabled(key, raw):
            return "사용 안 함"
        needed = missing(key, raw)
        if not needed:
            return "등록됨"
        fallback = "나중에 설정" if key in self.deferred else "아직 시도하지 않음"
        if needed == [key]:
            return self.outcomes.get(key, fallback)
        return " / ".join(("보스 체력바" if region == "boss" else BY_KEY[region].name)
                          + ": " + self.outcomes.get(region, fallback) for region in needed)

    def refresh(self):
        raw = config._read_local_config()
        logged_in = config.load_discord_user() is not None
        self.step_label.setText(f"첫 사용 안내 · {self.stage + 1} / 4   게임창 등록 → 전투 기능 → 추가 기능 → 앱 둘러보기")
        self.title.setText(("게임창 등록", "전투에서 사용할 기능", "이런 기능도 있어요")[self.stage])
        self.description.setText((
            ("처음 오셨군요. 사용할 기능을 골라 나에게 맞게 설정해 보세요.\n" if self.first_run else
             "사용할 기능과 등록된 설정을 확인해 보세요.\n")
            + "게임 화면과 활성 상태를 구별하기 위해 게임창을 등록합니다. 게임이 없다면 나중에 설정할 수 있습니다.",
            "전투에서 도움받고 싶은 기능을 선택하세요.\n하나만 선택하거나, 이 단계를 건너뛰어도 됩니다.",
            "더 편하게 사용할 수 있는 기능도 있어요.\n필요한 것만 선택하고, 지금 필요하지 않으면 건너뛰세요.",
        )[self.stage])
        game = section(raw, "general").get("gameExe")
        self.game_status.setText("등록된 게임: " + str(game) if game else "게임창 등록 필요")
        self.game_row.setVisible(self.stage == 0)
        self.game_space.setVisible(self.stage == 0)
        self.selection.setVisible(self.stage in (1, 2))
        self.run_btn.setVisible(self.stage in (1, 2))
        groups = {key: [] for key in self.groups}
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            check = self.checks[key]
            check.blockSignals(True)
            check.setChecked(enabled(key, raw))
            check.blockSignals(False)
            check.setEnabled(not self.busy and (logged_in or not feature.beta or check.isChecked()))
            check.setVisible(key in self.feature_keys)
            check.setToolTip("테스트 중인 베타 기능입니다." if feature.beta else "")
            self.feature_rows[key].setVisible(key in self.feature_keys)
            text = self.status_text(key, raw)
            self.statuses[key].setText(text)
            if key in self.feature_keys:
                group = "unused" if not enabled(key, raw) else "need" if missing(key, raw) else "done"
                groups[group].append(self.feature_rows[key])
        for key, widgets in groups.items():
            title, scroll, lines = self.groups[key]
            for index, widget in enumerate(widgets):
                lines.insertWidget(index, widget)
            title.setVisible(bool(widgets) and self.stage in (1, 2))
            scroll.setVisible(bool(widgets) and self.stage in (1, 2))
            if key != "unused":
                title.setText(("설정 필요" if key == "need" else "등록된 설정") + f" · {len(widgets)}")
        self.skip.blockSignals(True)
        self.skip.setChecked(section(raw, "general").get("skipSetup") is True)
        self.skip.blockSignals(False)
        self.back_btn.setEnabled(not self.busy and self.stage > 0)
        self.next_btn.setText("다음")
        self.stop_btn.setVisible(self.busy)
        self.progress_area.setVisible(bool(self.progress.text()))
        for button in (self.game_btn, self.run_btn, self.later_btn, self.next_btn):
            button.setEnabled(not self.busy)
        self.skip.setEnabled(not self.busy)

    def set_busy(self, busy):
        self.busy = busy
        self.refresh()
