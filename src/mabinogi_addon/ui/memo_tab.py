"""메모 탭.

메모 오버레이의 위치·크기(영역 지정), 고정(클릭 통과) 토글, 글자 크기를 다룬다.
실제 글은 오버레이 창에 직접 입력한다(해제 상태에서).
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .help_dialog import help_title_row
from .widgets import hint_label, section_label

# 메모 사용법(? 아이콘 → 새 창).
HELP_TITLE = "메모 사용법"
HELP_HTML = """
<h3>메모란?</h3>
<p>게임 화면 위에 띄워두는 <b>메모 오버레이</b>입니다. 던전 패턴 표, 재료 체크리스트
등을 적어 두고 게임하면서 볼 수 있습니다. <b>마크다운</b>으로 표·리스트·강조가 됩니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>메모 영역 지정</b> — 오버레이가 들어갈 위치·크기를 드래그로 잡습니다.</li>
<li><b>내용 입력</b> — 아래 편집창에 <b>마크다운</b>으로 적습니다(입력은 여기서,
오버레이엔 바로 렌더됨). 툴바의 <b>표/리스트/굵게</b> 버튼으로 문법 몰라도 넣을 수 있어요.
글자 크기도 조절됩니다.</li>
<li><b>위치 조정·고정</b> — 오버레이는 <b>'해제'</b> 상태에서 끌어 옮기고(입력 아님),
<b>'고정'</b>하면 클릭이 통과되어(표시 전용) 게임을 가리지 않습니다.</li>
</ol>

<h3>마크다운 예</h3>
<p><code>## 제목</code> · <code>- 리스트</code> · <code>**굵게**</code> ·
표는 <code>| 관문 | 수치 |</code> 아래 <code>| --- | --- |</code>.</p>

<p>메모는 <b>마비노기가 활성(화면 맨 앞)일 때만</b> 보입니다.</p>
"""


class MemoTab(QWidget):
    lock_toggled = Signal(bool)  # 고정(클릭 통과) 토글
    region_changed = Signal()  # 메모 영역(위치·크기) 변경
    font_changed = Signal(int)  # 글자 크기 변경
    text_changed = Signal(str)  # 메모(마크다운) 내용 변경 → 오버레이 렌더·저장

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addLayout(help_title_row("메모", HELP_TITLE, HELP_HTML, self))

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

        # ---- 메모 입력(마크다운) + 빠른 삽입 툴바 ----
        v.addWidget(section_label("메모 내용 (마크다운)"))
        tools = QHBoxLayout()
        tools.setSpacing(4)
        for text, snippet in (
            ("제목", "## 제목\n"),
            ("굵게", "**굵게**"),
            ("리스트", "- 항목\n"),
            ("표", "| 구분 | 값 |\n| --- | --- |\n| 1관 | 85, 35 |\n"),
            ("구분선", "\n---\n"),
        ):
            b = QPushButton(text)
            b.setToolTip("커서 위치에 마크다운 삽입")
            b.clicked.connect(lambda _c=False, s=snippet: self._insert(s))
            tools.addWidget(b)
        tools.addStretch(1)
        v.addLayout(tools)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "예)\n## 던전 패턴\n| 관문 | 수치 |\n| --- | --- |\n| 1관 | 85, 35 |\n\n- **중요** 항목"
        )
        self.editor.setPlainText(str(config.load_memo().get("text", "")))
        self.editor.textChanged.connect(
            lambda: self.text_changed.emit(self.editor.toPlainText())
        )
        v.addWidget(self.editor, 1)

        v.addWidget(
            hint_label(
                "여기서 적으면 오버레이에 표·리스트·강조로 바로 나타납니다.\n"
                "오버레이는 '해제' 상태에서 끌어 위치를 옮기고, '고정'하면 클릭이 통과돼요.\n"
                "메모는 마비노기가 활성일 때만 보입니다."
            )
        )

    def _insert(self, snippet: str) -> None:
        """커서 위치에 마크다운 조각 삽입(선택 영역이 있으면 '굵게'는 감싼다)."""
        cur = self.editor.textCursor()
        if snippet == "**굵게**" and cur.hasSelection():
            cur.insertText(f"**{cur.selectedText()}**")
        else:
            cur.insertText(snippet)
        self.editor.setFocus()

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
