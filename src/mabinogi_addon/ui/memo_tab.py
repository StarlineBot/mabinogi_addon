"""메모 탭.

메모 오버레이의 위치·크기(영역 지정), 고정(클릭 통과) 토글, 글자 크기를 다룬다.
실제 글은 오버레이 창에 직접 입력한다(해제 상태에서).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import config
from .help_dialog import tab_header
from .markdown_highlighter import MarkdownHighlighter
from .widgets import checkbox, hint_label, section_label

# 마크다운 툴바 아이콘 버튼 스타일(hover 시 민트).
_TOOL_QSS = (
    "QPushButton { background:palette(button); color:palette(button-text);"
    " border:1px solid palette(mid); border-radius:7px; font-size:14px;"
    " font-weight:800; padding:4px 10px; }"
    "QPushButton:hover { background:#00B894; color:#06281e; border-color:#00B894; }"
    "QPushButton:checked { background:#00B894; color:#06281e; border-color:#00B894; }"
)

# 메모 사용법(? 아이콘 → 새 창).
HELP_TITLE = "메모 사용법"
HELP_HTML = """
<h3>메모란?</h3>
<p>게임 화면 위에 띄워두는 <b>메모 오버레이</b>입니다. 던전 패턴 표, 재료 체크리스트
등을 적어 두고 게임하면서 볼 수 있어요. <b>마크다운</b>이라 표·리스트·강조·제목이 됩니다.</p>

<h3>사용 순서</h3>
<ol>
<li><b>메모 영역 지정</b> — 오버레이가 들어갈 <b>위치·너비</b>를 드래그로 잡습니다.
<b>높이는 내용에 맞춰 자동</b>으로 늘어나니, 긴 메모도 잘리지 않습니다.</li>
<li><b>내용 입력</b> — 아래 편집창에 <b>마크다운</b>으로 적습니다(입력은 여기서, 오버레이엔
바로 렌더). 툴바 아이콘 <b>H·B·•·▦·―·&lt;&gt;</b>(제목·굵게·리스트·표·구분선·코드)로 문법
몰라도 넣을 수 있고, <b>👁 미리보기</b>로 결과를 미리 봅니다. 글자 크기도 조절돼요.</li>
<li><b>위치 조정·잠금</b> — 오버레이는 <b>잠그기 전</b>에 테두리를 끌어 옮기고(입력 아님),
<b>위치 잠금</b>하면 클릭이 통과되어(표시 전용) 게임을 가리지 않습니다.</li>
</ol>

<h3>마크다운 예</h3>
<p><code>## 제목</code> · <code>- 리스트</code> · <code>**굵게**</code> ·
표는 <code>| 관문 | 수치 |</code> 줄 아래 <code>| --- | --- |</code>.</p>

