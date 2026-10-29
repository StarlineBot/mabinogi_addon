"""Windows-sized controls must wrap without reducing fonts or hiding commands."""

import os
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtWidgets import QAbstractButton, QAbstractSpinBox, QComboBox, QFormLayout, QWidget

from test_navigation import window
from test_support.scroll_visibility import assert_control_reachable
from mabinogi_addon import config


def _top(widget, panel):
    return widget.mapTo(panel, widget.rect().topLeft()).y()


def _bottom(widget, panel):
    return widget.mapTo(panel, widget.rect().bottomLeft()).y()


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
        panel.lock_btn.setMinimumWidth(174)  # 0.27.0(명세 11.2): 전체 잠금/해제 → 잠금 버튼 하나
        for control in (*panel._alert_checks.values(), *panel._alert_spins.values()):
            control.setMinimumWidth(125)
    assert w._open_setup_feature(key)
    scroll = w._combat_pages[key]
    for _ in range(8):
        app.processEvents()
    primary = panel.region_row.itemAt(0, QFormLayout.ItemRole.LabelRole).widget()
    auxiliary = panel.region_row.itemAt(0, QFormLayout.ItemRole.FieldRole).widget()
    # Registration information is a separate row; these are now two command groups.
    # 0.27.0(명세 11절): 지정 전 정보 줄은 '영역 지정' 상자의 '● 아직 지정 안 됨' 줄
    assert _bottom(panel.region_section.unset_label, panel) <= _top(primary, panel)
    panel.clear_region_btn.setMinimumWidth(300)
    for _ in range(8):
        app.processEvents()
    assert auxiliary.y() >= primary.y() + primary.height()
    assert scroll.horizontalScrollBar().maximum() == 0
    for control in panel.findChildren(QAbstractButton) + panel.findChildren(QAbstractSpinBox) + panel.findChildren(QComboBox):
        if not control.isVisible():
            continue
        assert_control_reachable(control, app, key)
        assert control.font().pixelSize() == 20
    out = Path(os.environ.get("INTERACTION_RENDER_DIR", str(tmp_path)))
    out.mkdir(exist_ok=True)
    scroll.verticalScrollBar().setValue(0)
    app.processEvents()
    assert w.grab().save(str(out / f"{key}-windows-width.png"))
    for control in before:
        control.setMinimumWidth(0)
    panel.clear_region_btn.setMinimumWidth(0)
    if key == "stat_bars":
        for control in (panel.lock_btn, *panel._alert_checks.values(), *panel._alert_spins.values()):
            control.setMinimumWidth(0)
    for widget in w.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(12)
        widget.setFont(font)
    for _ in range(8):
        app.processEvents()
    assert auxiliary.y() == primary.y()
    assert _bottom(panel.region_section.unset_label, panel) <= _top(primary, panel)
    assert (panel.region_btn, panel.auto_find_btn, panel.view_region_btn) == before
    assert config._read_local_config() == saved
