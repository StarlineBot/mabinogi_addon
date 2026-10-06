"""설정 탭 (기획서 5.3).

일반 설정 묶음. (오버레이 배율은 각 버프/디버프 탭으로 이동, 창 식별은 내부 고정.)
아직 설정 파일과 연결하지 않은 항목이 있다.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)


def _checked(text: str, on: bool = True) -> QCheckBox:
    box = QCheckBox(text)
    box.setChecked(on)
    return box


class SettingsTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(12)
        v.addWidget(self._general_group())
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
