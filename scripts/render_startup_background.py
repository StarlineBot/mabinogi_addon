"""Render the approved background; original logo aspect and nontransparent pixels stay intact."""

from pathlib import Path
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QPainterPath, QColor, QFont
from PySide6.QtWidgets import QApplication
import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def background():
    source = QImage(
        str(ROOT / "src/mabinogi_addon/assets/startup_logo.png")
    ).convertToFormat(QImage.Format.Format_RGBA8888)
    if source.isNull():
        raise ValueError("approved startup logo missing")
    pixels = np.frombuffer(source.bits(), np.uint8).reshape(
        source.height(), source.bytesPerLine() // 4, 4
    )
    # The supplied export has isolated alpha=1 specks far outside the logo.
    # Exclude this invisible export margin, preserving every visible logo pixel.
    ys, xs = np.nonzero(pixels[:, :, 3] > 1)
    if not len(xs):
        raise ValueError("empty startup logo")
    source = source.copy(
        int(xs.min()),
        int(ys.min()),
        int(xs.max() - xs.min() + 1),
        int(ys.max() - ys.min() + 1),
    )
    image = QImage(440, 240, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
    )
    path = QPainterPath()
    path.addRoundedRect(QRectF(0.5, 0.5, 439, 239), 14, 14)
    p.fillPath(path, QColor("#1f2937"))
    p.setPen(QColor("#00B894"))
    p.drawPath(path)
    logo = source.scaled(
        264,
        126,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    p.drawImage((440 - logo.width()) // 2, 20, logo)
    font = QFont("Malgun Gothic")
    font.setPixelSize(13)
    p.setFont(font)
    p.setPen(QColor("#00D1A7"))
    p.drawText(
        QRectF(24, 170, 392, 23), Qt.AlignmentFlag.AlignCenter, "섯다라인은 지금…"
    )
    p.end()
    return image


if __name__ == "__main__":
    app = QApplication.instance() or QApplication([])
    destination = ROOT / "src/mabinogi_addon/assets/startup_background.png"
    assert background().save(str(destination))
    print(destination)
