"""메인 창 (기획서 5.1).

탭(버프 / 디버프 / 설정) + 오른쪽 위 실행 상태 표시.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QMenu,
    QSystemTrayIcon,
    QTabWidget,
)

from .. import config, paths
from ..capture import Region, create_live_source
from ..catalog import available_catalog, available_debuff_catalog, build_templates
from ..system.window_watcher import create_window_watcher
from ..tracker.debuff_engine import DebuffEngine
from ..tracker.engine import BuffEngine
from .buff_controller import BuffController
from .buff_tab import ANCHOR_ID, BuffTab
from .custom_overlay_tab import CustomOverlayTab
from .debuff_tab import DebuffTab
from .memo_overlay import MemoOverlay
from .memo_tab import MemoTab
from .notifier import SoundNotifier, default_sound_map
from .overlay import BuffOverlay
from .party_tab import PartyTab
from .settings_tab import SettingsTab
from .tuarim_tab import TuarimTab

# 번들 경로 사용(exe=_MEIPASS/assets). __file__ 기준은 frozen에서 어긋난다.
LOGO_PATH = paths.resource_dir() / "logo.png"
_log = logging.getLogger("mabinogi_addon.close")


def app_icon() -> QIcon:
    """앱 로고 아이콘(창·작업표시줄)."""
    return QIcon(str(LOGO_PATH))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        from ..version import display_version

        self.setWindowTitle(f"{config.APP_NAME}  {display_version()}")
        self.setWindowIcon(app_icon())
        self.resize(780, 620)

        # 포그라운드 감지(맥=항상 활성). 저장된 게임 실행파일로 판정(없으면 제목 폴백).
        self._watcher = create_window_watcher(game_exe=config.load_game_exe())
        self._restoring = False  # 복원 중엔 상태 저장 안 함
        # 설정 가져오기/초기화 후: 이 세션의 (가져오기 전) 낡은 오버레이·메모 상태가
        # 종료 시 방금 가져온 설정을 덮어쓰지 않도록 저장을 막는다. 다음 실행에서 반영.
        self._config_pending_restart = False
        self._force_quit = False  # 트레이 '종료'로 진짜 종료할 때만 True
        self._tray = self._build_tray()

        self.buff_tab = BuffTab()
        self.debuff_tab = DebuffTab()
        self.party_tab = PartyTab()
        self.memo_tab = MemoTab()
        self.tuarim_tab = TuarimTab(self._watcher)
        self.custom_overlay_tab = CustomOverlayTab(self._watcher)
        self.settings_tab = SettingsTab(self._watcher)
        self.settings_tab.config_imported.connect(self._on_config_imported)
        tabs = QTabWidget()
        tabs.addTab(self.buff_tab, "버프")
        tabs.addTab(self.debuff_tab, "디버프")
        tabs.addTab(self.tuarim_tab, "투아림")
        tabs.addTab(self.custom_overlay_tab, "커스텀 오버레이")
        tabs.addTab(self.party_tab, "파티")
        tabs.addTab(self.memo_tab, "메모")
        tabs.addTab(self.settings_tab, "설정")
        self.setCentralWidget(tabs)

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

        # 메모 오버레이: 위치·크기는 영역 지정, 고정=클릭통과. 게임 활성 시만 표시.
        memo = config.load_memo()
        self.memo_overlay = MemoOverlay(font_size=int(memo.get("fontSize", 16)))
        self.memo_overlay.set_text(str(memo.get("text", "")))
        self.memo_tab.lock_toggled.connect(self._on_memo_lock)
        self.memo_tab.region_changed.connect(self._apply_memo_region)
        self.memo_tab.font_changed.connect(self._on_memo_font)
        self.memo_overlay.moved.connect(self._on_memo_moved)
        self._memo_timer = QTimer(self)
        self._memo_timer.setInterval(300)
        self._memo_timer.timeout.connect(self._tick_memo_visibility)

        # 오버레이 배율(각 탭): 저장값 적용 + 변경 시 즉시 반영.
        buff_pct, debuff_pct = config.load_overlay_scales()
        self.buff_overlay.set_scale(buff_pct / 100)
        self.debuff_overlay.set_scale(debuff_pct / 100)
        self.buff_tab.scale_changed.connect(
            lambda pct: self.buff_overlay.set_scale(pct / 100)
        )
        self.debuff_tab.scale_changed.connect(
            lambda pct: self.debuff_overlay.set_scale(pct / 100)
        )

    # ---- 오버레이 고정/저장/복원(버프·디버프 공용 로직) ----
    def _apply_lock(self, overlay: BuffOverlay, locked: bool, section: str) -> None:
        overlay.set_locked(locked)
        if locked and not overlay._items:
            overlay.hide()  # 고정+비어있음 → 숨김
        else:
            overlay.show()
        self._save_overlay(overlay, section)

    def _save_overlay(self, overlay: BuffOverlay, section: str) -> None:
        if self._restoring or self._config_pending_restart:
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
        from ..system import autostart

        autostart.refresh()  # 자동실행 켜져 있으면 현재 exe 경로로 갱신(이동 시 self-heal)
        self.party_tab.start_polling()
        self._restore_overlay(self.buff_overlay, self.buff_tab, "buffTracker")
        self._restore_overlay(self.debuff_overlay, self.debuff_tab, "debuffTracker")
        self._restore_memo()
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

        catalog = available_catalog()
        catalog_by = {b.id: b for b in catalog}
        order, show_duration, alert_before, blink, alert_before2 = (
            self._compute_tracking(catalog)
        )
        self._sound_ids = self._sound_enabled_ids()
        # 앵커 게이팅: 앵커(프리미엄 전투)가 보이는 프레임만 '정상'으로 보고,
        # 안 보이면 상태를 동결(내부 시계로 버팀)하다 다시 보이면 동기화한다.
        # 단 앵커가 영역에 애초에 없으면(한 번도 안 보이면) 게이팅하지 않아
        # 기존 동작과 동일 — 엔진 쪽 anchor_seen 안전장치가 처리한다.
        self._engine = BuffEngine(
            build_templates(catalog),
            order,
            anchor_id=ANCHOR_ID,
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
            self._compute_tracking(available_catalog())
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

        catalog = available_debuff_catalog()
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
        # 디버프는 느리게 변하고 템플릿 수가 많아 500ms 주기(기획 0.3~0.5초).
        self.debuff_controller.start(source, self._debuff_engine, interval_ms=500)

    def _on_debuff_tracking_changed(self) -> None:
        if self._debuff_engine is None:
            return
        self._debuff_engine.set_order(self._debuff_order(available_debuff_catalog()))

    def _on_debuff_catalog_changed(self) -> None:
        self._start_debuff_tracking()

    # ---- 메모 오버레이 ----
    def _apply_memo_region(self) -> None:
        """저장된 메모 영역(위치·크기)을 오버레이에 적용."""
        region = config.load_capture_region("memoTracker")
        if region:
            self.memo_overlay.setGeometry(
                region["x"], region["y"], region["w"], region["h"]
            )

    def _on_memo_moved(self) -> None:
        """드래그로 옮긴 메모 위치를 저장(크기는 유지)."""
        if self._restoring:
            return
        pos = self.memo_overlay.pos()
        config.save_capture_region(
            pos.x(), pos.y(),
            self.memo_overlay.width(), self.memo_overlay.height(),
            "memoTracker",
        )

    def _on_memo_lock(self, locked: bool) -> None:
        self.memo_overlay.set_locked(locked)
        self._save_memo()

    def _on_memo_font(self, px: int) -> None:
        self.memo_overlay.set_font_size(px)
        self._save_memo()

    def _save_memo(self) -> None:
        if self._restoring or self._config_pending_restart:
            return
        config.save_memo(
            self.memo_overlay.text(),
            self.memo_overlay.locked,
            self.memo_tab.font_spin.value(),
        )

    def _tick_memo_visibility(self) -> None:
        """메모 표시 규칙: 게임 포그라운드면 표시. 해제(편집) 상태면 우리 앱에서도
        표시(위치/입력). 고정 상태인데 게임이 포그라운드 아니면 숨김."""
        if config.load_capture_region("memoTracker") is None:
            self.memo_overlay.hide()
            return
        if self._watcher.is_game_active() or self._watcher.is_self_active() and not self.memo_overlay.locked:
            self.memo_overlay.show()
        else:
            self.memo_overlay.hide()

    def _restore_memo(self) -> None:
        self._restoring = True
        try:
            self._apply_memo_region()
            locked = bool(config.load_memo().get("locked", False))
            self.memo_tab.set_lock_state(locked)  # 버튼 동기화 + set_locked 적용
        finally:
            self._restoring = False
        self._memo_timer.start()

    # ---- 시스템 트레이 ----
    def _build_tray(self) -> QSystemTrayIcon | None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        tray = QSystemTrayIcon(app_icon(), self)
        tray.setToolTip(config.APP_NAME)
        menu = QMenu()
        open_act = QAction("열기", self)
        open_act.triggered.connect(self._show_from_tray)
        quit_act = QAction("종료", self)
        quit_act.triggered.connect(self._quit_from_tray)
        menu.addAction(open_act)
        menu.addSeparator()
        menu.addAction(quit_act)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason) -> None:
        # 트레이 아이콘 클릭·더블클릭 → 창 복귀
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()

    def _on_config_imported(self) -> None:
        """설정 가져오기/초기화 직후: 종료 시 낡은 상태로 덮어쓰지 않도록 저장을 막는다.

        자동 재시작(QProcess로 자기 자신 재실행)은 PyInstaller onefile에서 기존
        인스턴스의 _MEI 임시폴더 추출/정리와 충돌해 새 프로세스의 네이티브 모듈
        (cv2 등) 로드가 깨졌다. 그래서 재실행은 하지 않고, 이 세션은 상태 저장만
        멈춘 뒤 사용자가 직접 종료→재실행하면 바뀐 설정·자산이 깨끗이 반영된다.
        """
        self._config_pending_restart = True

    def _minimize_to_tray_enabled(self) -> bool:
        return self._tray is not None and config.load_general_flag(
            "minimizeToTray", True
        )

    def closeEvent(self, event) -> None:
        import time

        # 트레이 최소화: X를 눌러도 종료하지 않고 트레이로 숨긴다(백그라운드 계속 동작).
        # 단, 설정 가져오기/초기화 후엔 낡은 인스턴스가 남지 않게 X로도 완전 종료한다
        # (재실행해야 반영되므로 트레이에 숨겨두면 혼란 — 재실행 시 중복 실행됨).
        if (
            self._minimize_to_tray_enabled()
            and not self._force_quit
            and not self._config_pending_restart
        ):
            event.ignore()
            self.hide()
            if self._tray is not None:
                self._tray.showMessage(
                    "마비노기 버프 트래커",
                    "트레이로 최소화됨. 트레이 아이콘으로 열거나 종료하세요.",
                    app_icon(),
                    2000,
                )
            return

        def _step(name, fn):
            # 한 단계가 실패해도 나머지(특히 '오버레이 닫기')는 반드시 실행되게 감싼다.
            t = time.perf_counter()
            try:
                fn()
            except Exception:  # noqa: BLE001 — 종료 중 오류로 오버레이가 남지 않게
                _log.exception("종료 단계 '%s' 실패", name)
            _log.info("종료 단계 '%s' %.0fms", name, (time.perf_counter() - t) * 1000)

        total = time.perf_counter()
        _step("상태 저장", lambda: (
            self._save_overlay_state(),
            self._save_debuff_overlay_state(),
            self._save_memo(),
            self._memo_timer.stop(),
        ))
        _step("파티 폴링 정지", lambda: self.party_tab.stop_polling(wait_ms=600))
        # 두 캡처 워커에 먼저 정지 신호를 보내고, '공유 마감시한'으로 대기를 겹친다.
        # (각각 600ms씩 순차로 기다리면 합산 ~1.2초. 둘 다 dxcam grab에 물려도 abandon은
        #  안전하므로, 전체 0.7초 안에서 나눠 기다려 총 종료를 1초 밑으로.)
        for c in (self.buff_controller, self.debuff_controller):
            if c is not None:
                c.request_stop()
        deadline = time.perf_counter() + 0.7
        for name, c in (
            ("버프 추적 정지", self.buff_controller),
            ("디버프 추적 정지", self.debuff_controller),
        ):
            if c is not None:
                remaining = max(0, deadline - time.perf_counter())
                _step(
                    name,
                    lambda c=c, ms=int(remaining * 1000): c.stop(timeout_ms=ms),
                )
        _step("오버레이 닫기", lambda: (
            self.buff_overlay.close(),
            self.debuff_overlay.close(),
            self.memo_overlay.close(),
            self.custom_overlay_tab.shutdown(),
            self.tuarim_tab.shutdown(),
        ))
        if self._tray is not None:
            self._tray.hide()
        _log.info("종료 총 %.0fms", (time.perf_counter() - total) * 1000)
        super().closeEvent(event)
        QApplication.quit()  # 트레이/오버레이가 남아도 프로세스 확실히 종료
