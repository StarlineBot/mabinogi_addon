"""메인 창 (기획서 5.1).

탭(버프 / 디버프 / 설정) + 오른쪽 위 실행 상태 표시.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QSystemTrayIcon,
    QTabBar,
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
from .bead_split_tab import BeadSplitTab
from .boss_tab import BossTab
from .buff_controller import BuffController
from .buff_tab import ANCHOR_ID, BuffTab
from .custom_overlay_tab import CustomOverlayTab
from .debuff_tab import DebuffTab
from .distribution_tab import DistributionTab
from .exchange_tab import ExchangeTab
from .memo_overlay import MemoOverlay
from .memo_tab import MemoTab
from .notifier import SoundNotifier, default_sound_map, second_sound_map
from .overlay import BuffOverlay
from .party_tab import PartyTab
from .settings_tab import SettingsTab
from .skillbar_tab import SkillbarTab
from .stat_bars_tab import StatBarsTab
from .dorcha_tab import DorchaTab
from .tuarim_tab import TuarimTab

# 번들 경로 사용(exe=_MEIPASS/assets). __file__ 기준은 frozen에서 어긋난다.
LOGO_PATH = paths.resource_dir() / "logo.png"
_log = logging.getLogger("mabinogi_addon.close")
_cap_log = logging.getLogger("mabinogi_addon.capture")  # 라이브 캡처 시작 진단
_up_log = logging.getLogger("mabinogi_addon.updater")  # 업데이트 확인 진단(계기·스로틀·결과)
_notes_log = logging.getLogger("mabinogi_addon.notes")  # 업데이트 노트 표시 진단


def app_icon() -> QIcon:
    """앱 로고 아이콘(창·작업표시줄)."""
    return QIcon(str(LOGO_PATH))


class _VScroll(QScrollArea):
    """세로 스크롤 영역: 가로는 뷰포트 폭에 맞추되, 세로는 내용의 '자연 높이'를 지킨다.

    그냥 setWidgetResizable(True)만 쓰면, 내용이 뷰포트보다 크면 눌리고(압축) 작으면
    늘어나(확대) 버튼 등이 찌그러진다. 내용 위젯의 최소 높이를 '현재 폭에서 실제로
    필요한 높이'로 고정해, 넘칠 때 '압축' 대신 '스크롤'이 생기게 한다.

    높이는 폭과 무관한 sizeHint().height() 대신 heightForWidth(현재 폭)로 구한다.
    sizeHint는 워드랩 라벨을 좁은 기본 폭 기준으로 과대 계산해, 실제 내용이 끝난
    뒤에도 빈 공간만큼 스크롤이 더 내려가는 문제가 있었다(예: 설정 탭 ~150px).
    """

    def _fit_content(self):
        inner = self.widget()
        if inner is not None:
            w = self.viewport().width()
            if hasattr(inner, "fit_width"):
                inner.fit_width(w)
            lay = inner.layout()
            h = lay.heightForWidth(w) if lay is not None and lay.hasHeightForWidth() else -1
            if h <= 0:
                h = inner.sizeHint().height()
            inner.setMinimumHeight(h)

    def resizeEvent(self, event) -> None:
        self._fit_content()
        super().resizeEvent(event)

    def eventFilter(self, watched, event):
        if (watched is self.widget() and event.type() == QEvent.Type.LayoutRequest
                and hasattr(watched, "fit_width")):
            self._fit_content()
        return super().eventFilter(watched, event)


def _scrolled(widget: QWidget) -> QScrollArea:
    """위젯을 세로 스크롤 영역으로 감싼다(창 높이 고정 시 내용 잘림·찌그러짐 방지)."""
    area = _VScroll()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.Shape.NoFrame)
    # 줄바꿈 후 모든 탭이 창 폭에 들어오므로 가로 스크롤은 끈다(미세 잔차로 생기는
    # 얇은 가로 스크롤바 방지 — 세로만 스크롤).
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    area.setWidget(widget)
    return area


class _OverlayToggle(QPushButton):
    """오버레이 재생/일시정지 토글 버튼(오디오 플레이어식).

    폰트 이모지(⏸/▶)는 글리프마다 '자체 둥근 네모 테두리'가 딸려 와, 버튼 테두리와
    겹쳐 '네모 안에 버튼' 처럼 보인다. 그래서 글자 대신 아이콘(두 막대/삼각형)을 직접
    그린다. 색은 앱 전체 모노톤에 맞춰 무채색만 쓰고, 상태는 색이 아니라 모양·채움·
    밝기로 구분한다. checked = 일시정지 상태(→ ▶ 재개 아이콘).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(23, 23)  # 옆 상태 글자 대비 과하지 않게 작게
        self.setFlat(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)  # hover 때 다시 그리기
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggled.connect(self.update)

    def paintEvent(self, _event) -> None:
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QPainter, QPolygonF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paused = self.isChecked()
        pressed = self.isDown()
        hover = self.underMouse()
        circle = QRectF(1, 1, self.width() - 2, self.height() - 2)

        if paused:
            # 일시정지 상태: 밝은 무채색 원으로 채워 '멈춤'을 또렷이(색 대신 명도로).
            lum = 210 if pressed else (225 if hover else 200)
            p.setBrush(QColor(lum, lum, lum))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(circle)
            ink = QColor(40, 44, 52)  # 밝은 원 위 어두운 아이콘
        else:
            # 동작 중: 은은한 원(hover/press 때만 살짝 채움) + 가는 무채색 테두리.
            fill = 46 if pressed else (34 if hover else 0)
            p.setBrush(QColor(255, 255, 255, fill))
            p.setPen(QColor(150, 150, 150, 210 if hover else 150))
            p.drawEllipse(circle.adjusted(0.5, 0.5, -0.5, -0.5))
            ink = QColor(220, 224, 228) if hover else QColor(150, 155, 164)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        s = min(self.width(), self.height())  # 아이콘을 버튼 크기에 비례시켜 축소 대응
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        if paused:  # ▶ 재생(재개) 삼각형. 광학 중심 보정으로 살짝 오른쪽.
            half_h, w = s * 0.24, s * 0.40
            left = cx - w / 2.0 + s * 0.04
            tri = QPolygonF(
                [
                    QPointF(left, cy - half_h),
                    QPointF(left, cy + half_h),
                    QPointF(left + w, cy),
                ]
            )
            p.drawPolygon(tri)
        else:  # ❚❚ 두 막대.
            bw, bh, gap = s * 0.12, s * 0.46, s * 0.14
            r = bw * 0.45
            p.drawRoundedRect(QRectF(cx - gap / 2 - bw, cy - bh / 2, bw, bh), r, r)
            p.drawRoundedRect(QRectF(cx + gap / 2, cy - bh / 2, bw, bh), r, r)
        p.end()


# 탭 바: 밑줄 스타일 + 균등 고정 너비. 선택 탭은 민트색·굵게 + 민트 밑줄로 또렷하게.
# 색은 테마별로 분기한다(단일 색으론 라이트/다크를 동시에 못 맞춤):
# - 다크: 은은한 밝은 회색(원래 룩) / - 라이트: 어두운 회색.
# 미선택은 중간 회색(#8a8f98) 고정 — 양쪽 다 보임. 호버/선택만 테마로 또렷하게.


def _tab_qss(dark: bool) -> str:
    """상위 탭 스타일. 선택=민트(양쪽 공통), 호버는 테마별."""
    pane = "#2a2f3a" if dark else "#d5d7dd"
    hover = "#cfd3da" if dark else "#1f2124"
    return (
        f"QTabWidget::pane {{ border: none; border-top: 1px solid {pane}; }}"
        "QTabBar { qproperty-drawBase: 0; }"
        "QTabBar::tab { background: transparent; color: #8a8f98; padding: 9px 4px;"
        " min-width: 104px; border: none; border-bottom: 2px solid transparent;"
        " font-size: 13px; }"
        f"QTabBar::tab:hover {{ color: {hover}; }}"
        "QTabBar::tab:selected { color: #00C9A2; font-weight: 800;"
        " border-bottom: 2px solid #00D1A7; }"
    )


class _CombatTabBar(QTabBar):
    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().mid().color(), 1))
        for index in (4, 6):
            rect = self.tabRect(index)
            painter.drawLine(rect.left() + 1, rect.top() + 9, rect.left() + 1, rect.bottom() - 9)
        painter.end()


