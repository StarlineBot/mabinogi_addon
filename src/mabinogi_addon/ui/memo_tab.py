"""메모 탭.

메모 오버레이의 위치·크기(영역 지정), 고정(클릭 통과) 토글, 글자 크기를 다룬다.
실제 글은 오버레이 창에 직접 입력한다(해제 상태에서).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .widgets import hint_label, section_label


class MemoTab(QWidget):
    lock_toggled = Signal(bool)  # 고정(클릭 통과) 토글
    region_changed = Signal()  # 메모 영역(위치·크기) 변경
    font_changed = Signal(int)  # 글자 크기 변경

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(6)
        region_btn = QPushButton("메모 영역 지정")
        region_btn.clicked.connect(self._pick_region)
        top.addWidget(region_btn, 1)
        self.lock_btn = QPushButton("오버레이 고정")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setStyleSheet(
            "QPushButton:checked { background:#00B894; color:white; font-weight:600; }"
        )
        self.lock_btn.toggled.connect(self._on_lock_toggled)
        top.addWidget(self.lock_btn, 1)
        v.addLayout(top)

        self.region_hint = hint_label("")
        self._update_region_hint()
        v.addWidget(self.region_hint)

        v.addWidget(section_label("글자 크기"))
        font_row = QHBoxLayout()
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 48)
        self.font_spin.setValue(int(config.load_memo().get("fontSize", 16)))
        self.font_spin.setSuffix(" px")
        self.font_spin.valueChanged.connect(self.font_changed.emit)
        font_row.addWidget(self.font_spin)
        font_row.addStretch(1)
        v.addLayout(font_row)

        v.addWidget(
            hint_label(
                "메모 영역을 지정한 뒤, '해제' 상태에서 그 영역을 클릭해 입력하세요.\n"
                "'고정'하면 클릭이 통과되어(표시 전용) 게임을 가리지 않습니다.\n"
                "메모는 마비노기가 활성일 때만 보입니다."
            )
        )
        v.addStretch(1)

    def _update_region_hint(self) -> None:
        region = config.load_capture_region("memoTracker")
        if region:
            self.region_hint.setText(
                f"영역: {region['x']},{region['y']}  "
                f"{region['w']}×{region['h']}  ✔"
            )
            self.region_hint.setStyleSheet("color:#2ecc71;")
        else:
            self.region_hint.setText("영역 미지정 — 버튼으로 메모 위치·크기를 지정하세요")
            self.region_hint.setStyleSheet("color:#8a8f98;")

    def _pick_region(self) -> None:
        from .region_selector import RegionSelector

        self._selector = RegionSelector()  # 참조 유지(GC 방지)
        self._selector.selected.connect(self._on_region_selected)
        self._selector.start()

    def _on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        config.save_capture_region(x, y, w, h, "memoTracker")
        self._update_region_hint()
        self.region_changed.emit()

    def _on_lock_toggled(self, locked: bool) -> None:
        self.lock_btn.setText("오버레이 고정됨" if locked else "오버레이 고정")
        self.lock_toggled.emit(locked)

    def set_lock_state(self, locked: bool) -> None:
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self._on_lock_toggled(locked)
