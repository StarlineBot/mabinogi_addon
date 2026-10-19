"""Independent access cycles, actual nested scrolling and cancelled disk writes."""

from copy import deepcopy
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtWidgets import QAbstractButton, QScrollArea, QWidget

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_navigation import window  # noqa: E402,F401
from test_resource_integration import runtime  # noqa: E402,F401
from mabinogi_addon import config, feature_access  # noqa: E402
from mabinogi_addon.ui import dpi  # noqa: E402


def settle(app):
    for _ in range(12):
        app.processEvents()


def finish(session):
    if session.thread is not None:
        session.thread.join(timeout=3)
        assert not session.thread.is_alive()
    return session.poll()


def test_fifty_account_cycles_preserve_public_display_and_alert_cycle(runtime, monkeypatch):
    w, state, pump = runtime
    account = {"id": feature_access.CREATOR_DISCORD_ID}
    monkeypatch.setattr(config, "load_discord_user", lambda: account or None)
    d, t = w.dorcha_tab, w.tuarim_tab
    d.enable.setChecked(True)
    w.resource_tab.percent_chk.setChecked(True)
    t.enable.setChecked(True)
    pump()
    tracker, overlay = t._tracker, d._overlay
    before = deepcopy(config._read_local_config())
    timers = set(w.findChildren(QTimer))
    for _ in range(50):
        for user in (None, "ordinary", feature_access.CREATOR_DISCORD_ID):
            account.clear()
            if user is not None:
                account["id"] = user
            d._apply_gate()
            pump()
            assert d._overlay is overlay and overlay.isVisible() and overlay.value == 13
            assert overlay._show_tuarim is (user == feature_access.CREATOR_DISCORD_ID)
            assert t._tracker is tracker and state.fired == [90, 95]
    assert config._read_local_config() == before
    assert set(w.findChildren(QTimer)) == timers


@pytest.mark.parametrize("font_size", [12, 20])
@pytest.mark.parametrize("creator", [False, True])
def test_nested_boss_buttons_reachable_in_every_ancestor(window, monkeypatch, tmp_path, font_size, creator):
    w, app = window
    monkeypatch.setattr(config, "load_discord_user", lambda: {
        "id": feature_access.CREATOR_DISCORD_ID if creator else "ordinary"})
    for widget in w.boss_tab.findChildren(QWidget):
        font = widget.font()
        font.setPixelSize(font_size)
        widget.setFont(font)
    boss = w.boss_tab
    if font_size == 20:
        for button in (boss.region_btn, boss.auto_find_btn, boss.view_region_btn):
            button.setMinimumWidth(174)
        boss.clear_region_btn.setMinimumWidth(300)
    boss.halo_capture._refresh()
    boss.diagnostics_btn.setChecked(True)
    boss._apply_collect_gate()
    boss.halo_capture.disclosure.setChecked(True)
    w._open_setup_feature("boss")
    before = deepcopy(config._read_local_config())
    for index in range(2 if creator else 1):
        boss.pattern_tabs.setCurrentIndex(index)
        settle(app)
        for button in boss.findChildren(QAbstractButton):
            if not button.isVisible():
                continue
            ancestor = button.parentWidget()
            scrolls = []
            while ancestor is not None:
                if isinstance(ancestor, QScrollArea):
                    scrolls.append(ancestor)
                ancestor = ancestor.parentWidget()
            for scroll in scrolls:
                scroll.ensureWidgetVisible(button)
                settle(app)
            for scroll in scrolls:
                rect = QRect(button.mapTo(scroll.viewport(), QPoint()), button.size())
                assert scroll.viewport().rect().contains(rect), (button.text(), rect, scroll.viewport().rect())
                assert scroll.horizontalScrollBar().maximum() == 0
        boss.pattern_tabs.widget(index).verticalScrollBar().setValue(0)
        settle(app)
        assert w.grab().save(str(tmp_path / f"boss-{creator}-{index}-{font_size}.png"))
    if font_size == 20:
        for button in (boss.region_btn, boss.auto_find_btn, boss.view_region_btn, boss.clear_region_btn):
            button.setMinimumWidth(0)
        for widget in boss.findChildren(QWidget):
            font = widget.font()
            font.setPixelSize(12)
            widget.setFont(font)
        boss.pattern_tabs.setCurrentIndex(0)
        settle(app)
        primary = boss.region_row.itemAt(0).widget()
        auxiliary = boss.region_row.itemAt(1).widget()
        assert primary.y() == auxiliary.y()
    assert config._read_local_config() == before


@pytest.mark.parametrize("action", ["logout", "region", "shutdown"])
def test_stop_during_metadata_write_never_commits_old_capture(window, monkeypatch, tmp_path, action):
    w, app = window
    account = {"id": feature_access.CREATOR_DISCORD_ID}
    monkeypatch.setattr(config, "load_discord_user", lambda: account or None)
    s = w.boss_tab.halo_capture
    s._root = tmp_path / "capture"
    s._watcher = SimpleNamespace(is_game_active=lambda: True)
    monkeypatch.setattr(s, "_foreground_target", lambda: (11, 22, 0, 0, 1920, 1080))
    monkeypatch.setattr(s, "_grab", lambda *args: np.full((20, 100, 3), 200, np.uint8))
    s._save_region(10, 20, 100, 20)
    entered, release = threading.Event(), threading.Event()
    write = Path.write_bytes
    def blocked(path, data):
        if path.name == "metadata.json":
            entered.set()
            assert release.wait(timeout=3)
        return write(path, data)
    monkeypatch.setattr(Path, "write_bytes", blocked)
    s.collect.setChecked(True)
    s._tick()
    session = s._session
    try:
        assert entered.wait(timeout=3)
        if action == "logout":
            account.clear()
            s._tick()
        elif action == "region":
            s._save_region(20, 20, 100, 20)
        else:
            s.shutdown()
        assert not s.collect.isChecked() and session.cancelled.is_set()
    finally:
        release.set()
        result = finish(session)
    assert result == "cancelled"
    assert session.count == session.bytes == 0
    assert not (session.path / "0001").exists()
    assert (session.path / "0001.pending").exists()


def test_negative_monitor_scaled_capture_uses_physical_target(window, monkeypatch):
    w, app = window
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": feature_access.CREATOR_DISCORD_ID})
    monkeypatch.setattr(dpi, "screen_scale", lambda: 2.)
    s = w.boss_tab.halo_capture
    s._watcher = SimpleNamespace(is_game_active=lambda: True)
    s._save_region(-300, 100, 80, 20)
    target = (11, 22, -800, 20, 800, 600)
    monkeypatch.setattr(s, "_foreground_target", lambda: target)
    captures = []
    def grab(*rect):
        captures.append(rect)
        return np.zeros((40, 160, 3), np.uint8)
    monkeypatch.setattr(s, "_grab", grab)
    assert s._capture().shape == (40, 160, 3)
    assert captures == [(-600, 200, 160, 40)]
    states = iter([target, None])
    monkeypatch.setattr(s, "_foreground_target", lambda: next(states))
    assert s._capture() is None
