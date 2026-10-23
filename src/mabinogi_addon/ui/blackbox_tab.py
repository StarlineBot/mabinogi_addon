"""제작자 블랙박스 패널. 캡처 어댑터 연결 전 조작은 비활성 상태다."""

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from .widgets import FeatureHeader


def _label(text, *, muted=False):
    label = QLabel(text)
    label.setWordWrap(True)
    if muted:
        label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
    return label


class BlackboxTab(QWidget):
    """기본 상태는 조작 불가. 샘플 상태는 렌더 도구에서만 주입한다."""

    def __init__(self, parent=None):
        super().__init__(parent)
        body = QVBoxLayout(self)
        body.setSpacing(12)
        body.addWidget(FeatureHeader('블랙박스', '최근 게임 영상을 보관하고, 필요한 순간을 저장해요.'))
        self.preview_notice = _label('화면 검토용 시안이에요. 아직 실제 녹화·저장은 동작하지 않아요.')
        body.addWidget(self.preview_notice)

        box = QGroupBox('최근 영상 보관')
        group = QVBoxLayout(box)
        # 사용 켜기/끄기는 '위치 잠금'과 같은 토글 버튼(명세 11.3): 꺼짐 '블랙박스 사용', 켜짐 '블랙박스 사용 중'(민트).
        from PySide6.QtCore import Qt
        from .settings_layout import LOCK_STYLE
        self.enabled = QPushButton('블랙박스 사용')
        self.enabled.setCheckable(True)
        self.enabled.setStyleSheet(LOCK_STYLE)
        self.enabled.toggled.connect(lambda on: self.enabled.setText('블랙박스 사용 중' if on else '블랙박스 사용'))
        group.addWidget(self.enabled, 0, Qt.AlignmentFlag.AlignLeft)
        group.addWidget(_label('녹화 중에는 시스템 자원을 사용해요.', muted=True))
        # 녹화 방식(명세 12.2): 평소 녹화(기본) / 전투 녹화(보스 체력바가 보이는 동안)
        from PySide6.QtWidgets import QButtonGroup, QRadioButton
        self.mode_always = QRadioButton('평소 녹화')
        self.mode_combat = QRadioButton('전투 녹화')
        self.mode_always.setChecked(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.mode_always); self.mode_group.addButton(self.mode_combat)
        row = QHBoxLayout()
        row.addWidget(self.mode_always); row.addWidget(self.mode_combat); row.addStretch()
        form = QFormLayout()
        form.addRow('녹화 방식', row)
        group.addLayout(form)
        self.mode_help = _label('평소 녹화: 게임 창이 최소화되지 않았으면 항상 보관해요.\n'
                                '전투 녹화: 보스 체력바가 보이는 동안 보관하고, 사라지면 60초 뒤 멈춰요.', muted=True)
        group.addWidget(self.mode_help)
        self.mode_notice = _label('')
        self.mode_notice.setStyleSheet('color:#e67e22;')
        self.mode_notice.hide()
        group.addWidget(self.mode_notice)
        self.retention = QLineEdit('10')
        self.retention.setMaximumWidth(100)
        row = QHBoxLayout()
        row.addWidget(self.retention)
        row.addWidget(QLabel('분'))
        row.addStretch()
        form = QFormLayout()
        form.addRow('최근 보관 시간', row)
        group.addLayout(form)
        group.addWidget(_label('게임 창이 뒤에 있어도 보관해요. 최소화하면 잠시 멈추고, 복원하면 이어서 보관해요.\n'
                               '보관 시간에는 실제로 녹화한 게임 영상만 포함해요.', muted=True))
        body.addWidget(box)

        box = QGroupBox('현재 상태')
        group = QVBoxLayout(box)
        self.status = _label('녹화 연결 전 · 보관한 영상 없음')
        font = self.status.font()
        font.setBold(True)
        self.status.setFont(font)
        group.addWidget(self.status)
        self.available = _label('확보한 영상 0초 / 설정 10분')
        group.addWidget(self.available)
        self.capture_info = _label('게임 화면만 · 목표 1080p / 60FPS', muted=True)
        group.addWidget(self.capture_info)
        self.audio_info = _label('게임 소리: 지원 환경 확인 전', muted=True)
        group.addWidget(self.audio_info)
        body.addWidget(box)

        box = QGroupBox('영상 저장')
        group = QVBoxLayout(box)
        self.save = QPushButton('최근 영상 저장')
        row = QHBoxLayout()
        row.addWidget(self.save)
        self.hotkey = _label('게임 내 저장 단축키: 실게임 검증 후 지정', muted=True)
        row.addWidget(self.hotkey, 1)
        group.addLayout(row)
        self.save_result = _label('저장한 영상은 사용을 꺼도 그대로 남아요.', muted=True)
        group.addWidget(self.save_result)
        self.recovery = QPushButton('저장 내역·복구')
        self.recovery.setEnabled(False)
        group.addWidget(self.recovery)
        self.folder = _label('Windows 동영상 폴더 아래 전용 폴더 · 이름 확인 전')
        form = QFormLayout()
        form.addRow('저장 위치', self.folder)
        group.addLayout(form)
        row = QHBoxLayout()
        self.change_folder = QPushButton('저장 위치 변경')
        self.open_folder = QPushButton('폴더 열기')
        row.addWidget(self.change_folder)
        row.addWidget(self.open_folder)
        row.addStretch()
        group.addLayout(row)
        group.addWidget(_label('게임 종료나 사용 해제 후에도 앱을 닫기 전까지 최근 영상을 저장할 수 있어요.', muted=True))
        body.addWidget(box)
        body.addStretch()
        for control in (self.enabled, self.retention, self.save, self.change_folder, self.open_folder,
                        self.mode_always, self.mode_combat):
            control.setEnabled(False)
