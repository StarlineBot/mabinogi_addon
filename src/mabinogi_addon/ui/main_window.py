"""메인 창 (기획서 5.1).

탭(버프 / 디버프 / 설정) + 오른쪽 위 실행 상태 표시.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QTabWidget,
    QWidget,
)

from .buff_tab import BuffTab
from .debuff_tab import DebuffTab
from .overlay import BuffOverlay
from .party_tab import PartyTab
from .settings_tab import SettingsTab

LOGO_PATH = Path(__file__).resolve().parents[1] / "assets" / "logo.png"


def app_icon() -> QIcon:
    """앱 로고 아이콘(창·작업표시줄)."""
    return QIcon(str(LOGO_PATH))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("마비노기 버프 트래커")
        self.setWindowIcon(app_icon())
        self.resize(780, 620)

        self.buff_tab = BuffTab()
        self.party_tab = PartyTab()
        tabs = QTabWidget()
        tabs.addTab(self.buff_tab, "버프")
        tabs.addTab(DebuffTab(), "디버프")
        tabs.addTab(self.party_tab, "파티")
        tabs.addTab(SettingsTab(), "설정")
        tabs.setCornerWidget(self._status_widget(), Qt.Corner.TopRightCorner)
        self.setCentralWidget(tabs)

        # 버프 오버레이: 고정 버튼으로 클릭통과/드래그 토글
        self.buff_overlay = BuffOverlay()
        self.buff_tab.lock_toggled.connect(self._on_overlay_lock)

    def _on_overlay_lock(self, locked: bool) -> None:
        self.buff_overlay.set_locked(locked)
        if locked:
            # 아이템이 없으면 숨고, 있으면 고정된 위치에 클릭통과로 유지
            if not self.buff_overlay._items:
                self.buff_overlay.hide()
        else:
            self.buff_overlay.show()  # 드래그로 위치 잡기

    def start(self) -> None:
        """탐지/폴링 시작. 실제 앱 실행(main)에서만 호출한다(스크린샷 렌더 땐 미호출)."""
        self.party_tab.start_polling()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        self.party_tab.stop_polling()
        self.buff_overlay.close()
        super().closeEvent(event)

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
