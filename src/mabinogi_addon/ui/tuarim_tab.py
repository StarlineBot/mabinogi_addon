"""투아림 관리 탭 (기획서 3.3 변형).

화면의 투아림 % 게이지 위에 '리더 박스'를 올려두면, 그 영역의 % 숫자를 읽어 지정한
임계(예 95/98) 이상이 될 때 소리로 알린다. 오버레이로 뭔가를 더 띄우지는 않는다.

숫자 템플릿(detect/templates/tuarim)이 아직 없으면 판독이 None이라 '현재 값: —'로
표시되고 알림도 울리지 않는다(집 스크린샷으로 템플릿을 채우면 동작).
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer
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
from .tuarim_box import TuarimBox
from .widgets import hint_label


class TuarimTab(QWidget):
    def __init__(self, watcher) -> None:
        super().__init__()
        self._watcher = watcher
        cfg = config.load_tuarim()
        self._thresholds = cfg["thresholds"]
        self._sounds = cfg["sounds"]
        self._box: TuarimBox | None = None
        self._box_state = cfg["box"]
        self._sct = None
        self._tracker = TuarimTracker(self._thresholds)
        self._notifier = None  # 지연 생성(소리)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(
            hint_label(
                "투아림 % 게이지 위에 리더 박스를 올려두면, 지정한 %에 도달할 때 소리로"
                " 알립니다. (추가 오버레이는 없음)"
            )
        )

        # 리더 박스
        box_row = QHBoxLayout()
        self.region_btn = QPushButton("영역 지정")
        self.region_btn.setToolTip("% 숫자 두 자리에 맞춰 드래그(돋보기). 리더 박스가 생깁니다.")
        self.region_btn.clicked.connect(self._on_region)
        self.lock_btn = QPushButton("고정")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(
            "QPushButton:checked { background:#00B894; color:white; font-weight:600; }"
        )
        self.lock_btn.toggled.connect(self._on_lock)
        box_row.addWidget(self.region_btn)
        box_row.addWidget(self.lock_btn)
        box_row.addStretch(1)
        v.addLayout(box_row)
        v.addWidget(
            hint_label(
                "영역 지정으로 % 숫자 두 자리에 맞춰 박스를 만든 뒤, 드래그로 미세조정·"
                "휠로 크기조절. 다 맞추면 '고정'(투명+클릭통과)."
            )
        )

        self.value_label = QLabel("현재 값: —")
        self.value_label.setStyleSheet("font-size:14px; font-weight:600;")
        v.addWidget(self.value_label)

        # 사용 + 임계
        self.enable = QCheckBox("투아림 알림 사용")
        self.enable.setChecked(cfg["enabled"])
        self.enable.toggled.connect(self._save)
        v.addWidget(self.enable)

        v.addWidget(self._threshold_group())
        v.addStretch(1)

        if self._box_state:  # 저장된 박스 복원
            self._ensure_box(self._box_state)
            self._box.show()
            locked = bool(self._box_state.get("locked"))
            self.lock_btn.setChecked(locked)
            self._box.set_locked(locked)

        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def _threshold_group(self) -> QGroupBox:
        box = QGroupBox("알림 기준 (% 이상)")
        grid = QGridLayout(box)
        self._spins: list[QSpinBox] = []
        self._sound_checks: list[QCheckBox] = []
        labels = ["1차", "2차"]
        for i in range(2):
            grid.addWidget(QLabel(labels[i]), i, 0)
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

    # ---- 리더 박스 ----
    def _ensure_box(self, state: dict | None = None) -> None:
        if self._box is None:
            self._box = TuarimBox(state or {})
            self._box.moved.connect(self._save)

    def _on_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        self._selector.selected.connect(self._on_selected)
        self._selector.start()

    def _on_selected(self, x: int, y: int, w: int, h: int) -> None:
        self._ensure_box({"x": x, "y": y, "w": w, "h": h})
        self._box.move(x, y)
        self._box.resize(w, h)
        self.lock_btn.setChecked(False)  # 방금 지정 → 미세조정 가능하게 해제
        self._box.set_locked(False)
        self._box.show()
        self._save()

    def _on_lock(self, locked: bool) -> None:
        self.lock_btn.setText("고정됨" if locked else "고정")
        if self._box is not None:
            self._box.set_locked(locked)
        self._save()

    # ---- 저장 ----
    def _save(self) -> None:
        self._thresholds = [s.value() for s in self._spins]
        self._sounds = [c.isChecked() for c in self._sound_checks]
        self._tracker.set_thresholds(self._thresholds)
        config.save_tuarim(
            {
                "enabled": self.enable.isChecked(),
                "box": self._box.to_dict() if self._box is not None else self._box_state,
                "thresholds": self._thresholds,
                "sounds": self._sounds,
            }
        )

    # ---- 읽기 루프 ----
    def _tick(self) -> None:
        if not self.enable.isChecked() or self._box is None or not self._box.isVisible():
            return
        if not self._watcher.is_game_active():
            return
        rect = self._box.to_dict()
        frame = self._grab_rect(rect["x"], rect["y"], rect["w"], rect["h"])
        value = read_percent(frame) if frame is not None else None
        self.value_label.setText(f"현재 값: {value}%" if value is not None else "현재 값: —")
        for t in self._tracker.observe(value):
            self._play(t)

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
        if self._box is not None:
            self._box.close()
