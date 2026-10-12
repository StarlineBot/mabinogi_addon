"""체력/마나/스태미나 바 오버레이 탭.

게임 하단의 HP/MP/스태미나 세 바를 감싸는 영역을 한 번 지정하면, 그 영역을 실시간으로
읽어 각 바의 채움 비율을 구하고, **우리가 그린 깨끗한 가로 바 3개(각각 독립 오버레이)**로
보여준다. 미러링이 아니라 값만 읽어 새로 그리므로, 버프로 최대치가 늘거나 체력이 깎이면
그 비율이 매 틱(≈0.2초) 반영된다.

구조는 투아림 탭(자체 타이머로 영역 grab·판독)과 커스텀 오버레이 탭(영역 지정·오버레이
관리)을 합친 형태다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..detect.stat_bars import read_stat_bars
from .help_dialog import tab_header
from .stat_overlay import STAT_LABELS, StatBarOverlay
from .widgets import checkbox, hint_label

# 체력·마나·스태미나 세 바를 덮는 고정 박스 기본 크기(px). 바 크기는 해상도와 무관하게
# 고정(100% UI 배율)이라, 자유 드래그 대신 '고정 박스를 클릭 배치'한다(필요하면 휠로 조절).
# 세 바 블록 실측 ≈ 180×37 → 여백을 둬 넉넉히(경험치 바는 안 걸리게 가로는 과하지 않게).
STAT_BOX_SIZE = (200, 46)

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

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "체력·마나·스태미나를 읽어 깨끗한 바로 표시", HELP_TITLE, HELP_HTML, self
        ))
        v.addWidget(hint_label(
            "'영역 지정'을 누르면 고정 크기 박스가 커서를 따라옵니다. 게임 하단의"
            " 체력·마나·스태미나 세 바 위에 올려 클릭 배치하세요(그 아래 경험치 바는 제외,"
            " 필요하면 휠로 크기 조절). 읽은 비율을 깨끗한 바 3개로 원하는 위치에 띄웁니다."
        ))
        # 베타 기능 — 디스코드 로그인 사용자에게만. 미로그인 시 안내만 보이고 조작은 잠근다.
        self._beta_notice = hint_label(
            "🧪 개발 중인 기능 — 설정 탭에서 Discord 로그인 후 가장 먼저 써볼 수 있어요."
        )
        self._beta_notice.setStyleSheet("color:#e67e22; font-weight:600;")
        v.addWidget(self._beta_notice)

        row = QHBoxLayout()
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip(
            "고정 크기 박스가 커서를 따라옵니다. 세 바 위에 올려 클릭 배치(휠로 크기 조절)"
        )
        self.region_btn.clicked.connect(self._on_region)
        row.addWidget(self.region_btn)
        self.region_label = hint_label("")
        row.addWidget(self.region_label, 1)
        self.view_region_btn = QPushButton("영역 보기")
        self.view_region_btn.clicked.connect(self._flash_region)
        row.addWidget(self.view_region_btn)
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
        v.addStretch(1)

        # 로그인 시에만 조작 가능하게 묶어 두는 컨트롤들.
        self._gated_widgets = [
            self.region_btn, self.view_region_btn, self.enable,
            self.scale_spin, self.align_combo, self.lock_all_btn, self.unlock_all_btn,
            *self._show_checks.values(),
        ]
        self._update_region_label()
        self._apply_login_gate()
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

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
            pos = self._bars_cfg[sid]["pos"]
            if pos:
                ov.move(int(pos["x"]), int(pos["y"]))
            elif geo is not None:
                # 기본: 화면 좌측 1/4 지점에 세로로 쌓아 분명히 보이게(사용자가 옮김).
                ov.move(geo.x() + geo.width() // 4, geo.y() + geo.height() // 3 + i * 30)
            ov.set_locked(self._bars_cfg[sid]["locked"])
            self._overlays[sid] = ov

    def _active(self) -> bool:
        """게임이 포그라운드거나, 우리 앱이 포그라운드이면서 이 탭을 보는 중(배치)."""
        return self._watcher.is_game_active() or (
            self._watcher.is_self_active() and self.isVisible()
        )

    def _apply_visibility(self) -> None:
        if not self._enabled or self._paused or not self._logged_in():
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
                ov.hide()

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
            return
        from .dpi import to_physical

        px, py, pw, ph = to_physical(self._region)
        frame = self._grab_rect(px, py, pw, ph)
        if frame is None:
            return
        self._show_preview(frame)
        readings = {r.stat_id: r for r in read_stat_bars(frame)}
        parts = []
        for sid, ov in self._overlays.items():
            r = readings.get(sid)
            if r is not None:
                ov.set_value(r.ratio)
                parts.append(f"{STAT_LABELS[sid]} {int(r.ratio * 100)}%")
        self.value_label.setText("현재 값: " + ("  ".join(parts) if parts else "—"))

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
        self._region = {"x": x, "y": y, "w": w, "h": h}
        self._update_region_label()
        self._save()
        self._flash_region()

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
            self._bars_cfg[sid]["pos"] = {"x": ov.x(), "y": ov.y()}
        config.save_stat_bars(
            {
                "enabled": self._enabled,
                "box": self._region,
                "scale": self._scale,
                "align": self._align,
                "bars": self._bars_cfg,
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
        self._apply_visibility()

    def shutdown(self) -> None:
        self._timer.stop()
        for ov in self._overlays.values():
            ov.close()
