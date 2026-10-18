"""Registration, selection and transactional removal are independent states."""

from copy import deepcopy

import pytest
from PySide6.QtCore import QObject, Signal, QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QMessageBox

from test_setup import settings, BOX, app
from mabinogi_addon import config, setup_state
from mabinogi_addon.ui.region_registration import REGIONS, connect_selection
from mabinogi_addon.ui import region_registration


class Selector(QObject):
    selected = Signal(int, int, int, int)


@pytest.fixture
def panels(app, settings):
    from types import SimpleNamespace
    from mabinogi_addon.ui.buff_tab import BuffTab
    from mabinogi_addon.ui.debuff_tab import DebuffTab
    from mabinogi_addon.ui.boss_tab import BossTab
    from mabinogi_addon.ui.stat_bars_tab import StatBarsTab
    from mabinogi_addon.ui.skillbar_tab import SkillbarTab
    from mabinogi_addon.ui.dorcha_tab import DorchaTab
    from mabinogi_addon.ui.tuarim_tab import TuarimTab
    raw = config._read_local_config()
    for key, (name, field, _) in REGIONS.items():
        raw.setdefault(name, {}).update({field: dict(x=10, y=20) if key == "skillbar" else dict(BOX),
                                        "enabled": False, "preserved": "unchanged"})
    config._write_local_config(raw)
    watcher = SimpleNamespace(is_game_active=lambda: False, is_self_active=lambda: False)
    tabs = SimpleNamespace(buff_tab=BuffTab(), debuff_tab=DebuffTab(), boss_tab=BossTab(watcher),
        stat_bars_tab=StatBarsTab(watcher), skillbar_tab=SkillbarTab(watcher),
        dorcha_tab=DorchaTab(watcher), tuarim_tab=TuarimTab(watcher))
    for tab in vars(tabs).values():
        for timer in tab.findChildren(QTimer):
            timer.stop()
    try:
        yield tabs, app
    finally:
        for tab in vars(tabs).values():
            if hasattr(tab, "shutdown"):
                tab.shutdown()
            tab.close()
            tab.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


