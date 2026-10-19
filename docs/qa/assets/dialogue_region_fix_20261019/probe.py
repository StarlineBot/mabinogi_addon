"""Actual Qt request with shaped coverage, scaled negative-origin coordinates and diagnostics."""

import logging
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QTimer

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_dialogue_window_region import app, window, native_model, region_model  # noqa: E402,F401
from mabinogi_addon.system import dialogue_visibility as visibility  # noqa: E402


@pytest.mark.parametrize("scale", [1.0, 1.5])
@pytest.mark.parametrize("automatic", [False, True])
def test_qt_display_and_real_coverage_remain_separate(window, app, region_model, monkeypatch,
                                                    caplog, scale, automatic):
    state = region_model
    state.owner = int(window.winId())
    state.client = (0, 0, round(window.width() * scale), round(window.height() * scale))
    state.origin = (-1600, 20)
    state.cover = (-1920, 0, 2560, 1440)
    gui, api = sys.modules["win32gui"], sys.modules["win32api"]
    other_origin = (-1950, -30)
    monkeypatch.setattr(gui, "GetWindowRect", lambda hwnd: (*other_origin, 2590, 1480))
    monkeypatch.setattr(gui, "GetClassName", lambda hwnd: "ArbitraryLayeredWindow", raising=False)
    monkeypatch.setattr(api, "EnumDisplayMonitors", lambda: [
        (1, None, (-1920, 0, 0, 1440)), (2, None, (0, 0, 2560, 1440)),
    ])
    opened, closed = [], []

    def open_process(*args):
        opened.append(args)
        return SimpleNamespace(Close=lambda: closed.append(True))

    monkeypatch.setattr(api, "OpenProcess", open_process, raising=False)
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 818),
    ))
    # Native query signatures/exports are checked separately, not invented here.
    monkeypatch.setattr(visibility, '_process_basename', lambda handle:'overlay.exe')
    dialogue = window.creator_dialogue
    dialogue.timer.stop()
    dialogue.visibility = visibility.exposed
    dialogue.clock = lambda: 100.0
    dialogue.session.rng.random = lambda: 0.0
    timers = set(window.findChildren(QTimer))
    logger = "mabinogi_addon.ui.creator_dialogue"
    caplog.set_level(logging.INFO, logger=logger)

    # Region is drawn only on the right monitor; app targets are on the left.
    state.rectangles = [(4300, 30, 4340, 70)]
    if automatic:
        dialogue.tick()
    else:
        dialogue.face.click()
    assert dialogue.bubble.isVisible()
    assert not state.live and not opened

    # Add just one covered pixel at the face corner, not its center.
    point = dialogue.face.mapTo(window, QPoint())
    px = state.origin[0] + int(point.x() * scale) - other_origin[0]
    py = state.origin[1] + int(point.y() * scale) - other_origin[1]
    state.rectangles = [(px, py, px + 1, py + 1)]
    dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    records = [r.getMessage() for r in caplog.records if r.name == logger]
    assert len(records) == 1
    assert "overlay.exe" in records[0] and "blocker_pid" in records[0]
    assert "private" not in records[0]
    assert len(opened) == len(closed) == 1 and not state.live

    # Unknown region is not sufficient evidence to display the dialogue.
    state.region_kind = 0
    dialogue.face.click()
    assert not dialogue.bubble.isVisible()
    assert len(opened) == len(closed) == 2 and not state.live
    state.present = False
    dialogue.face.click()
    assert dialogue.bubble.isVisible()
    assert set(window.findChildren(QTimer)) == timers
