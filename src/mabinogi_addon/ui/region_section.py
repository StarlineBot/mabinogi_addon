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


# 위치 상태 문구(first-use-v3 1·4.1절) — 홈 줄·기능 화면이 같은 말을 쓰게
PLACE_TEXT = {"user": "직접 지정", "found": "위치 찾음", "wait": "화면에 보이면 찾아요", "hidden": "화면에 보이면 찾아요",
              "v1": "저장된 영역 사용", "missing": "못 찾음", "searching": "찾는 중"}


def place_text(key: str | None) -> str | None:
    """'위치 찾음' · '화면에 보이면 찾아요' · '저장된 영역 사용' · '못 찾음' · '직접 지정' · '찾는 중'. 자동 찾기 꺼짐(비상 값)이면 None."""
    from .. import autofind_regions
    if key is None:
        return None
    state = autofind_regions.place(key)
    return None if state is None else PLACE_TEXT[state]


def unplaced_text(key: str, legacy: str) -> str:
    """영역(자리)이 아직 없을 때 기능 화면 상태 문구. 자동 찾기 꺼짐이면 예전 '직접 지정' 안내(legacy) 그대로(QA 11-09 ③)."""
    from .. import autofind_regions
    state = autofind_regions.place(key)
    if state is None:
        return legacy
    if not autofind_regions.wanted(key):
        return "꺼짐 — 홈에서 켜면 위치를 찾아요"
    if state in ("wait", "hidden"):
        return "위치 — 게임 화면에 보이면 찾아요"
    if state == "missing":
        return "위치를 못 찾았어요 — '영역 다시 지정'에서 직접 맞추면 고정돼요"
    return "위치 찾는 중이에요"


def autofind_text(key: str | None) -> str | None:
    """영역 묶음 한 줄(자동 찾기 켜짐일 때만, 아니면 None) — 지금 읽는 자리의 출처."""
    from .. import autofind_regions
    if key is None or not autofind_regions.active():
        return None
    if autofind_regions.is_fixed(key):
        return "직접 지정 · 자동으로 찾지 않아요"
    if not autofind_regions.wanted(key):
        return "자동으로 찾기 · 꺼짐 — 읽지 않아요"
    state = autofind_regions.place(key)
    if state == "found":
        return "자동으로 찾은 자리로 읽어요"
    if state == "v1":
        return "저장된 영역 사용 · 자동으로 못 찾음"
    if state == "user":  # 디버프 줄 — 고정한 보스바에서 계산
        return "직접 지정한 보스바에서 계산해요"
    return f"자동으로 찾기 · {PLACE_TEXT[state]}"


def autofind_combined(keys: dict) -> str | None:
    """여러 기능을 한 묶음에서 보여 줄 때(도르카·투아림): '자동으로 찾기 · 도르카 위치 찾음 · 투아림 찾는 중'. 꺼짐이면 None."""
    from .. import autofind_regions
    if not keys or not autofind_regions.active():
        return None
    parts = []
    for key, name in keys.items():
        if not autofind_regions.wanted(key):
            state = "꺼짐"
        else:
            state = PLACE_TEXT[autofind_regions.place(key)]
        parts.append(f"{name} {state}")
    return "자동으로 찾기 · " + " · ".join(parts)


def refresh_autofind(key: str | None = None) -> None:
    """자동 찾기 자리가 바뀜 → 그 기능 영역 묶음의 위치 표시 갱신."""
    for section in list(_SECTIONS):
        if key is None or section.autofind_key == key or key in (section.autofind_keys or {}):
            section.refresh_autofind()


