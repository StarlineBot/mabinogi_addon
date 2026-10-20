"""계산기의 지역/던전 선택 목록에 같은 밀도와 기본 Qt 상태 표시를 적용한다."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QListWidget, QStyle

from ..market.dungeon_cost import NAMES
from ..market.exchange import REGION_NAMES


def calculator_sidebar(names):
    return _CalculatorSidebar(names)


class _CalculatorSidebar(QListWidget):
    def __init__(self, names):
        super().__init__()
        self.addItems(names)
        self.setStyleSheet("QListWidget::item { padding:7px 8px; }")
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self._fit_width()

    def _fit_width(self):
        # Both tabs reserve the same space for the longest label at the current font.
        labels = (*NAMES, *REGION_NAMES)
        text_width = max(self.fontMetrics().horizontalAdvance(name) for name in labels)
        # Qt's item delegate adds one pixel beyond each focus-frame margin for text.
        focus_margin = self.style().pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self) + 1
        self.setFixedWidth(max(136, text_width + 16 + 2 * (self.frameWidth() + focus_margin)))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_width()
