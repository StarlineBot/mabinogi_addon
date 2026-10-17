"""Repeated native reflow must preserve controls, settings and resources."""

from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from test_navigation import window
from mabinogi_addon import config


@pytest.mark.parametrize("key", ["boss", "stat_bars"])
def test_repeated_wrapping_has_no_control_overlap_or_state_writes(window, key):
    w, app = window
    panel = w.boss_tab if key == "boss" else w.stat_bars_tab
    assert w._open_setup_feature(key)
    app.processEvents()
    expected = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None
    controls = (panel.auto_find_btn, panel.region_btn, panel.view_region_btn)
    timers = set(w.findChildren(QTimer))
    windows = set(app.topLevelWidgets())
    for iteration in range(20):
        large = iteration % 2 == 0
        for widget in w.findChildren(QWidget):
            font = widget.font()
            font.setPixelSize(20 if large else 12)
            widget.setFont(font)
        for control in controls:
            control.setMinimumWidth(174 if large else 0)
        if key == "stat_bars":
            for control in (panel.lock_all_btn, panel.unlock_all_btn):
                control.setMinimumWidth(174 if large else 0)
            for control in (*panel._alert_checks.values(), *panel._alert_spins.values()):
                control.setMinimumWidth(125 if large else 0)
        for _ in range(4):
            app.processEvents()
        scroll = w._combat_pages[key]
        assert scroll.horizontalScrollBar().maximum() == 0
        widgets = (panel.findChildren(QAbstractButton) + panel.findChildren(QAbstractSpinBox)
                   + panel.findChildren(QComboBox))
        widgets = [control for control in widgets if control.isVisible()]
        rects = {control: QRect(control.mapTo(panel, QPoint()), control.size()) for control in widgets}
        for index, left in enumerate(widgets):
            for right in widgets[index+1:]:
                if left.isAncestorOf(right) or right.isAncestorOf(left):
                    continue
                assert not rects[left].intersects(rects[right]), (
                    key, iteration, type(left).__name__, rects[left], type(right).__name__, rects[right])
        for control in controls:
            scroll.ensureWidgetVisible(control)
            app.processEvents()
            rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
            assert scroll.viewport().rect().contains(rect)
        assert (panel.auto_find_btn, panel.region_btn, panel.view_region_btn) == controls
        assert set(w.findChildren(QTimer)) == timers
        assert set(app.topLevelWidgets()) == windows
        actual = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None
        assert actual == expected
