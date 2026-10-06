"""설정 탭 (기획서 5.3).

일반 / 오버레이 / 게임 세 묶음. 값은 아직 설정 파일과 연결하지 않았다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


def _checked(text: str, on: bool = True) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(on)
    return box


def _scale_spin(value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(50, 300)
    spin.setSingleStep(10)
    spin.setSuffix(" %")
    spin.setValue(value)
    return spin


class SettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        v.addWidget(self._general_group())
        v.addWidget(self._overlay_group())
        v.addWidget(self._game_group())
        v.addStretch(1)

    def _general_group(self) -> QGroupBox:
        box = QGroupBox("일반")
        v = QVBoxLayout(box)
        v.addWidget(_checked("Windows 시작 시 자동 실행"))
        v.addWidget(_checked("실행 시 트레이로 시작"))
        v.addWidget(_checked("닫기(X) 버튼을 누르면 트레이로 최소화"))
        v.addWidget(_checked("게임 비활성 중에도 소리 알림"))

        v.addSpacing(4)
        v.addWidget(QLabel("알림음 방식"))
        sound_row = QHBoxLayout()
        self.sound_group = QButtonGroup(self)
        beep = QRadioButton("기본음")
        tts = QRadioButton("TTS (버프명 + 연장)")
        tts.setChecked(True)
        self.sound_group.addButton(beep)
        self.sound_group.addButton(tts)
        sound_row.addWidget(beep)
        sound_row.addWidget(tts)
        sound_row.addStretch(1)
        v.addLayout(sound_row)
        return box

    def _overlay_group(self) -> QGroupBox:
        box = QGroupBox("오버레이")
        v = QVBoxLayout(box)

        form = QFormLayout()
        scaling = QComboBox()
        scaling.addItems(["Nearest", "Bilinear"])
        form.addRow("버프 배율", _scale_spin(150))
        form.addRow("디버프 배율", _scale_spin(100))
        form.addRow("아이콘 확대 방식", scaling)
        v.addLayout(form)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QPushButton("오버레이 위치 편집"))
        edit_row.addStretch(1)
        v.addLayout(edit_row)
        return box

    def _game_group(self) -> QGroupBox:
        box = QGroupBox("게임")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("마비노기 창 식별"))
        row.addWidget(QLineEdit("Mabinogi"))
        row.addWidget(QPushButton("자동 찾기"))
        v.addLayout(row)
        return box
