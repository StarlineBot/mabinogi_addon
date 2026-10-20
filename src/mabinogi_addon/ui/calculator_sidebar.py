"""계산기의 지역/던전 선택 목록에 같은 밀도와 기본 Qt 상태 표시를 적용한다."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QStandardItemModel
from PySide6.QtWidgets import QListWidget, QStyleOptionViewItem

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
        model = QStandardItemModel(len(labels), 1)
        option = QStyleOptionViewItem()
        self.initViewItemOption(option)
        widths = []
        for row, label in enumerate(labels):
            index = model.index(row, 0)
            model.setData(index, label)
            widths.append(self.itemDelegate().sizeHint(option, index).width())
        self.setFixedWidth(max(136, max(widths) + 2 * self.frameWidth()))

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._fit_width()
