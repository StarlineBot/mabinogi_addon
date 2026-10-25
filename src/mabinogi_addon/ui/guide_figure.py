"""설정 안내 그림 표시(2026-10-25 사용자 결정): 도움말 맨 위 작은 그림(약 420px) — 누르면 큰 창(약 1200px).

그림은 assets/guide/<이름>.jpg(scripts/build_guide_images.py로 미리 만듦). 도움말 HTML에는 `zoom:<이름>` 링크로 넣는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout

from .. import guide_images, paths

THUMB_WIDTH = 420
ZOOM_WIDTH = 1200


def guide_path(name: str):
    return paths.resource_dir() / 'guide' / f'{name}.jpg'


def figure_html(name: str) -> str:
    """도움말 맨 위 그림(누르면 크게) + 표시한 곳 이름. 그림 경로는 도움말 창의 검색 경로(assets) 기준."""
    return (f'<p><a href="zoom:{name}"><img src="guide/{name}.jpg" width="{THUMB_WIDTH}"></a><br>'
            f'<span style="color:#8a8f98;">연습 모드 화면 예시 · 표시한 곳: {guide_images.caption(name)} · 그림을 누르면 크게 볼 수 있어요</span></p>\n')


class ZoomDialog(QDialog):
    """그림 큰 창. 화면보다 크면 화면 폭에 맞춰 줄인다."""

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle('설정 예시 · ' + guide_images.caption(name))
        layout = QVBoxLayout(self)
        self.image = QLabel()
        pixmap = QPixmap(str(guide_path(name)))
        width = ZOOM_WIDTH
        screen = self.screen()
        if screen is not None:
            width = min(width, int(screen.availableGeometry().width() * 0.9))
        if not pixmap.isNull() and pixmap.width() > width:
            pixmap = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self.image.setPixmap(pixmap)
        layout.addWidget(self.image)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton('닫기')
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)


class ClickableFigure(QLabel):
    """누르면 큰 창이 열리는 작은 그림(첫 사용 안내용)."""
    clicked = Signal()

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        pixmap = QPixmap(str(guide_path(name)))
        if not pixmap.isNull():
            pixmap = pixmap.scaledToWidth(THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(pixmap)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip('누르면 크게 볼 수 있어요')
        self.clicked.connect(self.open_zoom)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def open_zoom(self):
        ZoomDialog(self.name, self.window()).exec()
