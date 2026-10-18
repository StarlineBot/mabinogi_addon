"""Path text may wrap, but cannot push any control outside its viewport."""

from pathlib import PureWindowsPath
from copy import deepcopy

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QWidget

from scripts.qa_tuarim_settings_width import test_auto_find_button_remains_inside_viewport
from test_navigation import window
from mabinogi_addon import config

pytestmark = pytest.mark.usefixtures("tuarim_width_diagnostics")


@pytest.mark.parametrize("registered", [False, True])
def test_all_controls_accessible_with_non_ascii_deep_windows_path(window, registered):
    w, app = window
    saved = deepcopy(config._read_local_config())
    path = PureWindowsPath("C:/Users/한글 사용자/AppData/Local") / ("아주 긴 폴더 이름 " * 12) / "투아림 수집"
    w._open_setup_feature("tuarim")
    tab = w.tuarim_tab
    w.resource_tab.diagnostics_btn.setChecked(True)
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(20)
        widget.setFont(font)
    tab._shot_dir = path
    tab._update_collect_label()
    tab._region = dict(x=1,y=2,w=42,h=16) if registered else None
    tab._update_region_label()
    scroll = w._combat_pages["tuarim"]
    for _ in range(10):
        app.processEvents()
    assert scroll.horizontalScrollBar().maximum() == 0
    resource = w.resource_tab
    assert not resource.individual_btn.isChecked()
    assert not tab.region_btn.isVisible()
    for expanded in (False, True):
        resource.individual_btn.setChecked(expanded)
        controls = [("common_"+name, getattr(resource, name)) for name in
                    ("region_btn", "view_region_btn", "auto_find_btn", "clear_region_btn")]
        controls += [(name, getattr(tab, name)) for name in
                     ("enable", "snap_btn", "open_dir_btn", "collect_chk")]
        if expanded:
            controls += [("individual_"+name, getattr(controller, name))
                         for controller in (tab, w.dorcha_tab)
                         for name in ("region_btn", "view_region_btn", "clear_region_btn")]
        for name, widget in controls:
            assert widget.isVisible(), name
            scroll.ensureWidgetVisible(widget)
            for _ in range(8):
                app.processEvents()
            rect = QRect(widget.mapTo(scroll.viewport(), QPoint()), widget.size())
            assert scroll.viewport().rect().contains(rect), (name,rect,scroll.viewport().size())
            assert widget.visibleRegion().contains(widget.rect()), name
            assert widget.font().pixelSize() == 20
        assert not tab.auto_find_btn.isVisible()
        assert scroll.horizontalScrollBar().maximum() == 0
    assert str(path) in tab.collect_label.text()
    assert tab.collect_label.toolTip() == str(path)
    assert tab.collect_label.hasHeightForWidth()
    layout, height = tab.collect_label._text_layout(tab.collect_label.width())
    assert height <= tab.collect_label.height()
    assert layout.lineCount() > 1
    for index in range(layout.lineCount()):
        assert layout.lineAt(index).naturalTextWidth() <= tab.collect_label.width()
    assert config._read_local_config() == saved
