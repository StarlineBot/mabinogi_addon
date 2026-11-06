"""설정을 마친 영역은 접는다(안내·도움말 명세 11절, 2026-10-29 사용자 결정).

처음 한 번 하는 설정(영역 지정 버튼·안내·판독 확인)과 평소 쓰는 조작을 같은 무게로 깔지 않는다.
- 지정 전: `영역 지정` 상자 — `● 아직 지정 안 됨 — 지정하면 …`(주황) + 본문(버튼·안내 한 줄·판독 확인).
- 지정 후: 한 줄 요약 + 접힌 `영역 다시 지정 ▸`. 본문은 그 안으로 옮긴다(같은 위젯을 옮겨 붙여 상태가 그대로 남음).
- 지정을 막 마친 직후에는 펼친 채 두어 판독 확인을 볼 수 있게 하고, 탭을 떠났다가 다시 열면 접는다.

요약 줄은 화면마다 다르다: 버프·디버프는 기존 상태 줄(아이콘 + 문구) 위젯을 넘기고, 그 밖의 화면은
`✓ 영역 지정됨 · <현재 판독 값>`을 set_summary로 갱신한다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGroupBox, QLabel, QToolButton, QVBoxLayout, QWidget

from .palette import color

import weakref

_SECTIONS: "weakref.WeakSet[RegionSection]" = weakref.WeakSet()


def autofind_text(key: str | None) -> str | None:
    """'자동(v2)' 한 줄 문구(v2 켜짐일 때만, 아니면 None) — 영역 묶음과 도르카·투아림 영역 문구가 같은 말을 쓰게."""
    from .. import autofind_regions
    if key is None or not autofind_regions.active():
        return None
    if key in autofind_regions.user_keys():
        return "자동(v2) 꺼짐 · 이번 실행은 직접 지정한 영역으로 읽어요"
    if not autofind_regions.wanted(key):
        return "자동(v2) · 사용 꺼짐 — 읽지 않아요(찾은 자리는 그대로)"
    if autofind_regions.is_auto(key):
        return "자동(v2) · 이번 실행에서 찾은 자리로 읽어요(저장된 영역은 그대로)"
    return "자동(v2) · 자리를 찾는 중이에요(찾기 전엔 쉬어요)"


class AutofindLine(QLabel):
    """영역 문구 위 '자동(v2)' 한 줄(RegionSection을 쓰지 않는 탭 — 도르카·투아림). v2 꺼짐이면 숨김."""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.autofind_key = None
        self.setWordWrap(True)
        self.setStyleSheet(f"color:{color('accent')};")
        self.hide()

    def set_autofind_key(self, key: str) -> None:
        self.autofind_key = key
        _SECTIONS.add(self)
        self.refresh_autofind()

    def refresh_autofind(self) -> None:
        text = autofind_text(self.autofind_key)
        self.setText(text or "")
        self.setVisible(bool(text))


def refresh_autofind(key: str | None = None) -> None:
    """자동 찾기 v2 자리가 바뀜 → 그 기능 영역 묶음의 '자동(v2)' 표시 갱신."""
    for section in list(_SECTIONS):
        if key is None or section.autofind_key == key:
            section.refresh_autofind()


class RegionSection(QWidget):
    def __init__(self, body: QWidget, *, unset_text: str, title: str = "영역 다시 지정",
                 summary: QWidget | None = None, box_title: str = "영역 지정", parent=None):
        super().__init__(parent)
        self.body = body
        self.registered = False
        self._keep_open = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.autofind_key = None  # 자동 찾기 v2(제작자): 이 묶음이 보여 주는 기능 키 — set_autofind_key로
        self.auto_badge = QLabel("")
        self.auto_badge.setWordWrap(True)
        self.auto_badge.setStyleSheet(f"color:{color('accent')};")
        self.auto_badge.hide()
        layout.addWidget(self.auto_badge)
        self.box = QGroupBox(box_title)
        box = QVBoxLayout(self.box)
        self.unset_label = QLabel(f'<span style="color:{color('warn')}">●</span> 아직 지정 안 됨 — {unset_text}')
        self.unset_label.setTextFormat(Qt.TextFormat.RichText)
        self.unset_label.setWordWrap(True)
        self.unset_label.setStyleSheet(f"color:{color('warn')};")
        box.addWidget(self.unset_label)
        self._box_layout = box
        layout.addWidget(self.box)
        if summary is None:
            summary = QLabel("")
            summary.setWordWrap(True)
            summary.setStyleSheet(f"color:{color('ok')};")
            self.summary_label = summary
        else:
            self.summary_label = None
        self.summary = summary
        layout.addWidget(summary)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setAutoRaise(True)
        layout.addWidget(self.toggle)
        self.fold = QWidget()
        fold = QVBoxLayout(self.fold)
        fold.setContentsMargins(14, 0, 0, 0)
        self._fold_layout = fold
        layout.addWidget(self.fold)
        self.toggle.toggled.connect(self._toggled)
        self.set_registered(False)

    def set_registered(self, registered: bool, *, just_set: bool = False) -> None:
        """영역 지정 여부 반영. just_set: 방금 지정을 마침 → 이번엔 펼쳐 두고 탭을 다시 열 때 접는다."""
        self.registered = bool(registered)
        target = self._fold_layout if registered else self._box_layout
        if self.body.parentWidget() is not (self.fold if registered else self.box):
            target.addWidget(self.body)
        self.body.show()
        self.box.setVisible(not registered)
        self.summary.setVisible(registered)
        self.toggle.setVisible(registered)
        if not registered:
            self._keep_open = False
            self._set_open(False)
            self.fold.hide()
        elif just_set:
            self._keep_open = True
            self._set_open(True)
        else:
            self.fold.setVisible(self.toggle.isChecked())

    def set_autofind_key(self, key: str) -> None:
        self.autofind_key = key
        _SECTIONS.add(self)
        self.refresh_autofind()

    def refresh_autofind(self) -> None:
        """v2 켜짐일 때만 한 줄 — 지금 읽는 자리가 v2가 찾은 자리인지(저장 영역은 그대로)."""
        text = autofind_text(self.autofind_key)
        self.auto_badge.setText(text or "")
        self.auto_badge.setVisible(bool(text))

    def set_summary(self, text: str, tint: str | None = None) -> None:
        if self.summary_label is not None:
            self.summary_label.setText(text)
            self.summary_label.setStyleSheet(f"color:{tint or color('ok')};")

    def _set_open(self, value: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(value)
        self.toggle.blockSignals(False)
        self._toggled(value)

    def _toggled(self, value: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if value else Qt.ArrowType.RightArrow)
        self.fold.setVisible(bool(value) and self.registered)
        if not value:
            self._keep_open = False

    def hideEvent(self, event) -> None:
        # 지정 직후 펼쳐 둔 것은 탭을 떠나면 접는다(다음에 열 때부터 접힘)
        if self._keep_open and self.registered and not self.window().isMinimized():
            self._keep_open = False
            self._set_open(False)
        super().hideEvent(event)
