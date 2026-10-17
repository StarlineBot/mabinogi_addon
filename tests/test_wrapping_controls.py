"""Windows-sized controls must wrap without reducing fonts or hiding commands."""

import os
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QFormLayout, QWidget

from test_navigation import window
from mabinogi_addon import config


@pytest.mark.parametrize("key", ["boss", "stat_bars"])
def test_windows_minimum_widths_wrap_and_restore_without_state_changes(window, key, tmp_path):
    w, app = window
    panel = w.boss_tab if key == "boss" else w.stat_bars_tab
    saved = deepcopy(config._read_local_config())
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(20)
        widget.setFont(font)
    before = (panel.region_btn, panel.auto_find_btn, panel.view_region_btn)
    for control in before:
        control.setMinimumWidth(174)
    if key == "stat_bars":
        for control in (panel.lock_all_btn, panel.unlock_all_btn):
            control.setMinimumWidth(174)
        for control in (*panel._alert_checks.values(), *panel._alert_spins.values()):
            control.setMinimumWidth(125)
    assert w._open_setup_feature(key)
    scroll = w._combat_pages[key]
    for _ in range(8):
        app.processEvents()
    label = panel.region_row.itemAt(0, QFormLayout.ItemRole.LabelRole).widget()
    commands = panel.region_row.itemAt(0, QFormLayout.ItemRole.FieldRole).widget()
    assert commands.y() >= label.y() + label.height()
    assert scroll.horizontalScrollBar().maximum() == 0
    for control in panel.findChildren(QAbstractButton) + panel.findChildren(QAbstractSpinBox) + panel.findChildren(QComboBox):
        if not control.isVisible():
            continue
        scroll.ensureWidgetVisible(control)
        for _ in range(3):
            app.processEvents()
        rect = QRect(control.mapTo(scroll.viewport(), QPoint()), control.size())
        assert scroll.viewport().rect().contains(rect), (key, control, rect)
        assert control.font().pixelSize() == 20
    out = Path(os.environ.get("INTERACTION_RENDER_DIR", str(tmp_path)))
    out.mkdir(exist_ok=True)
    scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    assert w.grab().save(str(out / f"{key}-windows-width.png"))
    for control in before:
        control.setMinimumWidth(0)
    if key == "stat_bars":
        for control in (panel.lock_all_btn, panel.unlock_all_btn, *panel._alert_checks.values(), *panel._alert_spins.values()):
            control.setMinimumWidth(0)
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(12)
        widget.setFont(font)
    for _ in range(8):
        app.processEvents()
    assert commands.y() == label.y()
    assert (panel.region_btn, panel.auto_find_btn, panel.view_region_btn) == before
    assert config._read_local_config() == saved
