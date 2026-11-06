"""보스 패턴 경고 탭 (기획서 12).

보스 HP바 영역을 한 번 지정하면, 그 안에서 왼쪽=이름 / 오른쪽=HP%를 읽어:
- 실시간으로 '식별된 보스 + 현재 HP%'를 표시(판독이 잘 되는지 눈으로 확인용)
- HP%가 임계의 T+5(1차)/T+1(2차)를 하강 교차하면 화면 중앙 큰 글씨 경고 + 소리

패턴 데이터(보스 이름 템플릿 + 임계%)는 번들(assets/boss). 투아림 탭과 같은 영역·캡처
방식이다.
"""

from __future__ import annotations

import threading
from time import monotonic, perf_counter

from .. import perf_meter
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QGroupBox,
    QTabWidget,
    QScrollArea,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .settings_layout import set_lock_text
from .. import config, image_io, paths
from ..detect.boss_bar import (
    normalize_box_height,
)
from ..detect.boss_hp_reader import read_percent, read_percent_frac
from .dpi import to_logical
from .screen_grab import capture_for_autofind
from ..detect.boss_name_matcher import identify, load_name_templates, load_name_variants
from ..tracker.boss_catalog import load_bosses, make_tracker
from . import overlay_capture
from .pattern_overlay import PatternWarningOverlay
from .upcoming_overlay import UpcomingPatternsOverlay
from .widgets import FeatureHeader, CapturePathLabel, checkbox, hint_label, wrapping_row

_SOUND_DIR = paths.resource_dir() / "sounds"
_PRE_SOUND = _SOUND_DIR / "보스패턴 예고.mp3"
_NEAR_SOUND = _SOUND_DIR / "보스패턴 진입.mp3"

HIGHLIGHT_TITLE = "보스 HP바 영역"
HIGHLIGHT_SUB = "보스 이름 ~ HP% 가 다 들어오게"

# 기본 영역(2560×1440 기준, 하단 중앙 보스 HP바). 오른쪽 끝 = 바 오른쪽 끝.
# 다른 해상도면 '영역 수정'으로 바에 맞춘다(판독기가 박스 높이로 스케일 보정).
DEFAULT_BOX = {"x": 1017, "y": 1248, "w": 523, "h": 36}