class RegionSection(QWidget):
    def __init__(self, body: QWidget, *, unset_text: str, title: str = "영역 다시 지정",
                 summary: QWidget | None = None, box_title: str = "영역 지정", header_title: str | None = None,
                 parent=None):
        """header_title: 버프·디버프 탭(명세 17절) — 한 줄 머리 '<굵은 제목> 상태 ⓘ … [영역 다시 지정]', 누르면 아래에 전체 폭으로 펼침."""
        super().__init__(parent)
        self.header = header_title is not None
        self.body = body
        self.registered = False
        self._keep_open = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.autofind_key = None  # 자동 찾기: 이 묶음이 보여 주는 기능 키 — set_autofind_key로
        self.autofind_keys = None  # 여러 기능을 한 줄로(도르카·투아림) — set_autofind_keys로
        self.auto_badge = QLabel("")
        self.auto_badge.setWordWrap(True)
        self.auto_badge.setStyleSheet(f"color:{color('accent')};")
        self.auto_badge.hide()
        from PySide6.QtWidgets import QPushButton
        self.auto_return = QPushButton("자동으로 돌아가기")  # 직접 지정 고정 풀기(first-use-v3 4.1)
        self.auto_return.setObjectName("autoReturn")
        self.auto_return.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_return.setFlat(True)
        self.auto_return.setStyleSheet(f"QPushButton#autoReturn {{ color:{color('accent')}; text-decoration: underline;"
                                       " border:none; padding:0 2px; }")
        self.auto_return.clicked.connect(self._auto_return)
        self.auto_return.hide()
        self._unset_text = unset_text
        if not self.header:
            from PySide6.QtWidgets import QHBoxLayout
            badge_row = QHBoxLayout()
            badge_row.setContentsMargins(0, 0, 0, 0)
            badge_row.setSpacing(6)
            badge_row.addWidget(self.auto_badge, 1)
            badge_row.addWidget(self.auto_return, 0, Qt.AlignmentFlag.AlignTop)
            layout.addLayout(badge_row)
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
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        if self.header:
            # 한 줄: 제목 · 상태(지금 상태는 툴팁에 숨기지 않음) · 자동(v2) · ⓘ(영역 자세히) … [영역 다시 지정]
            from PySide6.QtWidgets import QHBoxLayout, QSizePolicy
            self.header_row = QWidget()
            row = QHBoxLayout(self.header_row)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)
            self.header_label = QLabel(header_title)
            self.header_label.setStyleSheet("font-weight:700;")
            row.addWidget(self.header_label)
            for label in [summary, *summary.findChildren(QLabel)]:
                if isinstance(label, QLabel):
                    label.setWordWrap(False)  # 한 줄 상태 — 줄바꿈하면 좁은 세로 칸으로 찌그러짐
                    label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # 굵은 제목과 같은 줄 높이
            row.addWidget(summary)
            self.auto_badge.setWordWrap(False)
            row.addWidget(self.auto_badge)
            row.addWidget(self.auto_return)
            self.info = QLabel("ⓘ")
            self.info.setStyleSheet(f"color:{color('muted')};")
            self.info.setCursor(Qt.CursorShape.WhatsThisCursor)
            row.addWidget(self.info)
            row.addStretch(1)
            self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            self.toggle.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(self.toggle)
            layout.insertWidget(0, self.header_row)
        else:
            layout.addWidget(summary)
            self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.toggle.setArrowType(Qt.ArrowType.RightArrow)
            self.toggle.setAutoRaise(True)
            layout.addWidget(self.toggle)
        self.fold = QWidget()
        fold = QVBoxLayout(self.fold)
        fold.setContentsMargins(0 if self.header else 14, 0, 0, 0)
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
        if self.header:
            self.info.setVisible(registered and bool(self.info.toolTip()))
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

    def set_autofind_keys(self, keys: dict) -> None:
        """{기능 키: 이름} — 한 묶음에 기능이 둘 이상일 때 한 줄로 합쳐 보인다."""
        self.autofind_keys = dict(keys)
        _SECTIONS.add(self)
        self.refresh_autofind()

    def refresh_autofind(self) -> None:
        """자동 찾기 켜짐일 때만 한 줄 — 지금 읽는 자리의 출처(자동·저장된 영역·직접 지정) + 고정이면 [자동으로 돌아가기].
        자리가 아직 없으면 '아직 지정 안 됨' 대신 위치 상태(찾는 중·보이면 찾아요·못 찾음)."""
        from .. import autofind_regions
        self._apply_guide()
        text = autofind_combined(self.autofind_keys) if self.autofind_keys else autofind_text(self.autofind_key)
        if self.header:  # 버프·디버프 한 줄 머리(명세 17절): 짧은 말, 긴 설명은 툴팁 — 긴 문구로 탭 최소 폭이 936px까지 늘던 것(QA 50a07f9)
            self.auto_badge.setText(_short(self.autofind_key) if text else "")
            self.auto_badge.setToolTip(text or "")
        else:
            self.auto_badge.setText(text or "")
        self.auto_badge.setVisible(bool(text))
        fixed = [k for k in ([self.autofind_key] if self.autofind_key else list(self.autofind_keys or {}))
                 if k and autofind_regions.is_fixed(k)]
        self.auto_return.setVisible(bool(fixed))
        self._fixed_keys = fixed
        key = self.autofind_key or next(iter(self.autofind_keys or {}), None)
        if key is not None and autofind_regions.active():
            state = autofind_regions.place(key)
            warn = state == "missing" and autofind_regions.wanted(key)
            tone = color('warn') if warn else color('muted')
            self.unset_label.setText(f'<span style="color:{tone}">●</span> {unplaced_text(key, "")}')
            self.unset_label.setStyleSheet(f"color:{tone};")

    def set_guide(self, label: QLabel, auto_text: str) -> None:
        """영역 지정 안내(회색 한 줄)를 자동 찾기 켜짐이면 v3 문구('앱이 알아서 찾아요 · 틀리면 직접 지정하면 고정')로(QA 0429c66 4).
        자동 찾기 꺼짐(비상 값)이면 예전 안내 그대로."""
        self._guide = (label, label.text(), auto_text)
        _SECTIONS.add(self)
        self._apply_guide()

    def _apply_guide(self) -> None:
        from .. import autofind_regions
        guide = getattr(self, "_guide", None)
        if guide is not None:
            label, legacy, auto = guide
            text = auto if autofind_regions.active() else legacy
            if label.text() != text:
                label.setText(text)

    def _auto_return(self) -> None:
        from .. import autofind_regions
        for key in list(getattr(self, "_fixed_keys", ())):
            autofind_regions.auto_return(key)
        refresh_autofind()

    def set_summary(self, text: str, tint: str | None = None) -> None:
        if self.summary_label is not None:
            self.summary_label.setText(text)
            self.summary_label.setStyleSheet(f"color:{tint or color('ok')};")

    def _set_open(self, value: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(value)
        self.toggle.blockSignals(False)
        self._toggled(value)

    def set_info(self, text: str) -> None:
        """한 줄 머리의 ⓘ 툴팁(영역 위치·크기 등 자세한 것) — 지금 상태는 상태 문구에 그대로 보인다."""
        if self.header:
            self.info.setToolTip(text)
            self.info.setVisible(self.registered and bool(text))

    def _toggled(self, value: bool) -> None:
        if not self.header:
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


def _short(key: str | None) -> str:
    """한 줄 머리(버프·디버프)용 짧은 출처 — '자동' · '저장된 영역' · '직접 지정' · 위치 상태."""
    from .. import autofind_regions
    if key is None:
        return ""
    if autofind_regions.is_fixed(key):
        return "직접 지정 ·"
    if not autofind_regions.wanted(key):
        return "꺼짐"
    state = autofind_regions.place(key)
    return {"found": "자동", "v1": "저장된 영역", "user": "직접 지정"}.get(state, PLACE_TEXT.get(state, ""))
