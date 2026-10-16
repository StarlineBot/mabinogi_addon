import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.dorcha_overlay import DorchaOverlay, BAR_WIDTH


@pytest.mark.parametrize("scale", [.5,1,1.5,3])
def test_fifteen_cells_and_values_share_fixed_geometry(scale):
    app = QApplication.instance() or QApplication([])
    overlay = DorchaOverlay(scale)
    try:
        size = overlay.size()
        cells = overlay.cell_rects()
        assert len(cells) == 15
        assert cells[-1].right() - cells[0].left() == pytest.approx(BAR_WIDTH*scale)
        assert cells[5].left()-cells[4].right() > cells[1].left()-cells[0].right()
        assert cells[10].left()-cells[9].right() > cells[1].left()-cells[0].right()
        for value in (None,*range(16)):
            overlay.set_value(value)
            assert overlay.size() == size and overlay.cell_rects() == cells
            image = QImage(size,QImage.Format.Format_RGBA8888)
            image.fill(Qt.GlobalColor.transparent)
            overlay.render(image)
            pixels = np.frombuffer(image.constBits(),np.uint8).reshape(size.height(),size.width(),4)
            filled = sum(pixels[int(rect.center().y()),int(rect.center().x()),0] > 100 for rect in cells)
            assert filled == (value or 0)
        assert overlay.locked and overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        overlay.close()
        overlay.deleteLater()
        app.processEvents()
