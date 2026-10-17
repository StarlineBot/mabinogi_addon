"""Replay actual old/new renderings without changing the registered region."""

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads
from mabinogi_addon import config, image_io
from mabinogi_addon.ui import dpi
from mabinogi_addon.ui.boss_tab import BossTab


@pytest.mark.parametrize("warnings_enabled", (False, True))
def test_same_region_old_new_cycle_absence_and_reentry(monkeypatch, warnings_enabled):
    app = QApplication.instance() or QApplication([])
    sequence = [("09", "195115", 47), ("18", "001116", 99),
                ("18", "001216", 87), ("18", "001307", 75),
                ("18", "001541", 42), ("18", "001801", 8)]
    frames = [(image_io.imread(ROOT / f"tests/data/스크린샷 2026-10-{day} {stamp}.png"), hp)
              for day, stamp, hp in sequence]
    assert all(frame is not None for frame, _ in frames)
    box = {"x": 1018, "y": 1248, "w": 521, "h": 37}
    current = [frames[0][0]]
    calls = []
    sounds = []
    watcher = SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False)
    screen = SimpleNamespace(geometry=lambda: SimpleNamespace(height=lambda: current[0].shape[0]))
    monkeypatch.setattr(dpi, "to_physical", lambda reg: tuple(reg[key] for key in ("x", "y", "w", "h")))

    def grab(x, y, w, h):
        calls.append((x, y, w, h))
        return current[0][y:y+h, x:x+w]

    tab = BossTab(watcher)
    monkeypatch.setattr(QGuiApplication, "primaryScreen", lambda: screen)
    tab._timer.stop()
    tab._region = dict(box)
    monkeypatch.setattr(tab, "_grab_rect", grab)
    monkeypatch.setattr(tab, "_play", sounds.append)
    monkeypatch.setattr(tab._overlay, "show_message", lambda *args: None)
    tab.enable.setChecked(warnings_enabled)
    timers = set(tab.findChildren(QTimer))
    try:
        for _ in range(3):
            for frame, hp in frames:
                current[0] = frame
                for _ in range(4):
                    tab._tick()
                assert tab._cur_boss == "pellom"
                assert tab._stable_hp == hp
                assert tab._last_raw_hp == hp
                assert tab._tracker is not None
                assert tab._boss_present
                assert tab._region == box
                assert set(tab.findChildren(QTimer)) == timers
        assert sounds == []  # None of these sparse samples lies in a warning band.
        current[0] = frames[-1][0] * 0
        for _ in range(tab._GONE_FRAMES + 2):
            tab._tick()
        assert tab._tracker is None
        assert tab._stable_hp is None
        assert not tab._boss_present
        current[0] = frames[2][0]
        for _ in range(4):
            tab._tick()
        assert tab._cur_boss == "pellom" and tab._stable_hp == 87
        assert set(calls) == {tuple(box[key] for key in ("x", "y", "w", "h"))}
        assert tab._region == box
        assert config.load_boss_bar_region() in (None, box)
    finally:
        tab.shutdown()
        tab.close()
    assert app is not None
