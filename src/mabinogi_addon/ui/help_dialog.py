"""사용법 도움말 창 (각 탭의 ? 버튼에서 열림).

제목 + HTML 본문을 받아 스크롤 가능한 읽기 전용 창으로 띄운다. 탭마다 내용만 바꿔
재사용한다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)


class HelpDialog(QDialog):
    def __init__(self, title: str, html: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 460)
        v = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setHtml(html)
        browser.setOpenExternalLinks(True)
        v.addWidget(browser)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)


def help_button(title: str, html: str, parent=None) -> QPushButton:
    """'?' 도움말 아이콘. 버튼 테두리 없이 동그란 물음표만 보이며,
    누르면 HelpDialog를 띄운다.
    """
    btn = QPushButton("?")
    btn.setToolTip("사용법 보기")
    btn.setFixedSize(20, 20)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(
        "QPushButton {"
        " border:1px solid #8a8f98; border-radius:10px;"
        " color:#8a8f98; font-weight:700; background:transparent; padding:0; }"
        "QPushButton:hover { color:#00B894; border-color:#00B894; }"
    )

    def _open() -> None:
        HelpDialog(title, html, parent).exec()

    btn.clicked.connect(_open)
    return btn


def help_title_row(
    title_text: str, help_title: str, html: str, parent=None
) -> QHBoxLayout:
    """'<굵은 제목>  (?)' 한 줄. 탭 상단에 놓아 제목 옆에서 사용법을 연다.

    제목색은 palette(windowText)로 테마를 따라간다(다크→흰색, 라이트→검정).
    """
    row = QHBoxLayout()
    row.setSpacing(6)
    title = QLabel(title_text)
    title.setStyleSheet(
        "font-size:15px; font-weight:800; color:palette(windowText);"
    )
    row.addWidget(title)
    row.addWidget(help_button(help_title, html, parent))
    row.addStretch(1)
    return row
