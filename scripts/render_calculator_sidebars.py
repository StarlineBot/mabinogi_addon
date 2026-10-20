"""Render calculator lists with sample prices and isolated external devices/network.

PYTHONPATH=src:. QT_QPA_PLATFORM=offscreen python scripts/render_calculator_sidebars.py OUTPUT_DIR
Set CALCULATOR_PREVIEW_THEME=light for the native light palette.
"""

import json
import math
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPalette, QTextLayout, QTextOption
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from test_support.boundaries import ExternalBoundaries
from mabinogi_addon.market import exchange as exchange_calc
from mabinogi_addon.ui.dungeon_cost_tab import DungeonCostTab
from mabinogi_addon.ui.exchange_tab import ExchangeTab



def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    palette = QPalette(app.palette())
    for role, color in (
        (QPalette.Window, '#141b27'), (QPalette.WindowText, '#e5e7eb'),
        (QPalette.Base, '#202938'), (QPalette.AlternateBase, '#253246'),
        (QPalette.Text, '#e5e7eb'), (QPalette.Button, '#273449'),
        (QPalette.ButtonText, '#e5e7eb'), (QPalette.Highlight, '#227e72'),
        (QPalette.HighlightedText, '#ffffff')):
        if os.environ.get('CALCULATOR_PREVIEW_THEME') != 'light':
            palette.setColor(role, QColor(color))
    app.setPalette(palette)


    def settle():
        for _ in range(10):
            app.processEvents()


    def pair(images, labels, destination):
        widths = [round(i.width() / i.devicePixelRatio()) for i in images]
        heights = [round(i.height() / i.devicePixelRatio()) for i in images]
        canvas = QImage(sum(widths) + 36, max(heights) + 48, QImage.Format_RGB32)
        canvas.fill(QColor('#101722'))
        painter = QPainter(canvas)
        painter.setPen(QColor('#ffffff'))
        font = QFont(app.font())
        font.setPixelSize(15)
        painter.setFont(font)
        x = 12
        for image, width, height, label in zip(images, widths, heights, labels):
            painter.drawText(QPoint(x, 24), label)
            painter.drawImage(QRect(x, 36, width, height), image)
            x += width + 12
        painter.end()
        assert canvas.save(str(destination))


    results = []
    with ExternalBoundaries() as boundary:
        cost, exchange = DungeonCostTab(), ExchangeTab()
        try:
            for name in exchange_calc.REGION_NAMES:
                exchange._cache[name] = (time.time(), exchange_calc.calc_region(name, lambda material: 1000000))
            for pixels in (12, 20):
                for widget in (cost, exchange):
                    for child in [widget, *widget.findChildren(QWidget)]:
                        font = QFont(child.font())
                        font.setFamily('Noto Sans CJK KR')
                        font.setPixelSize(pixels)
                        child.setFont(font)
                    widget.resize(790, 760)
                    widget.show()
                cost.dungeons.setCurrentRow(0)
                exchange.region_list.setCurrentRow(2)
                settle()
                sidebars = (cost.dungeons, exchange.region_list)
                assert sidebars[0].width() == sidebars[1].width() >= 136
                for name, widget, sidebar in zip(('entry', 'exchange'), (cost, exchange), sidebars):
                    assert sidebar.horizontalScrollBar().maximum() == 0, (name,pixels,sidebar.width(),sidebar.sizeHintForColumn(0),sidebar.viewport().width(),sidebar.horizontalScrollBar().maximum())
                    assert widget.table.width() >= 500
                    for i in range(sidebar.count()):
                        item = sidebar.item(i)
                        rect = sidebar.visualItemRect(item)
                        width = rect.width() - 16
                        layout = QTextLayout(item.text(), sidebar.font())
                        option = QTextOption()
                        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
                        layout.setTextOption(option)
                        height = 0
                        layout.beginLayout()
                        while True:
                            line = layout.createLine()
                            if not line.isValid():
                                break
                            line.setLineWidth(width)
                            height += line.height()
                        layout.endLayout()
                        assert math.ceil(height) + 14 <= rect.height(), (name,pixels,item.text(),height,rect)
                    results.append({'name':name,'font_pixels':pixels,'width':sidebar.width(),
                                    'rows':[sidebar.visualItemRect(sidebar.item(i)).height() for i in range(sidebar.count())],
                                    'table_width':widget.table.width()})
                    sidebar.setFocus()
                    settle()
                    QTest.keyClick(sidebar, Qt.Key_Down)
                    assert sidebar.currentRow() == (1 if name == 'entry' else 3)
                    QTest.keyClick(sidebar, Qt.Key_Up)
                    assert sidebar.currentRow() == (0 if name == 'entry' else 2)
                    QTest.mouseClick(sidebar.viewport(), Qt.LeftButton,
                                     pos=sidebar.visualItemRect(sidebar.item(1)).center())
                    assert sidebar.currentRow() == 1
                cost.dungeons.setCurrentRow(0)
                exchange.region_list.setCurrentRow(2)
                exchange.region_list.clearFocus()
                settle()
                pair([w.grab().toImage() for w in (cost,exchange)],
                     ['던전 입장 계산기 · 샘플 계산 결과', '환전비율 계산기 · 샘플 시세'],
                     out / f'calculator-sidebars-{pixels}.png')
                # Both controls use the same native selection, hover and keyboard focus drawing.
                snapshots = []
                labels = []
                for state in ('default', 'selected', 'hover', 'keyboard-focus'):
                    for name, sidebar in zip(('entry','exchange'),sidebars):
                        sidebar.clearFocus()
                        sidebar.clearSelection()
                        QTest.mouseMove(sidebar.viewport(), QPoint(5, sidebar.height()-5))
                        if state != 'default':
                            sidebar.setCurrentRow(0)
                            sidebar.item(0).setSelected(True)
                        if state == 'hover':
                            QTest.mouseMove(sidebar.viewport(), sidebar.visualItemRect(sidebar.item(1)).center())
                        if state == 'keyboard-focus':
                            sidebar.activateWindow()
                            sidebar.setFocus(Qt.TabFocusReason)
                        settle()
                        image = sidebar.grab().toImage()
                        crop = QRect(0,0,image.width(),round(240*image.devicePixelRatio()))
                        snapshots.append(image.copy(crop))
                        labels.append(f'{name[:3]} {state[:3]}')
                pair(snapshots, labels, out / f'calculator-sidebar-states-{pixels}.png')
            assert not boundary.violations, boundary.violations
        finally:
            cost.shutdown()
            cost.close()
            exchange.close()
            cost.deleteLater()
            exchange.deleteLater()
            settle()
    print(json.dumps(results,ensure_ascii=False))


if __name__ == "__main__":
    main()
