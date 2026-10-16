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
    QVBoxLayout,
    QWidget,
)

from .. import config, image_io, paths
from ..detect.stat_bars import read_stat_bars
from .dpi import to_logical
from .help_dialog import tab_header
from .screen_grab import capture_for_autofind
from .stat_overlay import STAT_LABELS, WARNING_SAMPLE_MAX_AGE, StatBarOverlay
from .widgets import checkbox, hint_label

# 체력·마나·스태미나 세 바를 덮는 고정 박스 기본 크기(px). 바 크기는 해상도와 무관하게
# 고정(100% UI 배율)이라, 자유 드래그 대신 '고정 박스를 클릭 배치'한다(필요하면 휠로 조절).
# 세 바 블록 실측 ≈ 180×37 → 여백을 둬 넉넉히(경험치 바는 안 걸리게 가로는 과하지 않게).
STAT_BOX_SIZE = (200, 46)

# 저값 경고: 임계 이하가 이만큼(초) 연속돼야 발동(한 프레임 깜빡임 무시). 틱 200ms.
_ALERT_DEBOUNCE = 0.4

HELP_TITLE = "체력바 오버레이 사용법"
HELP_HTML = """
<h3>체력바 오버레이란?</h3>
<p>게임 하단의 <b>체력·마나·스태미나</b> 바를 읽어, 원하는 위치에 <b>우리가 그린 깨끗한
바</b>로 보여줍니다. 게임 화면을 복사(미러링)하는 게 아니라 <b>채움 비율만 읽어</b> 새로
그리므로, 버프로 최대치가 늘거나 체력이 깎여도 바로 반영됩니다. (읽기만 함)</p>

<h3>사용 순서</h3>
<ol>
<li><b>영역 지정</b> — <b>고정 크기 박스</b>가 커서를 따라옵니다. 게임 하단의
<b>체력·마나·스태미나 세 바</b> 위에 올려 클릭해 배치하세요(필요하면 <b>휠로 크기 조절</b>).
그 <b>아래 파란 경험치(lv) 바는 포함하지 마세요</b>(바가 하나 더 잡혀 어긋납니다).</li>
<li><b>바 이동</b> — 생긴 바 3개를 드래그로 원하는 곳에 둡니다. 고정하면 위치가 잠기고
클릭도 통과합니다. 배율로 크기를 바꿀 수 있습니다.</li>
</ol>
"""


class StatBarsTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_stat_bars()
        self._region = cfg["box"]
        self._scale = cfg["scale"]
        self._align = cfg["align"]
        self._bars_cfg = cfg["bars"]
        self._enabled = cfg["enabled"]
        self._paused = False
        self._sct = None
        self._overlays: dict[str, StatBarOverlay] = {}
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
            "생명력·마나·스태미나를 별도 오버레이로 표시합니다.", HELP_TITLE, HELP_HTML, self
        ))
        v.addWidget(hint_label(
            "게임의 세 바가 보이는 상태에서 자동 찾기를 실행하세요."
            " 직접 지정할 때는 생명력·마나·스태미나를 포함하고 경험치 바는 제외하세요."
        ))
        # 베타 기능 — 디스코드 로그인 사용자에게만. 미로그인 시 안내만 보이고 조작은 잠근다.
        self._beta_notice = hint_label(
            "🧪 개발 중인 기능 — 설정 탭에서 Discord 로그인 후 가장 먼저 써볼 수 있어요."
        )
        self._beta_notice.setStyleSheet("color:#e67e22; font-weight:600;")
        v.addWidget(self._beta_notice)

        row = QHBoxLayout()
        self.region_btn = QPushButton("직접 지정")
        self.region_btn.setToolTip(
            "고정 크기 박스가 커서를 따라옵니다. 세 바 위에 올려 클릭 배치(휠로 크기 조절)"
        )
        self.region_btn.clicked.connect(self._on_region)
        row.addWidget(self.region_btn)
        self.region_label = hint_label("")
        row.addWidget(self.region_label, 1)
        self.view_region_btn = QPushButton("지정 영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        row.addWidget(self.view_region_btn)
        self.auto_find_btn = QPushButton("🧪 자동 찾기")
        self.auto_find_btn.setToolTip("체력바(생/마/스)를 화면에서 자동으로 찾아 지정 — Discord 베타")
        self.auto_find_btn.clicked.connect(self._on_auto_find)
        row.addWidget(self.auto_find_btn)
        v.addLayout(row)

        # 미리보기 + 현재 값
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(80)
        self.preview.setStyleSheet(
            "background:palette(base); border:1px solid palette(mid);"
        )
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.value_label = QLabel("현재 값: —")
        self.value_label.setStyleSheet("font-size:13px; font-weight:600;")
        prev_row.addWidget(self.value_label, 1)
        v.addLayout(prev_row)

        self.enable = checkbox("체력바 오버레이 사용")
        self.enable.setChecked(self._enabled)
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)

        # 바별 표시 토글
        show_row = QHBoxLayout()
        show_row.addWidget(QLabel("표시:"))
        self._show_checks: dict[str, QWidget] = {}
        for sid in ("hp", "mp", "sta"):
            chk = checkbox(STAT_LABELS[sid])
            chk.setChecked(self._bars_cfg[sid]["show"])
            chk.toggled.connect(self._on_show_toggle)
            show_row.addWidget(chk)
            self._show_checks[sid] = chk
        show_row.addStretch(1)
        v.addLayout(show_row)

        # 배율 + 고정/해제
        ctl_row = QHBoxLayout()
        ctl_row.addWidget(QLabel("배율"))
        self.scale_spin = QSpinBox()
        self.scale_spin.setRange(50, 300)
        self.scale_spin.setSingleStep(10)
        self.scale_spin.setSuffix(" %")
        self.scale_spin.setValue(self._scale)
        self.scale_spin.valueChanged.connect(self._on_scale)
        ctl_row.addWidget(self.scale_spin)
        ctl_row.addSpacing(12)
        ctl_row.addWidget(QLabel("% 정렬"))
        self.align_combo = QComboBox()
        for label, key in (("왼쪽", "left"), ("가운데", "center"), ("오른쪽", "right")):
            self.align_combo.addItem(label, key)
        idx = max(0, self.align_combo.findData(self._align))
        self.align_combo.setCurrentIndex(idx)
        self.align_combo.currentIndexChanged.connect(self._on_align)
        ctl_row.addWidget(self.align_combo)
        ctl_row.addStretch(1)
        self.lock_all_btn = QPushButton("전체 고정")
        self.lock_all_btn.clicked.connect(lambda: self._set_locked_all(True))
        self.unlock_all_btn = QPushButton("전체 해제")
        self.unlock_all_btn.clicked.connect(lambda: self._set_locked_all(False))
        ctl_row.addWidget(self.lock_all_btn)
        ctl_row.addWidget(self.unlock_all_btn)
        v.addLayout(ctl_row)

        # 저값 경고(생/마/스 각각 임계 이하면 알림).
        v.addWidget(self._alert_group())
        # 수집 모드(저HP·전환 프레임 제보용). 영역이 '눈에 띄게 바뀔 때' PNG로 저장만 한다.
        v.addWidget(self._collect_group())
        v.addStretch(1)

        # 로그인 시에만 조작 가능하게 묶어 두는 컨트롤들.
        self._gated_widgets = [
            self.region_btn, self.view_region_btn, self.auto_find_btn, self.enable,
            self.scale_spin, self.align_combo, self.lock_all_btn, self.unlock_all_btn,
            self.snap_btn, self.open_dir_btn, self.collect_chk,
            self.alert_sound_chk,
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
        box = QGroupBox("낮은 체력·마나·스태미나 알림")
        g = QVBoxLayout(box)
        g.addWidget(hint_label(
            "체력·마나·스태미나가 각자 정한 % 이하로 떨어지면 흔들림과 소리로 알립니다. 바 3개가"
            " 다 보일 때만 판정해(지역이동·가려짐 0% 오탐 방지), 임계 위로 회복하면"
            " 다시 무장합니다."
        ))
        g.addWidget(hint_label(
            "⚔️ 보스전 중일 때만 울립니다 — 보스 체력바가 화면에 떠 있어야 알림이 나갑니다"
            " (평소 사냥·이동 중엔 울리지 않음). 보스 탭의 영역이 보스 체력바에 맞춰져 있어야"
            " 정확합니다."
        ))
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
            g.addLayout(row)
            self._alert_checks[sid] = chk
            self._alert_spins[sid] = sp
        self.alert_sound_chk = checkbox("소리 알림")
        self.alert_sound_chk.setChecked(self._alert_sound_on)
        self.alert_sound_chk.toggled.connect(self._on_alert_changed)
        g.addWidget(self.alert_sound_chk)
        return box

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
                or not self._enabled or self._paused or not self._logged_in()
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
        return (self._enabled and not self._paused and self._logged_in()
                and any(self._bars_cfg[sid]["alert"]["on"] for sid in ("hp", "mp", "sta")))

    def _check_alerts(self, readings: dict, now: float) -> None:
        """임계 이하로 떨어지면(각 바 각자) 경고. 게이트: 바 3개가 다 보일 때만 판정해
        지역이동·가려짐으로 생기는 0% 오탐을 막는다. 임계 위로 회복하면 재무장."""
        if not all(sid in readings and np.isfinite(readings[sid].ratio)
                   and 0 <= readings[sid].ratio <= 1 for sid in ("hp", "mp", "sta")):
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
            "영역 지정 후 '수집 모드'를 켜면, 바가 바뀔 때마다 그 영역이 자동 저장됩니다.\n"
            "실제 사냥에서 HP가 낮게 깎일 때·지역이동(가려짐)일 때를 모아 보내주시면,"
            " 저HP 인식·경고 오작동을 잡는 데 씁니다."
        ))
        row = QHBoxLayout()
        self.snap_btn = QPushButton("스냅샷 저장")
        self.snap_btn.clicked.connect(self._save_snapshot)
        row.addWidget(self.snap_btn)
        self.open_dir_btn = QPushButton("폴더 열기")
        self.open_dir_btn.setToolTip("수집된 스냅샷이 저장되는 폴더를 탐색기로 엽니다")
        self.open_dir_btn.clicked.connect(self._open_shot_dir)
        row.addWidget(self.open_dir_btn)
        self.collect_chk = checkbox("수집 모드(바 바뀔 때 자동 저장)")
        row.addWidget(self.collect_chk, 1)
        g.addLayout(row)
        self.collect_label = hint_label("")
        self._update_collect_label()
        g.addWidget(self.collect_label)
        return box

    def _update_collect_label(self) -> None:
        self.collect_label.setText(
            f"저장 위치: {self._shot_dir}  ·  수집 {self._shot_count}장"
        )

    def _open_shot_dir(self) -> None:
        paths.open_folder(self._shot_dir)

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
        """베타 게이팅: 디스코드 로그인 사용자에게만 조작·표시를 허용."""
        ok = self._logged_in()
        self._beta_notice.setVisible(not ok)
        for w in self._gated_widgets:
            w.setEnabled(ok)

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
        if not self._enabled or self._paused or not self._logged_in():
            self._reset_visual_alerts()
            for ov in self._overlays.values():
                ov.hide()
            return
        self._ensure_overlays()
        show = self._active()
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
        self._apply_visibility()
        if (
            not self._enabled
            or self._paused
            or not self._logged_in()
            or not self._region
            or not self._active()
        ):
            self._alert_low_since.clear()
            self._reset_visual_alerts()
            return
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._region)
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
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
        if not readings:
            for ov in self._overlays.values():
                ov.hide()
        parts = []
        for sid, ov in self._overlays.items():
            r = readings.get(sid)
            if r is not None:
                ov.set_value(r.ratio)
                parts.append(f"{STAT_LABELS[sid]} {int(r.ratio * 100)}%")
        self.value_label.setText("현재 값: " + ("  ".join(parts) if parts else "—"))
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
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        region = {"x": x, "y": y, "w": w, "h": h}
        config.save_stat_bars({"box": region})
        self._region = region
        self._alert_low_since.clear()
        self._reset_visual_alerts()
        self._update_region_label()
        self._flash_region()

    def _on_auto_find(self) -> None:
        """체력바를 화면에서 자동 검출 → 민트 점선 미리보기 + 확인 후에만 저장."""
        from ..autofind_diagnostics import perform_autofind
        frame, ox, oy, box = perform_autofind("stat_bars", capture_for_autofind)
        if frame is None:
            QMessageBox.warning(self, "자동 찾기", "화면 캡처에 실패했습니다.")
            return
        if box is None:
            QMessageBox.information(
                self,
                "자동 찾기 — 못 찾음",
                "체력바(생/마/스)를 찾지 못했습니다.\n\n"
                "• 체력바가 화면에 보이나요? (하단 메뉴바가 최소화돼 있으면 안 보입니다)\n"
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
            "'아니오'를 누르면 기존 설정이 그대로 유지됩니다.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        self._highlight.close()  # 확인 끝나면 민트 점선 즉시 닫기(4초 타이머에만 의존 안 함)
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._on_selected(lx, ly, lw, lh)

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
        if self._region:
            r = self._region
            self.region_label.setText(f"영역: {r['x']},{r['y']}  {r['w']}×{r['h']}  ✔")
            self.region_label.setStyleSheet("color:#2ecc71;")
            self.view_region_btn.setEnabled(True)
        else:
            self.region_label.setText("영역 미지정 — 세 바를 감싸게 지정하세요")
            self.region_label.setStyleSheet("color:#8a8f98;")
            self.view_region_btn.setEnabled(False)

    # ---- 설정 변경 ----
    def _on_enable(self, checked: bool) -> None:
        self._enabled = checked
        if not checked:
            self._alert_low_since.clear()
        self._apply_visibility()
        self._save()

    def _on_show_toggle(self) -> None:
        for sid, chk in self._show_checks.items():
            self._bars_cfg[sid]["show"] = chk.isChecked()
        self._apply_visibility()
        self._save()

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
        self._save()

    def _save(self) -> None:
        for sid, ov in self._overlays.items():
            self._bars_cfg[sid]["locked"] = ov.locked
            pos = ov.base_position
            self._bars_cfg[sid]["pos"] = {"x": pos.x(), "y": pos.y()}
        config.save_stat_bars(
            {
                "enabled": self._enabled,
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
        self._apply_visibility()

    def shutdown(self) -> None:
        self._timer.stop()
        self._alert_low_since.clear()
        self._reset_visual_alerts()
        for ov in self._overlays.values():
            ov.close()
