"""메인 창 (기획서 5.1).

탭(버프 / 디버프 / 설정) + 오른쪽 위 실행 상태 표시.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
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


# 탭 바: 밑줄 스타일 + 균등 고정 너비. 선택 탭은 민트색·굵게 + 민트 밑줄로 또렷하게.
# (앱은 OS 테마를 따르므로, 무채색 글자 + 민트 강조로 라이트/다크 모두 자연스럽게.)
_TAB_QSS = (
    "QTabWidget::pane { border: none; border-top: 1px solid #2a2f3a; }"
    "QTabBar { qproperty-drawBase: 0; }"
    "QTabBar::tab { background: transparent; color: #8a8f98; padding: 9px 4px;"
    " min-width: 104px; border: none; border-bottom: 2px solid transparent;"
    " font-size: 13px; }"
    "QTabBar::tab:hover { color: #cfd3da; }"
    "QTabBar::tab:selected { color: #00C9A2; font-weight: 800;"
    " border-bottom: 2px solid #00D1A7; }"
)


class MainWindow(QMainWindow):
    # 백그라운드 스레드(업데이트 확인/다운로드)에서 UI 스레드로 안전하게 넘기는 신호.
    _update_found = Signal(dict)  # 새 버전 발견 → 배너 표시
    _update_progress = Signal(int)  # 다운로드 진행률(0~100)
    _update_result = Signal(bool, str)  # (성공?, 메시지) 교체 끝

    def __init__(self) -> None:
        super().__init__()
        from ..version import display_version

        self.setWindowTitle(f"{config.APP_NAME}  {display_version()}")
        self.setWindowIcon(app_icon())
        self.resize(780, 620)

        # 포그라운드 감지(맥=항상 활성). 저장된 게임 실행파일로 판정(없으면 제목 폴백).
        self._watcher = create_window_watcher(game_exe=config.load_game_exe())
        self._restoring = False  # 복원 중엔 상태 저장 안 함
        # 부팅(생성~복원 완료) 구간엔 저장을 전부 막는다. 이 사이에 위젯 구성·레이아웃에서
        # 파생된 신호(예: 에디터 textChanged)가 _save_memo를 불러, '기본 해제 상태'로
        # 저장된 잠금을 덮어쓰던 버그 방지. start() 끝에서 해제.
        self._booting = True
        # 설정 가져오기/초기화 후: 이 세션의 (가져오기 전) 낡은 오버레이·메모 상태가
        # 종료 시 방금 가져온 설정을 덮어쓰지 않도록 저장을 막는다. 다음 실행에서 반영.
        self._config_pending_restart = False
        self._force_quit = False  # 트레이 '종료'로 진짜 종료할 때만 True
        self._paused = False  # 오버레이 일시정지(사냥 안 할 때 잠깐 끄기) — 세션 한정
        self._tray = self._build_tray()

        self.buff_tab = BuffTab()
        self.debuff_tab = DebuffTab()
        self.party_tab = PartyTab()
        self.memo_tab = MemoTab()
        self.tuarim_tab = TuarimTab(self._watcher)
        self.custom_overlay_tab = CustomOverlayTab(self._watcher)
        self.settings_tab = SettingsTab(self._watcher)
        self.settings_tab.config_imported.connect(self._on_config_imported)
        self.settings_tab.voice_pack_changed.connect(self._on_voice_pack_changed)
        self.settings_tab.replay_tour.connect(self._run_tour)
        tabs = QTabWidget()
        self._tabs = tabs  # 온보딩 투어에서 탭 전환에 사용
        tabs.addTab(self.buff_tab, "버프 트래커")
        tabs.addTab(self.debuff_tab, "디버프 트래커")
        tabs.addTab(self.tuarim_tab, "투아림 트래커")
        tabs.addTab(self.custom_overlay_tab, "커스텀 오버레이")
        tabs.addTab(self.party_tab, "파티 모집")
        tabs.addTab(self.memo_tab, "메모")
        tabs.addTab(self.settings_tab, "설정")
        tabs.setStyleSheet(_TAB_QSS)

        # 중앙: 상단 업데이트 배너(기본 숨김) + 탭
        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self._update_banner = self._build_update_banner()
        self._pending_update: dict | None = None  # 확인된 새 버전 정보
        self._update_found.connect(self._on_update_found)
        cv.addWidget(self._update_banner)
        cv.addWidget(self._build_status_bar())  # 탭 위 최상단: 재생/일시정지 + 상태
        cv.addWidget(tabs)
        self.setCentralWidget(central)

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
        self.memo_overlay.set_markdown(str(memo.get("text", "")))
        self.memo_tab.lock_toggled.connect(self._on_memo_lock)
        self.memo_tab.region_changed.connect(self._apply_memo_region)
        self.memo_tab.font_changed.connect(self._on_memo_font)
        self.memo_tab.text_changed.connect(self._on_memo_text)
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

    # ---- 상단 업데이트 배너(새 버전 있을 때만) ----
    def _build_update_banner(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("updateBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 8, 6)
        h.setSpacing(8)
        self._update_label = QLabel("새 버전이 있습니다")
        self._update_label.setObjectName("updateMsg")
        h.addWidget(self._update_label)
        h.addStretch(1)
        btn = QPushButton("지금 업데이트")
        btn.setObjectName("updateBtn")
        btn.clicked.connect(self._on_update_clicked)
        h.addWidget(btn)
        close = QPushButton("✕")
        close.setObjectName("updateClose")
        close.setFixedWidth(26)
        close.setToolTip("이번만 숨기기")
        close.clicked.connect(self._update_banner_hide)
        h.addWidget(close)
        bar.setStyleSheet(
            "#updateBar { background:#10402f; border-bottom:1px solid #00B894; }"
            "#updateMsg { color:#d1fae5; font-size:12px; }"
            "#updateBtn { background:#00B894; color:#06281e; border:none;"
            " border-radius:4px; padding:4px 12px; font-weight:700; }"
            "#updateBtn:hover { background:#00D1A7; }"
            "#updateClose { background:transparent; color:#9ae6c7; border:none;"
            " font-size:13px; }"
            "#updateClose:hover { color:#ffffff; }"
        )
        bar.hide()  # 기본 숨김 — 새 버전이 확인될 때만 show_update_banner로 표시
        return bar

    def show_update_banner(self, latest: str) -> None:
        """새 버전이 있을 때 상단 배너 표시(자동업데이트 확인에서 호출 예정)."""
        from ..version import __version__

        cur = __version__ if __version__ != "0.0.0" else "개발"
        self._update_label.setText(
            f"🔔 새 버전 v{latest} 가 나왔어요   (현재 {cur})"
        )
        self._update_banner.show()

    def _update_banner_hide(self) -> None:
        self._update_banner.hide()

    # ---- 탭 위 최상단: 재생/일시정지 토글 + 상태 표시 ----
    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(10)
        h.addStretch(1)  # 오른쪽 정렬: 상태·버튼을 우상단에 모은다.
        self._status_label = QLabel("● 전체 오버레이 동작중")
        self._status_label.setObjectName("statusText")
        self._status_label.setToolTip(
            "오버레이 동작 여부입니다. '동작중'이어도 실제 표시는 "
            "마비노기가 맨 앞일 때만 — 자세한 추적 상태는 각 탭 안내를 보세요."
        )
        h.addWidget(self._status_label)
        # 재생/일시정지 토글: 감지 중이면 ⏸(누르면 멈춤), 멈추면 ▶(누르면 재개).
        self._pause_btn = QPushButton("⏸")
        self._pause_btn.setObjectName("playPause")
        self._pause_btn.setCheckable(True)
        self._pause_btn.setFixedSize(30, 26)
        self._pause_btn.setToolTip("사냥 안 할 때 오버레이를 잠깐 끄고/켭니다")
        self._pause_btn.toggled.connect(self._set_paused)
        h.addWidget(self._pause_btn)
        bar.setStyleSheet(
            "#statusBar { border-bottom:1px solid rgba(128,128,128,0.25); }"
            # 감지 중(기본): 무색 — 가는 테두리만.
            "#playPause { background:transparent; color:#8a8f98;"
            " border:1px solid rgba(128,128,128,0.45);"
            " border-radius:5px; font-size:12px; font-weight:800; }"
            "#playPause:hover { color:#c8ccd4; border-color:rgba(128,128,128,0.85); }"
            # 일시정지: ▶ 재개 버튼을 민트로 강조(눈에 띄게).
            "#playPause:checked { background:#00B894; color:#06281e; border:none; }"
            "#playPause:checked:hover { background:#00D1A7; }"
            "#statusText { font-size:12px; }"
        )
        return bar

    def _overlay_status(self) -> tuple[str, str]:
        """최상단 상태 한 줄 = 재생/일시정지 토글과 1:1(2상태).

        게임 포그라운드 여부는 성격이 다른 축이라 여기 섞지 않는다(각 탭의 진단
        상태 줄에 '게임 비활성' 안내가 따로 있음).
        """
        if self._paused:
            return ("⏸ 전체 오버레이 정지중", self._STATUS_WARN)
        return ("● 전체 오버레이 동작중", self._STATUS_OK)

    def _update_header_status(self) -> None:
        text, color = self._overlay_status()
        self._status_label.setText(text)  # 앞의 ●/⏸ 가 상태 표시('상태:' 접두어 없음)
        self._status_label.setStyleSheet(f"color:{color}; font-size:12px;")
        # 버튼 글리프: 재생 중이면 ⏸(멈춤 유도), 일시정지면 ▶(재개 유도).
        # 색은 QSS :checked 로 반전(감지 중=무색, 일시정지=강조).
        self._pause_btn.setText("▶" if self._paused else "⏸")

    # ---- 진단 상태 한 줄 ----
    _STATUS_OK = "#2ecc71"
    _STATUS_WARN = "#e67e22"
    _STATUS_MUTED = "#8a8f98"

    def _update_tracking_status(self) -> None:
        self.buff_tab.set_status(*self._buff_status())
        self.debuff_tab.set_status(*self._debuff_status())
        self._update_header_status()

    def _buff_status(self) -> tuple[str, str]:
        if not config.load_capture_region("buffTracker"):
            return ("⚠ 영역 미지정 — '버프 영역 지정'을 먼저 하세요", self._STATUS_WARN)
        if self.buff_controller is None:
            return ("ℹ 추적 대기 — 이 PC에선 라이브 캡처가 안 됩니다", self._STATUS_MUTED)
        if not self._watcher.is_game_active():
            return ("⏸ 게임 비활성 — 마비노기 창을 맨 앞으로 두면 추적합니다",
                    self._STATUS_MUTED)
        if self._engine is not None and not self._engine.anchor_seen:
            return ("⚠ 기준 버프 미검출 — 영역에 ⚓ 프리미엄 배틀 멤버십이 보이나요?",
                    self._STATUS_WARN)
        n = self.buff_controller.item_count
        if n:
            return (f"● 추적 중 — 버프 {n}개 표시", self._STATUS_OK)
        return ("● 추적 중 — 지금 표시할 버프 없음", self._STATUS_OK)

    def _debuff_status(self) -> tuple[str, str]:
        if not config.load_capture_region("debuffTracker"):
            return ("⚠ 영역 미지정 — '디버프 줄 영역 지정'을 먼저 하세요",
                    self._STATUS_WARN)
        if self.debuff_controller is None:
            return ("ℹ 추적 대기 — 이 PC에선 라이브 캡처가 안 됩니다", self._STATUS_MUTED)
        if not self._watcher.is_game_active():
            return ("⏸ 게임 비활성 — 마비노기 창을 맨 앞으로 두면 추적합니다",
                    self._STATUS_MUTED)
        n = self.debuff_controller.item_count
        if n:
            return (f"● 추적 중 — 안 걸린 디버프 {n}개 표시", self._STATUS_OK)
        return ("● 추적 중 — 표시할 디버프 없음", self._STATUS_OK)

    def _maybe_run_tour(self) -> None:
        """첫 실행 때 한 번, 사용 순서를 노란 점선 강조로 안내(코치마크)."""
        if not self.isVisible():
            return
        if config.load_general_flag("tourShown", False):
            return
        self._run_tour()

    def _run_tour(self) -> None:
        """온보딩 투어 실행(첫 실행 + '다시 보기' 공용)."""
        if not self.isVisible():
            self.show()  # 트레이 상태에서 '다시 보기' 누르면 창을 띄운다
        from .tour_overlay import TourOverlay, TourStep

        def _go_buff() -> None:
            self._tabs.setCurrentWidget(self.buff_tab)

        steps = [
            TourStep(
                target=self.buff_tab.region_btn,
                title="① 영역 지정",
                body="먼저 게임에서 버프가 모여 있는 곳을 드래그로 잡아요.\n"
                     "⚓ 기준 버프(프리미엄 배틀 멤버십)도 영역 안에 꼭 포함하세요.",
                before=_go_buff,
            ),
            TourStep(
                target=self.buff_tab.add_btn,
                title="② 버프 등록",
                body="＋로 추적할 버프를 추가하고, 그 아이콘을 상태창에서 바로 집어요.",
            ),
            TourStep(
                target=self.buff_tab.lock_btn,
                title="③ 위치 잠금",
                body="오버레이를 원하는 위치로 옮긴 뒤 '위치 잠금'을 누르면\n"
                     "위치가 고정되고 클릭도 통과해 게임에 방해되지 않아요.",
            ),
            TourStep(
                target=None,
                title="준비 끝! 🎉",
                body="디버프·투아림 탭도 같은 순서로 쓰면 됩니다.\n"
                     "자세한 설명은 각 탭의 ? 버튼, 세부 설정은 ⚙️ 설정 탭에서.",
            ),
        ]

        def _done() -> None:
            config.save_general_flag("tourShown", True)

        self._tour = TourOverlay(self, steps, on_done=_done)
        self._tour.start()

    def _maybe_prompt_game_window(self) -> None:
        """게임 창 인식이 안 돼 있으면 시작 시 한 번 선택 팝업을 띄운다(권장).

        창이 보일 때만(트레이 시작 아님) + 아직 미등록 + '다시 묻지 않기' 안 했을 때.
        """
        import sys

        if not self.isVisible():
            return  # 트레이로 시작 등 창이 없으면 팝업도 생략
        if sys.platform != "win32":
            return  # 맥/리눅스는 포그라운드 개념이 없어(항상 활성) 불필요
        if config.load_game_exe():
            return  # 이미 등록됨
        if config.load_general_flag("suppressGamePrompt", False):
            return  # 사용자가 '다시 묻지 않기' 선택

        from .game_window_dialog import GameWindowDialog

        dlg = GameWindowDialog(self._watcher, self)
        dlg.exec()
        self.settings_tab.refresh_game_label()  # 지정했으면 설정 라벨도 갱신

    def _maybe_check_update(self) -> None:
        """시작 시 백그라운드로 새 버전 확인(개발/실패는 조용히 무시)."""
        import threading

        from ..system import updater

        if not updater.can_update():
            return

        def work() -> None:
            info = updater.check_latest()
            if info:
                self._update_found.emit(info)  # UI 스레드로 전달 → 배너

        threading.Thread(target=work, daemon=True).start()

    def _on_update_found(self, info: dict) -> None:
        self._pending_update = info
        self.show_update_banner(str(info.get("version", "?")))

    def _on_update_clicked(self) -> None:
        """[지금 업데이트] → 다운로드(진행바) → B안 교체 → 재실행."""
        import threading

        from PySide6.QtWidgets import QMessageBox, QProgressDialog

        from ..system import updater

        info = self._pending_update
        if not info:
            return

        ver = info.get("version", "?")
        if QMessageBox.question(
            self, "업데이트",
            f"새 버전 v{ver} 을(를) 받아 교체하고 다시 시작합니다.\n진행할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return

        dlg = QProgressDialog("새 버전 받는 중…", None, 0, 100, self)
        dlg.setWindowTitle("업데이트")
        dlg.setAutoClose(False)
        dlg.setCancelButton(None)  # 교체 중 취소는 위험 → 막음
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        dlg.show()

        self._update_progress.connect(dlg.setValue)
        self._update_result.connect(
            lambda ok, msg: self._on_update_result(ok, msg, dlg)
        )

        def work() -> None:
            try:
                new_path = updater.download(
                    info, progress_cb=lambda p: self._update_progress.emit(p)
                )
                updater.apply_update(new_path)  # 교체 + 새 exe 실행
            except Exception as exc:  # noqa: BLE001 — 사용자에게 사유 표시
                self._update_result.emit(False, str(exc))
                return
            self._update_result.emit(True, "")

        threading.Thread(target=work, daemon=True).start()

    def _on_update_result(self, ok: bool, msg: str, dlg) -> None:
        from PySide6.QtWidgets import QMessageBox

        dlg.close()
        if ok:
            # 새 exe 가 이미 떠 있으니 현재(구버전) 프로세스는 완전히 종료.
            self._force_quit = True
            QApplication.quit()
            return
        QMessageBox.warning(
            self, "업데이트 실패",
            f"업데이트에 실패했습니다.\n{msg}\n\n나중에 다시 시도해 주세요.",
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
        if self._restoring or self._booting or self._config_pending_restart:
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
        self._maybe_check_update()
        self._maybe_prompt_game_window()
        self._maybe_run_tour()
        # 진단 상태 한 줄(추적 중/게임 비활성/영역 미지정 등) 주기 갱신.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(700)
        self._status_timer.timeout.connect(self._update_tracking_status)
        self._status_timer.start()
        self._update_tracking_status()
        self._booting = False  # 부팅 끝 — 이제부터 사용자 변경을 저장

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
            from .dpi import to_physical

            source = create_live_source(Region(*to_physical(region)))
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
        self.buff_controller.set_paused(self._paused)  # 재생성 시 일시정지 상태 유지
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
            from .dpi import to_physical

            source = create_live_source(Region(*to_physical(region)))
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
        self.debuff_controller.set_paused(self._paused)  # 재생성 시 일시정지 상태 유지
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
        """저장된 메모 영역에서 위치·너비를 적용. 높이는 내용에 맞춰 자동."""
        region = config.load_capture_region("memoTracker")
        if region:
            self.memo_overlay.setGeometry(
                region["x"], region["y"], region["w"], region["h"]
            )
            self.memo_overlay.autosize()  # 높이는 내용에 맞춰(드래그 높이 무시)

    def _on_memo_moved(self) -> None:
        """드래그로 옮긴 메모 위치를 저장(크기는 유지)."""
        if self._restoring or self._booting:
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

    def _on_memo_text(self, md: str) -> None:
        self.memo_overlay.set_markdown(md)  # 입력 즉시 오버레이에 렌더
        self._save_memo()

    def _save_memo(self) -> None:
        if self._restoring or self._booting or self._config_pending_restart:
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
        # 글자가 상태를 말하므로 체크표시 대신 라벨을 토글(⏸ 정지 ↔ ▶ 다시 시작).
        self._pause_act = QAction("⏸ 전체 오버레이 정지", self)
        self._pause_act.setToolTip(
            "버프·디버프·커스텀 오버레이를 한 번에 끕니다(메모·투아림은 따로)"
        )
        self._pause_act.triggered.connect(lambda: self._set_paused(not self._paused))
        quit_act = QAction("종료", self)
        quit_act.triggered.connect(self._quit_from_tray)
        menu.addAction(open_act)
        menu.addAction(self._pause_act)
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

    # ---- 오버레이 일시정지(사냥 안 할 때 잠깐 끄기) ----
    def _set_paused(self, paused: bool) -> None:
        """사냥용 오버레이(버프·디버프·커스텀)를 끄거나(True) 다시 켠다(False).

        추적 스레드는 그대로 두고 표시·알림만 토글하므로, 다시 켜면 재시작 없이
        즉시 현재 상태가 보인다. 세션 한정(저장 안 함) — 재실행하면 항상 켜진 상태.
        투아림(소리 알림)·메모(직접 띄운 참고 노트)는 성격이 달라 영향받지 않는다.
        """
        self._paused = paused
        for c in (self.buff_controller, self.debuff_controller):
            if c is not None:
                c.set_paused(paused)
        self.custom_overlay_tab.set_paused(paused)
        # 트레이 라벨 + 상단 버튼 동기화(어느 쪽에서 눌러도 둘 다 반영, 루프 방지).
        self._pause_act.setText(
            "▶ 전체 오버레이 시작" if paused else "⏸ 전체 오버레이 정지"
        )
        if self._pause_btn.isChecked() != paused:
            self._pause_btn.blockSignals(True)
            self._pause_btn.setChecked(paused)
            self._pause_btn.blockSignals(False)
        self._update_header_status()
        if self._tray is not None:
            self._tray.setToolTip(
                f"{config.APP_NAME} — 오버레이 정지됨"
                if paused else config.APP_NAME
            )
        from .toast import show_toast
        if paused:
            show_toast("전체 오버레이 정지", "버프·디버프·커스텀을 껐어요. 다시 시작하려면 ▶", 2500)
        else:
            show_toast("전체 오버레이 시작", "버프·디버프·커스텀 오버레이가 다시 동작합니다", 2000)

    def _on_voice_pack_changed(self) -> None:
        """설정에서 알림 목소리 팩이 바뀌면 실행 중 재생기들을 새 팩으로 갱신(바로 적용)."""
        from .notifier import default_sound_map

        if self._notifier is not None:
            self._notifier.set_sounds(default_sound_map())  # 버프
        self.tuarim_tab.refresh_sound()
        self.party_tab.refresh_sound()

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
