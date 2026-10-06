"""메인 창 (기획서 5.1).

탭(버프 / 디버프 / 설정) + 오른쪽 위 실행 상태 표시.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QWidget,
)

from .buff_tab import BuffTab
from .debuff_tab import DebuffTab
from .party_tab import PartyTab
from .settings_tab import SettingsTab


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("마비노기 버프 트래커")
        self.resize(780, 620)

        tabs = QTabWidget()
        tabs.addTab(BuffTab(), "버프")
        tabs.addTab(DebuffTab(), "디버프")
        tabs.addTab(PartyTab(), "파티")
        tabs.addTab(SettingsTab(), "설정")
        tabs.setCornerWidget(self._status_widget(), Qt.Corner.TopRightCorner)

        self.setCentralWidget(tabs)

    def _status_widget(self) -> QWidget:
        """오른쪽 위 '● 실행 중' 표시. 나중에 탐지 상태와 연결한다."""
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(8, 0, 12, 0)

        dot = QLabel("●")
        dot.setStyleSheet("color:#2ecc71;")
        text = QLabel("실행 중")
        row.addWidget(dot)
        row.addWidget(text)
        return widget
