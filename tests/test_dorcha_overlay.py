import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from mabinogi_addon.ui.dorcha_overlay import DorchaOverlay, BAR_WIDTH
from PySide6.QtGui import QFont, QFontMetrics


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


@pytest.mark.parametrize('scale',[.5,1,1.25,1.5,2,3])
def test_display_modes_keep_geometry_and_hide_dorcha_pixels_for_percent_only(scale):
    app = QApplication.instance() or QApplication([])
    overlay = DorchaOverlay(scale)
    overlay.move(-400,120)
    size,position,cells = overlay.size(),overlay.pos(),overlay.cell_rects()
    try:
        font = QFont()
        font.setPixelSize(max(9,round(18*scale)))
        font.setBold(True)
        metrics = QFontMetrics(font)
        assert max(metrics.horizontalAdvance(t) for t in ('99%','--%','15/15','--/15'))+4 < BAR_WIDTH*scale/2
        for show_d,show_t in ((True,False),(False,True),(True,True),(False,False)):
            overlay.set_elements(show_d,show_t)
            for value in (0,95,99,None,100):
                overlay.set_percent(value)
                overlay.set_value(13)
                assert overlay.percent == (value if value is not None and value < 100 else None)
                assert overlay.size() == size and overlay.pos() == position and overlay.cell_rects() == cells
                assert overlay.locked
                image = QImage(size,QImage.Format.Format_RGBA8888)
                image.fill(Qt.GlobalColor.transparent)
                overlay.render(image)
                pixels = np.frombuffer(image.constBits(),np.uint8).reshape(size.height(),size.width(),4)
                alpha = [pixels[int(rect.center().y()),int(rect.center().x()),3] for rect in cells]
                assert all(a > 0 for a in alpha) if show_d else not any(alpha)
    finally:
        overlay.close();overlay.deleteLater();app.processEvents()
