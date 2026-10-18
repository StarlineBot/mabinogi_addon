"""보스 패턴 경고 탭 (기획서 12).

보스 HP바 영역을 한 번 지정하면, 그 안에서 왼쪽=이름 / 오른쪽=HP%를 읽어:
- 실시간으로 '식별된 보스 + 현재 HP%'를 표시(판독이 잘 되는지 눈으로 확인용)
- HP%가 임계의 T+5(1차)/T+1(2차)를 하강 교차하면 화면 중앙 큰 글씨 경고 + 소리

패턴 데이터(보스 이름 템플릿 + 임계%)는 번들(assets/boss). 투아림 탭과 같은 영역·캡처
방식이다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import config, image_io, paths
from ..detect.boss_bar import (
    normalize_box_height,
)
from ..detect.boss_hp_reader import read_percent
from .dpi import to_logical
from .screen_grab import capture_for_autofind
from ..detect.boss_name_matcher import identify, load_name_templates, load_name_variants
from ..tracker.boss_catalog import load_bosses, make_tracker
from .pattern_overlay import PatternWarningOverlay
from .upcoming_overlay import UpcomingPatternsOverlay
from .widgets import CapturePathLabel, checkbox, hint_label, wrapping_row

_SOUND_DIR = paths.resource_dir() / "sounds"
_PRE_SOUND = _SOUND_DIR / "보스패턴 예고.mp3"
_NEAR_SOUND = _SOUND_DIR / "보스패턴 진입.mp3"

HIGHLIGHT_TITLE = "보스 HP바 영역"
HIGHLIGHT_SUB = "보스 이름 ~ HP% 가 다 들어오게"

# 기본 영역(2560×1440 기준, 하단 중앙 보스 HP바). 오른쪽 끝 = 바 오른쪽 끝.
# 다른 해상도면 '영역 수정'으로 바에 맞춘다(판독기가 박스 높이로 스케일 보정).
DEFAULT_BOX = {"x": 1017, "y": 1248, "w": 523, "h": 36}


class BossTab(QWidget):
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
        self._overlay = PatternWarningOverlay()
        self._overlay.moved.connect(self._on_warn_moved)
        self._notifier = None
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

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)

        title = QLabel("보스 패턴 알림")
        title.setStyleSheet("font-size:14px; font-weight:700;")
        v.addWidget(title)
        v.addWidget(
            hint_label(
                "보스 체력이 패턴 기준에 가까워지면 화면과 소리로 알립니다. "
                "보스 체력바가 보이는 상태에서 자동 찾기를 실행하세요."
            )
        )

        prev_btn = QPushButton("알림 미리보기")
        prev_btn.setToolTip("경고가 화면 어디에 어떻게 뜨는지 한 번 띄워 봅니다")
        prev_btn.clicked.connect(self._preview_warning)

        # 실제 컨트롤 묶음(항상 표시 — 로그인 불필요)
        self._controls = QWidget()
        cv = QVBoxLayout(self._controls)
        cv.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        cv.addWidget(QLabel("판독 영역 · 보스 체력바"))
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.setToolTip(
            "보스 HP바의 이름과 체력 비율이 들어오도록 지정합니다."
        )
        self.region_btn.clicked.connect(self._on_region)
        self.region_label = hint_label("")
        cv.addWidget(self.region_label)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        # 자동 찾기(🧪 Discord 베타) — 로그인 사용자만 보임. 보스 체력바를 화면에서 찾아
        # 디버프 영역(바로 위)까지 함께 지정. 저장은 반드시 확인 후에만.
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip(
            "보스 체력바(+디버프 영역)를 화면에서 자동으로 찾아 지정합니다 — Discord 베타"
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
        self.status_label.setStyleSheet("font-size:14px; font-weight:600;")
        prev_row.addWidget(self.status_label, 1)
        preview_layout.addLayout(prev_row)
        cv.addWidget(preview_group)

        cv.addWidget(
            hint_label("영역을 맞춘 뒤 위의 '식별'과 'HP'가 실제와 맞는지 먼저 확인하세요.")
        )

        # 경고 위치 이동/고정(다음 패턴 목록과 동일 구조).
        warn_row = QHBoxLayout()
        self.warn_lock_btn = QPushButton("경고 위치 잠금")
        self.warn_lock_btn.setCheckable(True)
        self.warn_lock_btn.clicked.connect(self._toggle_warn_lock)
        warn_row.addWidget(self.warn_lock_btn)
        warn_row.addWidget(prev_btn)
        warn_row.addStretch()
        self.warn_lock_hint = hint_label("")
        warning_group = QGroupBox("패턴 경고")
        warning_layout = QVBoxLayout(warning_group)
        warning_layout.addLayout(warn_row)
        warning_layout.addWidget(self.warn_lock_hint)
        cv.addWidget(warning_group)
        self._sync_warn_btn()

        # 다음 패턴 목록(왼쪽에 남은 패턴 % 나열) — 준비(5% 전) 알림이 뜨면 그 %가 빠짐.
        self.show_upcoming = checkbox("남은 패턴 목록 표시")
        self.show_upcoming.setToolTip("남은 패턴의 체력 비율을 별도 목록으로 표시합니다.")
        self.show_upcoming.setChecked(cfg["showUpcoming"])
        self.show_upcoming.toggled.connect(self._on_show_upcoming)
        upcoming_group = QGroupBox("남은 패턴 목록")
        upcoming_layout = QVBoxLayout(upcoming_group)
        upcoming_layout.addWidget(self.show_upcoming)
        up_row = QHBoxLayout()
        self.upcoming_lock_btn = QPushButton("목록 위치 잠금")
        self.upcoming_lock_btn.setCheckable(True)
        self.upcoming_lock_btn.clicked.connect(self._toggle_upcoming_lock)
        up_row.addWidget(self.upcoming_lock_btn)
        up_row.addStretch()
        self.upcoming_lock_hint = hint_label("")
        upcoming_layout.addLayout(up_row)
        upcoming_layout.addWidget(self.upcoming_lock_hint)
        cv.addWidget(upcoming_group)
        self._sync_upcoming_btn()
        v.addWidget(self._controls)

        # 보스 HP바 수집(오독 제보용) — 로그인 사용자만.
        self._collect_box = self._collect_group()
        from .settings_layout import disclosure
        self.diagnostics_btn = disclosure("진단 · 보스 HP바 수집",self._collect_box,v)
        self.diagnostics_btn.toggled.connect(self._apply_collect_gate)
        v.addWidget(self._supported_label())
        v.addStretch(1)

        self._update_region_label()
        self._apply_collect_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(300)  # HP는 천천히 변함 — 300ms면 충분
        self._timer.timeout.connect(self._safe_tick)
        self._timer.start()

    def _safe_tick(self) -> None:
        """타이머 틱 가드 — 한 틱의 예외(판독·캡처 등)가 앱 전체를 죽이지 않게 흡수한다.
        (메인 스레드 QTimer 슬롯의 미처리 예외는 PySide6에서 프로세스를 abort시킬 수 있다.)"""
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
        lines = ["지원 보스 & 알림 %:"]
        for b in self._bosses.values():
            if b.thresholds:
                pct = ", ".join(f"{t}%" for t in b.thresholds)
                lines.append(f"  • {b.name} — {pct}")
        lbl = hint_label("\n".join(lines))
        lbl.setStyleSheet("color:#9aa0aa; font-size:12px;")
        return lbl

    def _preview_warning(self) -> None:
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
        if self._region:
            r = self._region
            self.region_label.setText(f"등록됨 · {r['w']}×{r['h']}")
        else:
            self.region_label.setText("영역 미지정")

    def reload_region(self) -> None:
        """공유 보스 HP바 영역을 다시 읽어 반영(디버프 탭에서 바꿨을 때 메인이 호출).

        300ms 타이머가 메모리의 self._region을 읽으므로, 탭을 안 열어도 즉시 새 영역을
        쓰게 하려면 이렇게 메모리를 갱신해야 한다(매 틱 파일 I/O는 피한다).
        """
        shared = config.load_boss_bar_region()
        if shared != self._region:
            if shared is None:
                self._region_cleared()
                return
            self._region = shared
            self._update_region_label()

    def _region_cleared(self):
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
        self.warn_lock_btn.setText("경고 위치 잠금됨" if self._overlay.locked else "경고 위치 잠금")
        self.warn_lock_hint.setText("잠금됨 · 경고 창은 클릭을 통과합니다." if self._overlay.locked
                                   else "잠금 해제됨 · 경고 창을 드래그해 위치를 변경할 수 있습니다.")

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
        self.upcoming_lock_btn.setText("목록 위치 잠금됨" if self._upcoming.locked else "목록 위치 잠금")
        self.upcoming_lock_hint.setText("잠금됨 · 목록은 클릭을 통과합니다." if self._upcoming.locked
                                       else "잠금 해제됨 · 목록을 드래그해 위치를 변경할 수 있습니다.")

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
        if not self.show_upcoming.isChecked():
            self._upcoming.hide()
            return
        if not self._upcoming.locked:
            # 위치 조정 중 — 항상 보여준다(비면 샘플).
            items = self._tracker.upcoming(hp) if self._tracker is not None else []
            self._upcoming.set_items(items)
            self._upcoming.show()
            self._upcoming.raise_()
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
            self._upcoming.raise_()
        else:
            self._upcoming.hide()

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        active = self._watcher.is_game_active() or self._watcher.is_self_active()
        if not self._region or not active:
            self._boss_present = False  # 게임 비활성 → '보스전 아님'(저체력 알림 게이트)
            self._upcoming.hide()
            return
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._grab_region())
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            return
        self._show_preview(frame)
        self._last_frame = frame
        self._apply_collect_gate()

        w = frame.shape[1]
        name_reg = frame[:, : int(w * 0.60)]  # 왼쪽=이름
        pct_reg = frame[:, int(w * 0.58) :]  # 오른쪽=HP%(가운데 빈 띠는 글자 없음)
        boss_id = identify(name_reg, self._name_templates, variants=self._name_variants)

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
            self._last_raw_hp = read_percent(pct_reg)  # 원판독(수집 태그·진단용)
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
        if self._presence_wanted_fn is None or self._presence_wanted_fn():
            if boss_id is not None or self._boss_bar_visible(frame):
                self._bar_absent = 0
            else:
                self._bar_absent += 1
            self._boss_present = self._bar_absent <= self._UPCOMING_GONE_FRAMES
        else:
            self._boss_present = False

        # 수집 모드: 로그인 사용자가 켠 동안, 보스가 식별된 상태에서 바가 눈에 띄게
        # 바뀌면 자동 저장(오독 프레임 제보). 보스 없는 프레임은 길바닥이라 제외.
        if (
            self.collect_chk.isChecked()
            and self._logged_in()
            and boss_id is not None
            and self._frame_changed(frame)
        ):
            self._write_shot(frame)
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

        # 트래커 상태 갱신: 보스가 이번 프레임 식별됐을 때만(garbage 발동 차단).
        # 관측은 '경고 사용'과 무관하게 돌려 '다음 패턴 목록'도 최신으로 유지하고,
        # 중앙 경고·소리만 '경고 사용'일 때 낸다.
        alerts = []
        if boss_id is not None and self._tracker is not None and hp is not None:
            alerts = self._tracker.observe(hp)
        if self._region:
            for alert in alerts:
                self._overlay.show_message(alert.text, 3000)
                self._play(alert.sound)

        self._update_upcoming(hp)

    def _boss_bar_visible(self, frame) -> bool:
        """이 프레임의 보스 영역이 '보스 체력바'로 검증되는지(등록 여부 무관).

        자동 찾기와 같은 기준(이름 글자 + % 판독)으로 본다 → 미등록 보스도 존재로 인식.
        검증기는 상태가 없어 캐시해 재사용한다."""
        from ..detect.boss_bar import has_wide_bar_row, make_validator
        from ..detect.boss_hp_reader import number_area_flooded

        # 값싼 사전 판정(~1ms): 넓은 가로 연속(고HP 바 가장자리) '또는' 숫자 영역 flooded
        # (저HP 빨간 바 — 채움이 짧아 가로 연속이 없지만 숫자 영역이 회색으로 꽉 참)가
        # 아니면 보스바 아님 → 즉시 False. 평상시 프레임마다 비싼 make_validator(~36ms)를
        # 안 돈다. 저HP 보스 막바지(≤13%)를 걸러 저체력 경고가 꺼지던 문제를 flood OR로 해결.
        if not (has_wide_bar_row(frame) or number_area_flooded(frame)):
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

    # ---- 보스 HP바 수집(오독 제보용) ----
    def _collect_group(self) -> QGroupBox:
        box = QGroupBox("보스 HP바 수집 (오독 제보용)")
        g = QVBoxLayout(box)
        g.addWidget(hint_label(
            "'수집 모드'를 켜면 보스 HP바 영역이 바뀔 때마다 자동 저장됩니다(보스별로).\n"
            "실제와 다른 %가 뜰 때(예: 48%인데 30% 알림)를 모아 보내주시면 오독 원인을 잡습니다."
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
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _apply_collect_gate(self) -> None:
        box = getattr(self, "_collect_box", None)
        if box is not None:
            box.setVisible(self._logged_in() and self.diagnostics_btn.isChecked())
            self.diagnostics_btn.setVisible(self._logged_in())
        btn = getattr(self, "auto_find_btn", None)
        if btn is not None:
            btn.setVisible(self._logged_in())  # 자동 찾기도 Discord 베타

    def _on_auto_find(self) -> None:
        from .region_registration import generation, save_boxes, editing_allowed
        stamp = generation(self)
        """보스 체력바를 화면에서 자동 검출 → 민트 점선 미리보기 + 확인 후에만 저장."""
        from ..autofind_diagnostics import perform_autofind
        frame, ox, oy, box = perform_autofind("boss", capture_for_autofind)
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했습니다.")
            return
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "보스 체력바를 찾지 못했습니다.\n\n"
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
            "'아니오'를 누르면 기존 설정이 그대로 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes or generation(self) != stamp or not editing_allowed(self):
            return
        if not save_boxes(self, {"boss": (lx, ly, lw, lh), "debuff": db}):
            return
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

    def _save_snapshot(self) -> None:
        if self._last_frame is None:
            self.collect_label.setText("저장할 캡처가 없습니다 — 먼저 영역을 지정하세요")
            return
        self._write_shot(self._last_frame)

    def _write_shot(self, frame) -> None:
        try:
            self._shot_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        boss = self._cur_boss or "unknown"
        pct = f"{self._last_raw_hp:03d}" if self._last_raw_hp is not None else "xxx"
        path = self._shot_dir / f"{boss}_hp{pct}_{self._shot_count:03d}.png"
        if image_io.imwrite(path, frame):
            self._shot_count += 1
            self._update_collect_label()

    def _frame_changed(self, frame, threshold: float = 4.0) -> bool:
        prev = self._last_saved_frame
        if prev is None or prev.shape != frame.shape:
            return True
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
        return float(diff.mean()) >= threshold

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
        """판독용 영역 — 저장된 박스의 세로 중심은 두고 높이만 화면 비율로 정규화한다.

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
        x, y, w, h = normalize_box_height((reg["x"], reg["y"], reg["w"], reg["h"]), sh)
        return {"x": x, "y": y, "w": w, "h": h}

    def _grab_rect(self, x: int, y: int, w: int, h: int):
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
        self.preview.setPixmap(
            QPixmap.fromImage(img).scaledToHeight(38, Qt.TransformationMode.FastTransformation)
        )

    def _play(self, stage: str) -> None:
        from .notifier import SoundNotifier

        if self._notifier is None:
            self._notifier = SoundNotifier(
                {"pre": _PRE_SOUND, "near": _NEAR_SOUND}, volume=0.8
            )
        if not self._notifier.play(stage):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def shutdown(self) -> None:
        self._timer.stop()
        self._upcoming.close()
        self._overlay.close()
