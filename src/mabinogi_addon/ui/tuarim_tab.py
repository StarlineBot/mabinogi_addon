"""투아림 관리 탭 (기획서 3.3 변형).

화면의 투아림 % 게이지 영역을 '영역 지정'으로 한 번 잡아두면, 그 화면 좌표를 직접
읽어(오버레이로 가리지 않음) 지정한 임계(예 95/98) 이상이 될 때 소리로 알린다.

제대로 읽는지 확인용으로, 탭에 '캡처된 영역 미리보기 + 현재 값'을 실시간 표시한다.
숫자 템플릿(detect/templates/tuarim)이 아직 없으면 판독은 None('현재 값: —')이지만,
미리보기 이미지로 영역이 숫자에 맞았는지 눈으로 확인할 수 있다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..detect.tuarim_reader import read_percent
from ..tracker import TuarimTracker
from .help_dialog import help_title_row
from .widgets import hint_label

# 숫자 두 자리+% 를 덮는 고정 박스 크기(px). 스샷 측정: 한 글자 ~16px, '0%'=32×19.
# 2자리+% ≈ 48×19 → 여유를 둔 기본값. (해상도/UI 배율 다르면 추후 조정)
TUARIM_BOX_SIZE = (58, 28)

# 투아림 관리 사용법(? 아이콘 → 새 창).
HELP_TITLE = "투아림 관리 사용법"
HELP_HTML = """
<h3>투아림 관리란?</h3>
<p>화면의 투아림 <b>% 게이지</b>(작은 원 안 숫자 아래 %)를 읽어, 지정한 %(예: 95·98)
이상이 되면 소리로 알립니다. 100%가 되면 다시 0%부터 시작합니다.
오버레이로 화면을 가리지 않고 <b>읽기만</b> 합니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>영역 지정</b> — 버튼을 누르면 고정 크기 박스가 커서를 따라옵니다.
투아림 <b>%(숫자 두 자리)</b> 위에 올려 클릭해 배치합니다. (돋보기)</li>
<li><b>알림 기준</b> — 1차·2차 %를 정하고, 각각 <b>소리</b> 알림을 켤 수 있습니다.</li>
</ol>

