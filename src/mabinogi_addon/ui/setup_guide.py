"""단계별 첫 사용 안내(5단계: 게임창 등록 → 전투 보조 → 추가 설정 → 다른 기능 → 앱 둘러보기, 명세 auto-setup-v2 11절).
저장된 사용 설정과 기존 자동찾기를 공유한다."""

from html import escape

from PySide6.QtCore import Signal, Qt, QEvent, QTimer
from PySide6.QtGui import QTextLayout, QTextOption
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from .. import config
from ..setup_state import BY_KEY, selected as enabled, missing, section, batch_allowed, needs_boss_preparation, BOSS_PREPARATION
from .. import guide_images
from .guide_figure import ClickableFigure
from .setup_page import CHOICE_TEXT, _label


STAGES = ((), ("buff", "debuff", "boss", "halo_timer"), ("tuarim", "dorcha", "stat_bars", "skillbar"), ())
GUIDE_KEYS = STAGES[1] + STAGES[2]
STAGE_NAMES = ('게임창 등록', '전투 보조', '추가 설정', '다른 기능', '앱 둘러보기')
LAST = len(STAGES) - 1  # '다음'을 누르면 앱 둘러보기(하이라이트)로 넘어가는 마지막 안내 단계
GUIDE_FIGURE_TEXT = '연습 모드에 들어가 보스 체력바가 보이는 화면에서 설정해 주세요. 점선이 앱이 찾는 곳이에요(그림을 누르면 크게 볼 수 있어요).'
ORANGE, GREEN, GRAY = '#e67e22', '#2ecc71', '#8a8f98'
# 4단계 '다른 기능도 있어요'(명세 11절): 영역 지정 없이 쓰는 기능은 여기 카드로만 소개한다. 기능이 늘면 카드만 추가.
OPTIMIZATION_ITEMS = '게임 우선순위 높음 · CPU 배치 · 패스트핑 · 그래픽 효율(NVIDIA)'
OTHER_FEATURES = (
    ('블랙박스', '최근 게임 화면을 보관해 두었다가 필요한 순간을 저장해요.', '블랙박스 탭'),
    ('파티 모집', '디스코드 파티 모집 현황을 보고 키워드 알림을 받아요.', '파티 모집 탭'),
    ('커스텀 오버레이', '게임 화면 일부를 원하는 위치에도 띄워요.', '전투 보조 › 커스텀 오버레이 탭'),
    ('메모', '게임을 보면서 메모를 화면 위에 띄워 둬요.', '전투 보조 › 메모 탭'),
    ('계산기', '분배·구슬 분배·환전 비율·던전 입장 비용을 계산해요.', '편의기능 탭'),
)


def _gray(text):
    label = _label(text)
    label.setStyleSheet(f'color:{GRAY};')
    return label


def _card(object_name):
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)
    return frame, layout