<p>메모는 <b>마비노기가 활성(화면 맨 앞)일 때만</b> 보입니다.</p>
"""


class MemoTab(QWidget):
    lock_toggled = Signal(bool)  # 고정(클릭 통과) 토글
    region_changed = Signal()  # 메모 영역(위치·크기) 변경
    font_changed = Signal(int)  # 글자 크기 변경
    text_changed = Signal(str)  # 메모(마크다운) 내용 변경 → 오버레이 렌더·저장
    enabled_toggled = Signal(bool)  # 메모 오버레이 표시 on/off

    def __init__(self) -> None:
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(10)
        v.addWidget(tab_header(
            "게임 위에 표시할 메모를 작성합니다.", HELP_TITLE, HELP_HTML, self
        ))

        # 메모 오버레이 표시 on/off (끄면 영역·내용은 그대로 두고 화면에만 안 띄움)
        self.enable_chk = checkbox("메모 오버레이 사용")
        self.enable_chk.setToolTip(
            "끄면 영역·내용은 그대로 두고 게임 화면에 메모를 띄우지 않습니다."
        )
        self.enable_chk.setChecked(bool(config.load_memo().get("enabled", True)))
        self.enable_chk.toggled.connect(self.enabled_toggled.emit)
        v.addWidget(self.enable_chk)

        top = QHBoxLayout()
        top.setSpacing(6)
        region_btn = QPushButton("표시 위치·너비 지정")
        region_btn.clicked.connect(self._pick_region)
        top.addWidget(region_btn, 1)
        self.lock_btn = QPushButton("위치 잠금")
        self.lock_btn.setCheckable(True)
        self.lock_btn.setToolTip(
            "잠그면 메모 위치가 고정되고, 클릭이 통과돼 게임을 가리지 않습니다.\n"
            "해제하면 테두리를 끌어 위치를 옮길 수 있어요."
        )
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

        # ---- 메모 입력(마크다운): 아이콘 툴바 + 하이라이팅 편집 + 미리보기 토글 ----
        v.addWidget(section_label("메모 내용 (마크다운)"))
        tools = QHBoxLayout()
        tools.setSpacing(6)
        _TABLE = "| 구분 | 값 |\n| --- | --- |\n| 1관 | 85, 35 |\n"
        for glyph, tip, snippet in (
            ("H", "제목", "## 제목\n"),
            ("B", "굵게", "**굵게**"),
            ("•", "리스트", "- 항목\n"),
            ("▦", "표", _TABLE),
            ("―", "구분선", "\n---\n"),
            ("<>", "코드", "`코드`"),
        ):
            b = QPushButton(glyph)
            b.setFixedSize(34, 30)
            b.setToolTip(f"{tip} 삽입")
            b.setStyleSheet(_TOOL_QSS)
            b.clicked.connect(lambda _c=False, s=snippet: self._insert(s))
            tools.addWidget(b)
        tools.addStretch(1)
        self.preview_btn = QPushButton("👁 미리보기")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setStyleSheet(_TOOL_QSS)
        self.preview_btn.toggled.connect(self._on_preview_toggled)
        tools.addWidget(self.preview_btn)
        v.addLayout(tools)

        # 편집(좌) | 미리보기(우) — 가운데 손잡이로 좌우 너비 조절. 미리보기 기본 숨김.
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "예)\n## 던전 패턴\n| 관문 | 수치 |\n| --- | --- |\n| 1관 | 85, 35 |\n\n- **중요** 항목"
        )
        self.editor.setPlainText(str(config.load_memo().get("text", "")))
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPixelSize(14)
        self.editor.setFont(mono)
        self._highlighter = MarkdownHighlighter(self.editor.document())
        self.editor.textChanged.connect(self._on_editor_changed)

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.document().setDefaultStyleSheet(
            "th,td{border:1px solid #556; padding:2px 8px;} "
            "h1,h2,h3{color:#7CF0D6;}"
        )
        self.preview.hide()

        self._split = QSplitter(Qt.Orientation.Horizontal)
        self._split.addWidget(self.editor)
        self._split.addWidget(self.preview)
        self._split.setSizes([600, 0])
        v.addWidget(self._split, 1)

        v.addWidget(
            hint_label(
                "여기서 적으면 오버레이에 표·리스트·강조로 바로 나타납니다. "
                "👁 미리보기로 결과를 미리 보고, 가운데를 끌어 좌우 너비를 조절하세요.\n"
                "오버레이는 잠그기 전에 끌어 위치를 옮기고, 위치 잠금하면 클릭이 통과돼요."
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

    def _on_editor_changed(self) -> None:
        md = self.editor.toPlainText()
        self.text_changed.emit(md)
        if self.preview.isVisible():
            self.preview.setMarkdown(md)

    def _on_preview_toggled(self, on: bool) -> None:
        self.preview.setVisible(on)
        if on:
            self.preview.setMarkdown(self.editor.toPlainText())
            self._split.setSizes([360, 300])  # 편집/미리보기 반반쯤
        else:
            self._split.setSizes([600, 0])

    def _update_region_hint(self) -> None:
        region = config.load_capture_region("memoTracker")
        if region:
            self.region_hint.setText(
                f"위치 {region['x']},{region['y']}  ·  너비 {region['w']}px  "
                "(높이 자동)  ✔"
            )
            self.region_hint.setStyleSheet("color:#2ecc71;")
        else:
            self.region_hint.setText(
                "영역 미지정 — 버튼으로 메모 위치·너비를 지정하세요 (높이는 자동)"
            )
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
        self.lock_btn.setText("위치 잠금됨" if locked else "위치 잠금")
        self.lock_toggled.emit(locked)

    def set_lock_state(self, locked: bool) -> None:
        self.lock_btn.blockSignals(True)
        self.lock_btn.setChecked(locked)
        self.lock_btn.blockSignals(False)
        self._on_lock_toggled(locked)
