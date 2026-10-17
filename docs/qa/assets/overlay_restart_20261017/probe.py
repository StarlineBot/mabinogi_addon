"""Actual UI save/close/recreate checks with only external workers replaced."""

from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QPoint, QRect, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from mabinogi_addon import config
from mabinogi_addon.ui.main_window import MainWindow


def stop_timers(window):
    for timer in window.findChildren(QTimer):
        timer.stop()


def state(window):
    bars = window.stat_bars_tab
    bars._ensure_overlays()
    skills = window.skillbar_tab
    skills._ensure_overlays()
    dorcha = window.dorcha_tab
    dorcha._ensure_overlay()
    overlays = {
        "buff": window.buff_overlay,
        "debuff": window.debuff_overlay,
        "memo": window.memo_overlay,
        "boss_warning": window.boss_tab._overlay,
        "boss_upcoming": window.boss_tab._upcoming,
        "dorcha": dorcha._overlay,
        **{"stat_" + key: overlay for key, overlay in bars._overlays.items()},
        **{"skill_" + key: overlay for key, overlay in skills._overlays.items()},
        **{"custom_" + str(index): overlay for index, overlay in enumerate(window.custom_overlay_tab._mgr.overlays())},
    }
    return {
        key: (overlay.locked, (position.x(), position.y()))
        for key, overlay in overlays.items()
        for position in [overlay.base_position if key.startswith("stat_") else overlay.pos()]
    }


def arrange(window, offset):
    x, y = offset
    for index, (overlay, tab) in enumerate([
        (window.buff_overlay, window.buff_tab),
        (window.debuff_overlay, window.debuff_tab),
        (window.memo_overlay, window.memo_tab),
    ]):
        overlay.move(x + 50 + 30 * index, y + 80 + 30 * index)
        overlay.moved.emit()
        tab.set_lock_state(True)
    boss = window.boss_tab
    for index, (overlay, save) in enumerate([
        (boss._overlay, boss._on_warn_moved),
        (boss._upcoming, boss._on_upcoming_moved),
    ]):
        overlay.move(x + 100 + 30 * index, y + 200 + 30 * index)
        overlay.set_locked(True)
        save()
    boss._save()
    bars = window.stat_bars_tab
    bars._ensure_overlays()
    for index, overlay in enumerate(bars._overlays.values()):
        overlay.move_base(QPoint(x + 160, y + 300 + 30 * index))
    bars._set_locked_all(True)
    skills = window.skillbar_tab
    skills._ensure_overlays()
    for index, overlay in enumerate(skills._overlays.values()):
        overlay.move(x + 30 + index % 3 * 190, y + 400 + index // 3 * 45)
    skills._set_locked_all(True)
    dorcha = window.dorcha_tab
    dorcha._ensure_overlay()
    dorcha._overlay.move(x + 250, y + 150)
    dorcha._on_locked(True)
    custom = window.custom_overlay_tab
    custom._mgr.add(dict(x=10, y=20, w=80, h=40, posX=x + 300, posY=y + 200,
                         locked=True, name="QA"))
    config.save_custom_preset("QA restart", custom._mgr.to_dicts())
    config.save_auto_preset("QA restart")
    stop_timers(window)


@pytest.mark.parametrize("offset", [(0, 0), (-1600, 120)])
@pytest.mark.parametrize("repeat", [1, 3])
@pytest.mark.parametrize("visible", [False, True])
def test_every_overlay_keeps_saved_lock_and_position(offset, repeat, visible, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa", "name": "qa"})
    screen = type(app.primaryScreen())
    monkeypatch.setattr(screen, "geometry", lambda self: QRect(-1600, 0, 3200, 1100))
    monkeypatch.setattr(screen, "availableGeometry", lambda self: QRect(-1600, 0, 3200, 1100))
    monkeypatch.setattr(MainWindow, "_start_buff_tracking", lambda self: None)
    monkeypatch.setattr(MainWindow, "_start_debuff_tracking", lambda self: None)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a, **k: None)
    from mabinogi_addon.ui.party_tab import PartyTab
    monkeypatch.setattr(PartyTab, "start_polling", lambda self: None)
    config._write_local_config({"general": {"skipSetup": True, "tourShown": True},
                                "qaUnknown": {"preserve": [1, 2, 3]}})
    windows = []
    try:
        first = MainWindow()
        windows.append(first)
        first._post_show_done = True
        first.start()
        stop_timers(first)
        if visible:
            first.show()
            app.processEvents()
        arrange(first, offset)
        expected = state(first)
        assert len(expected) == 22 and all(value[0] for value in expected.values())
        first._force_quit = True
        first.close()
        app.processEvents()
        for _ in range(repeat):
            current = MainWindow()
            windows.append(current)
            current._post_show_done = True
            current.start()
            stop_timers(current)
            if visible:
                current.show()
            app.processEvents()
            actual = state(current)
            assert actual == expected
            assert current.buff_tab.lock_btn.isChecked()
            assert current.debuff_tab.lock_btn.isChecked()
            assert current.memo_tab.lock_btn.isChecked()
            assert config._read_local_config()["qaUnknown"] == {"preserve": [1, 2, 3]}
            current._force_quit = True
            current.close()
            app.processEvents()
    finally:
        for window in windows:
            stop_timers(window)
            window._force_quit = True
            window.close()
        app.processEvents()
