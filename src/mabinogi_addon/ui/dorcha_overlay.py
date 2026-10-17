"""A stable fifteen-cell resource display, separate from the source game UI."""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

BAR_WIDTH = 225
BAR_HEIGHT = 16
LABEL_HEIGHT = 22
LABEL_GAP = 4
PAD = 4


class DorchaOverlay(QWidget):
    moved = Signal()

    def __init__(self, scale=1.5, parent=None):
        flags = (Qt.WindowType.Widget if parent is not None else
                 Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, parent is None)
        self.setAutoFillBackground(parent is not None)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._scale = scale
        self._value = None
        self._percent = None
        self._show_dorcha = True
        self._show_tuarim = False
        self._locked = True
        self._drag_offset = None
        self.set_scale(scale)
        self.set_locked(True)

    @property
    def locked(self):
        return self._locked

    @property
    def value(self):
        return self._value

    def set_value(self, value):
        value = value if type(value) is int and 0 <= value <= 15 else None
        if value != self._value:
            self._value = value
            self.update()

    def set_scale(self, scale):
        self._scale = max(.5, min(3.0, scale))
        self.setFixedSize(round(BAR_WIDTH * self._scale) + PAD * 2,
                          round((LABEL_HEIGHT + LABEL_GAP + BAR_HEIGHT) * self._scale) + PAD * 2)
        self.update()

    @property
    def percent(self):
        return self._percent

    def set_percent(self, value):
        value = value if type(value) is int and 0 <= value < 100 else None
        if value != self._percent:
            self._percent = value
            self.update()

    def set_elements(self, dorcha, tuarim):
        elements = bool(dorcha), bool(tuarim)
        if elements != (self._show_dorcha,self._show_tuarim):
            self._show_dorcha, self._show_tuarim = elements
            self.update()

    def set_locked(self, locked):
        from ..system.clickthrough import set_click_through
        if locked and self._drag_offset is not None:
            from . import grid
            grid.hide_guide()
            self._drag_offset = None
        self._locked = locked
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, locked)
        if self.isWindow():
            set_click_through(self, locked)
        self.update()

    def cell_rects(self):
        scale = self._scale
        gap, group_gap = 2 * scale, 5 * scale
        cell = (BAR_WIDTH * scale - 12 * gap - 2 * group_gap) / 15
        x = PAD
        result = []
        for index in range(15):
            result.append(QRectF(x, PAD + (LABEL_HEIGHT + LABEL_GAP) * scale,
                                 cell, BAR_HEIGHT * scale))
            x += cell + (group_gap if index in (4, 9) else gap)
        return result

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, rect in enumerate(self.cell_rects() if self._show_dorcha else []):
            painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
            painter.setBrush(QColor(170, 85, 218) if self._value is not None and index < self._value
                             else QColor(42, 42, 49, 225))
            painter.drawRoundedRect(rect, 2 * self._scale, 2 * self._scale)
        font = QFont()
        font.setPixelSize(max(9, round(18 * self._scale)))
        font.setBold(True)
        painter.setFont(font)
        rect = QRectF(PAD, PAD, BAR_WIDTH * self._scale, LABEL_HEIGHT * self._scale).toRect()
        labels = []
        if self._show_dorcha:
            labels.append((f"{self._value}/15" if self._value is not None else "--/15",Qt.AlignmentFlag.AlignRight))
        if self._show_tuarim:
            labels.append((f"{self._percent}%" if self._percent is not None else "--%",Qt.AlignmentFlag.AlignLeft))
        for text,side in labels:
            alignment = side | Qt.AlignmentFlag.AlignVCenter
            painter.setPen(QColor(0, 0, 0))
            for x, y in ((-1,0),(1,0),(0,-1),(0,1)):
                painter.drawText(rect.translated(x,y), alignment, text)
            painter.setPen(QColor(255,255,255))
            painter.drawText(rect, alignment, text)
        if not self._locked:
            painter.setPen(QPen(QColor(0,209,167), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0,0,-1,-1))
        painter.end()

    def mousePressEvent(self, event):
        if not self._locked and event.button() == Qt.MouseButton.LeftButton:
            from . import grid
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self._snap = grid.enabled()
            self._grid_size = grid.size()
            if self._snap:
                grid.show_guide()
            event.accept()

    def mouseMoveEvent(self, event):
        if not self._locked and self._drag_offset is not None:
            from . import grid
            target = event.globalPosition().toPoint() - self._drag_offset
            self.move(grid.snap(target, self._grid_size) if self._snap else target)
            event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            from . import grid
            grid.hide_guide()
            self._drag_offset = None
            self.moved.emit()

    def closeEvent(self, event):
        if self._drag_offset is not None:
            from . import grid
            grid.hide_guide()
            self._drag_offset = None
        super().closeEvent(event)
