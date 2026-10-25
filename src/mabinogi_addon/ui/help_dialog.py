"""사용법 도움말 창 (각 탭의 ? 버튼에서 열림).

제목 + HTML 본문을 받아 스크롤 가능한 읽기 전용 창으로 띄운다. 탭마다 내용만 바꿔
재사용한다.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .widgets import FEATURE_HEADER_ACTION_SIZE

_ICON_PX = 22  # 도움말 아이콘 크기


def _help_icon(color: str) -> QIcon:
    """테두리 원 + ? 를 벡터로 그린 또렷한 도움말 아이콘(폰트 글리프보다 선명)."""
    scale = 3  # 3배로 그린 뒤 축소 → 안티앨리어싱 또렷
    s = _ICON_PX * scale
    pm = QPixmap(s, s)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidth(max(2, int(s * 0.07)))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    inset = int(s * 0.1)
    p.drawEllipse(inset, inset, s - 2 * inset, s - 2 * inset)
    f = QFont("Arial")
    f.setPixelSize(int(s * 0.56))
    f.setBold(True)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    p.end()
    return QIcon(pm.scaled(
        _ICON_PX, _ICON_PX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ))


class _HelpButton(QPushButton):
    """아이콘만 있는 도움말 버튼. hover 시 민트색 아이콘으로 교체."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._normal = _help_icon("#9aa0aa")
        self._hover = _help_icon("#00B894")
        self.setIcon(self._normal)
        self.setIconSize(QSize(_ICON_PX, _ICON_PX))
        self.setFixedSize(FEATURE_HEADER_ACTION_SIZE, FEATURE_HEADER_ACTION_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("사용법 보기")
        self.setStyleSheet("QPushButton { border:none; background:transparent; }")

    def enterEvent(self, event) -> None:
        self.setIcon(self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(self._normal)
        super().leaveEvent(event)


class HelpDialog(QDialog):
    def __init__(self, title: str, html: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(480, 520)
        v = QVBoxLayout(self)
        browser = QTextBrowser()
        # 설정 안내 그림(guide/<이름>.jpg)은 assets 기준 경로로 찾는다. `zoom:<이름>` 링크는 큰 그림 창, 그 밖의 링크는 브라우저.
        from .. import paths
        browser.setSearchPaths([str(paths.resource_dir())])
        browser.setOpenLinks(False)
        browser.anchorClicked.connect(self._link)
        browser.setHtml(html)
        self.browser = browser
        v.addWidget(browser)
        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("닫기")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        v.addLayout(row)


    def _link(self, url) -> None:
        if url.scheme() == 'zoom':
            from .guide_figure import ZoomDialog
            ZoomDialog(url.path(), self).exec()
            return
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(url)


def help_button(title: str, html: str, parent=None) -> QPushButton:
    """'?' 도움말 아이콘. 버튼 테두리 없이 동그란 물음표만 보이며,
    누르면 HelpDialog를 띄운다.
    """
    btn = _HelpButton(parent)

    def _open() -> None:
        HelpDialog(title, html() if callable(html) else html, parent).exec()

    btn.clicked.connect(_open)
    return btn


def tab_header(
    desc_text: str, help_title: str, html: str, parent=None
) -> QWidget:
    """Feature title, muted summary, divider and the existing help action."""
    from .widgets import FeatureHeader

    return FeatureHeader(help_title.removesuffix(" 사용법"), desc_text,
                         help_button(help_title, html, parent))


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
