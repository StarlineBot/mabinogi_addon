"""Independent cross-feature clearing and click-only logging checks."""

from copy import deepcopy
import logging
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from mabinogi_addon import config  # noqa: E402
from mabinogi_addon.ui import region_registration  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402


@pytest.mark.parametrize("key", ["dorcha", "tuarim"])
def test_clearing_one_live_resource_preserves_other_region_options_and_value(runtime, monkeypatch, key):
    w, state, pump = runtime
    d, t = w.dorcha_tab, w.tuarim_tab
    d.enable.setChecked(True)
    w.resource_tab.percent_chk.setChecked(True)
    t.enable.setChecked(True)
    raw = config._read_local_config()
    raw.setdefault("dorcha", {})["box"] = dict(d._region)
    raw.setdefault("tuarim", {})["box"] = dict(t._region)
    config._write_local_config(raw)
    pump()
    assert d._overlay.value == 13 and d._overlay.percent == 95
    assert state.fired == [90, 95]
    before = deepcopy(config._read_local_config())
    timers = set(w.findChildren(QTimer))
    monkeypatch.setattr(region_registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    tab = d if key == "dorcha" else t
    tab.clear_region_btn.click()
    pump()
    after = config._read_local_config()
    expected = deepcopy(before)
    expected[key]["box"] = None
    assert after == expected
    assert tab._region is None
    assert d._overlay.value == (None if key == "dorcha" else 13)
    assert d._overlay.percent == (95 if key == "dorcha" else None)
    assert state.fired == [90, 95]
    assert set(w.findChildren(QTimer)) == timers


def test_initial_click_denial_logs_count_once_but_automatic_ticks_are_silent(window, caplog):
    w, _ = window
    d = w.creator_dialogue
    d.timer.stop()
    d.visibility = lambda *args: False
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.creator_dialogue")
    d.face.click()
    records = [r for r in caplog.records if r.name == "mabinogi_addon.ui.creator_dialogue"]
    assert len(records) == 1
    assert "Windows" in records[0].getMessage() and "유효 대사" in records[0].getMessage()
    for _ in range(100):
        d.tick()
    assert len([r for r in caplog.records if r.name == records[0].name]) == 1


def test_no_selectable_dialogue_is_diagnosed_without_false_display(window, caplog):
    w, _ = window
    d = w.creator_dialogue
    d.timer.stop()
    d.visibility = lambda *args: True
    d.session.entries = ()
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.creator_dialogue")
    d.face.click()
    assert not d.bubble.isVisible()
    assert "선택 가능한 대사 없음 (유효 대사 0개)" in caplog.text
