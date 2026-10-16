"""Unresolved Dorcha manual selector closeEvent stall; explicit pytest run."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.ui.dorcha_tab import DorchaTab
from mabinogi_addon.ui.region_selector import RegionSelector


@pytest.fixture
def runtime(monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = {"dorcha": {"enabled": True, "box": dict(x=941, y=948, w=28, h=23)}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    # Avoid a real desktop screenshot; retain the actual widget close/key events.
    monkeypatch.setattr(RegionSelector, "start", lambda self: self.show())
    tab = DorchaTab(SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False))
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: None)
    monkeypatch.setattr(tab, "_flash_region", lambda: None)
    assert tab._timer.isActive()
    try:
        yield app, tab
    finally:
        tab.shutdown()
        for widget in (tab._selector, tab._overlay):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        tab.close()
        tab.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("recovery", ("none", "toggle", "reopen-escape"))
def test_regular_close_event_must_not_permanently_stop_tracking(runtime, recovery):
    app, tab = runtime
    tab._on_region()
    assert not tab._timer.isActive() and tab._selector_timer_was_running
    tab._selector.close()
    app.processEvents()
    if recovery == "toggle":
        tab.enable.setChecked(False)
        tab.enable.setChecked(True)
    elif recovery == "reopen-escape":
        tab._on_region()
        QTest.keyClick(tab._selector, Qt.Key.Key_Escape)
        app.processEvents()
    assert tab._timer.isActive(), "normal selector close left Dorcha polling stopped"


def test_explicit_escape_resumes_tracking(runtime):
    app, tab = runtime
    tab._on_region()
    QTest.keyClick(tab._selector, Qt.Key.Key_Escape)
    app.processEvents()
    assert tab._timer.isActive()


def test_successful_selection_resumes_tracking(runtime):
    _, tab = runtime
    tab._on_region()
    tab._selector.selected.emit(50, 60, 28, 23)
    assert tab._timer.isActive()


def test_shutdown_never_restarts_timer_from_late_cancel(runtime):
    _, tab = runtime
    tab._on_region()
    selector = tab._selector
    tab.shutdown()
    selector.cancelled.emit()
    assert tab._shutting_down and not tab._timer.isActive()
