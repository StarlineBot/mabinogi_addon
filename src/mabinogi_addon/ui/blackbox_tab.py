"""블랙박스 패널(0.16.0 디스코드 로그인 사용자). 캡처 연결 전 조작은 비활성 상태다.

상태·오류·최근 저장은 각각 다른 위젯이라 0.1초 갱신이 서로의 문구를 덮어쓰지 않는다.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (QAbstractSpinBox, QButtonGroup, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget)

from ..blackbox import MAX_RETENTION_MINUTES
from .widgets import FeatureHeader

ERROR_COLOR = '#d35b58'


def _label(text, *, muted=False):
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
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
        body.setSpacing(12)
        body.addWidget(FeatureHeader('블랙박스', '최근 게임 영상을 보관하고, 필요한 순간을 저장해요.',
                                     help_button('블랙박스 사용법', HELP['블랙박스'], self)))

        box = QGroupBox('최근 영상 보관')
        group = QVBoxLayout(box)
        # 사용 켜기/끄기는 '위치 잠금'과 같은 토글 버튼(명세 11.3): 꺼짐 '블랙박스 사용', 켜짐 '블랙박스 사용 중'(민트).
        from .settings_layout import LOCK_STYLE
        self.enabled = QPushButton('블랙박스 사용')
        self.enabled.setCheckable(True)
        self.enabled.setStyleSheet(LOCK_STYLE)
        self.enabled.toggled.connect(lambda on: self.enabled.setText('블랙박스 사용 중' if on else '블랙박스 사용'))
        group.addWidget(self.enabled, 0, Qt.AlignmentFlag.AlignLeft)
        group.addWidget(_label('켜 두는 동안 컴퓨터 자원과 임시 저장 공간(5분 보관 기준 약 450MB)을 사용해요.', muted=True))
        # 녹화 방식(명세 12.2): 평소 녹화(기본) / 전투 녹화(보스 체력바가 보이는 동안)
        self.mode_always = QRadioButton('평소 녹화')
        self.mode_combat = QRadioButton('전투 녹화')
        self.mode_always.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_always)
        self.mode_group.addButton(self.mode_combat)
        row = QHBoxLayout()
        row.addWidget(self.mode_always)
        row.addWidget(self.mode_combat)
        row.addStretch()
        self.retention = QSpinBox()
        self.retention.setRange(1, MAX_RETENTION_MINUTES)
        self.retention.setValue(5)
        self.retention.setSuffix(' 분')
        self.retention.setKeyboardTracking(False)  # 입력 중간값(1→15 사이의 '1')으로 저장하지 않게
        self.retention.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        self.retention.setFixedWidth(90)
        form = QFormLayout()
        form.addRow('녹화 방식', row)
        form.addRow('최근 보관 시간', self.retention)
        group.addLayout(form)
        self.mode_notice = _label('')
        self.mode_notice.setStyleSheet('color:#e67e22;')
        self.mode_notice.hide()
        group.addWidget(self.mode_notice)
        self.mode_help = _label('평소 녹화: 게임 창이 최소화되지 않았으면 항상 보관해요.\n'
                                '전투 녹화: 보스 체력바가 보이는 동안 보관하고, 사라지면 60초 뒤 멈춰요.\n'
                                '게임 창이 뒤에 있어도 보관해요. 최소화하면 잠시 멈추고, 복원하면 이어서 보관해요.', muted=True)
        group.addWidget(self.mode_help)
        body.addWidget(box)

        box = QGroupBox('현재 상태')
        group = QVBoxLayout(box)
        self.status = _bold(_label('녹화 연결 전'))
        group.addWidget(self.status)
        self.available = _label('확보한 영상 0초 / 설정 5분')
        group.addWidget(self.available)
        self.capture_info = _label('게임 화면만 · 1080p / 60FPS · 게임 소리는 저장하지 않아요', muted=True)
        group.addWidget(self.capture_info)
        self.error = _label('')
        self.error.setStyleSheet(f'color:{ERROR_COLOR};')
        self.error.hide()
        group.addWidget(self.error)
        body.addWidget(box)

        box = QGroupBox('영상 저장')
        group = QVBoxLayout(box)
        self.save = QPushButton('최근 영상 저장')
        _left(group, self.save)
        self.hotkey = _bold(QLabel('Ctrl+Alt+PrintScreen'))
        self.change_hotkey = QPushButton('단축키 변경')
        row = _left(group, QLabel('저장 단축키'), self.hotkey, self.change_hotkey)
        row.setSpacing(10)
        group.addWidget(_label('단축키는 게임 창이 앞에 있을 때만 저장해요. 키 입력은 게임에도 그대로 전달돼요.', muted=True))
        self.recent = _label('최근 저장: 아직 없어요')
        group.addWidget(self.recent)
        self.folder = _label('저장 위치 확인 전')
        self.folder.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        group.addWidget(self.folder)
        self.change_folder = QPushButton('저장 위치 변경')
        self.open_folder = QPushButton('폴더 열기')
        self.recovery = QPushButton('저장 내역·복구')
        _left(group, self.change_folder, self.open_folder, self.recovery)
        group.addWidget(_label('저장 내역·복구: 저장이 실패했거나 오래 걸릴 때, 게임을 끈 뒤 직전 게임 영상을 저장할 때 써요. '
                               '저장한 영상은 블랙박스를 꺼도 그대로 남아요.', muted=True))
        body.addWidget(box)
        body.addStretch()
        for control in self.controls():
            control.setEnabled(False)

    def controls(self):
        return (self.enabled, self.retention, self.save, self.change_folder, self.open_folder, self.recovery,
                self.mode_always, self.mode_combat, self.change_hotkey)

    def show_error(self, text):
        self.error.setText(text or '')
        self.error.setVisible(bool(text))
