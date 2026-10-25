"""단계별 첫 사용 안내. 저장된 사용 설정과 기존 자동찾기를 공유한다."""

from PySide6.QtCore import Signal, Qt, QEvent, QTimer
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from .. import config
from ..setup_state import BY_KEY, selected as enabled, missing, section, batch_allowed, needs_boss_preparation, BOSS_PREPARATION
from .. import guide_images
from .guide_figure import ClickableFigure
from .setup_page import CHOICE_TEXT, _label


STAGES = ((), ("buff", "debuff", "boss", "halo_timer"), ("tuarim", "dorcha", "stat_bars", "skillbar"))
GUIDE_KEYS = STAGES[1] + STAGES[2]
GUIDE_FIGURE_TEXT = '연습 모드에 들어가 보스 체력바가 보이는 화면에서 설정해 주세요. 점선이 앱이 찾는 곳이에요(그림을 누르면 크게 볼 수 있어요).'


class SetupGuide(QWidget):
    feature_changed = Signal(str, bool)
    open_feature = Signal(str)
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
        self._fit_pending = False
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.timeout.connect(self._fit_content)
        self.body_scroll = QScrollArea()
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setMinimumSize(0, 0)
        self.body_scroll.viewport().installEventFilter(self)
        content = QWidget()
        self.body_scroll.setWidget(content)
        layout.addWidget(self.body_scroll, 1)
        footer_layout = layout
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.header = _label('첫 사용 안내', bold=True)
        self.header.setStyleSheet('font-size:20px; font-weight:600;')
        layout.addWidget(self.header)
        self.title = _label("", bold=True)
        layout.addWidget(self.title)
        self.description = _label("")
        layout.addWidget(self.description)
        # 설정 안내 그림(2026-10-25 사용자 결정): 다섯 곳 전체 + 연습 모드 안내. 누르면 큰 창.
        self.figure = ClickableFigure('all')
        layout.addWidget(self.figure)
        self.figure_caption = _label(GUIDE_FIGURE_TEXT + '\n' + guide_images.caption('all'))
        self.figure_caption.setStyleSheet('color:#8a8f98;')
        layout.addWidget(self.figure_caption)

        self.game_row = QWidget()
        row = QVBoxLayout(self.game_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.game_status = _label("")
        row.addWidget(self.game_status)
        self.game_btn = QPushButton("게임창 등록 시작")
        self.game_btn.setToolTip("‘게임창 등록 시작’을 누른 뒤 3초 안에 마비노기 창을 선택해 주세요.")
        self.game_btn.clicked.connect(self.register_game.emit)
        row.addWidget(self.game_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.game_row)
        self.game_space = QWidget()
        layout.addWidget(self.game_space)

        self.selection = QScrollArea()
        self.selection.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        rows.setContentsMargins(10, 0, 10, 0)
        rows.setSpacing(0)
        self.checks, self.feature_rows, self.statuses, self.manual_buttons = {}, {}, {}, {}
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            check = QCheckBox(CHOICE_TEXT[key] + " - " + feature.name)
            check.toggled.connect(lambda value, key=key: self.feature_changed.emit(key, value))
            check.setMinimumHeight(max(30, check.sizeHint().height() + 8))
            rows.addWidget(check)
            self.checks[key] = check
        rows.addStretch(1)
        self.selection.setWidget(content)
        self.selection.setMinimumSize(0, 0)
        layout.addWidget(self.selection)
        self.boss_preparation = _label(BOSS_PREPARATION)
        self.boss_preparation.setStyleSheet('color:#c78c32; padding:8px; border:1px solid #806837; border-radius:3px;')
        layout.addWidget(self.boss_preparation)
        self.run_btn = QPushButton("자동설정")
        self.run_btn.setMinimumHeight(34)
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)
        self.groups = {}
        for key, name in (("need", "설정 필요"), ("done", "등록된 설정"), ("unused", "이번 설정에서 제외")):
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
            layout.addWidget(scroll)
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
            button = QPushButton('직접 설정')
            button.clicked.connect(lambda _=False, key=key: self.open_feature.emit(key))
            line.addWidget(button)
            self.manual_buttons[key] = button
            self.feature_rows[key], self.statuses[key] = widget, status
            self.groups["unused"][2].insertWidget(0, widget)

        self.progress = _label("")
        self.progress_area = QScrollArea()
        self.progress_area.setWidgetResizable(True)
        self.progress_area.setFrameShape(QFrame.Shape.NoFrame)
        self.progress_area.setWidget(self.progress)
        self.progress_area.setFixedHeight(85)
        layout.addWidget(self.progress_area)
        layout.addStretch(1)
        layout = footer_layout
        self.step_label = _label('')
        self.step_label.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.step_label)
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
        needed = missing(key, raw)
        if not needed:
            return "등록됨"
        if not enabled(key, raw):
            return "영역 지정 필요 · 이번 설정에서 제외"
        fallback = "나중에 설정" if key in self.deferred else "아직 시도하지 않음"
        if needed == [key]:
            return self.outcomes.get(key, fallback)
        return " / ".join(("보스 체력바" if region == "boss" else BY_KEY[region].name)
                          + ": " + self.outcomes.get(region, fallback) for region in needed)

    def refresh(self):
        raw = config._read_local_config()
        stages = ('게임창 등록', '전투 보조', '추가 설정', '앱 둘러보기')
        trail = ' → '.join(f'<b>{name}</b>' if i == self.stage else name for i, name in enumerate(stages))
        self.step_label.setText(f'<b>{self.stage + 1} / 4 단계</b> · {trail}')
        self.title.setText(("게임창 등록", "전투 보조 설정", "전투 보조 추가 설정")[self.stage])
        self.description.setText((
            ("처음 오셨군요. 필요한 기능만 골라 함께 설정해 봐요.\n"
             "게임창을 등록하면 앱이 마비노기 창을 찾을 수 있어요.\n"
             "게임이 실행 중이지 않다면 나중에 등록해도 돼요." if self.first_run else
             "등록한 영역을 확인하고, 추가로 설정할 기능을 골라봐요.\n"
             "게임창을 바꿔야 한다면 여기서 다시 등록할 수 있어요."),
            "이번 자동설정에 포함할 전투 보조 기능을 골라주세요.\n선택하지 않아도 이미 등록한 영역과 세부 설정은 그대로 유지해요.",
            "도르카·투아림·체력바·단축바도 함께 설정할 수 있어요.\n이 기능들도 ‘전투 보조’ 탭에 있어요. 필요한 것만 고르거나 이 단계를 넘어가도 돼요.",
        )[self.stage])
        game = section(raw, "general").get("gameExe")
        self.game_status.setText("등록된 게임: " + str(game) if game else "게임창 등록 필요")
        self.game_row.setVisible(self.stage == 0)
        self.game_space.setVisible(self.stage == 0)
        self.selection.setVisible(self.stage in (1, 2))
        self.run_btn.setVisible(self.stage in (1, 2))
        self.figure.setVisible(self.stage in (1, 2))
        self.figure_caption.setVisible(self.stage in (1, 2))
        groups = {key: [] for key in self.groups}
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            check = self.checks[key]
            check.blockSignals(True)
            check.setChecked(enabled(key, raw))
            check.blockSignals(False)
            check.setEnabled(not self.busy and batch_allowed(key))
            check.setVisible(key in self.feature_keys and batch_allowed(key))
            check.setToolTip(feature.guidance)
            self.feature_rows[key].setVisible(key in self.feature_keys and batch_allowed(key))
            text = self.status_text(key, raw)
            self.statuses[key].setText(text)
            self.manual_buttons[key].setVisible(bool(missing(key, raw)) and enabled(key, raw))
            self.manual_buttons[key].setEnabled(not self.busy and batch_allowed(key))
            if key in self.feature_keys and batch_allowed(key):
                group = "done" if not missing(key, raw) else "need" if enabled(key, raw) else "unused"
                groups[group].append(self.feature_rows[key])
        for key, widgets in groups.items():
            title, scroll, lines = self.groups[key]
            for index, widget in enumerate(widgets):
                lines.insertWidget(index, widget)
            title.setVisible(bool(widgets) and self.stage in (1, 2))
            scroll.setVisible(bool(widgets) and self.stage in (1, 2))
            if key != "unused":
                title.setText(("설정 필요" if key == "need" else "등록된 설정") + f" · {len(widgets)}")
        self.boss_preparation.setVisible(self.stage in (1, 2) and
                                         needs_boss_preparation(raw, feature_keys=self.feature_keys))
        self._queue_fit()
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

    def _queue_fit(self):
        if self._fit_pending:
            return
        self._fit_pending = True
        self._fit_timer.start(0)

    def eventFilter(self, watched, event):
        if watched is self.body_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._queue_fit()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._queue_fit()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._queue_fit()

    def _fit_content(self):
        self._fit_pending = False
        if not hasattr(self, 'selection'):
            return
        width = max(80, self.body_scroll.viewport().width() - 32)
        height = 0
        for key, check in self.checks.items():
            text = CHOICE_TEXT[key] + ' - ' + BY_KEY[key].name
            lines = QTextLayout(text, check.font())
            option = QTextOption()
            option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            lines.setTextOption(option)
            lines.beginLayout()
            wrapped = []
            while (line := lines.createLine()).isValid():
                line.setLineWidth(max(40, width - check.style().pixelMetric(check.style().PixelMetric.PM_IndicatorWidth) - 12))
                wrapped.append(text[line.textStart():line.textStart()+line.textLength()].rstrip())
            lines.endLayout()
            check.setText('\n'.join(wrapped))
            row_height = max(30, check.sizeHint().height() + 8)
            check.setMinimumHeight(row_height)
            if key in self.feature_keys and batch_allowed(key):
                height += row_height
        self.selection.setFixedHeight(height + 2*self.selection.frameWidth())
        for title, scroll, rows in self.groups.values():
            rows.invalidate()
            row_width = max(80, scroll.viewport().width() - 20)
            height = rows.totalHeightForWidth(row_width) if rows.hasHeightForWidth() else rows.sizeHint().height()
            scroll.setFixedHeight(max(40, height + 2*scroll.frameWidth()))