class SetupGuide(QWidget):
    feature_changed = Signal(str, bool)
    open_feature = Signal(str)
    open_tab = Signal(str)  # 4단계 카드의 탭 열기('optimization')
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
        # 제목 줄: 왼쪽 '첫 사용 안내', 오른쪽 위 진행 표시(n / 5 + 현재 단계 강조)
        top = QHBoxLayout()
        self.header = QLabel('첫 사용 안내')
        self.header.setStyleSheet('font-size:20px; font-weight:600;')
        top.addWidget(self.header, 0, Qt.AlignmentFlag.AlignTop)
        top.addStretch(1)
        self.step_label = QLabel('')
        self.step_label.setTextFormat(Qt.TextFormat.RichText)
        self.step_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.step_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
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
        self.title = _label("", bold=True)
        layout.addWidget(self.title)
        self.description = _label("")
        layout.addWidget(self.description)
        # 설정 안내 그림(2026-10-25 사용자 결정): 여섯 곳 전체 + 연습 모드 안내. 누르면 큰 창.
        self.figure = ClickableFigure('all')
        layout.addWidget(self.figure)
        self.figure_caption = _gray(GUIDE_FIGURE_TEXT + '\n' + guide_images.caption('all'))
        layout.addWidget(self.figure_caption)

        # 1단계: 등록 상태 + 전체 너비 버튼 + 회색 안내를 '게임창' 상자 하나로
        self.game_row = QGroupBox('게임창')
        row = QVBoxLayout(self.game_row)
        row.setSpacing(8)
        self.game_status = _label("")
        self.game_status.setTextFormat(Qt.TextFormat.RichText)
        row.addWidget(self.game_status)
        self.game_btn = QPushButton("게임창 등록 시작")
        self.game_btn.setMinimumHeight(34)
        self.game_btn.setToolTip("‘게임창 등록 시작’을 누른 뒤 3초 안에 마비노기 창을 선택해 주세요.")
        self.game_btn.clicked.connect(self.register_game.emit)
        row.addWidget(self.game_btn)
        self.game_hint = _gray("버튼을 누른 뒤 3초 안에 마비노기 창을 클릭해 주세요. 게임이 꺼져 있으면 나중에 등록해도 돼요.")
        row.addWidget(self.game_hint)
        layout.addWidget(self.game_row)

        # 2·3단계: 스크롤 없이 모두 펼친 '쓸 기능 고르기' 상자. 줄 = 체크 | 상태 | 직접 설정
        self.selection = QGroupBox('쓸 기능 고르기')
        rows = QVBoxLayout(self.selection)
        rows.setSpacing(2)
        self.checks, self.feature_rows, self.statuses, self.manual_buttons = {}, {}, {}, {}
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            widget = QWidget()
            line = QHBoxLayout(widget)
            line.setContentsMargins(0, 2, 0, 2)
            check = QCheckBox(CHOICE_TEXT[key] + " - " + feature.name)
            # 너비는 줄 레이아웃이 정하고 글자는 _fit_content가 그 너비에 맞춰 접는다(체크박스는 스스로 줄바꿈하지 않음)
            check.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            check.toggled.connect(lambda value, key=key: self.feature_changed.emit(key, value))
            line.addWidget(check, 1)
            status = QLabel("")
            line.addWidget(status, 0, Qt.AlignmentFlag.AlignVCenter)
            button = QPushButton('직접 설정')
            button.clicked.connect(lambda _=False, key=key: self.open_feature.emit(key))
            line.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            rows.addWidget(widget)
            self.checks[key] = check
            self.feature_rows[key], self.statuses[key], self.manual_buttons[key] = widget, status, button
        layout.addWidget(self.selection)
        self.boss_preparation = _label(BOSS_PREPARATION)
        self.boss_preparation.setStyleSheet('color:#c78c32; padding:8px; border:1px solid #806837; border-radius:3px;')
        layout.addWidget(self.boss_preparation)
        self.run_btn = QPushButton("고른 기능 자동설정")
        self.run_btn.setMinimumHeight(34)
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)

        # 4단계: 게임 최적화 강조 카드 + 그 밖의 기능 3열 카드(로그인 표시·버튼 없음 — 전체 공개)
        self.others = QWidget()
        others = QVBoxLayout(self.others)
        others.setContentsMargins(0, 4, 0, 0)
        others.setSpacing(10)
        self.optimization_card, card = _card('guideRecommendCard')
        self.optimization_card.setStyleSheet(
            f'#guideRecommendCard {{ border:2px solid {GREEN}; border-radius:6px; }}')
        head = QHBoxLayout()
        head.addWidget(_label('게임 최적화', bold=True))
        tag = QLabel('추천')
        tag.setStyleSheet(f'color:#ffffff; background:{GREEN}; border-radius:3px; padding:1px 6px; font-weight:600;')
        head.addWidget(tag)
        head.addStretch(1)
        card.addLayout(head)
        card.addWidget(_label('마비노기가 더 매끄럽게 돌도록 윈도우 설정을 바꿔요. 언제든 원래대로 되돌릴 수 있어요.'))
        card.addWidget(_label('바뀌는 항목: ' + OPTIMIZATION_ITEMS))
        self.optimization_btn = QPushButton('최적화 탭 열기')
        self.optimization_btn.setMinimumHeight(30)
        self.optimization_btn.clicked.connect(lambda: self.open_tab.emit('optimization'))
        card.addWidget(self.optimization_btn)
        card.addWidget(_gray('위치: 최적화 탭 · 마비노기를 켜면 자동 적용도 할 수 있어요'))
        others.addWidget(self.optimization_card)
        others.addWidget(_label('그 밖의 기능', bold=True))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.feature_cards = {}
        for index, (name, text, where) in enumerate(OTHER_FEATURES):
            frame, box = _card('guideFeatureCard')
            frame.setStyleSheet(f'#guideFeatureCard {{ border:1px solid {GRAY}; border-radius:6px; }}')
            box.addWidget(_label(name, bold=True))
            box.addWidget(_label(text))
            box.addStretch(1)
            box.addWidget(_gray('위치: ' + where))
            grid.addWidget(frame, index // 3, index % 3)
            self.feature_cards[name] = frame
        for column in range(3):
            grid.setColumnStretch(column, 1)
        others.addLayout(grid)
        layout.addWidget(self.others)

        self.progress = _label("")
        self.progress_area = QScrollArea()
        self.progress_area.setWidgetResizable(True)
        self.progress_area.setFrameShape(QFrame.Shape.NoFrame)
        self.progress_area.setWidget(self.progress)
        self.progress_area.setFixedHeight(85)
        layout.addWidget(self.progress_area)
        layout.addStretch(1)
        layout = footer_layout
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
        if self.stage == LAST and delta > 0:
            self.finish()
            return
        self.stage = max(0, min(LAST, self.stage + delta))
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
        fallback = "나중에 설정" if key in self.deferred and enabled(key, raw) else "영역 지정 필요"
        if not enabled(key, raw):
            return fallback
        if needed == [key]:
            return self.outcomes.get(key, fallback)
        return " / ".join(("보스 체력바" if region == "boss" else BY_KEY[region].name)
                          + ": " + self.outcomes.get(region, fallback) for region in needed)

    def refresh(self):
        raw = config._read_local_config()
        trail = ' → '.join(f'<b style="color:{GREEN}">{name}</b>' if i == self.stage else name
                           for i, name in enumerate(STAGE_NAMES))
        self.step_label.setText(f'<b>{self.stage + 1} / {len(STAGE_NAMES)}</b><br>'
                                f'<span style="color:{GRAY}">{trail}</span>')
        self.title.setText(("게임창 등록", "전투 보조 설정", "전투 보조 추가 설정", "다른 기능도 있어요")[self.stage])
        self.description.setText((
            ("처음 오셨군요. 필요한 기능만 골라 함께 설정해 봐요.\n"
             "게임창을 등록하면 앱이 마비노기 창을 찾을 수 있어요." if self.first_run else
             "등록한 게임창을 확인해 주세요.\n게임창을 바꿔야 한다면 여기서 다시 등록할 수 있어요."),
            "이번 자동설정에 포함할 전투 보조 기능을 골라주세요.\n선택하지 않아도 이미 등록한 영역과 세부 설정은 그대로 유지해요.",
            "도르카·투아림·체력바·단축바도 함께 설정할 수 있어요.\n이 기능들도 ‘전투 보조’ 탭에 있어요. 필요한 것만 고르거나 이 단계를 넘어가도 돼요.",
            "영역을 지정하지 않아도 바로 쓸 수 있는 기능들이에요. 필요할 때 해당 탭에서 켜 보세요.",
        )[self.stage])
        game = section(raw, "general").get("gameExe")
        self.game_status.setText(f'<span style="color:{GREEN}">●</span> 등록됨 · {escape(str(game))}' if game else
                                 f'<span style="color:{ORANGE}">●</span> 아직 등록 안 됨')
        choosing = self.stage in (1, 2)
        self.game_row.setVisible(self.stage == 0)
        self.selection.setVisible(choosing)
        self.run_btn.setVisible(choosing)
        self.figure.setVisible(choosing)
        self.figure_caption.setVisible(choosing)
        self.others.setVisible(self.stage == 3)
        for key in GUIDE_KEYS:
            feature = BY_KEY[key]
            check = self.checks[key]
            check.blockSignals(True)
            check.setChecked(enabled(key, raw))
            check.blockSignals(False)
            check.setEnabled(not self.busy and batch_allowed(key))
            check.setToolTip(feature.guidance)
            self.feature_rows[key].setVisible(key in self.feature_keys and batch_allowed(key))
            # 자동설정 승인·거절·실패 결과는 이 줄의 상태로 바로 보인다(6.1 즉시 갱신)
            text = self.status_text(key, raw)
            self.statuses[key].setText(text)
            self.statuses[key].setStyleSheet(f'color:{GREEN if text == "등록됨" else ORANGE};')
            self.manual_buttons[key].setEnabled(not self.busy and batch_allowed(key))
        self.boss_preparation.setVisible(choosing and needs_boss_preparation(raw, feature_keys=self.feature_keys))
        self._queue_fit()
        self.skip.blockSignals(True)
        self.skip.setChecked(section(raw, "general").get("skipSetup") is True)
        self.skip.blockSignals(False)
        self.back_btn.setEnabled(not self.busy and self.stage > 0)
        self.later_btn.setVisible(self.stage != LAST)
        self.next_btn.setText("다음")
        self.stop_btn.setVisible(self.busy)
        self.progress_area.setVisible(bool(self.progress.text()))
        for button in (self.game_btn, self.run_btn, self.later_btn, self.next_btn, self.optimization_btn):
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
        for key, check in self.checks.items():
            if not self.feature_rows[key].isVisibleTo(self):
                continue
            width = check.width()
            if width < 40:  # 아직 배치 전: 상태·버튼 몫을 빼고 어림잡는다
                width = self.body_scroll.viewport().width() - 260
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
            joined = '\n'.join(wrapped)
            if check.text() != joined:
                check.setText(joined)
            check.setMinimumHeight(max(30, check.sizeHint().height() + 8))
