"""설정 › 테마 › 개인화 패널과 직접 고르기 창(테마 개인화 명세 3·4절).

패널은 값(배경·강조·내용 칸)만 다루고, 적용·저장은 신호로 설정 화면에 맡긴다.
- preview(values): 미리 적용(저장 안 함) — 직접 고르기 창에서 고르는 동안. 끄는 동안은 묶어서
  마지막 값만(PREVIEW_DELAY_MS 동안 멈추면), 손을 떼거나 색 코드를 넣으면 바로.
- commit(values): 적용하고 저장 — 프리셋·내용 칸·되돌리기·직접 고르기 '적용'
- cancel_preview(): 직접 고르기를 취소 — 창을 열기 전 값으로 되돌림
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..theme_colors import ACCENT_PRESETS, BG_PRESETS, DEFAULT, normalize, text_on
from .palette import color
from .widgets import hint_label

TONES = (("auto", "자동"), ("dark", "어둡게"), ("light", "밝게"))
ADJUSTED_TEXT = "읽기 쉽게 조금 조정했어요"
# 미리보기 1회는 화면 전체를 다시 꾸며서(위젯 약 1400개, 수백 ms) 끄는 동안 매번 하면 쌓인다(QA)
PREVIEW_DELAY_MS = 100


def rainbow_style(selected: bool) -> str:
    """'개인화' 동그라미: 무지개 원뿔 그라데이션(크기·선택 테두리는 다른 동그라미와 같다)."""
    border = f"2px solid {color('accent')}" if selected else "1px solid #6b6e76"
    stops = "stop:0 #ff4d4d, stop:0.17 #ffb84d, stop:0.33 #e6f04d, stop:0.5 #4de08a, stop:0.67 #4dc3ff, stop:0.83 #8a6bff, stop:1 #ff4d4d"
    return (f"QPushButton {{ background: qconicalgradient(cx:0.5, cy:0.5, angle:90, {stops});"
            f" border: {border}; border-radius: 12px; color: #111111; font-size: 12px; font-weight: 900; }}")


class _Swatch(QPushButton):
    """프리셋 동그라미. 선택되면 ✓ + 강조색 테두리."""

    def __init__(self, value, size=26, parent=None):
        super().__init__(parent)
        self.value = value
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_selected(False)

    def set_selected(self, selected: bool, fill: str | None = None):
        fill = fill or self.value
        border = f"2px solid {color('accent')}" if selected else "1px solid #6b6e76"
        self.setText("✓" if selected else "")
        self.setStyleSheet(f"QPushButton {{ background:{fill}; border:{border}; border-radius:{self.width() // 2}px;"
                           f" color:{text_on(fill)}; font-size:12px; font-weight:900; }}")


class _PickSwatch(QPushButton):
    """'직접 고르기'(+). 직접 고른 색을 쓰는 중이면 그 색으로 칠하고 ✓."""

    def __init__(self, parent=None):
        super().__init__("+", parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_value(None)

    def set_value(self, value: str | None):
        if value is None:
            self.setText("+")
            self.setStyleSheet(f"QPushButton {{ background:transparent; border:2px solid {color('accent')}; border-radius:13px;"
                               f" color:{color('accent')}; font-size:15px; font-weight:900; padding:0 0 2px 0; }}")
        else:
            self.setText("✓")
            self.setStyleSheet(f"QPushButton {{ background:{value}; border:2px solid {color('accent')}; border-radius:13px;"
                               f" color:{text_on(value)}; font-size:12px; font-weight:900; }}")


class CustomThemePanel(QFrame):
    preview = Signal(dict)
    commit = Signal(dict)
    cancel_preview = Signal()

    def __init__(self, values: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("customThemePanel")
        self.setStyleSheet("#customThemePanel { border:1px solid palette(mid); border-radius:8px; }")
        self.values = dict(values)
        self.picker = None
        self._pending = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(PREVIEW_DELAY_MS)
        self._preview_timer.timeout.connect(self._flush_preview)
        grid = QGridLayout(self)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self._swatches = {"background": [], "accent": []}
        self._pick = {}
        for row, (key, title, presets) in enumerate((("background", "배경", BG_PRESETS), ("accent", "강조색", ACCENT_PRESETS))):
            grid.addWidget(QLabel(title), row, 0, Qt.AlignmentFlag.AlignTop)
            line = QHBoxLayout()
            line.setSpacing(14)
            for name, value in presets:
                cell = QVBoxLayout()
                cell.setSpacing(3)
                swatch = _Swatch(value)
                swatch.clicked.connect(lambda _=False, k=key, v=value: self._choose(k, v))
                self._swatches[key].append(swatch)
                label = QLabel(name)
                label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                cell.addWidget(swatch, 0, Qt.AlignmentFlag.AlignHCenter)
                cell.addWidget(label)
                line.addLayout(cell)
            separator = QFrame()
            separator.setFrameShape(QFrame.Shape.VLine)
            separator.setFrameShadow(QFrame.Shadow.Plain)
            separator.setStyleSheet("color: palette(mid);")
            line.addWidget(separator)
            cell = QVBoxLayout()
            cell.setSpacing(3)
            pick = _PickSwatch()
            pick.clicked.connect(lambda _=False, k=key: self.open_picker(k))
            self._pick[key] = pick
            label = QLabel("직접 고르기")
            label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            cell.addWidget(pick, 0, Qt.AlignmentFlag.AlignHCenter)
            cell.addWidget(label)
            line.addLayout(cell)
            line.addStretch(1)
            grid.addLayout(line, row, 1)
        grid.addWidget(QLabel("내용 칸"), 2, 0)
        tones = QHBoxLayout()
        tones.setSpacing(0)
        self.tone_buttons = {}
        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, text) in enumerate(TONES):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setFixedWidth(72)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._choose("content", k))
            group.addButton(button)
            self.tone_buttons[key] = button
            tones.addWidget(button)
        tones.addSpacing(10)
        tones.addWidget(hint_label("자동: 배경이 밝으면 밝게, 어두우면 어둡게"))
        tones.addStretch(1)
        grid.addLayout(tones, 2, 1)
        bottom = QHBoxLayout()
        bottom.addWidget(hint_label("읽기 어려운 조합이면 글자·강조색 밝기를 조금 조정해요.\n"
                                    "상태 색(초록 정상·주황 주의·빨강 위험)은 바뀌지 않아요."), 1)
        self.reset_btn = QPushButton("기본으로 되돌리기")
        self.reset_btn.clicked.connect(lambda: self._set_all(dict(DEFAULT)))
        bottom.addWidget(self.reset_btn, 0, Qt.AlignmentFlag.AlignBottom)
        grid.addLayout(bottom, 3, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        self.refresh()

    # ---- 값 ----
    def _choose(self, key, value):
        self._set_all({**self.values, key: value})

    def _set_all(self, values):
        self.values = dict(values)
        self.refresh()
        self.commit.emit(dict(self.values))  # 한 번 누르면 바로 적용·저장

    def set_values(self, values):
        self.values = dict(values)
        self.refresh()

    def refresh(self):
        """동그라미·직접 고르기·내용 칸 선택 표시를 지금 값으로(강조색이 바뀌면 테두리 색도 따라감)."""
        for key, presets in (("background", BG_PRESETS), ("accent", ACCENT_PRESETS)):
            current = normalize(self.values.get(key), DEFAULT[key])
            preset = any(value.upper() == current.upper() for _, value in presets)
            for swatch in self._swatches[key]:
                swatch.set_selected(swatch.value.upper() == current.upper())
            self._pick[key].set_value(None if preset else current)
        tone = self.values.get("content", "auto")
        accent = color("accent")
        for key, button in self.tone_buttons.items():
            button.setChecked(key == tone)
            on = key == tone
            button.setStyleSheet(
                "QPushButton { border:1px solid palette(mid); padding:4px 0;"
                + (f" background:{accent}; color:{color('on-accent')}; border-color:{accent};" if on else " background:palette(button);")
                + " }")

    # ---- 직접 고르기 ----
    def open_picker(self, key):
        before = dict(self.values)
        title = "배경 직접 고르기" if key == "background" else "강조색 직접 고르기"
        dialog = ColorPickerDialog(title, normalize(self.values.get(key), DEFAULT[key]), self)
        self.picker = dialog
        dialog.color_changed.connect(lambda value: self._queue_preview({**before, key: value}))
        dialog.settled.connect(self._flush_preview)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._preview_timer.stop()
        self._pending = None  # 닫은 뒤에 늦게 미리보기가 덮어쓰지 않게
        self.picker = None
        if accepted:
            self._set_all({**before, key: dialog.value()})
        else:
            self.values = before
            self.refresh()
            self.cancel_preview.emit()

    def _queue_preview(self, values):
        self._pending = dict(values)
        self._preview_timer.start()  # 다시 시작 = 멈출 때까지 미룸(마지막 값만)

    def _flush_preview(self):
        self._preview_timer.stop()
        if self._pending is not None:
            values, self._pending = self._pending, None
            self._preview(values)

    def _preview(self, values):
        self.values = dict(values)
        self.preview.emit(dict(values))
        self.refresh()
        if self.picker is not None:
            from .palette import custom
            result = custom()
            self.picker.set_adjusted(bool(result and result.get("adjusted")))


class _SvSquare(QWidget):
    """네모판: 가로 진하기(S), 세로 밝기(V)."""
    changed = Signal(float, float)
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 150)
        self.hue, self.s, self.v = 0.0, 1.0, 1.0
        self.setCursor(Qt.CursorShape.CrossCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        horizontal = QLinearGradient(rect.topLeft(), rect.topRight())
        horizontal.setColorAt(0, QColor("#ffffff"))
        horizontal.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        p.fillRect(rect, horizontal)
        vertical = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        vertical.setColorAt(0, QColor(0, 0, 0, 0))
        vertical.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, vertical)
        x = rect.left() + self.s * rect.width()
        y = rect.top() + (1 - self.v) * rect.height()
        p.setPen(QPen(QColor("#ffffff" if self.v < 0.6 else "#111111"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(x, y), 6, 6)
        p.end()

    def _pick(self, pos):
        s = min(1.0, max(0.0, pos.x() / max(1, self.width())))
        v = 1 - min(1.0, max(0.0, pos.y() / max(1, self.height())))
        self.changed.emit(s, v)

    def mousePressEvent(self, event):
        self._pick(event.position())

    def mouseMoveEvent(self, event):
        self._pick(event.position())

    def mouseReleaseEvent(self, _event):
        self.released.emit()


class _HueBar(QWidget):
    """색조 무지개 막대."""
    changed = Signal(float)
    released = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.hue = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 1.5, -0.5, -1.5)
        gradient = QLinearGradient(rect.topLeft(), rect.topRight())
        for i in range(7):
            gradient.setColorAt(i / 6, QColor.fromHsvF((i / 6) % 1.0, 1, 1))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawRoundedRect(rect, 6, 6)
        x = rect.left() + self.hue * rect.width()
        p.setPen(QPen(QColor("#ffffff"), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(x - 3, 0.5, 6, self.height() - 1), 2, 2)
        p.end()

    def _pick(self, pos):
        self.changed.emit(min(0.999, max(0.0, pos.x() / max(1, self.width()))))

    def mousePressEvent(self, event):
        self._pick(event.position())

    def mouseMoveEvent(self, event):
        self._pick(event.position())

    def mouseReleaseEvent(self, _event):
        self.released.emit()


class ColorPickerDialog(QDialog):
    """직접 고르기 창: 네모판·색조 막대·색 코드·RGB가 서로 연동. 밝기·진하기 제한 없음, 고르는 동안 미리 적용."""
    color_changed = Signal(str)
    settled = Signal()  # 손을 뗌·색 코드 입력 — 묶어 둔 미리보기를 바로 적용

    def __init__(self, title: str, value: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._color = QColor(value)
        self._updating = False
        v = QVBoxLayout(self)
        v.setSpacing(10)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight:700;")
        v.addWidget(heading)
        self.square = _SvSquare()
        self.square.changed.connect(self._from_square)
        self.square.released.connect(self.settled)
        v.addWidget(self.square)
        self.hue_bar = _HueBar()
        self.hue_bar.changed.connect(self._from_hue)
        self.hue_bar.released.connect(self.settled)
        v.addWidget(self.hue_bar)
        row = QHBoxLayout()
        row.addWidget(QLabel("색 코드"))
        self.hex_edit = QLineEdit()
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setFixedWidth(90)
        self.hex_edit.editingFinished.connect(self._from_hex)
        row.addWidget(self.hex_edit)
        self.sample = QLabel()
        self.sample.setFixedSize(28, 22)
        row.addWidget(self.sample)
        row.addStretch(1)
        v.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("RGB"))
        self.rgb = {}
        for channel in ("R", "G", "B"):
            row.addWidget(QLabel(channel))
            spin = QSpinBox()
            spin.setRange(0, 255)
            spin.setSingleStep(1)  # 화살표·휠로 1씩
            spin.valueChanged.connect(self._from_rgb)
            self.rgb[channel] = spin
            row.addWidget(spin)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(hint_label("색 코드와 RGB는 서로 같이 바뀌어요.\n밝기까지 자유롭게 고르고, 즉시 미리 적용돼요."))
        self.adjusted = hint_label(ADJUSTED_TEXT)
        self.adjusted.hide()
        v.addWidget(self.adjusted)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = QPushButton("취소")
        self.cancel_btn.clicked.connect(self.reject)
        self.apply_btn = QPushButton("적용")
        self.apply_btn.setDefault(True)
        self.apply_btn.clicked.connect(self.accept)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.apply_btn)
        v.addLayout(buttons)
        self._sync(emit=False)

    def value(self) -> str:
        return self._color.name().upper()

    def set_adjusted(self, adjusted: bool):
        self.adjusted.setVisible(adjusted)

    # 한 곳을 바꾸면 내부 색 하나를 고친 뒤 나머지 칸을 다시 채운다(_updating으로 서로 다시 부르는 반복을 막음)
    def _from_square(self, s, v):
        h = self.square.hue
        self._set(QColor.fromHsvF(h, s, v), keep_hue=h)

    def _from_hue(self, h):
        s, v = self.square.s, self.square.v
        self._set(QColor.fromHsvF(h, s, v), keep_hue=h)

    def _from_hex(self):
        text = self.hex_edit.text().strip()
        if normalize(text if text.startswith("#") else "#" + text, None) is None:
            self._sync(emit=False)  # 잘못된 색 코드는 직전 값 유지
            return
        self._set(QColor(normalize(text if text.startswith("#") else "#" + text, None)))
        self.settled.emit()

    def _from_rgb(self, _value=None):
        if self._updating:
            return
        self._set(QColor(self.rgb["R"].value(), self.rgb["G"].value(), self.rgb["B"].value()))

    def _set(self, value: QColor, keep_hue: float | None = None):
        if self._updating:
            return
        if value.name().upper() == self.value() and keep_hue is None:
            return
        self._color = value
        self._sync(keep_hue=keep_hue)

    def _sync(self, emit=True, keep_hue=None):
        self._updating = True
        try:
            h, s, v, _a = self._color.getHsvF()
            self.square.hue = keep_hue if keep_hue is not None else (h if h >= 0 else self.square.hue)
            self.square.s, self.square.v = s, v
            self.hue_bar.hue = self.square.hue
            self.square.update()
            self.hue_bar.update()
            self.hex_edit.setText(self.value())
            self.sample.setStyleSheet(f"background:{self.value()}; border:1px solid palette(mid); border-radius:3px;")
            for channel, number in zip("RGB", (self._color.red(), self._color.green(), self._color.blue())):
                self.rgb[channel].setValue(number)
        finally:
            self._updating = False
        if emit:
            self.color_changed.emit(self.value())

    def sizeHint(self):
        return QSize(320, 380)
