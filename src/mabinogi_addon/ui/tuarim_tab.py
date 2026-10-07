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

from .. import config, image_io, paths
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
<li><b>영역 지정</b> — 버튼을 누르면 박스가 커서를 따라옵니다.
<b>마우스 휠로 크기를 숫자에 맞게</b> 조절하고, 투아림 <b>%(숫자 두 자리)</b> 위에
올려 클릭해 배치합니다. 선택 중 화면에 '박스 미리보기'로 실제 잡는 영역이 보입니다.</li>
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
        # 숫자 템플릿 수집용 상태
        self._last_frame = None  # 마지막으로 캡처한 영역(스냅샷 저장 대상)
        self._last_saved_frame = None  # 수집 모드: 직전 '저장한' 영상(변화 감지 기준)
        # 개발용: git 추적 폴더에 저장 → 집에서 수집 후 '푸시'하면 클로드가 템플릿을 만든다.
        self._shot_dir = paths.project_root() / "tests" / "data" / "tuarim_shots"
        self._shot_count = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addLayout(help_title_row("투아림 관리", HELP_TITLE, HELP_HTML, self))
        v.addWidget(
            hint_label(
                "'영역 지정'을 누르면 박스가 커서를 따라옵니다. 마우스 휠로 크기를 숫자에"
                " 맞게 조절하고, 투아림 %(숫자 두 자리) 위에 올려 클릭해 배치하세요. 그 자리를"
                " 읽어 지정 %에 소리로 알립니다. (읽기만 하며 화면을 가리지 않음)"
            )
        )

        row = QHBoxLayout()
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip("% 숫자에 휠로 크기 맞춰 클릭 배치(돋보기). 다시 누르면 재지정.")
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
        v.addWidget(self._collect_group())
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

    def _collect_group(self) -> QGroupBox:
        """숫자 템플릿 수집(개발용). 앱이 이미 캡처 중인 영역을 PNG로 저장만 한다."""
        box = QGroupBox("숫자 템플릿 수집 (개발용)")
        g = QVBoxLayout(box)
        g.addWidget(
            hint_label(
                "영역 지정 후, 지금 캡처된 영역을 PNG로 저장합니다(전체화면 캡처 불필요).\n"
                "'수집 모드'를 켜면 값이 바뀔 때마다 자동 저장 → 0~100 한 바퀴면 0~9 숫자가 모입니다.\n"
                "저장 후 커밋·푸시하면 저장소에서 숫자 템플릿을 만들 수 있습니다."
            )
        )
        row = QHBoxLayout()
        self.snap_btn = QPushButton("스냅샷 저장")
        self.snap_btn.setToolTip("지금 캡처된 영역 1장 저장")
        self.snap_btn.clicked.connect(self._save_snapshot)
        row.addWidget(self.snap_btn)
        self.collect_chk = QCheckBox("수집 모드(값 바뀔 때 자동 저장)")
        row.addWidget(self.collect_chk, 1)
        g.addLayout(row)
        self.collect_label = hint_label("")
        self._update_collect_label()
        g.addWidget(self.collect_label)
        return box

    def _update_collect_label(self) -> None:
        self.collect_label.setText(f"저장 위치: {self._shot_dir}  ·  수집 {self._shot_count}장")

    def _save_snapshot(self) -> None:
        if self._last_frame is None:
            self.collect_label.setText("저장할 캡처가 없습니다 — 먼저 영역을 지정하세요")
            return
        self._write_shot(self._last_frame, self._last_value)

    def _write_shot(self, frame, value: int | None) -> None:
        try:
            self._shot_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        tag = f"v{value:02d}" if value is not None else "raw"
        path = self._shot_dir / f"{tag}_{self._shot_count:03d}.png"
        if image_io.imwrite(path, frame):
            self._shot_count += 1
            self._update_collect_label()

    # ---- 영역 지정 ----
    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        # 고정 크기 박스를 커서에 붙여 % 위에 클릭 한 번으로 배치(돋보기, 휠로 크기 조절).
        # 이전에 지정한 적 있으면 그 크기로 시작(사용자가 맞춰 둔 크기 유지).
        if self._region:
            size = (int(self._region["w"]), int(self._region["h"]))
        else:
            size = TUARIM_BOX_SIZE
        self._selector = RegionSelector(fixed_size=size)
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
        self._last_frame = frame  # 스냅샷 저장 대상
        value = read_percent(frame)
        self.value_label.setText(
            f"현재 값: {value}%" if value is not None else "현재 값: —"
        )
        # 수집 모드: 영상이 '눈에 띄게 바뀌면' 저장(중복 방지). 값(read_percent) 기준이
        # 아니라 영상 변화 기준이라, 템플릿이 아직 없어(value=None) 판독이 안 돼도 숫자가
        # 바뀔 때마다 모인다.
        if self.collect_chk.isChecked() and self._frame_changed(frame):
            self._write_shot(frame, value)
            self._last_saved_frame = frame
        if self.enable.isChecked():
            for t in self._tracker.observe(value):
                self._play(t)

    def _frame_changed(self, frame, threshold: float = 6.0) -> bool:
        """직전 저장 영상 대비 평균 밝기차가 threshold 이상이면 '바뀜'(새 숫자)."""
        prev = self._last_saved_frame
        if prev is None or prev.shape != frame.shape:
            return True
        diff = np.abs(frame.astype(np.int16) - prev.astype(np.int16))
        return float(diff.mean()) >= threshold

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
            self._notifier = SoundNotifier(
                {"tuarim": SOUND_DIR / "투아림 부스트 발동 직전.mp3"}
            )
        if not self._notifier.play("tuarim"):
            from PySide6.QtWidgets import QApplication

            QApplication.beep()

    def shutdown(self) -> None:
        self._timer.stop()