class BossTab(QWidget):
    from .. import autofind_regions as _afr
    _region = _afr.region_property("boss")  # 자동 찾기 v2: 읽기 = 쓸 영역, 쓰기 = 저장 영역
    # 꼬리 끊김 조사(사용자 app.log 11-04): 보스 틱(300ms)이 화면 스레드에서 캡처·이름 식별·HP 판독·보스바 확인(최대 ~36ms)을 했다.
    # 도르카(0.38.0)처럼 그 계산은 작업 스레드 1개에서, 화면 스레드는 결과 반영(상태·표시·경고)만 한다.
    INLINE_JOBS = False  # 테스트: 같은 계산을 바로(동기로) — 판정 회귀를 그대로 확인
    SLOW_TICK_MS = 16.0  # 틱(계산+반영)이 커서 꼬리 한 박자(16ms)보다 길면 단계별 소요를 app.log에(분당 1번, 그 사이 횟수 함께)
    _job_ready = Signal(object)  # 작업 스레드 → 화면 스레드(대기열 연결)
    bar_region_changed = Signal()  # 보스 HP바 영역 변경 → 디버프 3차와 공유(재시작 알림)
    debuff_region_changed = Signal()  # 자동 찾기가 디버프 영역도 지정 → 디버프 추적 재시작

    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_boss_pattern()
        # 보스 HP바 영역은 디버프 3차와 '공유'(config.load_boss_bar_region = bossPattern.box).
        # 미등록/지정 해제는 기본 위치로 복원하지 않는다.
        self._region = config.load_boss_bar_region()
        self._sct = None
        self._last_frame = None
        self._last_raw_hp: int | None = None  # 이번 프레임 '원판독'값(수집 태그·진단용)
        # 보스 HP바 수집(오독 프레임 제보 — 보스별 스샷). 로그인 사용자만.
        self._last_saved_frame = None
        self._shot_count = 0
        if paths.is_frozen():
            self._shot_dir = paths.user_data_dir() / "boss_hp_shots"
        else:
            self._shot_dir = paths.project_root() / "tests" / "data" / "boss_hp_shots"
        self._bosses = load_bosses()
        self._name_templates = load_name_templates()
        self._name_variants = load_name_variants()
        self._tracker = None
        self._cur_boss: str | None = None
        self._stable_hp: int | None = None
        self._hp_cand: int | None = None  # 확정 대기 후보값
        self._hp_cand_n = 0  # 후보 연속 횟수
        self._unidentified = 0  # 이름이 연속으로 안 읽힌 프레임 수(보스 사라짐 판정)
        # 보스바 존재 신호(체력바 저체력 알림 게이트용) — 등록/미등록 무관, ~2초 유예.
        self._boss_present = False
        self._bar_absent = self._UPCOMING_GONE_FRAMES + 1  # 시작은 '없음'
        self._bar_validate = None  # make_validator 캐시(이름 글자 + % 판독)
        # 존재 판정이 필요한가(= 저체력 경고가 하나라도 켜져 있나). main_window가 연결한다.
        # 아무도 안 쓰면 매 틱 비싼 검증을 돌릴 이유가 없어 통째로 건너뛴다.
        self._presence_wanted_fn = None
        # 보스바 오버레이(제작자 전용, 보스바 오버레이 명세): 켜져 있으면 판독을 유지하고 그릴 값을 넘긴다.
        self._bar_overlay_wanted = None  # () -> bool
        self._bar_overlay_sink = None    # (dict) -> None, 화면 스레드
        self._overlay = PatternWarningOverlay()
        self._overlay.moved.connect(self._on_warn_moved)
        self._notifier = None
        self._paused = False
        # 다음 패턴 목록 오버레이(왼쪽에 남은 패턴 % 나열). 위치/고정은 설정에 저장.
        self._upcoming = UpcomingPatternsOverlay()
        self._upcoming.moved.connect(self._on_upcoming_moved)
        self._upcoming.set_locked(cfg["upcomingLocked"])
        if cfg["upcomingPos"]:
            self._upcoming.move(
                int(cfg["upcomingPos"]["x"]), int(cfg["upcomingPos"]["y"])
            )
        else:
            self._place_upcoming_default()
        # 경고 오버레이 위치/고정 복원(목록과 동일 구조). 저장 위치 없으면 기본(상단 중앙).
        if cfg["warnPos"]:
            self._overlay.move(int(cfg["warnPos"]["x"]), int(cfg["warnPos"]["y"]))
        else:
            self._place_warn_default()
        self._overlay.set_locked(cfg["warnLocked"])

        hp_page = QWidget()
        v = QVBoxLayout(hp_page)
        v.setContentsMargins(12, 12, 12, 12)

        from .feature_copy import HELP
        from .help_dialog import help_button
        v.addWidget(FeatureHeader("보스 패턴 알림", "보스 체력이 패턴 기준에 가까워지면 화면과 소리로 알려요. 보스 체력바가 보이는 상태에서 자동 찾기를 실행하세요.", help_button("보스 패턴 알림 사용법", HELP["보스 패턴 알림"], self)))

        prev_btn = QPushButton("알림 미리보기")
        prev_btn.setToolTip("경고가 화면 어디에 어떻게 뜨는지 한 번 띄워 봐요")
        prev_btn.clicked.connect(self._preview_warning)

        # 실제 컨트롤 묶음(항상 표시 — 로그인 불필요)
        self._controls = QWidget()
        controls = QVBoxLayout(self._controls)
        controls.setContentsMargins(0, 0, 0, 0)
        # 영역 묶음(안내·도움말 명세 11절): 버튼·안내 한 줄·판독 확인은 지정 후 '영역 다시 지정 · 판독 확인 ▸' 안으로
        region_body = QWidget()
        cv = QVBoxLayout(region_body)
        cv.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.setToolTip(
            "보스 HP바의 이름과 체력 비율이 들어오도록 지정해요."
        )
        self.region_btn.clicked.connect(self._on_region)
        self.region_label = hint_label("")
        cv.addWidget(self.region_label)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        # 자동 찾기 — 로그인 없이 사용 가능. 보스 체력바를 화면에서 찾아
        # 디버프 영역(바로 위)까지 함께 지정. 저장은 반드시 확인 후에만.
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip(
            "보스 체력바(+디버프 영역)를 화면에서 자동으로 찾아 지정해요"
        )
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        commands = QHBoxLayout()
        commands.addStretch(1)
        row.addWidget(self.auto_find_btn)
        row.addWidget(self.region_btn)
        row.addWidget(self.view_region_btn)
        from .region_registration import clear_button
        self.clear_region_btn = clear_button(self, "boss", self._region_cleared)
        commands.addWidget(self.clear_region_btn)
        self.region_row = wrapping_row(row, commands)
        cv.addLayout(self.region_row)
        cv.addWidget(hint_label("이름과 체력 비율이 보이는 보스 체력바를 지정해 주세요."))

        preview_group = QGroupBox("판독 미리보기")
        preview_layout = QVBoxLayout(preview_group)
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(160)
        self.preview.setStyleSheet("background:palette(base); border:1px solid palette(mid);")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.status_label = QLabel("식별: —   HP: —")
        prev_row.addWidget(self.status_label, 1)
        preview_layout.addLayout(prev_row)
        cv.addWidget(preview_group)
        from .region_section import RegionSection
        self.region_section = RegionSection(region_body, unset_text="지정하면 보스 체력이 패턴 기준에 가까워질 때 알려줘요",
                                            title="영역 다시 지정 · 판독 확인")
        controls.addWidget(QLabel("판독 영역 · 보스 체력바"))
        controls.addWidget(self.region_section)

        # 화면 표시(명세 13.2): `패턴 경고 [잠금] [알림 미리보기]` / `패턴 목록 [잠금] [ ] 표시`.
        # 이름 칸 폭은 이 상자의 가장 긴 이름에 맞춰 두 줄 잠금 버튼이 같은 세로선에 선다.
        display = QGroupBox("화면 표시")
        display_layout = QVBoxLayout(display)
        warn_row = QHBoxLayout()
        from .settings_layout import lock_button, name_label
        NAMES = ("패턴 경고", "패턴 목록")
        warn_row.addWidget(name_label("패턴 경고", NAMES))
        self.warn_lock_btn = lock_button()
        self.warn_lock_btn.clicked.connect(self._toggle_warn_lock)
        warn_row.addWidget(self.warn_lock_btn)
        warn_row.addWidget(prev_btn)
        warn_row.addStretch()
        display_layout.addLayout(warn_row)
        self._sync_warn_btn()

        # 다음 패턴 목록(왼쪽에 남은 패턴 % 나열) — 준비(5% 전) 알림이 뜨면 그 %가 빠짐.
        self.show_upcoming = checkbox("표시")
        self.show_upcoming.setToolTip("남은 패턴의 체력 비율을 별도 목록으로 표시해요.")
        self.show_upcoming.setChecked(cfg["showUpcoming"])
        self.show_upcoming.toggled.connect(self._on_show_upcoming)
        up_row = QHBoxLayout()
        up_row.addWidget(name_label("패턴 목록", NAMES))
        self.upcoming_lock_btn = lock_button()
        self.upcoming_lock_btn.clicked.connect(self._toggle_upcoming_lock)
        up_row.addWidget(self.upcoming_lock_btn)
        up_row.addWidget(self.show_upcoming)  # 표시 여부 체크는 잠금 뒤로(명세 13.2)
        up_row.addStretch()
        display_layout.addLayout(up_row)
        controls.addWidget(display)
        self._sync_upcoming_btn()
        v.addWidget(self._controls)
        from .boss_bar_section import BossBarSection
        self.bar_section = BossBarSection(self)  # 제작자 테스트(보스바 오버레이 명세) — 다른 사용자는 숨김
        v.addWidget(self.bar_section)

        # 보스 HP바 수집(오독 제보용) — 로그인 사용자만.
        # 0.25.0(앱 문구 명세 10절): 사용 정보인 지원 보스 목록은 제목 있는 상자로, 진단은 그 아래 맨 끝
        self.supported_box = QGroupBox("지원 보스 · 알림 체력 %")
        QVBoxLayout(self.supported_box).addWidget(self._supported_label())
        v.addWidget(self.supported_box)
        self._collect_box = self._collect_group()
        from .settings_layout import disclosure
        self.diagnostics_btn = disclosure("진단 · 보스 HP바 수집",self._collect_box,v)
        self.diagnostics_btn.toggled.connect(self._apply_collect_gate)
        from .halo_capture_section import HaloCaptureSection
        self.halo_capture = HaloCaptureSection(watcher, self._grab_rect, self)
        v.addStretch(1)
        halo_page = QWidget()
        halo_layout = QVBoxLayout(halo_page)
        halo_layout.setContentsMargins(12,12,12,12)
        halo_layout.addWidget(self.halo_capture)
        halo_layout.addStretch(1)
        self.pattern_tabs = QTabWidget()
        for page, label in ((hp_page,"체력별 패턴"),(halo_page,"1분 헤일로")):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(page)
            self.pattern_tabs.addTab(scroll,label)
        root = QVBoxLayout(self)
        root.setContentsMargins(0,0,0,0)
        root.addWidget(self.pattern_tabs)
        self.halo_capture.access_changed.connect(self._set_halo_access)

        self._update_region_label()
        self._apply_collect_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(300)  # HP는 천천히 변함 — 300ms면 충분
        self._timer.timeout.connect(self._safe_tick)
        self._timer.start()

    def _safe_tick(self) -> None:
        """타이머 틱 가드 — 한 틱의 예외(판독·캡처 등)가 앱 전체를 죽이지 않게 흡수한다.
        (메인 스레드 QTimer 슬롯의 미처리 예외는 PySide6에서 프로세스를 abort시킬 수 있다.)"""
        if getattr(self, "_tick_job", None) is not None:
            return  # 지난 틱 계산이 아직 도는 중 — 쌓지 않고 건너뛴다(헤일로 문맥은 그 결과가 정한다)
        self.halo_capture.set_boss_context(None)
        try:
            self._apply_collect_gate()
            if not self._region:
                self._boss_present = False
                self._upcoming.hide()
                return
            self._tick()
        except Exception:  # noqa: BLE001 — 틱 격리(앱 생존 우선)
            import logging

            logging.getLogger("mabinogi_addon.capture").exception(
                "보스 탭 틱 실패 — 이 틱만 건너뜀(앱 유지)"
            )

    def _supported_label(self) -> QLabel:
        lines = []
        for b in self._bosses.values():
            if b.thresholds:
                pct = ", ".join(f"{t}%" for t in b.thresholds)
                lines.append(f"{b.name} — {pct}")
        lbl = hint_label("\n".join(lines))
        return lbl

    def _preview_warning(self) -> None:
        if self._paused:
            return
        # 실제 경고처럼 소리까지 같이 내 어떻게 보이고 들리는지 보여준다. 위치 조정(해제)
        # 중이면 샘플이 이미 떠 있으므로 소리만 난다(show_message는 고정 상태에서만).
        self._overlay.show_message("고목의 페타크 85% 패턴 준비  (미리보기)", 2500)
        self._play("pre")

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        # 보스 HP바는 넓은 가로 띠 → 자유 드래그로 이름~% 를 감싸게 그린다.
        self._selector = RegionSelector()
        from .region_registration import connect_selection
        connect_selection(self, self._selector, self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        # 영역은 '공유 키'(bossPattern.box)에만 저장한다 — _save()가 토글 때마다 box를
        # 통째로 덮어써 디버프 쪽 변경을 날리던 문제 방지(box는 여기서만 쓴다).
        config.save_boss_bar_region(x, y, w, h)
        self._afr.user_set("boss")  # 이번 실행 동안 사용자 지정이 이김
        self._region = {"x": x, "y": y, "w": w, "h": h}
        self._update_region_label()
        self._flash_region()
        self.bar_region_changed.emit()  # 디버프 3차가 새 영역으로 재시작하도록 알림

    def _flash_region(self) -> None:
        if not self._region:
            return
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()
        r = self._region
        self._highlight.flash(r["x"], r["y"], r["w"], r["h"], HIGHLIGHT_TITLE, HIGHLIGHT_SUB)

    def _update_region_label(self) -> None:
        self.clear_region_btn.setEnabled(self._region is not None)
        self.view_region_btn.setEnabled(self._region is not None)
        if self._region:
            r = self._region
            self.region_label.setText(f"등록됨 · {r['w']}×{r['h']}")
        else:
            self.region_label.setText("영역 미지정")
        section = getattr(self, "region_section", None)
        if section is not None:  # 영역 묶음(명세 11절): 지정 후 한 줄 요약 + 접힘, 막 지정했으면 펼쳐 판독 확인
            newly = bool(self._region) and not section.registered and getattr(self, "_region_ready", False)
            section.set_registered(bool(self._region), just_set=newly)
            self.region_label.setVisible(bool(self._region))
            if self._region and not section.summary_label.text():
                section.set_summary("✓ 영역 지정됨 · 식별: — · HP —")
            self._region_ready = True

    def reload_region(self) -> None:
        """공유 보스 HP바 영역을 다시 읽어 반영(디버프 탭에서 바꿨을 때 메인이 호출).

        300ms 타이머가 메모리의 self._region을 읽으므로, 탭을 안 열어도 즉시 새 영역을
        쓰게 하려면 이렇게 메모리를 갱신해야 한다(매 틱 파일 I/O는 피한다).
        """
        shared = config.load_boss_bar_region()
        if shared != self._afr.saved_of(self):  # 저장 영역끼리 비교(v2가 찾은 자리와 비교하지 않음)
            if shared is None:
                self._region_cleared()
                return
            self._region = shared
            self._update_region_label()

    def _region_cleared(self):
        self._afr.user_set("boss")  # 지정 해제(여기·디버프 탭) = 사용자 지정
        self.halo_capture.set_boss_context(None)
        self.halo_capture._stop_monitoring()
        self._region = None
        self._tracker = None
        self._cur_boss = None
        self._reset_hp()
        self._last_raw_hp = self._last_frame = self._last_saved_frame = None
        self._unidentified = 0
        self._bar_absent = self._UPCOMING_GONE_FRAMES + 1
        self._boss_present = False
        self._upcoming.set_items([])
        self._upcoming.hide()
        self._overlay.hide()
        self.preview.clear()
        self.status_label.setText("영역 지정 필요")
        self._update_region_label()
        self.bar_region_changed.emit()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reload_region()  # 공유 영역(디버프 3차에서 지정했을 수도) 반영(양방향 공유)

    def _save(self) -> None:
        # box는 저장하지 않는다 — 공유 영역이라 _on_selected에서 save_boss_bar_region으로만
        # 쓴다. 여기서 box를 넣으면 토글(enable 등)마다 디버프가 바꾼 영역을 덮어쓴다.
        config.save_boss_pattern(
            {
                "showUpcoming": self.show_upcoming.isChecked(),
                "upcomingLocked": self._upcoming.locked,
                "warnLocked": self._overlay.locked,
            }
        )

    # ---- 경고 위치 ----
    def _place_warn_default(self) -> None:
        """기본 위치: 화면 상단 중앙(기존 경고 위치와 비슷하게)."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.geometry()
        self._overlay._relayout()  # 샘플 크기로 폭 확정 후 중앙 정렬
        x = int((g.width() - self._overlay.width()) / 2)
        self._overlay.move(max(0, x), int(g.height() * 0.14))

    def _sync_warn_btn(self) -> None:
        self.warn_lock_btn.setChecked(self._overlay.locked)
        set_lock_text(self.warn_lock_btn, self._overlay.locked)

    def _toggle_warn_lock(self) -> None:
        self._overlay.set_locked(not self._overlay.locked)
        self._sync_warn_btn()
        self._save()

    def _on_warn_moved(self) -> None:
        pos = self._overlay.pos()
        config.save_boss_pattern({"warnPos": {"x": pos.x(), "y": pos.y()}})

    # ---- 다음 패턴 목록 ----
    def _place_upcoming_default(self) -> None:
        """기본 위치: 화면 정중앙에서 왼쪽 1/4 지점, 세로 중간 위쪽."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.geometry()
        self._upcoming.move(int(g.width() * 0.25), int(g.height() * 0.40))

    def _sync_upcoming_btn(self) -> None:
        self.upcoming_lock_btn.setChecked(self._upcoming.locked)
        set_lock_text(self.upcoming_lock_btn, self._upcoming.locked)

    def _on_show_upcoming(self, checked: bool) -> None:
        self._save()
        if not checked:
            self._upcoming.hide()

    def _toggle_upcoming_lock(self) -> None:
        self._upcoming.set_locked(not self._upcoming.locked)
        self._sync_upcoming_btn()
        self._save()

    def _on_upcoming_moved(self) -> None:
        pos = self._upcoming.pos()
        config.save_boss_pattern({"upcomingPos": {"x": pos.x(), "y": pos.y()}})

    def _update_upcoming(self, hp: int | None) -> None:
        """남은 패턴 목록을 오버레이에 반영.
        - 해제(이동) 상태: 위치 지정용으로 항상 보인다(비면 샘플).
        - 고정 상태: 보스가 **최근에** 식별됐고 남은 패턴이 있을 때만 보인다.
          트래커·HP는 긴 패턴을 버티려 _GONE_FRAMES(~18초)까지 유지되지만, 목록까지
          그만큼 남으면 보스가 떠난 뒤에도 '다가오는 %'가 한참 떠 있다(#4). 그래서
          목록은 보스가 화면에서 사라지면(_UPCOMING_GONE_FRAMES) 금방 감춘다."""
        if self._paused or not self.show_upcoming.isChecked():
            self._upcoming.hide()
            return
        if not self._upcoming.locked:
            # 위치 조정 중 — 항상 보여준다(비면 샘플).
            items = self._tracker.upcoming(hp) if self._tracker is not None else []
            self._upcoming.set_items(items)
            self._upcoming.show()
            overlay_capture.raise_overlay(self._upcoming)  # 커서 창은 다시 그 위로(0.38.1)
            return
        # 고정: 보스가 최근 식별됐을 때만(짧은 유예로 전투 중 1~2프레임 미식별은 버팀).
        recent = self._unidentified <= self._UPCOMING_GONE_FRAMES
        items = (
            self._tracker.upcoming(hp)
            if (self._tracker is not None and recent)
            else []
        )
        self._upcoming.set_items(items)
        if items:
            self._upcoming.show()
            overlay_capture.raise_overlay(self._upcoming)  # 커서 창은 다시 그 위로(0.38.1)
        else:
            self._upcoming.hide()

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        active = self._watcher.is_game_active() or self._watcher.is_self_active()
        if not self._region or not active:
            self.halo_capture.set_boss_context(None)
            self._boss_present = False  # 게임 비활성 → '보스전 아님'(저체력 알림 게이트)
            self._upcoming.hide()
            return
        if getattr(self, "_tick_job", None) is not None:
            return
        from .dpi import to_physical

        area = to_physical(self._grab_region())
        presence = self._presence_wanted()
        ext = None
        if self._bar_overlay_on():
            # 보스바 오버레이: 영역을 위로 약 45px(한 칸 위 보스바 확인)·아래로 6px(띠 높이 재기) 늘린 사각형 하나로 찍는다(명세 3절-3·4)
            up = max(0, min(self.BAR_EXT_UP, area[1]))
            ext = (up, self.BAR_EXT_DOWN)
            area = (area[0], area[1] - up, area[2], area[3] + up + self.BAR_EXT_DOWN)
        if presence and self._bar_absent > self._UPCOMING_GONE_FRAMES:
            # 보스바 확인(이름 글자 + % 판독)은 사전 판정을 통과하면 1회 평균 80ms(최대 150ms, 게임 화면 525곳 측정 — 61% 통과).
            # 바가 이미 안 보이는 동안에는 BAR_CHECK_EVERY틱에 한 번만(약 0.9초 — 저체력 알림 게이트 반응은 1초 안).
            # 바가 보이거나 유예 중(깜빡임)일 때는 매 틱 확인 — '없음'으로 확정된 뒤에만 띄엄띄엄.
            self._bar_skip = (getattr(self, "_bar_skip", 0) + 1) % self.BAR_CHECK_EVERY
            presence = self._bar_skip == 0
        from .capture_guard import own_window_over
        # 우리 일반 창(메인 창 등)이 보스 영역을 덮으면 캡처 순간 제외가 필요하다 — 창 조작은 화면 스레드 전용이라
        # 이때만 예전처럼 화면 스레드에서(오버레이는 상시 캡처 제외라 해당 없음). 도르카와 같은 기준.
        guarded = own_window_over(area)
        grab = self._grab_rect if (guarded or self.INLINE_JOBS) else self._grab_worker
        self._run_job(lambda: self._compute_tick(area, grab, presence, ext), self._apply_tick, inline=guarded)

    @perf_meter.timed("보스")  # 기능별 처리 시간 — 계산(작업 스레드)과 반영(화면)을 따로 센다
    def _compute_tick(self, area, grab, presence, ext=None) -> dict:
        """작업 스레드: 캡처 → 이름 식별 → (식별되면) HP 판독 → (필요하면) 보스바 확인. 위젯·상태는 건드리지 않는다."""
        steps: dict[str, float] = {}

        def timed(name, fn, *args, **kwargs):
            started = perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                steps[name] = steps.get(name, 0.0) + (perf_counter() - started) * 1000

        out = dict(frame=None, boss_id=None, raw_hp=None, bar=None, steps=steps,
                   thread="화면" if threading.current_thread() is threading.main_thread() else "작업")
        self._raw_ms = None
        frame = timed("캡처", grab, *area)
        raw = self._raw_ms
        if raw is not None and grab == self._grab_rect:  # 화면 스레드 캡처: 우리 창 빼기(CaptureGuard)와 실제 캡처를 나눠 본다
            steps["CaptureGuard"] = max(0.0, steps["캡처"] - raw)
            steps["캡처"] = raw
        if frame is None:
            return out
        full = frame
        if ext is not None:  # 늘린 캡처 → 원래 영역만 잘라 기존 판독은 그대로
            up, down = ext
            frame = full[up:full.shape[0] - down]
            if frame.shape[0] == 0:
                return out
        out["frame"] = frame
        if ext is not None:
            out["full"], out["area"] = full, tuple(int(v) for v in area)  # 수집: 오버레이가 실제로 읽은 늘린 사각형
        w = frame.shape[1]
        name_reg = frame[:, : int(w * 0.60)]  # 왼쪽=이름
        pct_reg = frame[:, int(w * 0.58) :]  # 오른쪽=HP%(가운데 빈 띠는 글자 없음)
        boss_id = timed("이름 식별", identify, name_reg, self._name_templates, variants=self._name_variants)
        out["boss_id"] = boss_id
        if boss_id is not None and ext is not None:  # 오버레이: 같은 정수 + 소수 두 자리(표시용)
            out["raw_hp"], out["raw_frac"] = timed("HP 판독", read_percent_frac, pct_reg)
        elif boss_id is not None:
            out["raw_hp"] = timed("HP 판독", read_percent, pct_reg)
        elif presence and ext is not None:  # 오버레이: 존재 확인에서 읽은 %(+소수)도 받는다(추가 판독 없음)
            reading = timed("보스바 확인", self._boss_bar_reading, frame)
            out["bar_pct"], out["bar_frac"] = reading if reading is not None else (None, None)
            out["bar"] = out["bar_pct"] is not None
        elif presence:  # 미등록 보스 존재 확인(이름 글자 + % 판독 — 바가 보일 때만 ~36ms)
            out["bar"] = timed("보스바 확인", self._boss_bar_visible, frame)
        if ext is not None:
            out["overlay"] = timed("오버레이", self._overlay_reading, full, ext[0], frame.shape[0], out)
        return out

    BAR_EXT_UP, BAR_EXT_DOWN = 45, 6
    LOW_HP_SKIP_HEIGHT = 20  # 이 % 이하는 띠 높이 규칙을 쓰지 않는다
    BAR_PITCH = 39  # 바 한 칸 간격(펠롬 보스바 ↔ 어둠의 에르그, 해상도 무관 px) — 보호막 기믹 실화면 확인 전 추정값

    def _overlay_reading(self, full, up, h, out) -> dict:
        """작업 스레드: 오버레이에 그릴 값. 틀린 숫자를 그리지 않게 높이·한 칸 위 보스바를 확인한다(명세 3절).
        {"value": int|None, "boss": 등록 보스 id|None, "seen": 바가 보였나}"""
        from ..detect.boss_bar import BAR_BAND_MAX, BAR_BAND_MIN, bar_band_height, has_wide_bar_row
        from ..detect.boss_hp_reader import low_hp_bar_hint
        boss_id, value = out["boss_id"], out["raw_hp"] if out["boss_id"] is not None else out.get("bar_pct")
        frac = out.get("raw_frac") if out["boss_id"] is not None else out.get("bar_frac")
        raw, rule = value, None
        frame = out["frame"]
        # 영역에 바 모양이 있으면(보스로 확인 안 된 바 — 에르그·보호막 등 포함) 한 칸 위까지 본다
        seen = boss_id is not None or bool(out.get("bar")) or has_wide_bar_row(frame) or low_hp_bar_hint(frame)
        if not seen:
            return {"value": None, "boss": None, "seen": False, "raw": None, "rule": None}
        band = bar_band_height(full, up + h // 2)
        # 저HP(≤ 20% 또는 저HP 단서)는 채움이 짧아 띠 높이가 낮게 재진다(7.70%에서 18px, 11-05 수집) → 높이 규칙을 건너뛴다
        low_hp = (value is not None and value <= self.LOW_HP_SKIP_HEIGHT) or low_hp_bar_hint(frame)
        if band is not None and not low_hp and not BAR_BAND_MIN <= band <= BAR_BAND_MAX:
            if value is not None:
                rule = "height"
            value = frac = None  # 얇은 일반 체력바(또는 바가 아닌 띠) — 보스 값으로 쓰지 않는다
        # 등록 영역 % — 두 줄 구간에선 바가 영역보다 몇 px 아래로 그려져 숫자 띠가 잘린다('100.00'을 10으로, QA d52528a).
        # 확신 없는 판독이면 기억한 세로 위치·후보 위치로 다시 읽어 더 확신 있는 값을 쓴다(정상 화면은 판독 1번 그대로).
        if value is not None and rule is None and not self._confident(value, out):
            better = self._read_row(full, up, h, "low")
            if better is not None:
                value, frac = better
        top = up - self.BAR_PITCH
        if top >= 0:  # 한 칸 위에도 보스바가 있으면 위가 보스(기믹으로 보스바가 밀려 올라간 경우)
            upper = self._upper_bar(full, top, h)
            if upper is not None:
                above_boss, reading = upper
                boss_id = above_boss  # 위 줄 이름(등록 보스가 아니면 None — 보스 이름 대신 "보스")
                if reading is not None:
                    value, frac, rule = reading[0], reading[1], "upper"
                else:
                    # 위 줄이 보스바인데 %를 못 읽음(노란 바탕 등) — 아래 줄(다른 바) 값으로 되돌아가지 않는다:
                    # 이번 판독은 비우고 표시는 직전 값 흐리게(보스바 오버레이 값 규칙의 stale)
                    value, frac, rule = None, None, "upper_unread"
        return {"value": value, "frac": frac if value is not None else None, "boss": boss_id, "seen": True,
                "raw": raw, "rule": rule, "band": band}

    @perf_meter.timed("보스")
    def _apply_tick(self, out) -> None:
        """화면 스레드: 작업 스레드 결과를 순서대로 반영(상태 머신·표시·경고). 예전 _tick 뒷부분 그대로."""
        if out is None:
            self.halo_capture.set_boss_context(None)
            return
        started = perf_counter()
        ui: dict[str, float] = {}
        try:
            self._apply_frame(out, ui)
        finally:
            ui["반영"] = max(0.0, (perf_counter() - started) * 1000 - sum(ui.values()))
            self._log_slow(out["steps"], ui, out.get("thread", "작업"))

    def _apply_frame(self, out, ui) -> None:
        def timed(name, fn, *args):
            started = perf_counter()
            try:
                return fn(*args)
            finally:
                ui[name] = ui.get(name, 0.0) + (perf_counter() - started) * 1000

        frame = out["frame"]
        if frame is None:
            timed("헤일로", self.halo_capture.set_boss_context, None)
            return
        timed("미리보기", self._show_preview, frame)
        self._last_frame = frame
        self._apply_collect_gate()
        boss_id = out["boss_id"]
        timed("헤일로", self.halo_capture.set_boss_context, boss_id)

        # 보스 식별/소멸 관리. **HP 판독·경고는 보스가 '이번 프레임' 식별됐을 때만**
        # 처리한다 — 보스가 없으면 영역이 길바닥/UI라 HP가 garbage로 읽히는데, 그걸
        # 트래커에 넣으면 옛 보스 경고가 거짓 발동한다(보스 없는데 40% 알림 버그).
        #  - 식별되면 그 보스 트래커로. 깜빡임으로 1~수 프레임 미식별돼도 _stable_hp는
        #    유지되고, 이름이 한참(=_GONE_FRAMES) 안 읽히면 '사라짐'으로 보고 해제.
        if boss_id is not None:
            self._unidentified = 0
            if boss_id != self._cur_boss:
                self._cur_boss = boss_id
                self._tracker = (
                    make_tracker(self._bosses[boss_id])
                    if boss_id in self._bosses
                    else None
                )
                self._reset_hp()  # 새 보스 → HP 상태 초기화
            self._last_raw_hp = out["raw_hp"]  # 원판독(수집 태그·진단용)
            self._accept_hp(self._last_raw_hp)  # 식별된 프레임만 HP 반영
        else:
            self._last_raw_hp = None
            self._unidentified += 1
            if self._unidentified > self._GONE_FRAMES and self._tracker is not None:
                self._cur_boss = None
                self._tracker = None
                self._reset_hp()
        hp = self._stable_hp

        # 보스바 존재 신호(체력바 저체력 알림 게이트용). 등록 보스는 식별로 당연히 존재,
        # 미등록 보스는 영역이 '보스바'로 검증(이름 글자+% 판독)되면 존재로 본다. 깜빡임·
        # 가려짐은 ~2초(_UPCOMING_GONE_FRAMES) 유예로 흡수한다. 아무도 이 신호를 안 쓰면
        # (저체력 경고 전부 꺼짐) 비싼 검증을 돌리지 않고 건너뛴다(UI 스레드 부하 절감).
        if self._presence_wanted():
            if boss_id is not None or bool(out["bar"]):
                self._bar_absent = 0
            else:
                self._bar_absent += 1
            self._boss_present = self._bar_absent <= self._UPCOMING_GONE_FRAMES
        else:
            self._boss_present = False

        # 수집 모드: 로그인 사용자가 켠 동안, 보스가 식별된 상태에서 바가 눈에 띄게
        # 바뀌면 자동 저장(오독 프레임 제보). 보스 없는 프레임은 길바닥이라 제외.
        seen = boss_id is not None or bool(out.get("overlay", {}).get("seen"))  # 오버레이 중이면 미등록 보스도
        if boss_id is not None or bool(out["bar"]):
            self._afr.report("boss", True)  # 자동 찾기 v2(보스바는 나타나면 찾기 — 없을 땐 알리지 않음)
        if (
            self.collect_chk.isChecked()
            and self._diagnostics_allowed()
            and seen
            and self._frame_changed(frame)
            and self._auto_room()
        ):
            self._write_shot(out.get("full", frame), auto=True)
            self._last_saved_frame = frame

        # 실시간 상태 표시(현재 프레임 기준)
        if boss_id in self._bosses:
            name = self._bosses[boss_id].name
        elif boss_id is not None:
            name = "미등록 보스"
        else:
            name = "미식별"
        hp_txt = f"{hp}%" if hp is not None else "—"
        self.status_label.setText(f"식별: {name}   HP: {hp_txt}")
        self.region_section.set_summary(f"✓ 영역 지정됨 · 식별: {name} · HP {hp_txt}")

        # 트래커 상태 갱신: 보스가 이번 프레임 식별됐을 때만(garbage 발동 차단).
        # 관측은 '경고 사용'과 무관하게 돌려 '다음 패턴 목록'도 최신으로 유지하고,
        # 중앙 경고·소리만 '경고 사용'일 때 낸다.
        alerts = []
        if boss_id is not None and self._tracker is not None and hp is not None:
            alerts = self._tracker.observe(hp)
        pattern_on = self._afr.use_on("boss")  # v2 사용 꺼짐: 보스바는 다른 기능 때문에 읽어도 패턴 알림·목록은 멈춤
        if self._region and not self._paused and pattern_on:
            for alert in alerts:
                self._overlay.show_message(alert.text, 3000)
                self._play(alert.sound)

        if pattern_on:
            self._update_upcoming(hp)
        else:
            self._upcoming.hide()
        if self._bar_overlay_sink is not None and "overlay" in out:
            shown = timed("오버레이", self._bar_overlay_sink, out["overlay"])
            if shown is not None:
                timed("수집", self._collect_overlay, out, shown)

    def _run_job(self, work, done, inline=False) -> None:
        """work()는 작업 스레드(테스트·창이 덮을 때는 바로), done(결과)는 화면 스레드. 한 번에 하나만."""
        if self.INLINE_JOBS or inline:
            done(work())
            return
        if getattr(self, "_shutting_down", False):
            return
        executor = self.__dict__.get("_executor")
        if executor is None:
            from concurrent.futures import ThreadPoolExecutor
            executor = self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="boss-job")
            self._job_ready.connect(self._deliver_job)
        token = self._tick_job = object()

        def deliver(result):
            if self._tick_job is token:
                self._tick_job = None
            if not getattr(self, "_shutting_down", False):
                done(result)

        def run():
            try:
                result = work()
            except Exception:  # noqa: BLE001 — 틱 격리(앱 생존 우선)
                import logging
                logging.getLogger("mabinogi_addon.capture").exception("보스 탭 틱 실패(작업 스레드) — 이 틱만 건너뜀")
                result = None
            self._job_ready.emit(lambda: deliver(result))
        executor.submit(run)

    def _deliver_job(self, deliver) -> None:
        try:
            deliver()  # 화면 스레드
        except Exception:  # noqa: BLE001 — 틱 격리(앱 생존 우선)
            import logging
            logging.getLogger("mabinogi_addon.capture").exception("보스 탭 틱 반영 실패 — 이 틱만 건너뜀(앱 유지)")

    def _grab_worker(self, x: int, y: int, w: int, h: int):
        """작업 스레드 캡처 — mss는 스레드마다 따로(스레드 사이 공유 불가). 화면 스레드 것(_sct)과 별개."""
        import threading
        local = self.__dict__.setdefault("_sct_local", threading.local())
        try:
            sct = getattr(local, "sct", None)
            if sct is None:
                import mss
                sct = local.sct = mss.mss()
            shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3]
        except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 틱 건너뜀
            return None

    def _close_worker_mss(self) -> None:
        local = self.__dict__.get("_sct_local")
        sct = getattr(local, "sct", None) if local is not None else None
        if sct is not None:
            local.sct = None
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                pass

    def _log_slow(self, steps, ui=None, thread="작업") -> None:
        """틱(계산+화면 반영)이 SLOW_TICK_MS 넘으면 단계별 소요를 app.log에 — 분당 1번, 그 사이 느린 틱 횟수와 함께.
        예: 보스 틱 느림 52ms(지난 1분 느린 틱 12회): [계산·작업] 캡처 3ms · 이름 식별 2ms · 보스바 확인 43ms · [반영·화면] 미리보기 1ms · 헤일로 0ms · 반영 2ms
        [계산·화면]이면 우리 창이 보스 영역을 덮어 화면 스레드에서 읽은 틱(CaptureGuard 포함) — 이때는 꼬리를 멈춘다."""
        ui = ui or {}
        total = sum(steps.values()) + sum(ui.values())
        if total < self.SLOW_TICK_MS:
            return
        self._slow_count = getattr(self, "_slow_count", 0) + 1
        now = monotonic()
        if now < getattr(self, "_slow_logged_until", 0.0):
            return
        self._slow_logged_until = now + 60.0
        count, self._slow_count = self._slow_count, 0
        import logging
        work = " · ".join(f"{name} {ms:.0f}ms" for name, ms in steps.items())
        shown = " · ".join(f"{name} {ms:.0f}ms" for name, ms in ui.items())
        logging.getLogger(__name__).info("보스 틱 느림 %.0fms(지난 1분 느린 틱 %d회): [계산·%s] %s · [반영·화면] %s",
                                         total, count, thread, work or "-", shown or "-")

    ROW_OFFSETS = (0, 5, -5, 3, -3)  # 두 줄 구간: 바가 등록 영역보다 5px 아래(고목의 페타크 11-06 실측)
    ROW_EXPLORE_EVERY = 1.0  # 확신 없는 줄의 다른 세로 위치는 1초에 한 번까지만(판독 1번 25~70ms)

    def _confident(self, value, out) -> bool:
        """등록 영역 판독이 확신인지(모든 자리 강한 점수) — 작업 스레드 판독을 다시 하지 않도록 같은 판독기로 한 번만 확인."""
        from ..detect.boss_hp_reader import read_percent_scored
        frame = out.get("frame")
        if frame is None:
            return True
        got, key = read_percent_scored(frame)
        return got == value and key[0] == len(str(value))

    def _read_row(self, full, top, h, row: str):
        """full 안 [top, top+h) 줄의 % — 기억한 세로 위치부터, 확신 없으면 다른 위치(1초에 한 번). (정수, 소수|None) 또는 None."""
        from ..detect.boss_hp_reader import read_percent_scored
        offsets = self.__dict__.setdefault("_row_offset", {})
        explore_at = self.__dict__.setdefault("_row_explore_at", {})
        first = offsets.get(row, 0)
        order = [first] + [o for o in self.ROW_OFFSETS if o != first]
        now = monotonic()
        explore = now >= explore_at.get(row, 0.0)
        best = None
        for i, off in enumerate(order):
            if i and not explore:
                break
            y = top + off
            if y < 0 or y + h > full.shape[0]:
                continue
            crop = full[y:y + h]
            got, key = read_percent_scored(crop)
            if got is not None and (best is None or key > best[0]):
                best = (key, got, off, crop)
            if got is not None and key[0] == len(str(got)):
                break  # 확신 — 더 볼 필요 없음
            if i:
                explore_at[row] = now + self.ROW_EXPLORE_EVERY
        if best is None:
            return None
        key, got, off, crop = best
        offsets[row] = off
        w = crop.shape[1]
        whole, frac = read_percent_frac(crop[:, int(w * 0.58):])
        return got, (frac if whole == got else None)

    def _upper_bar(self, full, top, h):
        """한 칸 위 줄이 보스바면 (등록 보스 id|None, (정수, 소수)|None). 보스바가 아니면 None.
        - 등록 보스 이름이 보이면(세로 ±5px까지) 보스바 — %를 못 읽어도 돌려준다(아래 줄 값으로 되돌아가지 않게, QA d52528a).
        - 등록 보스가 아니면 예전처럼 %·이름 글자 검증이 통과할 때만(디버프 아이콘 시간 글자·풍경을 보스바로 보지 않게)."""
        from ..detect.boss_bar import has_wide_bar_row
        from ..detect.boss_hp_reader import low_hp_bar_hint
        tried = []
        for off in (self.__dict__.get("_row_offset", {}).get("up", 0), 0, 5, -5):
            y = top + off
            if off in tried or y < 0 or y + h > full.shape[0]:
                continue
            tried.append(off)
            above = full[y:y + h]
            if not (has_wide_bar_row(above) or low_hp_bar_hint(above)):
                continue
            w = above.shape[1]
            boss = identify(above[:, : int(w * 0.60)], self._name_templates, variants=self._name_variants)
            if boss is not None:
                return boss, self._read_row(full, top, h, "up")
        reading = self._boss_bar_reading(full[top:top + h])  # 미등록 보스: 예전 기준(% + 이름 글자 검증)
        if reading is not None:
            return None, reading
        return None

    def _boss_bar_reading(self, frame):
        """보스바면 (정수 %, 소수 두 자리|None), 아니면 None — 보스바 오버레이(미등록 보스 값·소수). 기준은 _boss_bar_visible과 같다."""
        from ..detect.boss_bar import has_wide_bar_row, make_validator
        from ..detect.boss_hp_reader import low_hp_bar_hint
        if frame is None or frame.size == 0 or not (has_wide_bar_row(frame) or low_hp_bar_hint(frame)):
            return None
        if getattr(self, "_bar_reading", None) is None:
            self._bar_reading = make_validator(with_frac=True)
        try:
            return self._bar_reading(frame)
        except Exception:  # noqa: BLE001
            return None

    def _boss_bar_percent(self, frame) -> int | None:
        """보스바면 존재 확인에서 읽은 정수 %(보스바 오버레이 — 미등록 보스 값), 아니면 None. 기준은 _boss_bar_visible과 같다."""
        from ..detect.boss_bar import has_wide_bar_row, make_validator
        from ..detect.boss_hp_reader import low_hp_bar_hint
        if frame is None or frame.size == 0 or not (has_wide_bar_row(frame) or low_hp_bar_hint(frame)):
            return None
        if getattr(self, "_bar_percent", None) is None:
            self._bar_percent = make_validator(return_percent=True)
        try:
            return self._bar_percent(frame)
        except Exception:  # noqa: BLE001
            return None

    def _boss_bar_visible(self, frame) -> bool:
        """이 프레임의 보스 영역이 '보스 체력바'로 검증되는지(등록 여부 무관).

        자동 찾기와 같은 기준(이름 글자 + % 판독)으로 본다 → 미등록 보스도 존재로 인식.
        검증기는 상태가 없어 캐시해 재사용한다."""
        from ..detect.boss_bar import has_wide_bar_row, make_validator
        from ..detect.boss_hp_reader import low_hp_bar_hint

        # 값싼 사전 판정(~1ms): 넓은 가로 연속(고HP 바 가장자리) '또는' 숫자 영역 flooded
        # (저HP 빨간 바 — 채움이 짧아 가로 연속이 없지만 숫자 영역이 회색으로 꽉 참)가
        # 아니면 보스바 아님 → 즉시 False. 평상시 프레임마다 비싼 make_validator(~36ms)를
        # 안 돈다. 저HP 보스 막바지(≤13%)를 걸러 저체력 경고가 꺼지던 문제를 flood OR로 해결.
        # 0.42.0: 저HP 단서는 flooded만이 아니라 흰 숫자 + 빨간 채움까지(회색 풍경 오통과 100% → 2.3%).
        if not (has_wide_bar_row(frame) or low_hp_bar_hint(frame)):
            return False
        if self._bar_validate is None:
            self._bar_validate = make_validator()
        try:
            return bool(self._bar_validate(frame))
        except Exception:  # noqa: BLE001 — 존재 신호라 실패해도 '없음'으로
            return False

    def is_boss_present(self) -> bool:
        """보스 체력바가 '지금' 화면에 떠 있는지(등록/미등록 무관, ~2초 유예).

        다른 탭(체력바 저체력 알림)이 '보스전 중일 때만' 울리도록 공유하는 신호다."""
        return self._boss_present

    def has_region(self) -> bool:
        """보스 체력바 영역이 등록돼 있는지(블랙박스 전투 녹화의 전제)."""
        return bool(self._region)

    def _presence_wanted(self) -> bool:
        return self._presence_wanted_fn is None or bool(self._presence_wanted_fn()) or self._bar_overlay_on()

    def _bar_overlay_on(self) -> bool:
        return self._bar_overlay_wanted is not None and bool(self._bar_overlay_wanted())

    def set_bar_overlay(self, wanted_fn, sink) -> None:
        """보스바 오버레이 연결: wanted_fn()이 True인 동안 판독을 유지(존재 확인 포함)하고, 틱마다 sink(값)를 화면 스레드에서 부른다."""
        self._bar_overlay_wanted, self._bar_overlay_sink = wanted_fn, sink

    def set_presence_consumer(self, wanted_fn) -> None:
        """'존재 신호가 지금 필요한가'를 알려줄 콜백을 연결한다(저체력 경고가 하나라도
        켜져 있을 때 True). 아무도 안 쓰면 매 틱 비싼 검증을 건너뛴다."""
        self._presence_wanted_fn = wanted_fn

    # 큰 점프(진입 애니메이션·오판독)와 완만한 감소를 구분해 확정.
    _SMALL_STEP = 12  # 이 이하 변화면 '완만' (2연속으로 확정)
    _CONFIRM_SMALL = 2
    _CONFIRM_JUMP = 3  # 큰 점프·첫 확정은 3연속 필요(글리치 차단)
    # 틱 300ms 기준. 보스 바는 '패턴 중'에도 사라지므로, 패턴이 길어도 잠금이
    # 유지되게 넉넉히 둔다. 이보다 오래 미식별이면 전투 종료로 보고 트래커 해제.
    _GONE_FRAMES = 60  # ~18초 (트래커 잠금 유지 — 긴 패턴 중 바가 사라져도 버팀)
    # '다음 패턴 목록'은 보스가 화면에서 사라지면 금방 감춘다. 트래커는 _GONE_FRAMES까지
    # 살아 있지만 목록까지 그만큼 떠 있으면 보스가 떠난 뒤 한참 남는다(#4). ~2초로 짧게.
    _UPCOMING_GONE_FRAMES = 6  # ~1.8초 (틱 300ms)
    BAR_CHECK_EVERY = 3  # 바가 안 보이는 동안 보스바 확인 간격(틱)

    # ---- 보스 HP바 수집(오독 제보용) ----
    def _collect_group(self) -> QGroupBox:
        box = QGroupBox("보스 HP바 수집 (오독 제보용)")
        g = QVBoxLayout(box)
        g.addWidget(hint_label(
            "'수집 모드'를 켜면 보스 HP바 영역이 바뀔 때마다 자동 저장돼요(보스별로).\n"
            "실제와 다른 %가 뜰 때(예: 48%인데 30% 알림)를 모아 보내주시면 오독 원인을 잡아요.\n"
            "보스바 오버레이를 켜 두면 미등록 보스·한 칸 위까지 찍고, 못 읽음·급상승·급하락·위 칸 전환·높이 제외 순간을 이유와 함께 저장해요"
            f"(한 번 실행에 {self.AUTO_LIMIT}장까지). 스냅샷 저장은 최근 약 3초 {self.RECENT_SHOTS}장을 한 번에 저장해요."
        ))
        row = QHBoxLayout()
        self.snap_btn = QPushButton("스냅샷 저장")
        self.snap_btn.clicked.connect(self._save_snapshot)
        row.addWidget(self.snap_btn)
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_dir_btn.clicked.connect(lambda: paths.open_folder(self._shot_dir))
        row.addWidget(self.open_dir_btn)
        self.collect_chk = checkbox("수집 모드(바 바뀔 때 자동 저장)")
        row.addWidget(self.collect_chk, 1)
        g.addLayout(row)
        self.collect_label = CapturePathLabel()
        self._update_collect_label()
        g.addWidget(self.collect_label)
        return box

    @staticmethod
    def _diagnostics_allowed() -> bool:
        """수집·진단 구역은 제작자만(문의 일원화 6.3 — 일반·로그인 사용자는 문의하기가 유일한 입구)."""
        from .. import feature_access
        return feature_access.is_creator()

    def _apply_collect_gate(self) -> None:
        self._set_halo_access(self.halo_capture._allowed())
        box = getattr(self, "_collect_box", None)
        if box is not None:
            box.setVisible(self._diagnostics_allowed() and self.diagnostics_btn.isChecked())
            self.diagnostics_btn.setVisible(self._diagnostics_allowed())
        btn = getattr(self, "auto_find_btn", None)
        if btn is not None:
            btn.setVisible(True)  # 일반 기능의 자동 찾기는 비로그인 공개

    def _set_halo_access(self, allowed):
        if not allowed and self.pattern_tabs.currentIndex() == 1:
            self.pattern_tabs.setCurrentIndex(0)
        self.pattern_tabs.setTabVisible(1,allowed)

    def _on_auto_find(self) -> None:
        from .region_registration import generation, save_boxes, editing_allowed
        stamp = generation(self)
        """보스 체력바를 화면에서 자동 검출 → 민트 점선 미리보기 + 확인 후에만 저장."""
        from ..autofind_diagnostics import perform_autofind
        frame, ox, oy, box = perform_autofind("boss", capture_for_autofind)
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했어요.")
            return
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "보스 체력바를 찾지 못했어요.\n\n"
                "• 보스 체력바가 지금 화면에 노출돼 있나요? "
                "(보스전 중, 첫 노출·HP 높은 구간에서 시도하세요)\n"
                "• 하단 메뉴바가 최소화돼 있지 않나요?\n\n"
                "다시 시도하거나 '보스 영역 수정'으로 직접 지정하세요.",
            )
            return
        x, y, w, h = box
        # 전역 물리픽셀 → 논리좌표(저장 규칙; 배율 100%면 그대로).
        lx, ly, lw, lh = to_logical(x + ox, y + oy, w, h)
        strip = max(12, int(lh * 1.4))  # 디버프 띠 높이
        dy = max(0, ly - strip)
        # 디버프 영역 = 띠 + 보스바(dy ~ 바 아래). 바를 포함해야 사라짐 경고·2차(띠)가 동작.
        db = (lx, dy, lw, (ly + lh) - dy)
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()
        self._highlight.flash(
            db[0], db[1], db[2], db[3],
            "자동 찾기 결과",
            "보스 HP바 + 디버프(위) · 이 영역으로 지정할까요?",
            msec=4000,
        )
        ans = QMessageBox.question(
            self,
            "자동 찾기 — 확인",
            "민트 점선으로 표시한 영역으로 **보스 체력바 + 디버프 영역**을 지정할까요?\n\n"
            "'아니오'를 누르면 기존 설정이 그대로 유지돼요.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes or generation(self) != stamp or not editing_allowed(self):
            return
        if not save_boxes(self, {"boss": (lx, ly, lw, lh), "debuff": db}):
            return
        self._afr.user_set("boss")
        self._afr.user_set("debuff")
        self._region = {"x": lx, "y": ly, "w": lw, "h": lh}
        self._update_region_label()
        self.bar_region_changed.emit()  # 보스바 공유(패턴알림/3차)
        self.debuff_region_changed.emit()  # 디버프 추적 재시작(1·2차 포함)
        self._flash_region()

    def _update_collect_label(self) -> None:
        self.collect_label.setToolTip(str(self._shot_dir))
        self.collect_label.setText(
            f"저장 위치: {self._shot_dir}  ·  수집 {self._shot_count}장"
        )

    # ---- 보스바 오버레이 문제 순간 수집(보스바 오버레이 명세 6절) ----
    RECENT_SHOTS = 10   # 최근 약 3초(판독 10회분) — 스냅샷 버튼이 한 번에 저장
    AUTO_LIMIT = 200    # 한 번 실행에 자동 저장 상한

    def _collect_overlay(self, out, shown) -> None:
        """화면 스레드: 오버레이 판독 한 번을 최근 묶음에 넣고, 방어 규칙이 '시작된' 순간이면 자동 저장(수집 모드일 때)."""
        reading = out["overlay"]
        rule = reading.get("rule") or self.bar_section.value.rule
        started = rule if rule != getattr(self, "_last_rule", None) else None
        self._last_rule = rule
        record = {"frame": out.get("full", out["frame"]), "main": out["frame"], "area": out.get("area"), "boss": reading.get("boss") or shown.boss,
                  "raw": reading.get("raw"), "shown": shown.value, "stale": shown.stale, "rule": rule,
                  "band": reading.get("band"), "time": __import__("time").time()}
        recent = self.__dict__.setdefault("_recent", __import__("collections").deque(maxlen=self.RECENT_SHOTS))
        recent.append(record)
        if (started and self.collect_chk.isChecked() and self._diagnostics_allowed() and self._auto_room()):
            self._queue_shots([record], auto=True)

    def _auto_room(self) -> bool:
        if getattr(self, "_auto_saved", 0) < self.AUTO_LIMIT:
            return True
        self.collect_label.setText(f"자동 저장이 {self.AUTO_LIMIT}장에 닿아 멈췄어요(앱을 다시 켜면 다시 모아요) · 저장 위치: {self._shot_dir}")
        return False

    def _save_snapshot(self) -> None:
        recent = list(self.__dict__.get("_recent") or ())
        if recent and self.bar_section.wanted():  # 오버레이 중: 눈치챈 순간은 지나갔으니 최근 3초 묶음을 한 번에
            self._queue_shots(recent, auto=False)
            return
        if self._last_frame is None:
            self.collect_label.setText("저장할 캡처가 없어요 — 먼저 영역을 지정하세요")
            return
        self._write_shot(self._last_frame)

    def _write_shot(self, frame, auto: bool = False) -> None:
        self._queue_shots([{"frame": frame, "boss": self._cur_boss, "raw": self._last_raw_hp}], auto=auto)

    def _queue_shots(self, records, auto: bool) -> None:
        """파일 이름·번호는 화면 스레드에서 정하고, PNG·JSON 쓰기는 작업 스레드에서(화면 스레드 PNG 쓰기 금지)."""
        jobs = []
        for rec in records:
            boss = rec.get("boss") or "unknown"
            raw = rec.get("raw")
            name = f"{boss}_hp{raw:03d}" if raw is not None else f"{boss}_hpxxx"
            if "shown" in rec:  # 오버레이 판독: 표시값·이유 태그도 이름에
                name += f"_show{rec['shown']:03d}" if rec.get("shown") is not None else "_showxxx"
                if rec.get("rule"):
                    name += f"_{rec['rule']}"
            jobs.append((self._shot_dir / f"{name}_{self._shot_count:03d}.png", rec))
            self._shot_count += 1
            if auto:
                self._auto_saved = getattr(self, "_auto_saved", 0) + 1
        self._update_collect_label()

        def write():
            try:
                self._shot_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                return
            for path, rec in jobs:
                if image_io.imwrite(path, rec["frame"]) and "shown" in rec:
                    meta = {k: rec.get(k) for k in ("time", "boss", "raw", "shown", "stale", "rule", "band", "area")}
                    meta["score"] = self._shot_score(rec.get("main"))
                    try:
                        path.with_suffix(".json").write_text(__import__("json").dumps(meta, ensure_ascii=False), encoding="utf-8")
                    except OSError:
                        pass
        if self.INLINE_JOBS:
            write()
            return
        writer = self.__dict__.get("_shot_writer")
        if writer is None:
            from concurrent.futures import ThreadPoolExecutor
            writer = self._shot_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="boss-shot")
        writer.submit(write)

    @staticmethod
    def _shot_score(main):
        """원판독 점수(기본 경로 최저 자리 점수, 숫자 칸) — 저장 작업 스레드에서."""
        try:
            from ..detect.boss_hp_reader import main_path_score
            score = None if main is None else main_path_score(main[:, int(main.shape[1] * 0.58):])
            return None if score is None else round(float(score), 3)
        except Exception:  # noqa: BLE001
            return None

    def _frame_changed(self, frame, threshold: float = 4.0) -> bool:
        prev = self._last_saved_frame
        if prev is None or prev.shape != frame.shape:
            return True
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
        return float(diff.mean()) >= threshold

    def reset_for_new_game(self) -> None:
        """게임 종료·재시작(프로세스 기준): 보스·HP·패턴 진행·1분 헤일로 시계를 비우고 오버레이를 숨긴다. 영역은 유지."""
        self.halo_capture._stop_monitoring()
        self._tracker = None
        self._cur_boss = None
        self._reset_hp()
        self._last_raw_hp = None
        self._unidentified = 0
        self._bar_absent = self._UPCOMING_GONE_FRAMES + 1
        self._boss_present = False
        self._upcoming.set_items([])
        self._upcoming.hide()
        self._overlay.hide()
        self.bar_section.value.reset()

    def _reset_hp(self) -> None:
        self._stable_hp = None
        self._hp_cand = None
        self._hp_cand_n = 0

    def _accept_hp(self, raw: int | None) -> None:
        """판독값을 확정 HP(self._stable_hp)로 반영할지 결정. 못 읽은 프레임(None)은
        후보를 리셋하고 직전 확정값을 유지한다."""
        if raw is None:
            self._hp_cand = None
            self._hp_cand_n = 0
            return
        self._hp_cand_n = self._hp_cand_n + 1 if raw == self._hp_cand else 1
        self._hp_cand = raw
        gradual = (
            self._stable_hp is not None
            and abs(raw - self._stable_hp) <= self._SMALL_STEP
        )
        need = self._CONFIRM_SMALL if gradual else self._CONFIRM_JUMP
        if self._hp_cand_n >= need:
            self._stable_hp = raw

    def _grab_region(self) -> dict:
        """판독용 영역 — 저장된 박스의 세로 중심은 두고 높이만 바 높이로 정규화한다.

        손으로 잡은 박스가 바보다 크면(예 40px) read_percent가 글자 크기를 과하게 잡아
        46%를 4로 읽는다(2자리 '46' 점수↓ → 1자리 '4'가 이김). 자동 찾기와 같은 방식으로
        높이를 화면 높이 비율(≈0.0257)로 고정해 바 크기에 맞춘다. 화면 내용이 아니라
        화면 높이 기반 고정 계산이라 프레임마다 결과가 같아 판독이 흔들리지 않는다.
        """
        reg = self._region
        from PySide6.QtGui import QGuiApplication

        s = QGuiApplication.primaryScreen()
        sh = int(s.geometry().height()) if s is not None else 0
        if not sh:
            return reg
        # 영역은 논리좌표 — 바 높이는 물리 화면 높이로 정해지므로 배율(dpr)을 함께 넘긴다(0.30.1: 4K·배율 무관 37px)
        ratio = getattr(s, "devicePixelRatio", None)
        dpr = float(ratio() or 1.0) if callable(ratio) else 1.0
        x, y, w, h = normalize_box_height((reg["x"], reg["y"], reg["w"], reg["h"]), sh, dpr)
        return {"x": x, "y": y, "w": w, "h": h}

    def _grab_rect(self, x: int, y: int, w: int, h: int):
        """판독 캡처. 판독 영역에 겹친 우리 오버레이(단축바 묶음 등)는 캡처하는 동안만 빼서 찍는다(0.36.1 —
        도르카와 같은 방식). 헤일로 판독도 이 함수를 쓴다."""
        if not hasattr(self, "_capture_guard"):
            from .capture_guard import CaptureGuard
            self._capture_guard = CaptureGuard()
        return self._capture_guard.grab(self._grab_raw, x, y, w, h)

    def _grab_raw(self, x: int, y: int, w: int, h: int):
        started = perf_counter()
        try:
            return self._grab_raw_inner(x, y, w, h)
        finally:
            self._raw_ms = (perf_counter() - started) * 1000  # 보스 틱 로그: CaptureGuard와 실제 캡처 나누기

    def _grab_raw_inner(self, x: int, y: int, w: int, h: int):
        try:
            if self._sct is None:
                import mss

                self._sct = mss.mss()
            shot = self._sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )[:, :, :3]
        except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 틱 건너뜀
            return None

    def _show_preview(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        # 높이 38에 맞춘다. 0.31.2 이름 잘림은 1080 화면에서 28px 띠를 키워 716px가 된 것 — 37px 고정으로 약 542px.
        # (라벨 폭에 맞춰 줄이면 stretch 없는 라벨이 처음 폭 160에 갇혀 158×11이 됐다 — QA 퇴행, 되돌림)
        self.preview.setPixmap(
            QPixmap.fromImage(img).scaledToHeight(38, Qt.TransformationMode.FastTransformation)
        )

    def _play(self, stage: str) -> None:
        if self._paused:
            return
        from .notifier import SoundNotifier

        if self._notifier is None:
            self._notifier = SoundNotifier(
                {"pre": _PRE_SOUND, "near": _NEAR_SOUND}, volume=0.8
            )
        if not self._notifier.play(stage):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def set_paused(self, paused):
        self._paused = paused
        self.bar_section.set_paused(paused)
        self._overlay.set_paused(paused)
        self.halo_capture.set_paused(paused)
        if not paused and not self._overlay.locked and not getattr(self.window(),'_closing',False):
            self._overlay.set_locked(False)  # Restore placement sample, never a queued warning.
        if paused:
            self._upcoming.hide()
            if self._notifier is not None:
                self._notifier.stop()

    def shutdown(self) -> None:
        self._shutting_down = True
        writer = self.__dict__.pop("_shot_writer", None)
        if writer is not None:
            writer.shutdown(wait=True)  # 저장 중인 수집 파일은 끝까지 쓴다
        executor = self.__dict__.pop("_executor", None)
        if executor is not None:
            executor.submit(self._close_worker_mss)  # 작업 스레드의 mss는 그 스레드에서 닫는다
            executor.shutdown(wait=True)
        self._tick_job = None
        guard = getattr(self, "_capture_guard", None)
        if guard is not None:
            guard.restore()
        self.halo_capture.shutdown()
        self.bar_section.shutdown()
        self._timer.stop()
        self._upcoming.close()
        self._overlay.close()
