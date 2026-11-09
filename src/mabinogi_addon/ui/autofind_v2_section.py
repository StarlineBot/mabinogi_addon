"""설정 맨 아래 '진단 · 자동 찾기'(제작자 전용, 접힘 — docs/first-use-v3-spec.md 4.1).

자동 찾기는 모든 사용자에게 항상 켬(스위치 없음). 여기는 진단만: 단계 상태 한 줄 · 항목별 상태(출처) · '지금 다시 찾기' · '찾은 자리 보기'.
숨은 비상 값(config autofind.disabled)으로 꺼져 있으면 그 사실만 보인다. 표시만 하고 화면 스레드에서 캡처·탐지는 하지 않는다.
"""
from __future__ import annotations

import time

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .. import autofind_v2 as v2
from .palette import color
from .widgets import hint_label


class AutofindV2Section(QWidget):
    def __init__(self, controller=None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self._controller = controller
        self._clock = clock
        self._highlights = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(hint_label("위치는 앱이 알아서 찾아요(항상 켬). 못 찾으면 저장된 영역을 쓰고, "
                               "기능 화면에서 직접 지정한 기능은 고정돼요. 저장된 영역은 바뀌지 않아요."))
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

    def refresh(self) -> None:
        c = self._controller
        running = c is not None
        self.again.setVisible(running)
        self.show_btn.setVisible(running)
        self.items.setVisible(running)
        if not running:
            self.phase.setText("꺼짐(비상 설정 autofind.disabled) · 저장된 영역 그대로 동작해요.")
            self.phase.setStyleSheet(f"color:{color('muted')};")
            return
        now = self._clock()
        self.phase.setText(c.engine.summary(now))
        self.phase.setStyleSheet(f"color:{color('ok') if c.engine.phase == 'stable' else color('muted')};")
        self.items.setText("\n".join(f"{v2.NAMES[k]}: {it.label(now)}{_source_note(k)}" for k, it in c.engine.items.items()))
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


def _source_note(key: str) -> str:
    """지금 기능이 읽는 자리의 출처가 자동이 아니면 덧붙임(저장된 영역 v1 대비)."""
    from .. import autofind_regions
    src = autofind_regions.source(key)
    return " · 저장된 영역 사용" if src == "v1" else ""