<p>아래 <b>미리보기</b>와 <b>현재 값</b>으로 영역이 숫자에 잘 맞았는지 확인하세요.</p>
"""


class TuarimTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_tuarim()
        self._thresholds = cfg["thresholds"]
        self._sounds = cfg["sounds"]
        self._region = cfg["box"]  # {x,y,w,h} 또는 None
        self._sct = None
        self._tracker = TuarimTracker(self._thresholds)
        self._notifier = None

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addLayout(help_title_row("투아림 관리", HELP_TITLE, HELP_HTML, self))
        v.addWidget(
            hint_label(
                "'영역 지정'을 누르면 고정 크기 박스가 커서를 따라옵니다. 투아림 %(숫자 두"
                " 자리) 위에 올려 클릭해 배치하면, 그 자리를 읽어 지정 %에 소리로 알립니다."
                " (읽기만 하며 화면을 가리지 않음)"
            )
        )

        row = QHBoxLayout()
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip("% 숫자 두 자리에 맞춰 드래그(돋보기). 다시 누르면 재지정.")
        self.region_btn.clicked.connect(self._on_region)
        row.addWidget(self.region_btn)
        self.region_label = hint_label("")
        row.addWidget(self.region_label, 1)
        v.addLayout(row)

        # 확인용: 캡처 미리보기 + 현재 값
        prev_row = QHBoxLayout()
        self.preview = QLabel()
        self.preview.setFixedHeight(40)
        self.preview.setMinimumWidth(80)
        self.preview.setStyleSheet("background:#202227; border:1px solid #3a3d44;")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prev_row.addWidget(self.preview)
        self.value_label = QLabel("현재 값: —")
        self.value_label.setStyleSheet("font-size:14px; font-weight:600;")
        prev_row.addWidget(self.value_label, 1)
        v.addLayout(prev_row)

        self.enable = QCheckBox("투아림 알림 사용")
        self.enable.setChecked(cfg["enabled"])
        self.enable.toggled.connect(self._save)
        v.addWidget(self.enable)

        v.addWidget(self._threshold_group())
        v.addStretch(1)

        self._update_region_label()
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _threshold_group(self) -> QGroupBox:
        box = QGroupBox("알림 기준 (% 이상)")
        grid = QGridLayout(box)
        self._spins: list[QSpinBox] = []
        self._sound_checks: list[QCheckBox] = []
        for i, name in enumerate(("1차", "2차")):
            grid.addWidget(QLabel(name), i, 0)
            spin = QSpinBox()
            spin.setRange(1, 99)
            spin.setSuffix(" %")
            spin.setValue(self._thresholds[i] if i < len(self._thresholds) else 95)
            spin.valueChanged.connect(self._save)
            grid.addWidget(spin, i, 1)
            chk = QCheckBox("소리")
            chk.setChecked(self._sounds[i] if i < len(self._sounds) else True)
            chk.toggled.connect(self._save)
            grid.addWidget(chk, i, 2)
            self._spins.append(spin)
            self._sound_checks.append(chk)
        grid.setColumnStretch(3, 1)
        return box

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        # 고정 크기 박스를 커서에 붙여 % 위에 클릭 한 번으로 배치(돋보기).
        self._selector = RegionSelector(fixed_size=TUARIM_BOX_SIZE)
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        self._region = {"x": x, "y": y, "w": w, "h": h}
        self._update_region_label()
        self._save()

    def _update_region_label(self) -> None:
        if self._region:
            r = self._region
            self.region_label.setText(f"영역: {r['x']},{r['y']}  {r['w']}×{r['h']}  ✔")
            self.region_label.setStyleSheet("color:#2ecc71;")
        else:
            self.region_label.setText("영역 미지정 — % 숫자 두 자리를 지정하세요")
            self.region_label.setStyleSheet("color:#8a8f98;")

    # ---- 저장 ----
    def _save(self) -> None:
        self._thresholds = [s.value() for s in self._spins]
        self._sounds = [c.isChecked() for c in self._sound_checks]
        self._tracker.set_thresholds(self._thresholds)
        config.save_tuarim(
            {
                "enabled": self.enable.isChecked(),
                "box": self._region,
                "thresholds": self._thresholds,
                "sounds": self._sounds,
            }
        )

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        if not self._region or not self._watcher.is_game_active():
            return
        r = self._region
        frame = self._grab_rect(r["x"], r["y"], r["w"], r["h"])
        if frame is None:
            return
        self._show_preview(frame)
        value = read_percent(frame)
        self.value_label.setText(
            f"현재 값: {value}%" if value is not None else "현재 값: —"
        )
        if self.enable.isChecked():
            for t in self._tracker.observe(value):
                self._play(t)

    def _show_preview(self, frame: np.ndarray) -> None:
        h, w = frame.shape[:2]
        rgb = np.ascontiguousarray(frame[:, :, ::-1])  # BGR→RGB
        img = QImage(rgb.tobytes(), w, h, 3 * w, QImage.Format.Format_RGB888)
        pm = QPixmap.fromImage(img).scaledToHeight(
            38, Qt.TransformationMode.FastTransformation
        )
        self.preview.setPixmap(pm)

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

    def _play(self, threshold: int) -> None:
        idx = self._thresholds.index(threshold) if threshold in self._thresholds else 0
        if idx < len(self._sounds) and not self._sounds[idx]:
            return
        from .notifier import SOUND_DIR, SoundNotifier

        if self._notifier is None:
            self._notifier = SoundNotifier({"tuarim": SOUND_DIR / "투아림 관리.mp3"})
        if not self._notifier.play("tuarim"):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def shutdown(self) -> None:
        self._timer.stop()
