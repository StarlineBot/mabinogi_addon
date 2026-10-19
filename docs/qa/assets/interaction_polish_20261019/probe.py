"""Independent checks of focused editing, preset identities and region cancellation."""

from copy import deepcopy
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_resource_common_settings import common  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui import region_registration as registration  # noqa: E402
from mabinogi_addon.ui.buff_tab import ANCHOR_ID  # noqa: E402


def settle(app):
    for _ in range(12):
        app.processEvents()


@pytest.mark.parametrize("mouse_selection", [False, True])
def test_pending_buff_name_survives_anchor_transition(window, mouse_selection):
    w, app = window
    w._open_setup_feature("buff")
    tab = w.buff_tab
    tab.buff_list.setCurrentRow(1)
    settle(app)
    original_id = tab._current_id()
    original_anchor = deepcopy(tab._settings[ANCHOR_ID])
    tab.name_edit.setFocus()
    QTest.keyClick(tab.name_edit, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(tab.name_edit, "QA pending name")
    assert tab.name_edit.hasFocus()
    if mouse_selection:
        point = tab.buff_list.visualItemRect(tab.buff_list.item(0)).center()
        QTest.mouseClick(tab.buff_list.viewport(), Qt.MouseButton.LeftButton, pos=point)
    else:
        tab.buff_list.setCurrentRow(0)
    settle(app)
    assert tab._current_id() == tab._current == ANCHOR_ID
    assert tab._form_stack.currentWidget() is tab.anchor_panel
    assert tab._settings[ANCHOR_ID] == original_anchor
    assert tab._settings[original_id].name == "QA pending name"
    tab.buff_list.setCurrentRow(tab._rows().index(original_id))
    assert tab.name_edit.text() == "QA pending name"
    saved = {item.id: item for item in config.load_buff_settings()}
    assert saved[original_id].name == "QA pending name"


def test_combo_selection_and_failed_load_do_not_redirect_save(window, monkeypatch):
    w, app = window
    tab = w.custom_overlay_tab
    box = dict(x=1, y=2, w=40, h=40, posX=100, posY=100, name="QA")
    for name in ("A", "B", "C"):
        config.save_custom_preset(name, [box])
    config.save_auto_preset("C")
    tab._refresh_presets()
    tab.preset_combo.setCurrentIndex(tab.preset_combo.findData("A"))
    tab.preset_load_btn.click()
    assert tab._active_preset == "A"
    tab.preset_combo.setCurrentIndex(tab.preset_combo.findData("B"))
    before_b = deepcopy(config.load_custom_presets()["B"])
    tab._mgr.add({**box, "name": "second"})
    def denied(*args, **kwargs):
        raise PermissionError("QA write denial")
    with monkeypatch.context() as patch:
        patch.setattr(config, "save_custom_edit", denied)
        tab.preset_load_btn.click()
        assert tab._active_preset == "A"
        assert tab.save_status.text() == "저장 실패"
    assert tab.flush_pending()
    assert len(config.load_custom_presets()["A"]) == 2
    assert config.load_custom_presets()["B"] == before_b
    assert config.load_auto_preset() == "C"
    monkeypatch.setattr(QInputDialog, "getText", lambda *args: ("D", True))
    tab.save_btn.click()
    assert tab._active_preset == "D"
    assert tab.preset_combo.currentData() == "B"
    tab._mgr.clear()
    assert tab.flush_pending()
    assert config.load_custom_presets()["D"] == []
    assert len(config.load_custom_presets()["A"]) == 2
    assert config.load_custom_presets()["B"] == before_b
    assert config.load_auto_preset() == "C"


def test_real_region_acceptance_allows_clear_during_detection(common, monkeypatch):
    w, view, _, approvals, _ = common
    tab = w.dorcha_tab
    registration.save_boxes(tab, {"dorcha": (534, 122, 28, 23)})
    tab._accept_region(534, 122, 28, 23)
    assert tab.clear_region_btn.isEnabled()
    monkeypatch.setattr(registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    QTimer.singleShot(0, tab.clear_region_btn.click)
    assert view.find_regions() == {}
    assert config.load_dorcha()["box"] is None
    assert tab._region is None
    assert not approvals
