"""Actual button visibility, separate from a nonzero hidden scrollbar range."""

from pathlib import Path, PureWindowsPath
import sys

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window


@pytest.mark.parametrize("path", ["C:/Users/qa/AppData/Local/MabinogiAddon/data/tuarim_shots",
    r"D:\a\mabinogi_addon\mabinogi_addon\tests\data\tuarim_shots",
    r"C:\Users\runneradmin\AppData\Local\Temp\pytest-of-runneradmin\pytest-0\test_seeded_navigation_and_tou3\app\data\tuarim_shots"])
@pytest.mark.parametrize("registered", [False, True])
def test_auto_find_button_remains_inside_viewport(window, path, registered, tmp_path):
    w, app = window
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(20)
        widget.setFont(font)
    w._open_setup_feature("tuarim")
    tab = w.tuarim_tab
    tab._shot_dir = PureWindowsPath(path)
    tab._update_collect_label()
    tab._region = dict(x=121, y=233, w=42, h=16) if registered else None
    tab._update_region_label()
    for _ in range(10):
        app.processEvents()
    scroll = w._combat_pages["tuarim"]
    view = scroll.viewport()
    print({"path":str(tab._shot_dir), "registered":registered, "viewport":view.width(), "tab":tab.width(),
           "min_hint":tab.minimumSizeHint().width(), "range":scroll.horizontalScrollBar().maximum(),
           "label_width":tab.collect_label.width(), "label_min_hint":tab.collect_label.minimumSizeHint().width()})
    resource = w.resource_tab
    for expanded in (False, True):
        resource.individual_btn.setChecked(expanded)
        controls = [getattr(resource, name) for name in
                    ("auto_find_btn", "region_btn", "view_region_btn", "clear_region_btn")]
        if expanded:
            controls += [getattr(tab, name) for name in
                         ("region_btn", "view_region_btn", "clear_region_btn")]
        for button in controls:
            assert button.isVisible()
            scroll.ensureWidgetVisible(button)
            for _ in range(8):
                app.processEvents()
            rect = QRect(button.mapTo(view, QPoint()), button.size())
            assert view.rect().contains(rect), (button.text(), rect, view.rect())
            assert button.visibleRegion().contains(button.rect())
        assert scroll.horizontalScrollBar().maximum() == 0