@pytest.fixture
def registered(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow
    from PySide6.QtWidgets import QApplication
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    raw = config._read_local_config()
    for key, (name, field, _) in REGIONS.items():
        raw.setdefault(name, {}).update({field: dict(x=10, y=20) if key == "skillbar" else dict(BOX),
                                        "enabled": False, "preserved": "unchanged"})
    config._write_local_config(raw)
    w = MainWindow()
    w._post_show_done = True
    w.show()
    w._leave_setup()
    w._booting = False
    for timer in w.findChildren(QTimer):
        timer.stop()
    app.processEvents()
    try:
        yield w, app
    finally:
        w._force_quit = True
        w.close()
        w.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def controller(w, key):
    return getattr(w, {"stat_bars": "stat_bars_tab"}.get(key, key + "_tab"))


@pytest.mark.parametrize("key", REGIONS)
def test_clear_only_removes_its_region_and_preserves_options(panels, monkeypatch, key):
    w, app = panels
    tab = controller(w, key)
    before = deepcopy(config._read_local_config())
    name, field, _ = REGIONS[key]
    monkeypatch.setattr(region_registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    tab.clear_region_btn.click()
    expected = deepcopy(before)
    expected[name][field] = None
    assert config._read_local_config() == expected
    if key in ("buff", "debuff", "boss", "stat_bars", "skillbar"):
        assert not setup_state.enabled(key)
    if key in ("dorcha", "tuarim", "stat_bars", "boss"):
        assert tab._region is None
    if key == "skillbar":
        assert tab._anchor is None
    for other in REGIONS:
        if other != key:
            sec, attribute, _ = REGIONS[other]
            assert config._read_local_config()[sec][attribute] == before[sec][attribute]
    if key == "boss":
        assert not w.boss_tab.is_boss_present()
        assert not w.boss_tab._overlay.isVisible()


@pytest.mark.parametrize("key", REGIONS)
@pytest.mark.parametrize("failure", ["cancel", "permission"])
def test_failed_or_cancelled_clear_preserves_disk_and_memory(panels, monkeypatch, key, failure):
    w, _ = panels
    tab = controller(w, key)
    before = deepcopy(config._read_local_config())
    region = deepcopy(getattr(tab, "_region", getattr(tab, "_anchor", None)))
    warnings = []
    monkeypatch.setattr(region_registration, "confirm_clear", lambda *a: QMessageBox.StandardButton.No if failure == "cancel" else QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(region_registration, "warn", lambda *a: warnings.append(a))
    if failure == "permission":
        def denied(*a, **k):
            raise PermissionError("read only")
        monkeypatch.setattr(config, "_write_local_config", denied)
    tab.clear_region_btn.click()
    assert config._read_local_config() == before
    assert getattr(tab, "_region", getattr(tab, "_anchor", None)) == region
    assert bool(warnings) == (failure == "permission")


def test_selection_changes_no_execution_option_or_region(registered):
    w, _ = registered
    before = deepcopy(config._read_local_config())
    for key in setup_state.BY_KEY:
        w._set_feature_enabled(key, True)
        assert setup_state.selected(key)
        w._set_feature_enabled(key, False)
        assert not setup_state.selected(key)
    after = config._read_local_config()
    for key, value in before.items():
        if key != "general":
            assert after[key] == value
    for key in ("buff", "debuff", "boss", "stat_bars", "skillbar"):
        assert setup_state.enabled(key)


def test_shared_clear_discards_late_selector_and_updates_other_consumers(registered, monkeypatch):
    w, _ = registered

    selector = Selector(w.debuff_tab)
    received = []
    connect_selection(w.debuff_tab, selector, lambda *box: received.append(box))
    questions = []
    def confirm(*args):
        questions.append(args[2])
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(region_registration, "confirm_clear", confirm)
    w.boss_tab.clear_region_btn.click()
    selector.selected.emit(1, 2, 3, 4)
    selector.selected.disconnect()
    assert received == []
    assert "디버프" in questions[0]
    assert config.load_boss_bar_region() is None
    assert "미등록" in w.stat_bars_tab.boss_region_status.text()


def test_boss_reads_registered_region_even_if_legacy_switch_was_off(registered, monkeypatch):
    w, _ = registered
    called = []
    assert config.load_boss_pattern()["enabled"] is False
    monkeypatch.setattr(type(w.boss_tab), "_tick", lambda self: called.append(True))
    w.boss_tab._safe_tick()
    assert called == [True]
    assert not hasattr(w.buff_tab, "enable") and not hasattr(w.debuff_tab, "enable")
    assert not hasattr(w.stat_bars_tab, "enable") and not hasattr(w.skillbar_tab, "enable")


def test_newer_registration_during_clear_confirmation_is_not_deleted(panels, monkeypatch):
    w, _ = panels
    tab = w.dorcha_tab
    warnings = []
    monkeypatch.setattr(region_registration, "warn", lambda *args: warnings.append(args))
    def confirm(*args):
        tab._apply_region(5, 6, 28, 23)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(region_registration, "confirm_clear", confirm)
    tab.clear_region_btn.click()
    assert tab._region == dict(x=5, y=6, w=28, h=23)
    assert config.load_dorcha()["box"] == tab._region
    assert len(warnings) == 1


def test_autofind_approval_cannot_restore_a_cleared_region(panels, monkeypatch):
    from types import SimpleNamespace
    from mabinogi_addon.ui import autofind_confirm

    w, _ = panels
    tab = w.tuarim_tab
    monkeypatch.setattr(region_registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    def question(*args):
        tab.clear_region_btn.click()
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(autofind_confirm, "QMessageBox", SimpleNamespace(
        question=question, StandardButton=QMessageBox.StandardButton))
    def perform(key, capture, confirm):
        result = confirm((10, 20, 42, 16), 0, 0)
        assert result["status"] == "cancelled"
        return object(), 0, 0, (10, 20, 42, 16)
    monkeypatch.setattr(autofind_confirm, "perform_autofind", perform)
    monkeypatch.setattr(autofind_confirm, "to_logical", lambda *box: box)
    tab._on_auto_find()
    assert tab._region is None and config.load_tuarim()["box"] is None
    assert not tab._autofind_busy


def test_same_boss_can_be_tracked_after_clear_and_reregistration(panels, monkeypatch):
    import numpy as np
    from types import SimpleNamespace
    from mabinogi_addon.ui import boss_tab

    w, _ = panels
    tab = w.boss_tab
    tab._watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    monkeypatch.setattr(type(tab), "_grab_rect", lambda *args: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(type(tab), "_show_preview", lambda *args: None)
    monkeypatch.setattr(type(tab), "_flash_region", lambda *args: None)
    monkeypatch.setattr(boss_tab, "identify", lambda *args, **kwargs: "lenen_miir")
    monkeypatch.setattr(boss_tab, "read_percent", lambda *args, **kwargs: 90)
    monkeypatch.setattr(region_registration, "confirm_clear", lambda *args: QMessageBox.StandardButton.Yes)
    for _ in range(4):
        tab._tick()
    previous = tab._tracker
    assert previous is not None
    tab.clear_region_btn.click()
    assert tab._tracker is None and tab._cur_boss is None
    tab._on_selected(*(BOX[k] for k in ("x", "y", "w", "h")))
    for _ in range(4):
        tab._tick()
    assert tab._tracker is not None and tab._tracker is not previous
    assert tab._stable_hp == 90


def test_pair_registration_is_one_atomic_update_and_failure_keeps_both(panels, monkeypatch):
    w, _ = panels
    before = deepcopy(config._read_local_config())
    calls = []
    original = config._write_local_config
    def save(raw):
        calls.append(deepcopy(raw))
        original(raw)
    monkeypatch.setattr(config, "_write_local_config", save)
    boxes = {"boss": (1, 2, 523, 36), "debuff": (1, 3, 523, 80)}
    assert region_registration.save_boxes(w.boss_tab, boxes)
    assert len(calls) == 1
    for key, box in boxes.items():
        name, field, _ = REGIONS[key]
        assert config._read_local_config()[name][field] == dict(zip(("x", "y", "w", "h"), box))
    stored = deepcopy(config._read_local_config())
    def denied(*args):
        raise PermissionError("denied")
    monkeypatch.setattr(config, "_write_local_config", denied)
    monkeypatch.setattr(region_registration, "warn", lambda *args: None)
    monkeypatch.setattr(region_registration, "QMessageBox", type('Messages', (), {'warning': staticmethod(lambda *args: None)}))
    assert not region_registration.save_boxes(w.boss_tab, {"boss": (5, 6, 7, 8), "debuff": (5, 6, 7, 8)})
    assert config._read_local_config() == stored
    assert stored["bossPattern"]["enabled"] == before["bossPattern"]["enabled"]
