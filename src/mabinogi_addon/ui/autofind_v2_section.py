"""설정 › 일반 '자동 찾기 v2' 구역(제작자 전용, docs/autofind-v2-creator-spec.md 5절).

스위치(기본 꺼짐, 다음 실행부터) · 단계 상태 한 줄 · 항목별 상태 · '지금 다시 찾기' · '찾은 자리 보기'.
비제작자에게는 만들지 않는다(설정 화면 변화 0). 표시만 하고 화면 스레드에서 캡처·탐지는 하지 않는다.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import autofind_v2 as v2, config
from .palette import color
from .widgets import hint_label, section_label, switch


class AutofindV2Section(QWidget):
    def __init__(self, controller=None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self._controller = controller
        self._clock = clock
        self._highlights = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(section_label("자동 찾기 v2 (제작자 테스트)"))
        self.toggle = switch("자동 찾기 v2 사용 (다음 실행부터)")
        self.toggle.setChecked(config.load_autofind_v2_enabled())
        self.toggle.toggled.connect(self._on_toggled)
        v.addWidget(self.toggle)
        v.addWidget(hint_label("켜면 저장된 영역 대신 이번 실행에서 찾은 자리로 읽어요. 저장된 영역은 바뀌지 않아요."))
        self.phase = QLabel("")
        self.phase.setWordWrap(True)
        v.addWidget(self.phase)
        self.items = QLabel("")
        self.items.setWordWrap(True)
        self.items.setStyleSheet(f"color:{color('muted')};")
        v.addWidget(self.items)
        row = QHBoxLayout()
        self.again = QPushButton("지금 다시 찾기")
        self.again.clicked.connect(self._again)
        self.show_btn = QPushButton("찾은 자리 보기")
        self.show_btn.clicked.connect(self._show_found)
        row.addWidget(self.again)
        row.addWidget(self.show_btn)
        row.addStretch(1)
        v.addLayout(row)
        if controller is not None:
            controller.changed.connect(self.refresh)
        self.refresh()

    def _on_toggled(self, on: bool) -> None:
        try:
            config.save_autofind_v2_enabled(on)
        except OSError:
            self.toggle.blockSignals(True)
            self.toggle.setChecked(not on)
            self.toggle.blockSignals(False)
        self.refresh()

    def refresh(self) -> None:
        c = self._controller
        running = c is not None
        self.again.setVisible(running)
        self.show_btn.setVisible(running)
        self.items.setVisible(running)
        if not running:
            self.phase.setText("다음 실행부터 켜져요." if self.toggle.isChecked() else "꺼짐 · 지금 설정 그대로 동작해요.")
            self.phase.setStyleSheet(f"color:{color('muted')};")
            return
        if not self.toggle.isChecked():
            note = " · 다음 실행부터 꺼져요"
        else:
            note = ""
        now = self._clock()
        self.phase.setText(c.engine.summary(now) + note)
        self.phase.setStyleSheet(f"color:{color('ok') if c.engine.phase == 'stable' else color('muted')};")
        self.items.setText("\n".join(f"{v2.NAMES[k]}: {it.label(now)}" for k, it in c.engine.items.items()))
        self.show_btn.setEnabled(any(c.engine.region(k) is not None for k in v2.KEYS))

    def showEvent(self, event) -> None:
        self.refresh()
        super().showEvent(event)

    def _again(self) -> None:
        if self._controller is not None:
            self._controller.restart()

    def _show_found(self) -> None:
        """찾은 자리를 화면에 잠깐 표시(region_highlight 재사용, 논리 좌표)."""
        from .dpi import to_logical
        from .region_highlight import RegionHighlight
        for h in self._highlights:
            h.close()
        self._highlights = []
        if self._controller is None:
            return
        for key in v2.KEYS:
            box = self._controller.engine.region(key)
            if box is None:
                continue
            x, y, w, h = to_logical(*box)
            hl = RegionHighlight()
            hl.flash(x, y, w, h, f"자동(v2) · {v2.NAMES[key]}", "", 3000)
            self._highlights.append(hl)
