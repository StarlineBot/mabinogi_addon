"""설정 탭 (기획서 5.3).

일반 설정 묶음. (오버레이 배율은 각 버프/디버프 탭으로 이동, 창 식별은 내부 고정,
알림음은 버프별로 등록된 사운드 파일로 재생 — TTS는 쓰지 않는다.)
아직 설정 파일과 연결하지 않은 항목이 있다.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QGroupBox, QVBoxLayout, QWidget


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
        return box
