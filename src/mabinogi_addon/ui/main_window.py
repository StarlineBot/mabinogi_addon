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
from ..catalog import build_templates, load_catalog, load_debuff_catalog
from ..system.window_watcher import create_window_watcher
from ..tracker.debuff_engine import DebuffEngine
from ..tracker.engine import BuffEngine
from .buff_controller import BuffController
from .buff_tab import ANCHOR_ID, BuffTab
from .debuff_tab import DebuffTab
from .notifier import SoundNotifier, default_sound_map
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
        self.debuff_tab = DebuffTab()
        self.party_tab = PartyTab()
        tabs = QTabWidget()
        tabs.addTab(self.buff_tab, "버프")
        tabs.addTab(self.debuff_tab, "디버프")
        tabs.addTab(self.party_tab, "파티")
        tabs.addTab(SettingsTab(), "설정")
        tabs.setCornerWidget(self._status_widget(), Qt.Corner.TopRightCorner)
        self.setCentralWidget(tabs)

        self._watcher = create_window_watcher()  # 포그라운드 감지(맥=항상 활성)
        self._restoring = False  # 복원 중엔 상태 저장 안 함

        # 버프 오버레이
        self.buff_overlay = BuffOverlay()
        self.buff_controller: BuffController | None = None
        self._engine: BuffEngine | None = None
        self._notifier = SoundNotifier(default_sound_map())
        self._sound_ids: set[str] = set()  # 소리 알림 켠 버프(알림 때 재생)
        self.buff_tab.lock_toggled.connect(self._on_overlay_lock)
        self.buff_tab.tracking_changed.connect(self._on_tracking_changed)
        self.buff_tab.catalog_changed.connect(self._on_catalog_changed)
        self.buff_overlay.moved.connect(self._save_overlay_state)

        # 디버프 오버레이
        self.debuff_overlay = BuffOverlay(placeholder_name="디버프")
        self.debuff_controller: BuffController | None = None
        self._debuff_engine = None
        self.debuff_tab.lock_toggled.connect(self._on_debuff_lock)
        self.debuff_tab.tracking_changed.connect(self._on_debuff_tracking_changed)
        self.debuff_tab.catalog_changed.connect(self._on_debuff_catalog_changed)
        self.debuff_overlay.moved.connect(self._save_debuff_overlay_state)

    # ---- 오버레이 고정/저장/복원(버프·디버프 공용 로직) ----
    def _apply_lock(self, overlay: BuffOverlay, locked: bool, section: str) -> None:
        overlay.set_locked(locked)
        if locked and not overlay._items:
            overlay.hide()  # 고정+비어있음 → 숨김
        else:
            overlay.show()
        self._save_overlay(overlay, section)

    def _save_overlay(self, overlay: BuffOverlay, section: str) -> None:
        if self._restoring:
            return
        pos = overlay.pos()
        config.save_overlay_state(pos.x(), pos.y(), overlay.locked, section)

    def _restore_overlay(self, overlay: BuffOverlay, tab, section: str) -> None:
        self._restoring = True
        try:
            overlay.set_items([])  # 플레이스홀더 크기 확정
            state = config.load_overlay_state(section)
            if state and "x" in state and "y" in state:
                overlay.move(int(state["x"]), int(state["y"]))
            locked = bool(state.get("locked")) if state else False
            tab.set_lock_state(locked)  # 버튼 동기화 + lock_toggled(→ 가시성 적용)
        finally:
            self._restoring = False

    def _on_overlay_lock(self, locked: bool) -> None:
        self._apply_lock(self.buff_overlay, locked, "buffTracker")

    def _save_overlay_state(self) -> None:
        self._save_overlay(self.buff_overlay, "buffTracker")

    def _on_debuff_lock(self, locked: bool) -> None:
        self._apply_lock(self.debuff_overlay, locked, "debuffTracker")

    def _save_debuff_overlay_state(self) -> None:
        self._save_overlay(self.debuff_overlay, "debuffTracker")

    def start(self) -> None:
        """탐지/폴링 시작. 실제 앱 실행(main)에서만 호출한다(스크린샷 렌더 땐 미호출)."""
        self.party_tab.start_polling()
        self._restore_overlay(self.buff_overlay, self.buff_tab, "buffTracker")
        self._restore_overlay(self.debuff_overlay, self.debuff_tab, "debuffTracker")
        self._start_buff_tracking()
        self._start_debuff_tracking()

    def _compute_tracking(
        self, catalog
    ) -> tuple[
        list[str],
        dict[str, bool],
        dict[str, int],
        dict[str, bool],
        dict[str, int | None],
    ]:
        """저장 설정으로 (순서, 지속시간, 1차초, 점멸, 2차초[없으면 None])를 만든다."""
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
        # 점멸: '종료 알림'과 '점멸'을 모두 켠 버프만. 설정 없으면 기본 켜짐.
        blink = {
            b.id: (
                saved[b.id].alert.enabled and saved[b.id].alert.blink
                if b.id in saved
                else True
            )
            for b in catalog
        }
        # 2차 알림 기준초: '종료 알림'+'2차 알림'을 모두 켠 버프만, 아니면 None(없음).
        alert_before2 = {
            b.id: (
                saved[b.id].alert.before_sec2
                if (
                    b.id in saved
                    and saved[b.id].alert.enabled
                    and saved[b.id].alert.enabled2
                )
                else None
            )
            for b in catalog
        }
        return order, show_duration, alert_before, blink, alert_before2

    def _start_buff_tracking(self) -> None:
        """저장된 영역이 있으면 라이브 캡처(dxcam)로 버프 추적 시작(재시작 포함)."""
        if self.buff_controller is not None:
            self.buff_controller.stop()
            self.buff_controller = None
            self._engine = None

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
        order, show_duration, alert_before, blink, alert_before2 = (
            self._compute_tracking(catalog)
        )
        self._sound_ids = self._sound_enabled_ids()
        # 초기 구동에선 앵커 게이팅 off(앵커가 영역 밖이면 전부 동결되는 것 방지).
        # 매칭 안정화 후 앵커 기반 '판정 불가' 로직을 다시 켠다.
        self._engine = BuffEngine(
            build_templates(catalog),
            order,
            anchor_id=None,
            show_duration=show_duration,
            alert_before=alert_before,
            alert_before2=alert_before2,
        )
        self.buff_controller = BuffController(
            self.buff_overlay,
            catalog_by,
            show_duration,
            on_alert=self._on_buff_alert,
            watcher=self._watcher,
            blink_enabled=blink,
        )
        self.buff_controller.start(source, self._engine)

    def _sound_enabled_ids(self) -> set[str]:
        """'종료 알림'과 '소리'를 모두 켠 버프 id 집합(알림 시 사운드 재생 대상)."""
        return {
            s.id
            for s in config.load_buff_settings()
            if s.alert.enabled and s.alert.sound
        }

    def _on_buff_alert(self, buff_ids) -> None:
        """엔진이 만료임박 알림을 올리면, 소리 켠 버프만 사운드 재생."""
        to_play = [b for b in buff_ids if b in self._sound_ids]
        if to_play:
            self._notifier.alert(to_play)

    def _on_tracking_changed(self) -> None:
        """순서·노출·지속시간·알림 변경을 실행 중 엔진에 즉시 반영(재시작 없이)."""
        if self._engine is None or self.buff_controller is None:
            return
        order, show_duration, alert_before, blink, alert_before2 = (
            self._compute_tracking(load_catalog())
        )
        self._engine.set_order(order)
        self._engine.set_show_duration(show_duration)
        self._engine.set_alert_before(alert_before)
        self._engine.set_alert_before2(alert_before2)
        self.buff_controller.set_show_duration(show_duration)
        self.buff_controller.set_blink_enabled(blink)
        self._sound_ids = self._sound_enabled_ids()

    def _on_catalog_changed(self) -> None:
        """버프 추가·삭제·아이콘 변경 → 템플릿 재구성을 위해 추적 재시작."""
        if self.buff_controller is not None:
            self._start_buff_tracking()

    # ---- 디버프 추적 ----
    def _debuff_order(self, catalog) -> list[str]:
        """저장 순서(숨김 제외) + 새 디버프. 등록 순서대로 표시."""
        catalog_by = {b.id: b for b in catalog}
        saved = {s.id: s for s in config.load_debuff_settings()}
        order: list[str] = []
        for s in config.load_debuff_settings():
            if s.id in catalog_by and not s.hidden:
                order.append(s.id)
        for b in catalog:
            if b.id not in order and (b.id not in saved or not saved[b.id].hidden):
                order.append(b.id)
        return order

    def _start_debuff_tracking(self) -> None:
        """저장된 디버프 영역이 있으면 라이브로 디버프 추적 시작(재시작 포함)."""
        if self.debuff_controller is not None:
            self.debuff_controller.stop()
            self.debuff_controller = None
            self._debuff_engine = None

        region = config.load_capture_region("debuffTracker")
        if not region:
            return
        try:
            source = create_live_source(
                Region(region["x"], region["y"], region["w"], region["h"])
            )
        except Exception:  # noqa: BLE001 — dxcam 없음(맥 등)
            return

        catalog = load_debuff_catalog()
        catalog_by = {b.id: b for b in catalog}
        self._debuff_engine = DebuffEngine(
            build_templates(catalog), self._debuff_order(catalog)
        )
        # 지속시간·알림·점멸 없음 → show_duration 전부 False.
        self.debuff_controller = BuffController(
            self.debuff_overlay,
            catalog_by,
            {b.id: False for b in catalog},
            watcher=self._watcher,
        )
        self.debuff_controller.start(source, self._debuff_engine)

    def _on_debuff_tracking_changed(self) -> None:
        if self._debuff_engine is None:
            return
        self._debuff_engine.set_order(self._debuff_order(load_debuff_catalog()))

    def _on_debuff_catalog_changed(self) -> None:
        self._start_debuff_tracking()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 시그니처)
        # 종료 시 위치·고정 상태 저장(드래그 후 미저장 대비)
        self._save_overlay_state()
        self._save_debuff_overlay_state()
        self.party_tab.stop_polling()
        if self.buff_controller is not None:
            self.buff_controller.stop()
        if self.debuff_controller is not None:
            self.debuff_controller.stop()
        self.buff_overlay.close()
        self.debuff_overlay.close()
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
