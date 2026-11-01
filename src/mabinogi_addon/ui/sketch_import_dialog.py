"""그림대화 › 이미지 불러오기 창(그림대화 명세 4절).

순서: 256×96 비율 상자로 자르기(끌어서 옮기기·휠로 크기) → 밝기·대비 → 4색(흑백/자동/선명/직접)
→ 점묘 → 실제 크기·확대 미리보기 → `캔버스에 넣기`. 변환은 sketch.convert 순수 함수가 한다.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QVBoxLayout, QWidget,
)

from ..sketch import convert
from ..sketch.pngfile import HEIGHT, WIDTH
from .palette import color
from .widgets import hint_label

MODE_ITEMS = (("흑백", "gray"), ("자동(많이 쓰인 색)", "auto"), ("선명(서로 다른 색 우선)", "vivid"),
              ("직접(지금 색 4칸)", "custom"))
MAX_SOURCE = 2048  # 아주 큰 그림은 먼저 줄여 변환을 빠르게


def qimage_to_rgb(image: QImage) -> np.ndarray:
    """QImage → (H,W,3) uint8 RGB(투명은 흰 바탕에 얹는다)."""
    if image.width() > MAX_SOURCE or image.height() > MAX_SOURCE:
        image = image.scaled(MAX_SOURCE, MAX_SOURCE, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    if image.hasAlphaChannel():
        flat = QImage(image.size(), QImage.Format.Format_RGB888)
        flat.fill(QColor("white"))
        p = QPainter(flat)
        p.drawImage(0, 0, image)
        p.end()
        image = flat
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    buf = np.frombuffer(image.constBits(), np.uint8, count=stride * h).reshape(h, stride)
    return buf[:, :w * 3].reshape(h, w, 3).copy()


def indices_pixmap(indices: np.ndarray, palette, scale: int = 1) -> QPixmap:
    rgb = np.ascontiguousarray(np.asarray(palette, np.uint8)[indices])
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
    if scale != 1:
        img = img.scaled(w * scale, h * scale, Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.FastTransformation)
    return QPixmap.fromImage(img)


class CropView(QWidget):
    """원본 그림 위에 8:3 자르기 상자. 끌어서 옮기고, 휠로 상자 크기(확대·축소)를 바꾼다."""

    changed = Signal()
    VIEW_W, VIEW_H = 560, 300

    def __init__(self, rgb: np.ndarray, parent=None):
        super().__init__(parent)
        self._rgb = rgb
        h, w = rgb.shape[:2]
        self._image = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()
        self._scale = min(self.VIEW_W / w, self.VIEW_H / h)
        self.setFixedSize(max(1, round(w * self._scale)), max(1, round(h * self._scale)))
        self.box = list(convert.fit_box(w, h))
        self._drag: QPointF | None = None
        self.setCursor(Qt.CursorShape.SizeAllCursor)

    def _clamp(self) -> None:
        h, w = self._rgb.shape[:2]
        bw = max(16, min(self.box[2], w, h * WIDTH / HEIGHT))
        bh = bw * HEIGHT / WIDTH
        self.box[2], self.box[3] = int(round(bw)), max(1, int(round(bh)))
        self.box[0] = int(max(0, min(self.box[0], w - self.box[2])))
        self.box[1] = int(max(0, min(self.box[1], h - self.box[3])))

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(QRectF(self.rect()), self._image)
        s = self._scale
        r = QRectF(self.box[0] * s, self.box[1] * s, self.box[2] * s, self.box[3] * s)
        shade = QColor(0, 0, 0, 120)
        full = QRectF(self.rect())
        p.fillRect(QRectF(0, 0, full.width(), r.top()), shade)
        p.fillRect(QRectF(0, r.bottom(), full.width(), full.height() - r.bottom()), shade)
        p.fillRect(QRectF(0, r.top(), r.left(), r.height()), shade)
        p.fillRect(QRectF(r.right(), r.top(), full.width() - r.right(), r.height()), shade)
        p.setPen(QPen(QColor(color("accent")), 2))
        p.drawRect(r)
        p.end()

    def mousePressEvent(self, event):
        self._drag = event.position()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        d = (event.position() - self._drag) / self._scale
        self._drag = event.position()
        self.box[0] += d.x()
        self.box[1] += d.y()
        self._clamp()
        self.update()
        self.changed.emit()

    def mouseReleaseEvent(self, _event):
        self._drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120
        if not steps:
            return
        cx, cy = self.box[0] + self.box[2] / 2, self.box[1] + self.box[3] / 2
        self.box[2] = self.box[2] * (0.9 ** steps)  # 휠 위 = 상자 작게 = 확대
        self._clamp()
        self.box[0], self.box[1] = cx - self.box[2] / 2, cy - self.box[3] / 2
        self._clamp()
        self.update()
        self.changed.emit()
        event.accept()


class SketchImportDialog(QDialog):
    """불러온 그림을 256×96 4색으로 바꿔 캔버스에 넣는 창."""

    def __init__(self, image: QImage, current_palette, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이미지 불러오기")
        self.setModal(True)
        self._rgb = qimage_to_rgb(image)
        self._current_palette = list(current_palette)
        self.result_indices: np.ndarray | None = None
        self.result_palette: list | None = None
        v = QVBoxLayout(self)
        v.setSpacing(8)
        v.addWidget(QLabel("① 자르기 — 상자를 끌어서 옮기고, 마우스 휠로 크기를 바꿔요."))
        self.crop = CropView(self._rgb)
        self.crop.changed.connect(self._schedule)
        v.addWidget(self.crop, 0, Qt.AlignmentFlag.AlignHCenter)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.brightness = self._slider()
        self.contrast = self._slider()
        grid.addWidget(QLabel("② 밝기"), 0, 0)
        grid.addWidget(self.brightness, 0, 1)
        grid.addWidget(QLabel("대비"), 0, 2)
        grid.addWidget(self.contrast, 0, 3)
        grid.addWidget(QLabel("③ 4색"), 1, 0)
        self.mode = QComboBox()
        for text, key in MODE_ITEMS:
            self.mode.addItem(text, key)
        self.mode.currentIndexChanged.connect(self._schedule)
        grid.addWidget(self.mode, 1, 1)
        self.dither = QCheckBox("④ 점묘")
        self.dither.toggled.connect(self._schedule)
        grid.addWidget(self.dither, 1, 2, 1, 2)
        v.addLayout(grid)
        v.addWidget(hint_label("색이 적은 그림(선화·이모티콘)이 잘 나와요. 사진·게임 화면은 4색 포스터 느낌이 돼요."))

        v.addWidget(QLabel("⑤ 미리보기"))
        prev = QHBoxLayout()
        self.preview_big = QLabel()
        self.preview_big.setFixedSize(WIDTH * 2, HEIGHT * 2)
        self.preview_real = QLabel()
        self.preview_real.setFixedSize(WIDTH, HEIGHT)
        prev.addWidget(self.preview_big)
        col = QVBoxLayout()
        col.addWidget(hint_label("실제 크기"))
        col.addWidget(self.preview_real)
        col.addStretch(1)
        prev.addLayout(col)
        prev.addStretch(1)
        v.addLayout(prev)

        buttons = QHBoxLayout()
        buttons.addWidget(hint_label("넣으면 지금 캔버스를 덮어써요. 되돌리기로 돌아갈 수 있어요."), 1)
        cancel = QPushButton("취소")
        cancel.clicked.connect(self.reject)
        self.apply_btn = QPushButton("캔버스에 넣기")
        self.apply_btn.setDefault(True)
        self.apply_btn.setStyleSheet(
            f"QPushButton {{ background:{color('accent')}; color:{color('on-accent')}; font-weight:700;"
            " border:none; border-radius:6px; padding:6px 14px; }")
        self.apply_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.apply_btn)
        v.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)  # 끌거나 슬라이더를 움직이는 동안 몰아서 한 번
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def _slider(self) -> QSlider:
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(-100, 100)
        s.setValue(0)
        s.setMinimumWidth(160)
        s.valueChanged.connect(self._schedule)
        return s

    def _schedule(self, *_):
        self._timer.start()

    def settings(self) -> dict:
        """탭이 '색 묶음'을 바꿀 때 같은 자르기·밝기로 다시 바꾸려고 기억하는 값."""
        return {"box": tuple(self.crop.box), "brightness": self.brightness.value(),
                "contrast": self.contrast.value(), "dither": self.dither.isChecked()}

    def refresh(self) -> None:
        img = convert.adjust(convert.crop_resize(self._rgb, self.crop.box),
                             self.brightness.value(), self.contrast.value())
        mode = self.mode.currentData()
        if mode == "custom":
            palette = self._current_palette
            indices = convert.quantize(img, palette, self.dither.isChecked())
        else:
            indices, palette = convert.convert(img, mode, self.dither.isChecked())
        self.result_indices, self.result_palette = indices, palette
        self.preview_big.setPixmap(indices_pixmap(indices, palette, 2))
        self.preview_real.setPixmap(indices_pixmap(indices, palette, 1))

    @property
    def source_rgb(self) -> np.ndarray:
        return self._rgb
