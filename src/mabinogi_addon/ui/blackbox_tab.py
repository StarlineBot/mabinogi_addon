"""블랙박스 패널(모든 사용자, 2026-10-28 기능 공개 정책 7절). 캡처 연결 전 조작은 비활성 상태다.

상태·오류·최근 저장은 각각 다른 위젯이라 0.1초 갱신이 서로의 문구를 덮어쓰지 않는다.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from .palette import Named, color
from ..blackbox import MAX_RETENTION_MINUTES
from .widgets import FeatureHeader

CAPTURE_INFO = '켜 두는 동안 컴퓨터 자원과 임시 공간(5분 기준 약 450MB)을 써요 · 게임 화면만 1080p/60FPS · 게임 소리는 저장하지 않아요'
STATE_COLORS = Named({'ok': 'ok', 'muted': 'muted', 'error': 'danger'})


class _NoWheelSpinBox(QSpinBox):
    """포커스가 없을 때는 휠을 무시하고 바깥 스크롤로 넘긴다(0.16.0 QA).
    탭을 휠로 스크롤하다 칸 위를 지나면 보관 시간이 줄어 오래된 영상이 즉시 지워지던 문제를 막는다."""

    def wheelEvent(self, event):
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)


def _label(text, *, muted=False):
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setStyleSheet(f"color:{color('muted')};")  # 안내 = 같은 회색(명세 14.2)
    return label


def _bold(label):
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def _left(layout, *widgets):
    """버튼을 글자 폭으로 왼쪽에 붙여 한 줄로 둔다."""
    row = QHBoxLayout()
    for widget in widgets:
        row.addWidget(widget)
    row.addStretch()
    layout.addLayout(row)
    return row


class BlackboxTab(QWidget):
    """기본 상태는 조작 불가. 샘플 상태는 렌더 도구에서만 주입한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        from .feature_copy import HELP
        from .help_dialog import help_button
        body = QVBoxLayout(self)
        body.setContentsMargins(12, 12, 12, 12)  # 다른 탭과 같은 여백(앱 문구 명세 10절)
        body.setSpacing(12)
        body.addWidget(FeatureHeader('블랙박스', '최근 게임 영상을 보관하고, 필요한 순간을 저장해요.',
                                     help_button('블랙박스 사용법', HELP['블랙박스'], self)))

        # 1줄(안내·도움말 명세 11.2): 사용 토글 + 상태 한 줄(예전 '현재 상태' 상자 흡수)
        # 사용 켜기/끄기는 홈과 같은 스위치(명세 14.5) — 켜짐·꺼짐은 스위치와 옆 상태 줄이 보여 준다.
        from .widgets import switch
        self.enabled = switch('블랙박스 사용')
        self.dot = QLabel('●')
        self.status = _label('녹화 연결 전')
        self.status.setWordWrap(False)
        self.available = QLabel('')
        row = QHBoxLayout()
        row.addWidget(self.enabled)
        row.addSpacing(6)
        row.addWidget(self.dot)
        row.addWidget(self.status)
        row.addWidget(self.available)
        row.addStretch()
        body.addLayout(row)
        self.error = _label('')
        self.error.setStyleSheet(f"color:{color('danger')};")
        self.error.hide()
        body.addWidget(self.error)
        self.paint_state(False, 'disabled')

        # 보관과 저장: 1줄 보관 시간 | 단축키(사용자 아이디어), 2줄 지금 저장 + 최근 저장, 안내 한 줄
        box = QGroupBox('보관과 저장')
        group = QVBoxLayout(box)
        self.retention = _NoWheelSpinBox()
        self.retention.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # 휠로 포커스를 가져가지 않음(클릭·Tab으로만)
        self.retention.setRange(1, MAX_RETENTION_MINUTES)
        self.retention.setValue(5)
        self.retention.setSuffix(' 분')
        self.retention.setKeyboardTracking(False)  # 입력 중간값(1→15 사이의 '1')으로 저장하지 않게
        self.retention.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.retention.setFixedWidth(90)
        self.hotkey = _bold(QLabel('Ctrl+Alt+PrintScreen'))
        self.change_hotkey = QPushButton('변경')
        separator = QLabel('|')
        separator.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        row = _left(group, QLabel('최근 보관 시간'), self.retention, separator, QLabel('저장 단축키'),
                    self.hotkey, self.change_hotkey)
        row.setSpacing(8)
        self.save = QPushButton('지금 최근 영상 저장')
        self.recent = _label('최근 저장: 아직 없어요')
        self.recent.setWordWrap(False)
        _left(group, self.save, self.recent)
        group.addWidget(_label('단축키는 게임 창이 앞에 있을 때만 저장해요. 키 입력은 게임에도 그대로 전달돼요.', muted=True))
        body.addWidget(box)

        # 녹화 방식(명세 12.2): 전투 녹화(기본, 보스 체력바가 보이는 동안) / 평소 녹화 — 고른 방식 설명 한 줄만
        box = QGroupBox('녹화 방식')
        group = QVBoxLayout(box)
        self.mode_combat = QRadioButton('전투 녹화')
        self.mode_always = QRadioButton('평소 녹화')
        self.mode_combat.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_combat)
        self.mode_group.addButton(self.mode_always)
        _left(group, self.mode_combat, self.mode_always)
        self.mode_notice = _label('')
        self.mode_notice.setStyleSheet(f'color:{color('warn')};')
        self.mode_notice.hide()
        group.addWidget(self.mode_notice)
        self.mode_help = _label('', muted=True)
        group.addWidget(self.mode_help)
        self.mode_combat.toggled.connect(self._mode_help)
        self._mode_help()
        body.addWidget(box)

        # 저장 위치: 경로 + 변경·폴더 열기 한 줄
        box = QGroupBox('저장 위치')
        group = QVBoxLayout(box)
        self.folder = _label('저장 위치 확인 전')
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.change_folder = QPushButton('변경')
        self.open_folder = QPushButton('폴더 열기')
        row = QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(self.change_folder)
        row.addWidget(self.open_folder)
        group.addLayout(row)
        body.addWidget(box)

        # 저장 내역·복구: 평소엔 접어 둔 줄(누르면 내역·복구 창)
        from .optimization_panel import DISCLOSURE_STYLE
        self.recovery = QPushButton('저장 내역·복구 ▸')
        self.recovery.setFlat(True)
        self.recovery.setStyleSheet(DISCLOSURE_STYLE)
        self.recovery.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recovery.setToolTip('저장이 실패했거나 오래 걸릴 때, 게임을 끈 뒤 직전 게임 영상을 저장할 때 써요. '
                                 '저장한 영상은 블랙박스를 꺼도 그대로 남아요.')
        body.addWidget(self.recovery, 0, Qt.AlignmentFlag.AlignLeft)
        self.capture_info = _label(CAPTURE_INFO)
        self.capture_info.setStyleSheet(f'color:{color('muted')};')  # 맨 아래 회색 한 줄(명세 11.2)
        body.addWidget(self.capture_info)
        body.addStretch()
        for control in self.controls():
            control.setEnabled(False)

    def controls(self):
        return (self.enabled, self.retention, self.save, self.change_folder, self.open_folder, self.recovery,
                self.mode_always, self.mode_combat, self.change_hotkey)

    def _mode_help(self, *_):
        self.mode_help.setText('전투 녹화: 보스 체력바가 보이는 동안 보관하고, 사라지면 60초 뒤 멈춰요.' if self.mode_combat.isChecked()
                               else '평소 녹화: 게임 창이 최소화되지 않았으면 항상 보관해요(뒤에 있어도 보관).')

    def paint_state(self, enabled, status):
        """1줄 상태(명세 11.2): 꺼짐 `● 꺼짐 — 켜면 최근 영상을 계속 보관해요`(회색) / 켜짐 `● 보관 중 3:12 / 5분 · 전투`(초록)."""
        if not enabled or status == 'disabled':
            self.status.setText('꺼짐 — 켜면 최근 영상을 계속 보관해요')
            self.available.hide()
            kind = 'muted'
        else:
            self.available.show()
            kind = 'error' if status == 'error' else 'ok' if status == 'recording' else 'muted'
        color = STATE_COLORS[kind]
        self.dot.setStyleSheet(f'color:{color};')
        self.status.setStyleSheet(f'color:{color};')
        self.available.setStyleSheet(f'color:{color};')

    def show_error(self, text):
        self.error.setText(text or '')
        self.error.setVisible(bool(text))
