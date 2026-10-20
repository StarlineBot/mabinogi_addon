"""Manual download progress, preserving the existing logo/avatar/bar layout."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import paths


def _round_pixmap(path, size: int) -> QPixmap | None:
    source = QPixmap(str(path))
    if source.isNull():
        return None
    source = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    source = source.copy(
        (source.width() - size) // 2, (source.height() - size) // 2, size, size
    )
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(0, 0, source)
    painter.end()
    return result


class UpdateSplash(QWidget):
    """An explicit progress display; no dialogue animation or bootloader IPC."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.SplashScreen,
        )
        self.setFixedSize(440, 208)
        card = QWidget(self)
        card.setObjectName("card")
        card.setFixedSize(440, 208)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.setSpacing(0)

        assets = paths.resource_dir()
        logo = QLabel()
        pixmap = QPixmap(str(assets / "logo.png"))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(
                    80,
                    80,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(logo)
        layout.addSpacing(14)

        row = QHBoxLayout()
        row.setSpacing(12)
        avatar = QLabel()
        avatar.setFixedSize(46, 46)
        picture = _round_pixmap(assets / "profile.png", 46) or _round_pixmap(
            assets / "logo.png", 46
        )
        if picture is not None:
            avatar.setPixmap(picture)
        row.addWidget(avatar)
        column = QVBoxLayout()
        column.setSpacing(2)
        column.addStretch(1)
        name = QLabel("섯다라인")
        name.setObjectName("name")
        column.addWidget(name)
        self.msg = QLabel()
        self.msg.setObjectName("msg")
        self.msg.setTextFormat(Qt.TextFormat.PlainText)
        column.addWidget(self.msg)
        column.addStretch(1)
        row.addLayout(column)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addSpacing(10)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(7)
        layout.addWidget(self.bar)
        layout.addStretch(1)
        self.setStyleSheet(
            "#card { background:#1f2937; border:1px solid #00B894; border-radius:14px; }"
            "#name { color:#00D1A7; font-size:14px; font-weight:700; }"
            "#msg { color:#e5e7eb; font-size:13px; }"
            "QProgressBar { background:#111827; border:none; border-radius:3px; }"
            "QProgressBar::chunk { background:#00D1A7; border-radius:3px; }"
        )

    def step(self, pct: int, msg: str | None = None) -> None:
        self.bar.setValue(max(0, min(100, pct)))
        if msg is not None:
            self.msg.setText(msg)
        QApplication.processEvents()

    def center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is not None:
            self.move(screen.availableGeometry().center() - self.rect().center())
