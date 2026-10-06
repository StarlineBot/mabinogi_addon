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

from .. import config
from ..capture import Region, create_live_source
from ..catalog import build_templates, load_catalog
from ..tracker.engine import BuffEngine
from .buff_controller import BuffController
from .buff_tab import ANCHOR_ID, BuffTab
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
        self.buff_controller: BuffController | None = None
        self.buff_tab.lock_toggled.connect(self._on_overlay_lock)

    def _on_overlay_lock(self, locked: bool) -> None:
        self.buff_overlay.set_locked(locked)
        if locked and not self.buff_overlay._items:
            self.buff_overlay.hide()  # 고정+비어있음 → 숨김
        else:
            self.buff_overlay.show()

    def start(self) -> None:
        """탐지/폴링 시작. 실제 앱 실행(main)에서만 호출한다(스크린샷 렌더 땐 미호출)."""
        self.party_tab.start_polling()
        # 시작부터 보이게(해제=드래그로 위치 잡기). 빈 목록으로 플레이스홀더 크기 확정.
        self.buff_overlay.set_items([])
        self.buff_overlay.show()
        self._start_buff_tracking()

    def _start_buff_tracking(self) -> None:
        """저장된 영역이 있으면 라이브 캡처(dxcam)로 버프 추적 시작."""
        region = config.load_capture_region("buffTracker")
        if not region:
            return
        try:
            source = create_live_source(
                Region(region["x"], region["y"], region["w"], region["h"])
            )
        except Exception:  # noqa: BLE001 — dxcam 없음(맥 등)이면 라이브 미시작
            return

        catalog = load_catalog()
        catalog_by = {b.id: b for b in catalog}
        saved = {s.id: s for s in config.load_buff_settings()}

        order: list[str] = []
        for s in config.load_buff_settings():
            if s.id in catalog_by and s.id != ANCHOR_ID and not s.hidden:
                order.append(s.id)
        for b in catalog:
            if b.id != ANCHOR_ID and b.id not in order:
                if b.id not in saved or not saved[b.id].hidden:
                    order.append(b.id)

        show_duration = {
            b.id: (saved[b.id].show_duration if b.id in saved else True)
            for b in catalog
        }
        alert_before = {
            b.id: (saved[b.id].alert.before_sec if b.id in saved else 30)
            for b in catalog
        }
        # 초기 구동에선 앵커 게이팅 off(앵커가 영역 밖이면 전부 동결되는 것 방지).
        # 매칭 안정화 후 앵커 기반 '판정 불가' 로직을 다시 켠다.
        engine = BuffEngine(
            build_templates(catalog),
            order,
            anchor_id=None,
            show_duration=show_duration,
            alert_before=alert_before,
        )
        self.buff_controller = BuffController(
            self.buff_overlay, catalog_by, show_duration
        )
        self.buff_controller.start(source, engine)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        self.party_tab.stop_polling()
        if self.buff_controller is not None:
            self.buff_controller.stop()
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