def _subtab_qss(dark: bool) -> str:
    """하위(트래커 내부) 탭. 선택 표시는 무채색 밑줄 → '한 단계 아래'. 테마별 색."""
    pane = "#2a2f3a" if dark else "#d5d7dd"
    hover = "#cfd3da" if dark else "#1f2124"
    sel = "#cfd3da" if dark else "#1f2124"  # 다크=은은한 회색(흰색 아님), 라이트=어두움
    underline = "#5a6270" if dark else "#b2b5bc"
    return (
        f"QTabWidget::pane {{ border: none; border-top: 1px solid {pane}; }}"
        "QTabBar { qproperty-drawBase: 0; }"
        "QTabBar::tab { background: transparent; color: #7d828b; padding: 6px 14px;"
        " min-width: 0px; border: none; border-bottom: 2px solid transparent;"
        " font-size: 12px; }"
        f"QTabBar::tab:hover {{ color: {hover}; }}"
        f"QTabBar::tab:selected {{ color: {sel}; font-weight: 700;"
        f" border-bottom: 2px solid {underline}; }}"
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
        # 고정 크기(크기 변경 비활성). 내용이 넘치면 각 탭이 스크롤로 처리한다.
        # (resize 가능 상태로 두면 가장자리에 리사이즈 커서만 뜨고 실제론 안 줄던 혼란.)
        # 고정 크기(크기 변경 비활성). 안내문 줄바꿈 후 탭 최대 폭이 ≈700이라 790이면
        # 가로 스크롤 없이 모두 들어온다. 높이 800이면 뷰포트가 ≈724px라 버프(≈493)·
        # 파티(≈612)·커스텀(≈718)이 스크롤 없이 들어오고, 길이가 압도적인 설정 탭
        # (≈1265)만 세로 스크롤로 본다(_VScroll이 눌림 방지).
        self.setFixedSize(790, 800)
        from ..setup_state import initialize_new_user
        initialize_new_user()
        self._restore_window_pos()  # 저장된 창 위치 복원(없으면 화면 중앙)

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
        self._closing = False
        self._started = False
        self._status_timer = None
        self._force_quit = False  # 트레이 '종료'로 진짜 종료할 때만 True
        self._paused = False  # 오버레이 일시정지(사냥 안 할 때 잠깐 끄기) — 세션 한정
        self._tray = self._build_tray()

        # 최초 1회: 기본 음성알림 있는 버프에 '사라짐 경고' 기본 켜짐(기존 사용자 이관).
        config.seed_warn_gone_defaults(set(default_sound_map()))

        self.buff_tab = BuffTab()
        self.debuff_tab = DebuffTab()
        self.party_tab = PartyTab()
        self.party_tab.activate_requested.connect(self._focus_party_tab)
        self.memo_tab = MemoTab()
        self.tuarim_tab = TuarimTab(self._watcher)
        self.boss_tab = BossTab(self._watcher)  # 베타(디스코드 로그인 게이팅)
        # 보스 HP바 영역은 디버프 3차와 공유 — 보스 탭에서 바꾸면 디버프 추적도 재시작.
        self.boss_tab.bar_region_changed.connect(self._on_boss_bar_region_changed)
        # 보스 탭 자동 찾기가 디버프 영역도 지정 → 디버프 추적 재시작 + 디버프 탭 표시 갱신.
        self.boss_tab.debuff_region_changed.connect(self._on_boss_debuff_region_changed)
        self.custom_overlay_tab = CustomOverlayTab(self._watcher)
        self.stat_bars_tab = StatBarsTab(self._watcher)
        self.dorcha_tab = DorchaTab(self._watcher)
        # 체력바 저체력 알림은 '보스전 중'일 때만 울린다 — 보스 탭의 보스바 존재 신호를 연결.
        self.stat_bars_tab.set_boss_presence_source(self.boss_tab.is_boss_present)
        # 반대로, 저체력 경고가 하나라도 켜져 있을 때만 보스 탭이 존재 판정을 돌리게 연결.
        self.boss_tab.set_presence_consumer(self.stat_bars_tab.has_active_alert)
        self.skillbar_tab = SkillbarTab(self._watcher)
        self.settings_tab = SettingsTab(self._watcher)
        self.settings_tab.config_imported.connect(self._on_config_imported)
        self.settings_tab.voice_pack_changed.connect(self._on_voice_pack_changed)
        self.settings_tab.replay_tour.connect(self._replay_tour)
        self.settings_tab.theme_changed.connect(self._apply_tab_styles)
        # Keep the full editor width: one combat tab row, without a sidebar.
        self._tracker_tabs = QTabWidget()
        self._tracker_tabs.setTabBar(_CombatTabBar())
        self._combat_pages = {}
        for key, title, panel in (
            ("buff", "버프", self.buff_tab), ("debuff", "디버프", self.debuff_tab),
            ("tuarim", "투아림", self.tuarim_tab), ("boss", "보스 패턴 알림", self.boss_tab),
            ("stat_bars", "체력바", self.stat_bars_tab), ("dorcha", "도르카", self.dorcha_tab),
            ("custom", "커스텀 오버레이", self.custom_overlay_tab),
            ("skillbar", "단축바", self.skillbar_tab), ("memo", "메모", self.memo_tab),
        ):
            scroll = _scrolled(panel)
            self._combat_pages[key] = scroll
            self._tracker_tabs.addTab(scroll, title)

        self.distribution_tab = DistributionTab()
        self.exchange_tab = ExchangeTab()
        self.bead_split_tab = BeadSplitTab()
        self._convenience_tabs = QTabWidget()
        self._convenience_tabs.addTab(_scrolled(self.distribution_tab), "분배 계산기")
        self._convenience_tabs.addTab(_scrolled(self.bead_split_tab), "구슬 분배 계산기")
        self._convenience_tabs.addTab(_scrolled(self.exchange_tab), "환전비율 계산기")

        tabs = QTabWidget()
        self._tabs = tabs  # 온보딩 투어에서 탭 전환에 사용
        tabs.addTab(self._tracker_tabs, "전투 보조")
        self._party_scroll = _scrolled(self.party_tab)  # 토스트 클릭 시 이 탭으로 전환
        tabs.addTab(self._party_scroll, "파티 모집")
        tabs.addTab(self._convenience_tabs, "편의기능")
        tabs.addTab(_scrolled(self.settings_tab), "설정")
        self._apply_tab_styles()  # 테마에 맞는 탭 색 적용(테마 변경 시 재적용)

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
        from .setup_page import SetupPage
        from .setup_flow import SetupFlow
        from .setup_guide import SetupGuide
        self.setup_page = SetupPage()
        self.setup_guide = SetupGuide()
        self._pages = QStackedWidget()
        self._pages.addWidget(tabs)
        self._pages.addWidget(self.setup_page)
        self._pages.addWidget(self.setup_guide)
        cv.addWidget(self._pages)
        self._guide_return_btn = QPushButton("첫 사용 안내로 돌아가기")
        self._guide_return_btn.clicked.connect(self._resume_guide)
        self._guide_return_btn.hide()
        cv.addWidget(self._guide_return_btn)
        self._pages.currentChanged.connect(self._refresh_guide_return)
        self._setup_flow = SetupFlow(self.setup_page, self._apply_setup_region)
        self.setup_page.leave_requested.connect(self._leave_setup)
        self.setup_page.open_feature.connect(self._open_setup_feature)
        self.setup_page.register_game.connect(self._register_setup_game)
        self.setup_page.login_requested.connect(self._open_setup_login)
        self.setup_page.feature_changed.connect(self._set_feature_enabled)
        self.settings_tab.reopen_setup.connect(self._open_setup)
        self.settings_tab.reopen_guide.connect(self._open_guide)
        self.setup_guide.feature_changed.connect(self._set_feature_enabled)
        self.setup_guide.register_game.connect(self._register_setup_game)
        self.setup_guide.run_requested.connect(self._run_guide_setup)
        self.setup_guide.cancel_requested.connect(self._setup_flow.cancel)
        self.setup_guide.finished.connect(self._finish_guide)
        self.settings_tab.login_changed.connect(self.setup_page.refresh)
        self.settings_tab.login_changed.connect(self._guide_login_changed)
        self.settings_tab.game_registered.connect(self.setup_page.refresh)
        self.settings_tab.game_registration_finished.connect(self._setup_game_finished)
        self.setCentralWidget(central)

        # 버프 오버레이
        self.buff_overlay = BuffOverlay()
        self.buff_controller: BuffController | None = None
        self._engine: BuffEngine | None = None
        self._notifier = SoundNotifier(default_sound_map())  # 1차
        self._notifier2 = SoundNotifier(second_sound_map())  # 2차(막차 경고)
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
        self.debuff_tab.gate_mode_changed.connect(self._on_debuff_gate_mode)
        # 디버프 탭에서 보스 HP바 영역을 바꾸면 보스패턴알림(메모리)도 즉시 반영(양방향 공유).
        self.debuff_tab.bar_region_changed.connect(self.boss_tab.reload_region)
        self.debuff_overlay.moved.connect(self._save_debuff_overlay_state)

        # 메모 오버레이: 위치·크기는 영역 지정, 고정=클릭통과. 게임 활성 시만 표시.
        memo = config.load_memo()
        self.memo_overlay = MemoOverlay(font_size=int(memo.get("fontSize", 16)))
        self.memo_overlay.set_markdown(str(memo.get("text", "")))
        self._memo_enabled = bool(memo.get("enabled", True))
        self.memo_tab.lock_toggled.connect(self._on_memo_lock)
        self.memo_tab.region_changed.connect(self._apply_memo_region)
        self.memo_tab.font_changed.connect(self._on_memo_font)
        self.memo_tab.text_changed.connect(self._on_memo_text)
        self.memo_tab.enabled_toggled.connect(self._on_memo_enabled)
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

        self._feature_checks = {
            "buff": self.buff_tab.enable, "debuff": self.debuff_tab.enable,
            "tuarim": self.tuarim_tab.enable, "boss": self.boss_tab.enable,
            "stat_bars": self.stat_bars_tab.enable, "skillbar": self.skillbar_tab.enable,
            "custom": self.custom_overlay_tab.enable, "memo": self.memo_tab.enable_chk,
        }
        for key, check in self._feature_checks.items():
            check.toggled.connect(lambda _value, key=key: self._feature_changed(key))
        from ..setup_state import needs_start_screen
        if needs_start_screen() and config.load_discord_user() is not None:
            # 실제 첫 표시에 노트를 먼저 처리하고 안내를 활성화한다.
            self._pages.setCurrentWidget(self.setup_guide)
        from .creator_dialogue import CreatorDialogue
        self.creator_dialogue = CreatorDialogue(self)

    def _open_setup(self):
        self._open_guide()

    def nativeEvent(self, event_type, message):
        import sys
        dialogue = getattr(self, "creator_dialogue", None)
        if sys.platform == "win32" and dialogue is not None:
            import ctypes
            from ctypes import wintypes
            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            dialogue.system_message(msg.message, msg.wParam)
        return super().nativeEvent(event_type, message)

    def _leave_setup(self):
        if self._setup_busy():
            return
        self._tabs.setCurrentWidget(self._tracker_tabs)
        self._tracker_tabs.setCurrentIndex(0)
        self._pages.setCurrentWidget(self._tabs)

    def _open_setup_feature(self, key):
        page = self._combat_pages.get(key)
        if (page is None or self._setup_busy() or self._closing
                or self._config_pending_restart or self._setup_flow.closed):
            return False
        self._pages.setCurrentWidget(self._tabs)
        self._tabs.setCurrentWidget(self._tracker_tabs)
        self._tracker_tabs.setCurrentWidget(page)
        return True

    def _register_setup_game(self):
        self.settings_tab._start_detect()
        self.setup_page.game_btn.setEnabled(False)
        self.setup_guide.game_btn.setEnabled(False)
        self.setup_page.progress.setText("3초 안에 게임창을 선택하세요. 등록 결과는 이 화면에 반영됩니다.")
        self.setup_guide.progress.setText(self.setup_page.progress.text())
        self.setup_guide.refresh()

    def _open_setup_login(self):
        if self._setup_busy() or self._config_pending_restart or self._setup_flow.closed:
            return
        self._pages.setCurrentWidget(self._tabs)
        scroll = self._tabs.widget(self._tabs.count() - 1)
        self._tabs.setCurrentWidget(scroll)
        scroll.ensureWidgetVisible(self.settings_tab._login_btn)
        self.settings_tab._login_btn.setFocus()

    def _setup_game_finished(self, success):
        self.setup_page.game_btn.setEnabled(not self.setup_page.busy)
        self.setup_page.refresh()
        self.setup_page.progress.setText("게임창을 등록했습니다. 사용할 기능을 선택하세요." if success else
                                         "게임창을 등록하지 못했습니다. 게임창을 선택한 뒤 다시 시도하세요.")
        self.setup_guide.refresh()
        self.setup_guide.progress.setText(self.setup_page.progress.text())
        self.setup_guide.refresh()

    def _set_feature_enabled(self, key, value):
        from ..setup_state import BY_KEY
        if value and BY_KEY[key].beta and config.load_discord_user() is None:
            self.setup_page.refresh()
            self.setup_guide.refresh()
            return
        self._feature_checks[key].setChecked(value)

    def _feature_changed(self, key):
        from ..setup_state import remember_order
        try:
            remember_order(key, self._feature_checks[key].isChecked())
        except OSError:
            _log.warning("기능 선택 순서를 저장하지 못했습니다")
        if not self._booting:
            if key == "buff":
                self._start_buff_tracking()
            elif key == "debuff":
                self._start_debuff_tracking()
        self.setup_page.refresh()
        self.setup_guide.refresh()

    def _setup_busy(self):
        return self.setup_page.busy or self.setup_guide.busy or self._setup_flow.running

    def _refresh_guide_return(self):
        self._guide_return_btn.setVisible(self.setup_guide.active and config.load_discord_user() is not None
                                          and self._pages.currentWidget() is not self.setup_guide)

    def _guide_login_changed(self):
        logged_in = config.load_discord_user() is not None
        self.settings_tab.guide_btn.setVisible(logged_in)
        if not logged_in:
            if self._setup_flow.running and self._setup_flow.page is self.setup_guide:
                self._setup_flow.cancel()
            self.setup_guide.active = False
            if self._pages.currentWidget() is self.setup_guide:
                self._pages.setCurrentWidget(self._tabs)
            if getattr(self, "_tour_from_guide", False) and getattr(self, "_tour", None) is not None:
                self._tour.dismiss()
                self._tour = None
                self._tour_from_guide = False
        self.setup_guide.refresh()
        self._refresh_guide_return()

    def _open_guide(self, *, first_run=False):
        if config.load_discord_user() is None:
            return
        if self._setup_busy() or self._config_pending_restart or self._setup_flow.closed:
            return
        previous = getattr(self, "_tour", None)
        if previous is not None:
            previous.dismiss()
            self._tour = None
        self.setup_guide.reset(first_run=first_run)
        self._pages.setCurrentWidget(self.setup_guide)
        self._refresh_guide_return()

    def _resume_guide(self):
        if config.load_discord_user() is None:
            return
        if self._setup_busy() or self._config_pending_restart or self._setup_flow.closed:
            return
        self.setup_guide.refresh()
        self._pages.setCurrentWidget(self.setup_guide)

    def _run_guide_setup(self):
        if config.load_discord_user() is None:
            return
        self._setup_flow.run(page=self.setup_guide, feature_keys=self.setup_guide.feature_keys,
                             on_result=self.setup_guide.record_result)
        if not self._setup_flow.closed:
            self.setup_guide.refresh()
            if config.load_discord_user() is None:
                self._guide_login_changed()

    def _finish_guide(self):
        if config.load_discord_user() is None:
            self._guide_login_changed()
            return
        try:
            config.save_general_flag("firstUseGuideShown", True)
        except OSError:
            _log.warning("첫 사용 안내 표시 기록을 저장하지 못했습니다")
        self._leave_setup()
        self._refresh_guide_return()
        self._run_tour(from_guide=True)

    def _apply_setup_region(self, key, box):
        if self._config_pending_restart or self._setup_flow.closed:
            raise RuntimeError("종료 또는 설정 재시작 대기 중에는 등록할 수 없습니다")
        if key in ("buff", "debuff"):
            section = "buffTracker" if key == "buff" else "debuffTracker"
            config.save_capture_region(*box, section)
            if key == "buff":
                self.buff_tab._update_region_hint()
                self._start_buff_tracking()
            else:
                self.debuff_tab.refresh_region_hint()
                self._start_debuff_tracking()
        elif key == "boss":
            config.save_boss_bar_region(*box)
            self.boss_tab.reload_region()
            self._on_boss_bar_region_changed()
        elif key == "tuarim":
            self.tuarim_tab._apply_region(*box)
        elif key == "stat_bars":
            self.stat_bars_tab._on_selected(*box)
        elif key == "skillbar":
            self.skillbar_tab._on_anchor_selected(*box)

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
        self._status_label = QLabel("● 전체 오버레이: 켜짐")
        self._status_label.setObjectName("statusText")
        self._status_label.setToolTip(
            "각 기능의 사용 설정과 게임 활성 상태에 따라 표시됩니다. 영역 등록 여부는 각 탭에서 확인하세요."
        )
        h.addWidget(self._status_label)
        # 재생/일시정지 토글: 감지 중이면 ❚❚(누르면 멈춤), 멈추면 ▶(누르면 재개).
        # 아이콘은 직접 그린다(_OverlayToggle) — 이모지의 자체 네모 테두리 artifact 제거 +
        # 앱 민트 기조와 달리 이 버튼만 모노톤으로.
        self._pause_btn = _OverlayToggle()
        self._pause_btn.setToolTip(
            "사냥 안 할 때 오버레이를 잠깐 끄고/켭니다 "
            "(앱이 앞에 있을 때 Space로도 토글)"
        )
        self._pause_btn.toggled.connect(self._set_paused)
        h.addWidget(self._pause_btn)
        bar.setStyleSheet(
            "#statusBar { border-bottom:1px solid rgba(128,128,128,0.25); }"
            "#statusText { font-size:12px; }"
        )
        return bar

    def _overlay_status(self) -> tuple[str, str]:
        """최상단 상태 한 줄 = 재생/일시정지 토글과 1:1(2상태).

        게임 포그라운드 여부는 성격이 다른 축이라 여기 섞지 않는다(각 탭의 진단
        상태 줄에 '게임 비활성' 안내가 따로 있음).
        """
        if self._paused:
            # 정지중은 빨간 ●로(동작중 초록 ●과 대비). 앞 글리프는 ⏸ 이모지가 아니라
            # 일반 원(●)이라 OS 이모지 폰트의 네모 박스 artifact가 없다.
            return ("● 전체 오버레이: 일시정지", self._STATUS_STOP)
        return ("● 전체 오버레이: 켜짐", self._STATUS_OK)

    def _update_header_status(self) -> None:
        text, color = self._overlay_status()
        self._status_label.setText(text)  # 앞의 ●/⏸ 가 상태 표시('상태:' 접두어 없음)
        self._status_label.setStyleSheet(f"color:{color}; font-size:12px;")
        # 버튼 아이콘: 재생 중이면 ❚❚(멈춤 유도), 일시정지면 ▶(재개 유도).
        # 체크 상태는 _set_paused 에서 동기화되고, _OverlayToggle 이 직접 그린다.
        self._pause_btn.update()

    # ---- 진단 상태 한 줄 ----
    _STATUS_OK = "#2ecc71"
    _STATUS_WARN = "#e67e22"
    _STATUS_STOP = "#e74c3c"  # 정지중 빨간 ●
    _STATUS_MUTED = "#8a8f98"

    def _apply_tab_styles(self) -> None:
        """현재 테마(다크/라이트)에 맞춰 상·하위 탭 색을 적용. 테마 변경 시 재호출."""
        from .theme import is_dark

        dark = is_dark()
        sub = _subtab_qss(dark)
        self._tracker_tabs.setStyleSheet(sub + "QTabBar::tab { padding:6px 9px; }")
        self._convenience_tabs.setStyleSheet(sub)
        self._tabs.setStyleSheet(_tab_qss(dark))
        # 파티 현황판은 매칭 행 배경색이 셀에 박혀 있어, 테마가 바뀌면 다시 그려야
        # 새 테마 색으로 갱신된다(안 그러면 호버 전까지 옛 색으로 보임).
        self.party_tab.apply_theme()

    def _maybe_retry_live_capture(self) -> None:
        """라이브 캡처가 시작 실패로 비어 있으면 주기적으로 재시도한다.

        앱이 부팅 직후 자동실행되면 바탕화면 구성(Desktop Duplication)이 아직 준비 안 돼
        dxcam·mss가 '액세스 거부(0x80070005)'로 실패할 수 있고, 게임이 '전체화면(독점)'
        이면 캡처가 거부된다. 둘 다 '그 순간만' 안 되는 일시 상태라, 시작 때 한 번만
        시도하고 포기하면(기존) 나중에 캡처가 가능해져도 '추적 대기'로 영영 멈춘다.
        그래서 영역은 있는데 컨트롤러가 없으면 일정 간격으로 다시 붙여, 게임이 테두리
        없는 창으로 바뀌거나 바탕화면이 준비되면 자동으로 추적이 살아나게 한다.
        (실패 시 _start_*_tracking이 내부에서 로그만 남기고 조용히 되돌아오므로, 간격을
        충분히 둬 로그 폭주를 막는다.)
        """
        import time

        if self._closing or self._config_pending_restart:
            return
        now = time.monotonic()
        if now - getattr(self, "_last_cap_retry", 0.0) < 5.0:
            return
        need_buff = (
            self.buff_controller is None
            and self.buff_tab.enable.isChecked()
            and bool(config.load_capture_region("buffTracker"))
        )
        need_debuff = (
            self.debuff_controller is None
            and self.debuff_tab.enable.isChecked()
            and bool(config.load_capture_region("debuffTracker"))
        )
        if not (need_buff or need_debuff):
            return
        self._last_cap_retry = now
        if need_buff:
            self._start_buff_tracking()
        if need_debuff:
            self._start_debuff_tracking()

    def _update_tracking_status(self) -> None:
        if self._closing or self._config_pending_restart:
            return
        self._maybe_retry_live_capture()
        self.buff_tab.set_status(*self._buff_status())
        self.debuff_tab.set_status(*self._debuff_status())
        # 사라짐 경고 가능 여부 안내. 방식과 무관하게 '디버프 영역에서 띠를 한 번이라도
        # 봤는지'(bar_ever_seen)로 표시한다 — 보스가 잠깐 없어도 "인식됨"을 유지해, 영역이
        # 맞는데도 "안 보여요"가 깜빡이던 문제를 없앤다. 1차에서도 동일하게 동작.
        self.debuff_tab.set_bar_status(
            self._debuff_engine.bar_ever_seen
            if self._debuff_engine is not None
            else False
        )
        if self._debuff_engine is not None:
            self.debuff_tab.set_gate_status(self._debuff_engine.gate_diagnostics)
        self._update_header_status()
        self._maybe_tick_update_check()

    def _maybe_tick_update_check(self) -> None:
        """업데이트 확인을 '항상 도는' 상태 타이머(700ms)에 얹는다.

        전용 업데이트 타이머가 모종의 이유로 안 돌아도(시작 중 모달에 막히거나 등)
        백그라운드 감지가 보장된다. 상태 타이머는 상태 라벨이 갱신되는 것으로 실제
        동작이 눈에 확인된다. 자체 60초 게이트로 과호출·로그 스팸을 막는다
        (_maybe_check_update의 30초 스로틀과 별개).
        """
        import time

        now = time.monotonic()
        if now - getattr(self, "_last_bg_update_tick", 0.0) >= 60.0:
            self._last_bg_update_tick = now
            self._maybe_check_update("주기")

    def _buff_status(self) -> tuple[str, str]:
        if not self.buff_tab.enable.isChecked():
            return ("버프 트래커: 사용 안 함", self._STATUS_MUTED)
        if not config.load_capture_region("buffTracker"):
            return ("⚠ 영역 미지정 — '버프 영역 지정'을 먼저 하세요", self._STATUS_WARN)
        if self.buff_controller is None:
            return (
                ("ℹ 추적 대기 — 화면 캡처 준비 중 (게임이 '전체화면'이면 '테두리 없는 창'"
                 "으로 바꿔 주세요 · 자동 재시도 중)"),
                self._STATUS_MUTED,
            )
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
        if not self.debuff_tab.enable.isChecked():
            return ("디버프 트래커: 사용 안 함", self._STATUS_MUTED)
        if not config.load_capture_region("debuffTracker"):
            return ("⚠ 영역 미지정 — '디버프 줄 영역 지정'을 먼저 하세요",
                    self._STATUS_WARN)
        if self.debuff_controller is None:
            return (
                ("ℹ 추적 대기 — 화면 캡처 준비 중 (게임이 '전체화면'이면 '테두리 없는 창'"
                 "으로 바꿔 주세요 · 자동 재시도 중)"),
                self._STATUS_MUTED,
            )
        if not self._watcher.is_game_active():
            return ("⏸ 게임 비활성 — 마비노기 창을 맨 앞으로 두면 추적합니다",
                    self._STATUS_MUTED)
        n = self.debuff_controller.item_count
        if n:
            return (f"● 추적 중 — 안 걸린 디버프 {n}개 표시", self._STATUS_OK)
        return ("● 추적 중 — 표시할 디버프 없음", self._STATUS_OK)

    def _maybe_run_tour(self) -> None:
        """시청 기록과 무관하게 명시적 숨김만 존중하는 베타 시작 안내."""
        from ..setup_state import needs_start_screen

        if not self.isVisible():
            return
        if not needs_start_screen():
            return
        first_run = not (config.load_general_flag("tourShown", False)
                         or config.load_general_flag("firstUseGuideShown", False))
        self._open_guide(first_run=first_run)

    def _maybe_show_release_notes(self) -> None:
        """버전이 바뀌었으면(마지막 본 버전 != 현재) 업데이트 노트를 띄운다.

        개발 빌드(0.0.0)·창 비표시·같은 버전은 건너뛴다. 이전엔 '투어 미노출=신규'로
        판단해 노트를 생략했는데, 투어 플래그가 환경마다 불안정해 기존 사용자에게도
        노트가 안 뜨는 원인이 됐다. 이제 그 게이트를 없애고, 진단 로그를 남긴다.
        """
        from ..version import __version__
        from .release_notes import ReleaseNotesDialog, notes_since

        if __version__ == "0.0.0":
            _notes_log.info("노트 생략: 개발 빌드(0.0.0)")
            return
        if not self.isVisible():
            _notes_log.info("노트 생략: 창이 아직 안 보임")
            return
        last_seen = config.load_last_seen_version()
        if last_seen == __version__:
            _notes_log.info("노트 생략: 이미 본 버전(%s)", last_seen)
            return
        body = notes_since(last_seen, __version__)
        config.save_last_seen_version(__version__)  # 재시도 방지로 먼저 기록
        _notes_log.info(
            "노트 판정: last_seen=%r cur=%s body=%d자 → %s",
            last_seen, __version__, len(body), "표시" if body else "내용없음",
        )
        if body:
            ReleaseNotesDialog(body, __version__, self).exec()

    def _replay_tour(self) -> None:
        if self._setup_busy() or self._config_pending_restart or self._setup_flow.closed:
            return
        self._run_tour()

    def _run_tour(self, *, from_guide=False) -> None:
        """단계별 설정과 구별되는 앱 둘러보기."""
        if from_guide and config.load_discord_user() is None:
            return
        if self._setup_busy() or self._config_pending_restart or self._setup_flow.closed:
            return
        self.creator_dialogue.dismiss()
        if not self.isVisible():
            self.show()
        previous = getattr(self, "_tour", None)
        if previous is not None:
            previous.dismiss()
            self._tour = None
        from .tour_overlay import TourOverlay, TourStep

        entry = (self._tabs.currentWidget(), self._tracker_tabs.currentWidget(),
                 self._convenience_tabs.currentWidget())

        def go_tracker():
            self._open_setup_feature("buff")

        def go_buff_control(control):
            go_tracker()
            self._combat_pages["buff"].ensureWidgetVisible(control)

        def go_convenience():
            self._pages.setCurrentWidget(self._tabs)
            self._tabs.setCurrentWidget(self._convenience_tabs)

        def go_settings():
            self._pages.setCurrentWidget(self._tabs)
            scroll = self._tabs.widget(3)
            self._tabs.setCurrentWidget(scroll)
            logged_in = config.load_discord_user() is not None
            settings_step.target = self.settings_tab.setup_btn if logged_in else self.settings_tab.tour_btn
            settings_step.body = ("단계별 자동설정과 앱 둘러보기를 설정에서 다시 열 수 있어요." if logged_in else
                                  "설정에서 앱 둘러보기를 다시 열 수 있어요.")
            scroll.ensureWidgetVisible(settings_step.target)

        settings_step = TourStep(self.settings_tab.setup_btn, "설정에서 다시 열기",
                                 "단계별 자동설정과 앱 둘러보기를 설정에서 다시 열 수 있어요.",
                                 before=go_settings)

        steps = [
            TourStep(self._tracker_tabs.tabBar(), "전투 보조",
                     "버프·디버프·투아림과 자원 표시, 화면 배치 기능을 아래 탭에서 선택할 수 있어요.", before=go_tracker),
            TourStep(self._convenience_tabs.tabBar(), "편의기능",
                     "분배금과 구슬 분배금, 구슬 교환 효율을 계산할 수 있어요.",
                     before=go_convenience),
            TourStep(self.buff_tab.region_btn, "개별 기능 설정",
                     "아직 등록하지 않은 영역은 각 기능에서 찾거나 직접 지정할 수 있어요.",
                     before=lambda: go_buff_control(self.buff_tab.region_btn)),
            TourStep(self.buff_tab.lock_btn, "오버레이 위치 잠금",
                     "오버레이를 옮긴 뒤 잠그면 클릭이 게임으로 통과해요.",
                     before=lambda: go_buff_control(self.buff_tab.lock_btn)),
            TourStep(self._pause_btn, "전체 일시정지",
                     "사용 중인 오버레이를 잠시 멈췄다가 다시 사용할 수 있어요.", before=go_tracker),
            settings_step,
            TourStep(None, "사용 안내 종료",
                     "남은 설정은 각 기능에서 이어서 진행할 수 있어요.", before=go_tracker),
        ]

        def done():
            self._tour = None
            self._tour_from_guide = False
            config.save_general_flag("tourShown", True)
            if self._closing or self._config_pending_restart or not self.isVisible():
                return
            if from_guide:
                self._open_setup_feature("buff")
            else:
                self._tracker_tabs.setCurrentWidget(entry[1])
                self._convenience_tabs.setCurrentWidget(entry[2])
                self._tabs.setCurrentWidget(entry[0])

        self._tour_from_guide = from_guide
        self._tour = TourOverlay(self, steps, on_done=done,
                                 section_title="첫 사용 안내 4 / 4" if from_guide else "")
        self._tour.start()

    def _maybe_prompt_game_window(self) -> None:
        """게임 창 인식이 안 돼 있으면 시작 시 '등록' 팝업을 띄운다(자동 찾기·오버레이에 필수).

        창이 보일 때만(트레이 시작 아님) + Windows + 아직 미등록일 때. 등록되기 전까지는
        매 실행 안내한다('다시 묻지 않기' 영구 숨김은 없앴다 — 이번 건너뛰기는 팝업의 '나중에').
        """
        import sys

        if not self.isVisible():
            return  # 트레이로 시작 등 창이 없으면 팝업도 생략
        if sys.platform != "win32":
            return  # 맥/리눅스는 포그라운드 개념이 없어(항상 활성) 불필요
        if config.load_game_exe():
            return  # 이미 등록됨 → 더 안 묻는다
        # '게임 창 인식'은 자동 찾기·오버레이 정확도에 필요(필수)하므로, 등록되기 전까지는
        # 매 실행 시 안내한다('다시 묻지 않기' 영구 숨김은 제거). 이번 실행 건너뛰기는 '나중에'.

        from .game_window_dialog import GameWindowDialog

        dlg = GameWindowDialog(self._watcher, self)
        dlg.exec()
        self.settings_tab.refresh_game_label()  # 지정했으면 설정 라벨도 갱신

    # 업데이트 확인 최소 간격(초). 포커스 얻을 때마다 확인하되 이 간격으론 과호출 방지.
    # 활성화(앱으로 돌아옴) 시 확인의 최소 간격. 너무 길면(2~3분) 자주 들락거리는
    # 실사용에서 돌아올 때마다 스로틀에 막혀 '포커스 확인'이 무용지물이 된다(로그로 확인).
    # 30초면 빠른 alt-tab 연타만 묶고, 30초 지나 돌아오면 바로 최신을 확인한다.
    _UPDATE_CHECK_MIN_GAP = 30.0

    def _maybe_check_update(self, reason: str = "?") -> None:
        """백그라운드로 새 버전 확인(시작 시·주기·창 활성화 시). 실패는 조용히 무시.

        여러 계기에서 호출되므로 최소 간격으로 스로틀한다(짧은 간격 중복 호출 무시).
        진단 로그: 어떤 계기로 호출됐고, 스로틀에 막혔는지, check_latest가 뭘 받았는지
        남겨 '릴리스~감지 지연'의 실제 원인(이벤트 미발생/스로틀/raw 전파 지연)을 가린다.
        """
        import threading
        import time

        from ..system import updater

        if not updater.can_update():
            _up_log.info("업데이트 확인 안 함(%s): 배포본 아님", reason)
            return
        now = time.monotonic()
        gap = now - getattr(self, "_last_update_check", 0.0)
        if gap < self._UPDATE_CHECK_MIN_GAP:
            _up_log.debug(  # 자주 울려 DEBUG(버그리포트 버퍼엔 남고 평소엔 조용히)
                "업데이트 확인 건너뜀(%s): %.0f초 전 확인함(스로틀 %.0f초)",
                reason, gap, self._UPDATE_CHECK_MIN_GAP,
            )
            return
        self._last_update_check = now
        _up_log.info("업데이트 확인 시작(%s)", reason)

        def work() -> None:
            from ..version import __version__

            try:
                info = updater.check_latest()
            except Exception as exc:  # noqa: BLE001 — 확인 실패는 무시(진단만 남김)
                _up_log.info("업데이트 확인 예외(%s): %r", reason, exc)
                return
            if info:
                _up_log.info("업데이트 확인 결과(%s): 새 버전 %s", reason, info.get("version"))
                self._update_found.emit(info)  # UI 스레드로 전달 → 배너
            else:
                _up_log.info("업데이트 확인 결과(%s): 새 버전 없음(현재 %s)", reason, __version__)

        threading.Thread(target=work, daemon=True).start()

    def _on_update_found(self, info: dict) -> None:
        ver = str(info.get("version", "?"))
        self._pending_update = info
        self.show_update_banner(ver)
        # 처음 감지한 버전일 때만 토스트+소리(주기 확인이 같은 버전을 반복해도 1회만).
        if ver != getattr(self, "_announced_update", None):
            self._announced_update = ver
            from .notifier import play_update_sound
            from .toast import show_toast

            # 토스트 클릭 → 창을 띄워(트레이·최소화 상태에서도) [지금 업데이트]를 누를 수 있게.
            show_toast(
                "새 버전 v" + ver,
                "눌러서 앱을 열고 상단의 [지금 업데이트]로 받으세요",
                6000,
                on_click=self._show_from_tray,
            )
            play_update_sound()

    def _on_update_clicked(self) -> None:
        """[지금 업데이트] → 다운로드(진행바) → B안 교체 → 재실행.

        교체 도중 사용자가 본 창을 건드려 상태를 바꾸면 위험해, 본 창을 숨기고(=뒤에서
        못 누르게) 시작 때와 같은 스플래시(로고+프로그레스바)를 재활용해 진행률만 보인다.
        성공하면 새 exe가 이미 떠 있으니 그대로 종료, 실패하면 본 창을 다시 띄워 안내한다.
        """
        import threading

        from PySide6.QtWidgets import QMessageBox

        from ..system import updater
        from .splash import Splash

        info = self._pending_update
        if not info:
            return

        ver = info.get("version", "?")
        if QMessageBox.question(
            self, "업데이트",
            f"새 버전 v{ver} 을(를) 받아 교체하고 다시 시작합니다.\n진행할까요?",
        ) != QMessageBox.StandardButton.Yes:
            return

        # 시작 스플래시 재활용: 본 창을 숨기고 그 자리에 진행률 스플래시만 띄운다.
        splash = Splash()
        splash.center_on_screen()
        splash.step(0, f"새 버전 v{ver} 받는 중…")
        splash.show()
        self._update_splash = splash  # 재생 중 GC 방지(모듈 아닌 self에 보관)
        self.hide()

        self._update_progress.connect(self._on_update_progress)
        self._update_result.connect(self._on_update_result)

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

    def _on_update_progress(self, pct: int) -> None:
        splash = getattr(self, "_update_splash", None)
        if splash is not None:
            splash.step(pct, "새 버전 받는 중…")

    def _on_update_result(self, ok: bool, msg: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        # 재시도(실패 후 다시 클릭) 시 신호가 중복 연결되지 않게 정리.
        for sig in (self._update_progress, self._update_result):
            try:
                sig.disconnect()
            except (TypeError, RuntimeError):
                pass
        splash = getattr(self, "_update_splash", None)
        if splash is not None:
            splash.close()
            self._update_splash = None
        if ok:
            # 새 exe 가 이미 떠 있으니 현재(구버전) 프로세스는 완전히 종료.
            self._force_quit = True
            QApplication.quit()
            return
        # 실패 → 숨겼던 본 창을 다시 띄우고 사유 안내.
        self.show()
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
        if self._closing or self._config_pending_restart or self._started:
            return
        self._started = True
        self.creator_dialogue.start()
        from ..system import autostart

        # 자동실행: 저장된 '의도'대로 현재 exe에 강제 동기화(신버전 실행=자동실행 대상).
        # 기존 사용자(의도 미저장)는 현재 작업 상태를 의도로 이어받아 한 번 저장한다.
        intent = config.load_autostart_intent()
        if intent is None:
            intent = autostart.is_enabled()
            config.save_autostart_intent(intent)
        autostart.reconcile(intent)
        self.party_tab.start_polling()
        self._restore_overlay(self.buff_overlay, self.buff_tab, "buffTracker")
        self._restore_overlay(self.debuff_overlay, self.debuff_tab, "debuffTracker")
        self._restore_memo()
        self._start_buff_tracking()
        self._start_debuff_tracking()
        self._maybe_check_update("시작")
        # 타이머들을 모달(게임창 안내/투어)보다 '먼저' 시작한다. 안 그러면 그 모달이
        # exec()로 열려 있는 동안 start()가 그 줄에서 멈춰, 주기 업데이트 확인·상태 갱신
        # 타이머가 영영 시작되지 않는다(자동실행 직후 등 '백그라운드 감지 안 됨'의 원인).
        # 모달 exec() 중에도 이미 start()된 타이머는 그 이벤트 루프에서 계속 돈다.
        # 진단 상태 한 줄(추적 중/게임 비활성/영역 미지정 등) 주기 갱신.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(700)
        self._status_timer.timeout.connect(self._update_tracking_status)
        self._status_timer.start()
        self._update_tracking_status()
        # 실행 중 업데이트 감지: 시작 1회·창 활성화 외에, 위 상태 타이머(_maybe_tick_
        # update_check)가 60초마다 확인한다. 전용 타이머 대신 '항상 도는' 상태 타이머에
        # 얹어, 시작 중 무엇이 막아도 백그라운드 감지가 보장되게 한다(캐시무효화로 최신 수신).
        # 모달 안내는 타이머 시작 '뒤'에(위 이유). 이게 떠 있어도 감지는 계속 돈다.
        # 노트·투어는 창이 '실제로 처음 보일 때'(showEvent) 띄운다. start()는 window.show()
        # '전'에 불리고(진입점 순서), 트레이로 시작하거나 업데이트 후 재실행되는 등 경로가
        # 다양해, start() 시점에 쏘면 isVisible=False라 놓친다. showEvent 로 옮겨 어느
        # 경로든 창이 보이는 순간 한 번 확실히 뜨게 한다.
        self._booting = False  # 부팅 끝 — 이제부터 사용자 변경을 저장

    def showEvent(self, event) -> None:
        """창이 처음 보일 때 업데이트 노트·온보딩 투어를 한 번 띄운다.

        최소화→복원 등으로 여러 번 불리므로 플래그로 1회만. 이벤트 루프로 한 틱 미뤄
        창이 완전히 뜬 뒤 그 위에 올라오게 한다.
        """
        super().showEvent(event)
        if getattr(self, "_post_show_done", False) or self._booting:
            return
        self._post_show_done = True
        QTimer.singleShot(0, self._on_first_shown)

    def _on_first_shown(self) -> None:
        if self._closing or self._config_pending_restart:
            return
        self._maybe_show_release_notes()  # 버전 바뀌었으면 업데이트 노트
        self._maybe_run_tour()  # 단계별 베타 준비 안내

    def _compute_tracking(
        self, catalog
    ) -> tuple[
        list[str],
        dict[str, bool],
        dict[str, int],
        dict[str, int | None],
    ]:
        """저장 설정으로 (순서, 지속시간, 1차초, 2차초[없으면 None])를 만든다."""
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
        return order, show_duration, alert_before, alert_before2

    def _start_buff_tracking(self) -> None:
        """저장된 영역이 있으면 라이브 캡처(dxcam)로 버프 추적 시작(재시작 포함)."""
        if self._closing or self._config_pending_restart:
            return
        if self.buff_controller is not None:
            self.buff_controller.stop()
            self.buff_controller = None
            self._engine = None

        from ..setup_state import enabled
        if not enabled("buff"):
            self.buff_overlay.hide()
            return

        region = config.load_capture_region("buffTracker")
        if not region:
            return
        try:
            from .dpi import to_physical

            source = create_live_source(Region(*to_physical(region)))
        except ImportError:
            return  # dxcam 없음(맥/개발) → 라이브 미시작(정상)
        except Exception as exc:  # noqa: BLE001 — Windows에서 실제 실패 시 진단 로그
            _cap_log.error("버프 라이브 캡처 시작 실패: %s", exc)
            return

        catalog = available_catalog()
        catalog_by = {b.id: b for b in catalog}
        order, show_duration, alert_before, alert_before2 = (
            self._compute_tracking(catalog)
        )
        self._sound_ids = self._sound_enabled_ids()
        # 앵커 게이팅: 앵커(프리미엄 전투)가 보이는 프레임만 '정상'으로 보고,
        # 안 보이면 상태를 동결(내부 시계로 버팀)하다 다시 보이면 동기화한다.
        # 단 앵커가 영역에 애초에 없으면(한 번도 안 보이면) 게이팅하지 않아
        # 기존 동작과 동일 — 엔진 쪽 anchor_seen 안전장치가 처리한다.
        # 표시(오버레이 ON)된 버프 + 앵커만 매칭한다. 숨긴 버프까지 전부 매칭하면
        # 아이콘 탐지(매 틱)가 템플릿 수에 비례해 느려진다. 앵커는 프레임 게이팅에 필요.
        tracked_ids = set(order) | {ANCHOR_ID}
        tracked = [b for b in catalog if b.id in tracked_ids]
        self._engine = BuffEngine(
            build_templates(tracked),
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
            on_alert2=self._on_buff_alert2,
        )
        self.buff_controller.set_order(order)
        self.buff_controller.set_warn_gone_ids(self._warn_gone_ids())
        self.buff_controller.set_paused(self._paused)  # 재생성 시 일시정지 상태 유지
        # 아이콘 생성/소멸을 빠르게 캐치(50ms=20fps). 시간 판독은 엔진이 throttle하고,
        # 매칭 대상도 표시된 버프만이라 비용이 낮아 이 주기가 감당된다.
        self.buff_controller.start(source, self._engine, interval_ms=50)

    def _sound_enabled_ids(self) -> set[str]:
        """'종료 알림'과 '소리'를 모두 켠 버프 id 집합(알림 시 사운드 재생 대상)."""
        return {
            s.id
            for s in config.load_buff_settings()
            if s.alert.enabled and s.alert.sound
        }

    def _warn_gone_ids(self) -> set[str]:
        """'사라짐 경고'를 켠 버프 id 집합(사라지면 빨간 테두리+X+소리)."""
        return {s.id for s in config.load_buff_settings() if s.alert.warn_gone}

    def _on_buff_alert(self, buff_ids) -> None:
        """엔진이 만료임박(1차) 알림을 올리면, 소리 켠 버프만 사운드 재생."""
        to_play = [b for b in buff_ids if b in self._sound_ids]
        if to_play:
            self._notifier.alert(to_play)

    def _on_buff_alert2(self, buff_ids) -> None:
        """2차(막차) 알림 — 소리 켠 버프만 '연장2.mp3'(없으면 1차 폴백) 재생."""
        to_play = [b for b in buff_ids if b in self._sound_ids]
        if to_play:
            self._notifier2.alert(to_play)

    def _on_tracking_changed(self) -> None:
        """순서·노출·지속시간·알림 변경을 실행 중 엔진에 즉시 반영(재시작 없이)."""
        if self._engine is None or self.buff_controller is None:
            return
        order, show_duration, alert_before, alert_before2 = (
            self._compute_tracking(available_catalog())
        )
        self._engine.set_order(order)
        self._engine.set_show_duration(show_duration)
        self._engine.set_alert_before(alert_before)
        self._engine.set_alert_before2(alert_before2)
        self.buff_controller.set_show_duration(show_duration)
        self.buff_controller.set_order(order)
        self.buff_controller.set_warn_gone_ids(self._warn_gone_ids())
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
        if self._closing or self._config_pending_restart:
            return
        if self.debuff_controller is not None:
            self.debuff_controller.stop()
            self.debuff_controller = None
            self._debuff_engine = None

        from ..setup_state import enabled
        if not enabled("debuff"):
            self.debuff_overlay.hide()
            return

        region = config.load_capture_region("debuffTracker")
        if not region:
            return
        try:
            from .dpi import to_physical

            source = create_live_source(Region(*to_physical(region)))
        except ImportError:
            return  # dxcam 없음(맥/개발) → 라이브 미시작(정상)
        except Exception as exc:  # noqa: BLE001 — Windows에서 실제 실패 시 진단 로그
            _cap_log.error("디버프 라이브 캡처 시작 실패: %s", exc)
            return

        catalog = available_debuff_catalog()
        catalog_by = {b.id: b for b in catalog}
        order = self._debuff_order(catalog)
        # 표시(숨기지 않은) 디버프만 매칭 — 버프와 동일하게 비용 절감.
        tracked = [b for b in catalog if b.id in set(order)]
        reference_ids = DebuffEngine.reference_ids(order)
        references = [b for b in catalog if b.id in reference_ids]
        gate_mode = self.debuff_tab.effective_gate_mode()
        self._debuff_engine = DebuffEngine(
            build_templates(tracked),
            order,
            gate_mode=gate_mode,
            reference_templates=build_templates(references),
        )
        self._debuff_engine.set_warn_gone_ids(self._debuff_warn_gone_ids())
        # 3차(percent): 보스 HP바 영역(보스패턴알림과 공유)을 따로 캡처해 넘긴다.
        bar_source = None
        if gate_mode in ("percent", "auto"):
            bar_region = config.load_boss_bar_region()
            if bar_region:
                try:
                    from .dpi import to_physical

                    bar_source = create_live_source(Region(*to_physical(bar_region)))
                except ImportError:
                    bar_source = None  # dxcam 없음(맥/개발)
                except Exception as exc:  # noqa: BLE001
                    _cap_log.error("보스 바 라이브 캡처 시작 실패: %s", exc)
                    bar_source = None
        # 지속시간·알림·점멸 없음 → show_duration 전부 False.
        self.debuff_controller = BuffController(
            self.debuff_overlay,
            catalog_by,
            {b.id: False for b in catalog},
            on_alert=self._on_debuff_gone,  # 디버프 떨어짐 확정 → 사라짐 경고음
            watcher=self._watcher,
        )
        self.debuff_controller.set_paused(self._paused)  # 재생성 시 일시정지 상태 유지
        # 보스에서 떨어진 디버프(재적용 필요)를 빨리 캐치하도록 150ms 주기.
        # 표시한 것만 매칭이라 비용은 낮다(시간 판독도 없음).
        self.debuff_controller.start(
            source, self._debuff_engine, interval_ms=150, bar_source=bar_source
        )

    def _on_debuff_tracking_changed(self) -> None:
        if self._debuff_engine is None:
            return
        order = self._debuff_order(available_debuff_catalog())
        if not self._debuff_engine.can_track(order):
            self._start_debuff_tracking()
            return
        self._debuff_engine.set_order(order)
        self._debuff_engine.set_warn_gone_ids(self._debuff_warn_gone_ids())

    def _on_boss_bar_region_changed(self) -> None:
        """보스 탭에서 보스 HP바 영역이 바뀜 → 디버프 3차가 쓰면 새 영역으로 재시작."""
        if not self._booting and self.debuff_tab.effective_gate_mode() in ("percent", "auto"):
            self._start_debuff_tracking()

    def _on_debuff_gate_mode(self, _mode: str) -> None:
        """탐지 방식(1/2/3차) 또는 보스 바 영역 변경 → 디버프 추적 재구성.

        3차(percent)는 '보스 바 영역' 캡처 소스를 따로 붙여야 하므로, 라이브 전환이 아니라
        _start_debuff_tracking으로 재시작한다(엔진·바 소스를 현재 설정으로 다시 만든다).
        """
        if not self._booting:
            self._start_debuff_tracking()

    def _debuff_warn_gone_ids(self) -> set[str]:
        """'사라짐 경고'를 켠 디버프 id 집합(보스에서 떨어지면 빨간 테두리+X+소리)."""
        return {s.id for s in config.load_debuff_settings() if s.alert.warn_gone}

    def _on_debuff_gone(self, _ids) -> None:
        """디버프 떨어짐 확정 → 사라짐 경고음(여러 개 동시 확정돼도 한 번)."""
        from .notifier import play_warn_gone_sound

        play_warn_gone_sound()

    def _on_debuff_catalog_changed(self) -> None:
        self._start_debuff_tracking()

    def _on_boss_debuff_region_changed(self) -> None:
        """보스 탭 자동 찾기가 디버프 영역을 지정 → 디버프 추적 재시작(모드 무관) + 표시 갱신."""
        self.debuff_tab.refresh_region_hint()
        if not self._booting:
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

    def _on_memo_enabled(self, enabled: bool) -> None:
        self._memo_enabled = enabled
        self._save_memo()
        self._tick_memo_visibility()  # 즉시 반영(끄면 바로 숨김)

    def _save_memo(self) -> None:
        if self._restoring or self._booting or self._config_pending_restart:
            return
        config.save_memo(
            self.memo_overlay.text(),
            self.memo_overlay.locked,
            self.memo_tab.font_spin.value(),
            self._memo_enabled,
        )

    def _tick_memo_visibility(self) -> None:
        """메모 표시 규칙: '사용' 켜짐 + 게임 포그라운드면 표시. 해제(편집) 상태면
        우리 앱에서도 표시(위치/입력). 고정인데 게임이 포그라운드 아니면 숨김."""
        if not self._memo_enabled or config.load_capture_region("memoTracker") is None:
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
            memo = config.load_memo()
            locked = bool(memo.get("locked", False))
            self.memo_tab.set_lock_state(locked)  # 버튼 동기화 + set_locked 적용
            self._memo_enabled = bool(memo.get("enabled", True))
            self.memo_tab.enable_chk.blockSignals(True)
            self.memo_tab.enable_chk.setChecked(self._memo_enabled)
            self.memo_tab.enable_chk.blockSignals(False)
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
        # 트레이 복원은 '사용자가 앱을 보려는' 명백한 신호. Windows는 백그라운드
        # 프로세스의 포그라운드 강탈을 막아 activateWindow()가 실제 활성화를 못 해
        # changeEvent(활성화)가 안 울릴 수 있으므로, 여기서 직접 업데이트 확인을 돈다.
        self._maybe_check_update("트레이복원")

    def _focus_party_tab(self) -> None:
        """파티 알림 토스트 클릭 → 창을 띄우고 파티 모집 탭으로 전환."""
        self._show_from_tray()
        self._tabs.setCurrentWidget(self._party_scroll)

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
        self.stat_bars_tab.set_paused(paused)
        self.dorcha_tab.set_paused(paused)
        self.skillbar_tab.set_paused(paused)
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
        from .notifier import default_sound_map, second_sound_map

        if self._notifier is not None:
            self._notifier.set_sounds(default_sound_map())  # 버프 1차
        if self._notifier2 is not None:
            self._notifier2.set_sounds(second_sound_map())  # 버프 2차(막차)
        self.tuarim_tab.refresh_sound()
        # 파티 알림음은 보이스팩과 무관(기본 소리 고정)이라 갱신 불필요.

    def _on_config_imported(self) -> None:
        """설정 가져오기/초기화 직후: 종료 시 낡은 상태로 덮어쓰지 않도록 저장을 막는다.

        자동 재시작(QProcess로 자기 자신 재실행)은 PyInstaller onefile에서 기존
        인스턴스의 _MEI 임시폴더 추출/정리와 충돌해 새 프로세스의 네이티브 모듈
        (cv2 등) 로드가 깨졌다. 그래서 재실행은 하지 않고, 이 세션은 상태 저장만
        멈춘 뒤 사용자가 직접 종료→재실행하면 바뀐 설정·자산이 깨끗이 반영된다.
        """
        self._config_pending_restart = True
        self._setup_flow.shutdown()
        self.setup_page.setEnabled(False)

    def _minimize_to_tray_enabled(self) -> bool:
        return self._tray is not None and config.load_general_flag(
            "minimizeToTray", True
        )

    def changeEvent(self, event) -> None:
        # 창을 앞으로 가져올 때(포커스 얻기) 새 버전 확인 — 실행 중 감지를 30분 주기만
        # 기다리지 않고, 사용자가 앱을 볼 때 바로 잡는다(_maybe_check_update가 스로틀).
        from PySide6.QtCore import QEvent

        if event.type() == QEvent.Type.ActivationChange:
            active = self.isActiveWindow()
            _up_log.debug("창 활성화 변경: active=%s", active)  # 자주 울려 DEBUG(버퍼엔 남음)
            if active:
                self._maybe_check_update("창활성화")
        super().changeEvent(event)

    def keyPressEvent(self, event) -> None:
        # Space: 오버레이 정지/시작 토글(오디오 앱처럼). 앱이 앞일 때만 — 키 이벤트는
        # 포커스 창에만 오므로 전역이 아니다(게임엔 아무 영향 없음, 읽기전용 철학 유지).
        # 입력칸(이름·키워드·메모 등)에 포커스면 글자가 먹히게 토글하지 않는다.
        from PySide6.QtCore import Qt

        if (
            event.key() == Qt.Key.Key_Space
            and not event.isAutoRepeat()
            and not self._is_text_input_focused()
        ):
            self._set_paused(not self._paused)
            event.accept()
            return
        super().keyPressEvent(event)

    @staticmethod
    def _is_text_input_focused() -> bool:
        """현재 포커스가 글자를 입력받는 위젯인가(그러면 Space는 그쪽에 양보)."""
        from PySide6.QtWidgets import (
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QPlainTextEdit,
            QTextEdit,
        )

        w = QApplication.focusWidget()
        if w is None:
            return False
        if isinstance(w, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return True
        return isinstance(w, QComboBox) and w.isEditable()

    def _restore_window_pos(self) -> None:
        """저장된 창 위치로 복원. 저장값이 없거나 연결된 화면 밖이면 주 화면 중앙에
        둔다(자동 업데이트 재실행 등으로 좌상단 0,0에 뜨던 문제 방지)."""
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QGuiApplication

        pos = config.load_window_pos()
        if pos is not None:
            r = QRect(pos["x"], pos["y"], self.width(), self.height())
            if any(s.availableGeometry().intersects(r) for s in QGuiApplication.screens()):
                self.move(pos["x"], pos["y"])
                return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            self.move(
                g.x() + (g.width() - self.width()) // 2,
                g.y() + (g.height() - self.height()) // 2,
            )

    def _save_window_pos(self) -> None:
        if self._restoring or self._booting or self._config_pending_restart:
            return
        p = self.pos()
        config.save_window_pos(p.x(), p.y())

    def hideEvent(self, event) -> None:
        tour = getattr(self, "_tour", None)
        if tour is not None:
            self._tour = None
            self._tour_from_guide = False
            tour.dismiss()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:
        import time

        if self._closing:
            event.accept()
            return
        self._setup_flow.cancel(hide=True)
        tour = getattr(self, "_tour", None)
        if tour is not None:
            self._tour = None
            tour.dismiss()
        self._save_window_pos()  # 트레이 최소화·완전 종료 모두에서 현재 위치 기억

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

        # 종료 정리 중 Qt 이벤트가 처리되어도 새 캡처/워커를 만들지 않는다.
        self._closing = True
        self.creator_dialogue.shutdown()
        if self._status_timer is not None:
            self._status_timer.stop()

        def _step(name, fn):
            # 한 단계가 실패해도 나머지(특히 '오버레이 닫기')는 반드시 실행되게 감싼다.
            t = time.perf_counter()
            try:
                fn()
            except Exception:  # noqa: BLE001 — 종료 중 오류로 오버레이가 남지 않게
                _log.exception("종료 단계 '%s' 실패", name)
            _log.info("종료 단계 '%s' %.0fms", name, (time.perf_counter() - t) * 1000)

        total = time.perf_counter()
        self._setup_flow.shutdown()
        _step("상태 저장", lambda: (
            self._save_overlay_state(),
            self._save_debuff_overlay_state(),
            self._save_memo(),
            self._memo_timer.stop(),
        ))
        _step("파티 폴링 정지", lambda: self.party_tab.stop_polling(wait_ms=600))
        _step("진단 UI 정지", self.settings_tab.shutdown)
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
            self.boss_tab.shutdown(),
            self.stat_bars_tab.shutdown(),
            self.dorcha_tab.shutdown(),
            self.skillbar_tab.shutdown(),
        ))
        if self._tray is not None:
            self._tray.hide()
        _log.info("종료 총 %.0fms", (time.perf_counter() - total) * 1000)
        super().closeEvent(event)
        # 남은 워커(파티/캡처 좀비)가 grab·HTTP에 막혀 아직 돌고 있으면, 인터프리터 teardown에서
        # Qt가 '실행 중인 QThread'를 파괴하며 프로세스를 abort(rc=134)시킨다. 상태 저장·정지
        # 신호는 위에서 끝냈으니, 로그만 flush하고 **정리 없이 즉시 종료**해 abort를 원천 차단한다.
        # (설정 가져오기는 재실행에 의존하지 않음 — 안전.) 단 테스트 중엔 프로세스를 죽이면
        # 안 되므로 종전처럼 quit만 한다.
        import sys as _sys

        if "pytest" in _sys.modules:
            QApplication.quit()
            return
        import logging as _logging
        import os as _os

        _logging.shutdown()
        _os._exit(0)
