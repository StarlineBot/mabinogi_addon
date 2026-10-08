"""메모 편집기용 마크다운 문법 하이라이팅.

제목·굵게·리스트 마커·표 파이프·인라인 코드·구분선에 색을 입혀 '마크다운 쓰는 느낌'을
준다. 렌더가 아니라 '소스 색칠'이다(렌더된 결과는 미리보기/오버레이에서 본다).
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


def _fmt(color: str, *, bold: bool = False, mono: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if mono:
        f.setFontFamilies(["Consolas", "D2Coding", "Courier New", "monospace"])
    return f


class MarkdownHighlighter(QSyntaxHighlighter):
    """QPlainTextEdit 문서에 붙여 마크다운 토큰을 색칠한다."""

    _RULES: ClassVar[list] = [
        (r"^#{1,6}\s.*$", _fmt("#7CF0D6", bold=True)),  # 제목
        (r"\*\*[^*]+\*\*", _fmt("#ffd54a", bold=True)),  # **굵게**
        (r"^\s*[-*+]\s", _fmt("#00D1A7", bold=True)),  # 리스트 마커
        (r"\|", _fmt("#00D1A7")),  # 표 파이프
        (r"`[^`]+`", _fmt("#ff9a76", mono=True)),  # `코드`
        (r"^---+$", _fmt("#6b7280")),  # 구분선
    ]

    def __init__(self, document) -> None:
        super().__init__(document)
        opt = QRegularExpression.PatternOption.MultilineOption
        self._compiled = [(QRegularExpression(p, opt), f) for p, f in self._RULES]

    def highlightBlock(self, text: str) -> None:
        for rx, f in self._compiled:
            it = rx.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), f)
