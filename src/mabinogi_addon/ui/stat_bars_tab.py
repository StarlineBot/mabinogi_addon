"""체력/마나/스태미나 바 오버레이 탭.

게임 하단의 HP/MP/스태미나 세 바를 감싸는 영역을 한 번 지정하면, 그 영역을 실시간으로
읽어 각 바의 채움 비율을 구하고, **우리가 그린 깨끗한 가로 바 3개(각각 독립 오버레이)**로
보여준다. 미러링이 아니라 값만 읽어 새로 그리므로, 버프로 최대치가 늘거나 체력이 깎이면
그 비율이 매 틱(≈0.2초) 반영된다.

구조는 투아림 탭(자체 타이머로 영역 grab·판독)과 커스텀 오버레이 탭(영역 지정·오버레이
관리)을 합친 형태다.
"""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .palette import color
from .. import config, image_io, paths
from ..detect.stat_bars import read_stat_bars
from .dpi import to_logical
from .help_dialog import tab_header
from .screen_grab import capture_for_autofind
from .stat_overlay import WARNING_SAMPLE_MAX_AGE, StatBarOverlay
from .widgets import checkbox, hint_label, wrapping_row, switch
from .settings_layout import lock_button, set_lock_text

STAT_LABELS = {"hp": "생명력", "mp": "마나", "sta": "스태미나"}

# 체력·마나·스태미나 세 바를 덮는 고정 박스 기본 크기(px). 바 크기는 해상도와 무관하게
# 고정(100% UI 배율)이라, 자유 드래그 대신 '고정 박스를 클릭 배치'한다(필요하면 휠로 조절).
# 세 바 블록 실측 ≈ 180×37 → 여백을 둬 넉넉히(경험치 바는 안 걸리게 가로는 과하지 않게).
STAT_BOX_SIZE = (200, 46)

# 저값 경고: 임계 이하가 이만큼(초) 연속돼야 발동(한 프레임 깜빡임 무시). 틱 200ms.
_ALERT_DEBOUNCE = 0.4


def _complete_readings(readings: dict) -> bool:
    return all(sid in readings and np.isfinite(readings[sid].ratio)
               and 0 <= readings[sid].ratio <= 1 for sid in ("hp", "mp", "sta"))

from .feature_copy import HELP

HELP_TITLE = '체력바 사용법'
HELP_HTML = HELP['체력바']


class StatBarsTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_stat_bars()
        self._region = cfg["box"]
        self._scale = cfg["scale"]
        self._align = cfg["align"]
        self._bars_cfg = cfg["bars"]
        self._paused = False
        self._shutting_down = False
        self._sct = None
        self._overlays: dict[str, StatBarOverlay] = {}
        self._display_valid = False
        # 수집 모드 상태(저HP·전환 프레임 모으기 — 경고 기능 튜닝용 데이터).
        self._last_frame = None
        self._last_saved_frame = None
        self._shot_count = 0
        if paths.is_frozen():
            self._shot_dir = paths.user_data_dir() / "stat_bar_shots"
        else:
            self._shot_dir = paths.project_root() / "tests" / "data" / "stat_bar_shots"
        # 저값 경고 상태(게이트+디바운스+무장).
        self._alert_sound_on = cfg["alertSound"]
        self._alert_armed = {sid: True for sid in ("hp", "mp", "sta")}
        self._alert_low_since: dict[str, float] = {}
        self._visual_low_since: dict[str, float] = {}
        self._visual_readings: dict = {}
        self._visual_sample_at: float | None = None
        self._alert_player = None
        # 저체력 알림은 '보스전 중'일 때만 울린다 — 보스 체력바가 떠 있는지 묻는 콜백.
        # main_window가 boss_tab.is_boss_present로 연결한다(미연결 시 종전대로 항상 울림).
        self._boss_present_fn = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "생명력·마나·스태미나를 별도 오버레이로 표시해요.", HELP_TITLE, HELP_HTML, self
        ))
        self._beta_notice = hint_label("")
        self._beta_notice.hide()

        outer = v  # 영역 묶음(명세 11절): 버튼·안내·판독 확인은 지정 후 '영역 다시 지정 · 판독 확인 ▸' 안으로
        v.addWidget(QLabel("판독 영역 · 생명력·마나·스태미나"))
        region_body = QWidget()
        v = QVBoxLayout(region_body)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.setToolTip(
            "고정 크기 박스가 커서를 따라와요. 세 바 위에 올려 클릭 배치(휠로 크기 조절)"
        )
        self.region_btn.clicked.connect(self._on_region)
        self.region_label = hint_label("")
        v.addWidget(self.region_label)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        self.auto_find_btn = QPushButton("자동 찾기")
        self.auto_find_btn.setToolTip("체력바(생/마/스)를 화면에서 자동으로 찾아 지정")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        commands = QHBoxLayout()
        commands.addStretch(1)
        row.addWidget(self.auto_find_btn)
        row.addWidget(self.region_btn)
        row.addWidget(self.view_region_btn)
        from .region_registration import clear_button
        self.clear_region_btn = clear_button(self, "stat_bars", self._region_cleared)
        commands.addWidget(self.clear_region_btn)
        self.region_row = wrapping_row(row, commands)
        v.addLayout(self.region_row)
        v.addWidget(hint_label("생명력·마나·스태미나 세 바를 포함하고, 아래 경험치 바는 제외하세요."))

        # 미리보기 + 현재 값
        source_group = QGroupBox("판독 미리보기")
        source_layout = QVBoxLayout(source_group)
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(80)
        self.preview.setStyleSheet(
            "background:palette(base); border:1px solid palette(mid);"
        )
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.value_label = QLabel("현재 판독: —")
        self.value_label.setWordWrap(True)
        prev_row.addWidget(self.value_label, 1)
        source_layout.addLayout(prev_row)
        v.addWidget(source_group)
        from .region_section import RegionSection
        self.region_section = RegionSection(region_body, unset_text="지정하면 생명력·마나·스태미나를 보기 편한 위치에 보여줘요",
                                            title="영역 다시 지정 · 판독 확인")
        v = outer
        v.addWidget(self.region_section)

        # 표시(명세 11.2·13.3): 1줄 표시할 바 + '전체 위치 잠금', 2줄 배율·정렬, 접힌 '생명력·마나·스태미나 따로 잠그기'.
        display_group = QGroupBox("표시")
        display_layout = QVBoxLayout(display_group)
        v.addWidget(display_group)
        # 1줄: 체력바 표시 스위치(홈 체력바 스위치와 같은 값, 명세 14.5) + 전체 위치 잠금
        top_row = QHBoxLayout()
        self.show_switch = switch("체력바 표시")
        self.show_switch.toggled.connect(self.set_all_shown)
        top_row.addWidget(self.show_switch)
        top_row.addStretch(1)
        display_layout.addLayout(top_row)
        show_row = QHBoxLayout()
        show_row.addWidget(QLabel("표시할 바"))
        self._show_checks: dict[str, QWidget] = {}
        for sid in ("hp", "mp", "sta"):
            chk = checkbox(STAT_LABELS[sid])
            chk.setChecked(self._bars_cfg[sid]["show"])
            chk.toggled.connect(self._on_show_toggle)
            show_row.addWidget(chk)
            self._show_checks[sid] = chk
        show_row.addStretch(1)
        self.lock_btn = lock_button(every=True)  # 세 바 모두(명세 13.3)
        self.lock_btn.clicked.connect(lambda checked: self._set_locked_all(checked))
        top_row.addWidget(self.lock_btn)
        self.show_switch.setChecked(self.any_shown())
        display_layout.addLayout(show_row)

        ctl_row = QHBoxLayout()
        ctl_row.addWidget(QLabel("표시 배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._scale)
        self.scale_spin.valueChanged.connect(self._on_scale)
        ctl_row.addWidget(self.scale_spin)
        ctl_row.addSpacing(12)
        ctl_row.addWidget(QLabel("수치 정렬"))
        self.align_combo = QComboBox()
        for label, key in (("왼쪽", "left"), ("가운데", "center"), ("오른쪽", "right")):
            self.align_combo.addItem(label, key)
        idx = max(0, self.align_combo.findData(self._align))
        self.align_combo.setCurrentIndex(idx)
        self.align_combo.currentIndexChanged.connect(self._on_align)
        ctl_row.addWidget(self.align_combo)
        ctl_row.addStretch(1)
        self.placement_row = ctl_row
        display_layout.addLayout(ctl_row)

        per_bar = QWidget()
        per_bar_row = QHBoxLayout(per_bar)
        per_bar_row.setContentsMargins(14, 0, 0, 0)
        self.bar_lock_buttons = {}
        for sid in ("hp", "mp", "sta"):
            per_bar_row.addWidget(QLabel(STAT_LABELS[sid]))
            lock = lock_button(self._bars_cfg[sid]["locked"])
            lock.toggled.connect(lambda checked, sid=sid: self._set_bar_locked(sid, checked))
            per_bar_row.addWidget(lock)
            self.bar_lock_buttons[sid] = lock
        per_bar_row.addStretch(1)
        from .settings_layout import disclosure
        self.per_bar_toggle = disclosure("생명력·마나·스태미나 따로 잠그기", per_bar, display_layout)
        self._sync_bar_locks()

        # 저값 경고(생/마/스 각각 임계 이하면 알림).
        v.addWidget(self._alert_group())
        # 수집 모드(저HP·전환 프레임 제보용). 영역이 '눈에 띄게 바뀔 때' PNG로 저장만 한다.
        self.diagnostics_btn = QToolButton()
        self.diagnostics_btn.setText("진단 · 체력바 판독 / 수집")
        self.diagnostics_btn.setCheckable(True)
        self.diagnostics_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.diagnostics_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._collect_box = self._collect_group()
        self._collect_box.hide()
        self.diagnostics_btn.toggled.connect(self._show_diagnostics)
        v.addWidget(self.diagnostics_btn)
        v.addWidget(self._collect_box)
        v.addStretch(1)

        # Basic controls are public; auto-find and collection retain their gate.
        self._gated_widgets = [
            self.region_btn, self.view_region_btn, self.auto_find_btn,
            self.scale_spin, self.align_combo, self.lock_btn,
            self.snap_btn, self.open_dir_btn, self.collect_chk,
            self.alert_sound_chk,
            *self.bar_lock_buttons.values(),
            *self._show_checks.values(),
            *self._alert_checks.values(),
            *self._alert_spins.values(),
        ]
        self._update_region_label()
        self._apply_login_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ---- 저값 경고 ----
    def _alert_group(self) -> QGroupBox:
        box = QGroupBox("낮은 수치 알림 · 보스전")
        g = QVBoxLayout(box)
        g.addWidget(hint_label("보스 체력바가 보일 때만 동작해요"))  # 상자 첫 줄(명세 13.3)
        groups = []
        self._alert_checks: dict[str, QWidget] = {}
        self._alert_spins: dict[str, QSpinBox] = {}
        for sid in ("hp", "mp", "sta"):
            row = QHBoxLayout()
            chk = checkbox(STAT_LABELS[sid])
            chk.setChecked(self._bars_cfg[sid]["alert"]["on"])
            chk.toggled.connect(self._on_alert_changed)
            row.addWidget(chk)
            row.addWidget(QLabel("≤"))
            sp = QSpinBox()
            sp.setRange(1, 99)
            sp.setSingleStep(5)
            sp.setSuffix(" %")
            sp.setValue(self._bars_cfg[sid]["alert"]["pct"])
            sp.valueChanged.connect(self._on_alert_changed)
            row.addWidget(sp)
            row.addStretch(1)
            self._alert_checks[sid] = chk
            self._alert_spins[sid] = sp
            groups.append(row)
        remaining = QVBoxLayout()
        remaining.addLayout(wrapping_row(groups[1], groups[2]))
        self.alert_row = wrapping_row(groups[0], remaining)
        g.addLayout(self.alert_row)
        self.alert_sound_chk = checkbox("소리 알림")
        self.alert_sound_chk.setChecked(self._alert_sound_on)
        self.alert_sound_chk.toggled.connect(self._on_alert_changed)
        sound_row = QHBoxLayout()
        sound_row.addWidget(self.alert_sound_chk)
        sound_row.addStretch(1)
        g.addLayout(sound_row)
        self.boss_region_status = hint_label("")  # 보스 체력바가 미지정일 때만 보임(지정돼 있으면 위 한 줄로 충분)
        self.boss_region_status.setStyleSheet(f"color:{color('warn')};")
        self.refresh_boss_region()
        g.addWidget(self.boss_region_status)
        return box

    def _show_diagnostics(self, checked, logged_in=None):
        self.diagnostics_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        self._collect_box.setVisible(checked and (self._logged_in() if logged_in is None else logged_in))

    def refresh_boss_region(self):
        registered = config.load_boss_bar_region() is not None
        self.boss_region_status.setText("보스 체력바 · " + ("등록됨" if registered else "영역 미지정"))
        self.boss_region_status.setVisible(not registered)
        if not registered:
            self._alert_low_since.clear()
            self._reset_visual_alerts()

    def _clear_current_preview(self):
        self.preview.clear()
        self.value_label.setText("현재 판독: —")

    def _on_alert_changed(self, *_args) -> None:
        for sid in ("hp", "mp", "sta"):
            self._bars_cfg[sid]["alert"] = {
                "on": self._alert_checks[sid].isChecked(),
                "pct": self._alert_spins[sid].value(),
            }
        self._alert_sound_on = self.alert_sound_chk.isChecked()
        self._update_visual_alerts(time.monotonic())
        self._save()

    def _clear_visual_bar(self, sid: str) -> None:
        self._visual_low_since.pop(sid, None)
        overlay = self._overlays.get(sid)
        if overlay is not None:
            overlay.set_warning(False)

    def _reset_visual_alerts(self) -> None:
        self._visual_readings = {}
        self._visual_sample_at = None
        for sid in ("hp", "mp", "sta"):
            self._clear_visual_bar(sid)

    def _update_visual_alerts(self, now: float, readings: dict | None = None) -> None:
        if readings is not None:
            if self._visual_sample_at is not None and now - self._visual_sample_at >= WARNING_SAMPLE_MAX_AGE:
                self._reset_visual_alerts()
            self._visual_readings = dict(readings)
            self._visual_sample_at = now
        if (self._visual_sample_at is None
                or not 0 <= now - self._visual_sample_at < WARNING_SAMPLE_MAX_AGE
                or self._paused
                or not self._region or not self._active()
                or (self._boss_present_fn is not None and not self._boss_present_fn())):
            self._reset_visual_alerts()
            return
        for sid, overlay in self._overlays.items():
            alert = self._bars_cfg[sid]["alert"]
            reading = self._visual_readings.get(sid)
            if (not overlay.isVisible() or not self._bars_cfg[sid]["show"] or not alert["on"]
                    or reading is None or reading.ratio * 100 > alert["pct"]):
                self._clear_visual_bar(sid)
                continue
            since = self._visual_low_since.setdefault(sid, now)
            overlay.set_warning(now - since >= _ALERT_DEBOUNCE, self._visual_sample_at)

    def set_boss_presence_source(self, fn) -> None:
        """'지금 보스전인가'를 알려줄 콜백을 연결한다(없으면 항상 울림 — 종전 동작)."""
        self._boss_present_fn = fn

    def has_active_alert(self) -> bool:
        """저체력 경고가 하나라도 켜져 있는지. 보스 탭이 '존재 판정이 필요한가'를 묻는다
        (전부 꺼져 있으면 보스바 존재 판정 자체를 건너뛰어 UI 스레드 부하를 아낀다)."""
        return (self._region is not None and not self._paused
                and any(self._bars_cfg[sid]["alert"]["on"] for sid in ("hp", "mp", "sta")))

    def _check_alerts(self, readings: dict, now: float) -> None:
        """임계 이하로 떨어지면(각 바 각자) 경고. 게이트: 바 3개가 다 보일 때만 판정해
        지역이동·가려짐으로 생기는 0% 오탐을 막는다. 임계 위로 회복하면 재무장."""
        if not _complete_readings(readings):
            self._alert_low_since.clear()
            self._reset_visual_alerts()
            return
        # 보스전일 때만 울린다 — 보스 체력바가 안 떠 있으면 보류(디바운스만 리셋, 무장 유지).
        # 보스바가 뜨고 그때도 저체력이면 거기서 새로 디바운스 후 발동한다.
        if self._boss_present_fn is not None and not self._boss_present_fn():
            self._alert_low_since.clear()
            self._reset_visual_alerts()
            return
        self._update_visual_alerts(now, readings)
        fired = False
        for sid in ("hp", "mp", "sta"):
            al = self._bars_cfg[sid]["alert"]
            r = readings.get(sid)
            if r is None:
                continue
            low = r.ratio * 100 <= al["pct"]
            if not al["on"]:
                if not low:
                    self._alert_armed[sid] = True
                self._alert_low_since.pop(sid, None)
                continue
            if low:
                since = self._alert_low_since.setdefault(sid, now)
                if self._alert_armed[sid] and now - since >= _ALERT_DEBOUNCE:
                    self._alert_armed[sid] = False  # 1회 발동(회복 전까지 재발동 안 함)
                    fired = True
            else:
                self._alert_low_since.pop(sid, None)
                self._alert_armed[sid] = True  # 회복 → 재무장
        if fired and not self._paused and self._alert_sound_on:
            self._play_alert_sound()

    def _play_alert_sound(self) -> None:
        from .notifier import SoundNotifier, sound_path

        # 전용 음원(체력바 경고.mp3)이 있으면 쓰고(목소리 팩도 따라감), 없으면 비프.
        path = sound_path("체력바 경고.mp3")
        if self._alert_player is None and path.exists():
            self._alert_player = SoundNotifier({"low": path})
        if self._alert_player is not None and self._alert_player.play("low"):
            return
        from PySide6.QtWidgets import QApplication

        QApplication.beep()

    # ---- 수집 모드(저HP·전환 프레임 제보) ----
    def _collect_group(self) -> QGroupBox:
        box = QGroupBox("체력바 수집 (저HP·전환 프레임 제보용)")
        g = QVBoxLayout(box)
        g.addWidget(hint_label(
            "영역 지정 후 '수집 모드'를 켜면, 바가 바뀔 때마다 그 영역이 자동 저장돼요.\n"
            "실제 사냥에서 HP가 낮게 깎일 때·지역이동(가려짐)일 때를 모아 보내주시면,"
            " 저HP 인식·경고 오작동을 잡는 데 써요."
        ))
        row = QHBoxLayout()
        self.snap_btn = QPushButton("스냅샷 저장")
        self.snap_btn.clicked.connect(self._save_snapshot)
        row.addWidget(self.snap_btn)
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_dir_btn.setToolTip("수집된 스냅샷이 저장되는 폴더를 탐색기로 열어요")
        self.open_dir_btn.clicked.connect(self._open_shot_dir)
        row.addWidget(self.open_dir_btn)
        self.collect_chk = checkbox("수집 모드(바 바뀔 때 자동 저장)")
        row.addWidget(self.collect_chk, 1)
        g.addLayout(row)
        from .widgets import CapturePathLabel
        self.collect_label = CapturePathLabel()
        self._update_collect_label()
        g.addWidget(self.collect_label)
        return box

    def _update_collect_label(self) -> None:
        self.collect_label.setToolTip(str(self._shot_dir))
        self.collect_label.setText(
            f"저장 위치: {self._shot_dir}  ·  수집 {self._shot_count}장"
        )

    def _open_shot_dir(self) -> None:
        if not self._logged_in() or self._shutting_down:
            return
        paths.open_folder(self._shot_dir)

    def _save_snapshot(self) -> None:
        if not self._logged_in() or self._shutting_down:
            return
        if self._last_frame is None:
            self.collect_label.setText("저장할 캡처가 없어요 — 먼저 영역을 지정하세요")
            return
        self._write_shot(self._last_frame)

    def _write_shot(self, frame) -> None:
        try:
            self._shot_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        # 파일명에 측정 비율 태그(hp/mp/sta %) — 저HP 프레임을 바로 골라 분석.
        rr = {r.stat_id: r.ratio for r in read_stat_bars(frame, require_complete=True)}
        def pct(sid):
            return f"{int(rr[sid] * 100):03d}" if sid in rr else "xxx"
        tag = f"hp{pct('hp')}_mp{pct('mp')}_sta{pct('sta')}"
        path = self._shot_dir / f"{tag}_{self._shot_count:03d}.png"
        if image_io.imwrite(path, frame):
            self._shot_count += 1
            self._update_collect_label()

    def _frame_changed(self, frame, threshold: float = 5.0) -> bool:
        """직전 저장 영상 대비 평균 밝기차가 threshold 이상이면 '바뀜'."""
        prev = self._last_saved_frame
        if prev is None or prev.shape != frame.shape:
            return True
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
        return float(diff.mean()) >= threshold

    @staticmethod
    def _logged_in() -> bool:
        return config.load_discord_user() is not None

    def _apply_login_gate(self) -> None:
        """Keep login restrictions only on auto-find and diagnostic tools."""
        ok = self._logged_in()
        self._show_diagnostics(self.diagnostics_btn.isChecked(), ok)
        self.diagnostics_btn.setVisible(ok)
        self._beta_notice.hide()
        for w in self._gated_widgets:
            w.setEnabled(not self._shutting_down)
        self.auto_find_btn.setEnabled(not self._shutting_down)
        for w in (self.snap_btn, self.open_dir_btn, self.collect_chk):
            w.setEnabled(ok and not self._shutting_down)
        self.view_region_btn.setEnabled(self._region is not None and not self._shutting_down)

    # ---- 오버레이 생성/표시 ----
    def _ensure_overlays(self) -> None:
        if self._overlays:
            return
        screen = QGuiApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        for i, sid in enumerate(("hp", "mp", "sta")):
            ov = StatBarOverlay(sid, scale=self._scale / 100.0)
            ov.set_align(self._align)
            ov.moved.connect(self._save)
            ov.warning_interrupted.connect(lambda sid=sid: self._clear_visual_bar(sid))
            pos = self._bars_cfg[sid]["pos"]
            if pos:
                ov.move_base(QPoint(int(pos["x"]), int(pos["y"])))
            elif geo is not None:
                # 기본: 화면 좌측 1/4 지점에 세로로 쌓아 분명히 보이게(사용자가 옮김).
                ov.move_base(QPoint(geo.x() + geo.width() // 4, geo.y() + geo.height() // 3 + i * 30))
            ov.set_locked(self._bars_cfg[sid]["locked"])
            self._overlays[sid] = ov

    def _active(self) -> bool:
        """게임이 포그라운드거나, 우리 앱이 포그라운드이면서 이 탭을 보는 중(배치)."""
        return self._watcher.is_game_active() or (
            self._watcher.is_self_active() and self.isVisible()
        )

    def _apply_visibility(self) -> None:
        if (self._paused or self._shutting_down
                or not self._region or not self._active()):
            self._display_valid = False
            self._reset_visual_alerts()
            for ov in self._overlays.values():
                ov.hide()
            return
        self._ensure_overlays()
        show = self._display_valid
        for sid, ov in self._overlays.items():
            if show and self._bars_cfg[sid]["show"]:
                if not ov.isVisible():
                    ov.show()
            else:
                self._clear_visual_bar(sid)
                ov.hide()
        if not show:
            self._reset_visual_alerts()

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        self._apply_login_gate()
        if (
            self._paused
            or self._shutting_down
            or not self._region
            or not self._active()
        ):
            self._clear_current_preview()
            self._alert_low_since.clear()
            self._apply_visibility()
            self._reset_visual_alerts()
            return
        self._ensure_overlays()
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._region)
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            self._clear_current_preview()
            self._display_valid = False
            self._apply_visibility()
            self._alert_low_since.clear()
            self._reset_visual_alerts()
            return
        self._last_frame = frame
        self._show_preview(frame)
        # 수집 모드: 로그인 사용자가 켠 동안, 바가 눈에 띄게 바뀌면 자동 저장(튜닝용 제보).
        if (
            self.collect_chk.isChecked()
            and self._logged_in()
            and self._frame_changed(frame)
        ):
            self._write_shot(frame)
            self._last_saved_frame = frame
        readings = {r.stat_id: r for r in read_stat_bars(frame, require_complete=True)}
        self._display_valid = _complete_readings(readings)
        parts = []
        for sid, ov in self._overlays.items():
            r = readings.get(sid)
            if self._display_valid:
                ov.set_value(r.ratio)
                parts.append(f"{STAT_LABELS[sid]} {int(r.ratio * 100)}%")
        self.value_label.setText("현재 판독: " + ("  ".join(parts) if parts else "—"))
        self.region_section.set_summary("✓ 영역 지정됨 · " + (" · ".join(parts) if parts else "판독 대기"))
        # Values must be applied before the first Show; invalid input never shows a window.
        self._apply_visibility()
        self._check_alerts(readings, time.monotonic())

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        hwnd = None
        try:
            from ..system import dwm_thumbnail
            from ..system.window_watcher import DEFAULT_GAME_TITLES

            hwnd = dwm_thumbnail.find_game_window(
                config.load_game_exe(), DEFAULT_GAME_TITLES
            ) or None
        except Exception:  # noqa: BLE001
            hwnd = None
        # 고정 크기 박스로 '클릭 배치'(바 크기가 해상도 무관 고정이라 자유 드래그 불필요).
        # 이전에 지정한 적 있으면 그 크기로 시작(사용자가 맞춘 크기 유지).
        if self._region:
            size = (int(self._region["w"]), int(self._region["h"]))
        else:
            size = STAT_BOX_SIZE
        self._selector = RegionSelector(fixed_size=size, window_hwnd=hwnd)
        from .region_registration import connect_selection
        connect_selection(self, self._selector, self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        region = {"x": x, "y": y, "w": w, "h": h}
        config.save_stat_bars({"box": region})
        self._region = region
        self._display_valid = False
        self._apply_visibility()
        self._alert_low_since.clear()
        self._reset_visual_alerts()
        self._update_region_label()
        self._flash_region()

    def _region_cleared(self):
        self._region = None
        self._display_valid = False
        self._last_frame = self._last_saved_frame = None
        self._alert_low_since.clear()
        self._reset_visual_alerts()
        self._clear_current_preview()
        self._update_region_label()
        self._apply_visibility()

    def _on_auto_find(self) -> None:
        if self._shutting_down:
            return
        from .region_registration import generation, editing_allowed
        stamp = generation(self)
        """체력바를 화면에서 자동 검출 → 민트 점선 미리보기 + 확인 후에만 저장."""
        from ..autofind_diagnostics import perform_autofind
        frame, ox, oy, box = perform_autofind("stat_bars", capture_for_autofind)
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했어요.")
            return
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "체력바(생/마/스)를 찾지 못했어요.\n\n"
                "• 체력바가 화면에 보이나요? (하단 메뉴바가 최소화돼 있으면 안 보여요)\n"
                "• 세 바(분홍·파랑·노랑)가 가려지지 않았나요?\n\n"
                "다시 시도하거나 '영역 지정'으로 직접 잡으세요.",
            )
            return
        x, y, w, h = box
        lx, ly, lw, lh = to_logical(x + ox, y + oy, w, h)  # 물리 → 논리
        from .region_highlight import RegionHighlight

        self._highlight = RegionHighlight()
        self._highlight.flash(
            lx, ly, lw, lh, "자동 찾기 결과", "체력바 — 이 영역으로 지정할까요?", msec=4000
        )
        ans = QMessageBox.question(
            self,
            "자동 찾기 — 확인",
            "민트 점선으로 표시한 영역으로 체력바를 지정할까요?\n\n"
            "'아니오'를 누르면 기존 설정이 그대로 유지돼요.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self._highlight.close()  # 확인 끝나면 민트 점선 즉시 닫기(4초 타이머에만 의존 안 함)
        if ans != QMessageBox.StandardButton.Yes or generation(self) != stamp or not editing_allowed(self):
            return
        try:
            self._on_selected(lx, ly, lw, lh)
        except OSError:
            QMessageBox.warning(self, "영역 저장 실패", "기존 등록 영역을 유지해요.")

    def _flash_region(self) -> None:
        if not self._region:
            return
        from .region_highlight import RegionHighlight

        r = self._region
        self._highlight = RegionHighlight()
        self._highlight.flash(
            int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]),
            "체력바 영역 확인", "체력·마나·스태미나 세 바가 점선 안에 보이나요? (경험치 바는 제외)",
        )

    def _update_region_label(self) -> None:
        self.clear_region_btn.setEnabled(self._region is not None)
        if self._region:
            r = self._region
            self.region_label.setText(f"등록됨 · {r['x']},{r['y']}  {r['w']}×{r['h']}")
            self.region_label.setStyleSheet(f"color:{color('ok')};")
            self.view_region_btn.setEnabled(True)
        else:
            self.region_label.setText("영역 미지정 — 세 바를 감싸게 지정하세요")
            self.region_label.setStyleSheet(f"color:{color('muted')};")
            self.view_region_btn.setEnabled(False)
        section = self.region_section  # 영역 묶음(명세 11절): 지정 후 한 줄 요약 + 접힘, 막 지정했으면 펼침
        registered = self._region is not None
        section.set_registered(registered, just_set=registered and not section.registered
                               and getattr(self, "_region_ready", False))
        self.region_label.setVisible(registered)
        if registered and not section.summary_label.text():
            section.set_summary("✓ 영역 지정됨 · 판독 대기")
        self._region_ready = True

    # ---- 설정 변경 ----
    def _on_show_toggle(self) -> None:
        for sid, chk in self._show_checks.items():
            self._bars_cfg[sid]["show"] = chk.isChecked()
        switch_ = getattr(self, "show_switch", None)
        if switch_ is not None and switch_.isChecked() != self.any_shown():
            switch_.blockSignals(True)
            switch_.setChecked(self.any_shown())
            switch_.blockSignals(False)
            switch_.update()
        self._apply_visibility()
        self._save()

    def any_shown(self) -> bool:
        """홈 '체력바' 스위치(탐색 구조 명세 12.3): 표시할 바가 하나라도 켜져 있으면 켬."""
        return any(chk.isChecked() for chk in self._show_checks.values())

    def set_all_shown(self, on: bool) -> None:
        """홈 스위치: 끄면 모든 바 표시를 끄고(켜져 있던 바 기억), 켜면 기억한 바(없으면 전부)를 다시 켠다."""
        if on == self.any_shown():
            return
        if on:
            remembered = getattr(self, "_home_shown", None) or set(self._show_checks)
        else:
            self._home_shown = {sid for sid, chk in self._show_checks.items() if chk.isChecked()}
            remembered = set()
        for sid, chk in self._show_checks.items():
            chk.blockSignals(True)
            chk.setChecked(sid in remembered)
            chk.blockSignals(False)
        self._on_show_toggle()

    def _on_scale(self, value: int) -> None:
        self._scale = value
        for ov in self._overlays.values():
            ov.set_scale(value / 100.0)
        self._save()

    def _on_align(self) -> None:
        self._align = self.align_combo.currentData()
        for ov in self._overlays.values():
            ov.set_align(self._align)
        self._save()

    def _set_locked_all(self, locked: bool) -> None:
        self._ensure_overlays()
        for sid, ov in self._overlays.items():
            ov.set_locked(locked)
            self._bars_cfg[sid]["locked"] = locked
        self._sync_bar_locks()
        self._save()

    def _set_bar_locked(self, sid, locked):
        self._ensure_overlays()
        self._overlays[sid].set_locked(locked)
        self._bars_cfg[sid]["locked"] = locked
        self._sync_bar_locks()
        self._save()

    def _sync_bar_locks(self):
        for sid, button in self.bar_lock_buttons.items():
            button.blockSignals(True)
            button.setChecked(self._bars_cfg[sid]["locked"])
            set_lock_text(button, button.isChecked())
            button.blockSignals(False)
        lock = getattr(self, "lock_btn", None)
        if lock is not None:  # 잠금 하나(명세 13.3): 세 바가 모두 잠겼으면 '전체 위치 잠금됨', 하나라도 풀리면 '전체 위치 잠금'
            locked = all(cfg["locked"] for cfg in self._bars_cfg.values())
            lock.setChecked(locked)
            set_lock_text(lock, locked)

    def _save(self) -> None:
        for sid, ov in self._overlays.items():
            self._bars_cfg[sid]["locked"] = ov.locked
            pos = ov.base_position
            self._bars_cfg[sid]["pos"] = {"x": pos.x(), "y": pos.y()}
        self._sync_bar_locks()
        config.save_stat_bars(
            {
                "box": self._region,
                "scale": self._scale,
                "align": self._align,
                "bars": self._bars_cfg,
                "alertSound": self._alert_sound_on,
            }
        )

    # ---- 캡처/미리보기 ----
    def _grab_rect(self, x: int, y: int, w: int, h: int):
        try:
            if self._sct is None:
                import mss

                self._sct = mss.mss()
            shot = self._sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )[:, :, :3]
        except Exception:  # noqa: BLE001
            return None

    def _show_preview(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])
        img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img).scaledToHeight(
            38, Qt.TransformationMode.FastTransformation
        )
        self.preview.setPixmap(pm)

    # ---- 메인 윈도우 연동 ----
    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if paused:
            self._alert_low_since.clear()
            self._reset_visual_alerts()
            if self._alert_player is not None:
                self._alert_player.stop()
        self._apply_visibility()

    def shutdown(self) -> None:
        self._shutting_down = True
        self._timer.stop()
        self._display_valid = False
        self._alert_low_since.clear()
        self._reset_visual_alerts()
        for ov in self._overlays.values():
            ov.close()
