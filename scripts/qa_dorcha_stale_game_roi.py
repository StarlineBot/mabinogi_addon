"""Explicit QA: old numeric ROI outside a moved game must not stay authoritative."""

from copy import deepcopy
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.ui.dorcha_tab import DorchaTab


DATA = Path(__file__).resolve().parents[1] / "tests/data"


def wait_events(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def finish_search(tab):
    deadline = monotonic() + 5
    while tab._search_worker is not None and monotonic() < deadline:
        wait_events(10)
    assert tab._search_worker is None


@pytest.mark.parametrize("old_digits", [False, True], ids=["blank-old-location-control", "unrelated-old-digits"])
def test_moved_game_must_invalidate_outside_live_roi(monkeypatch, old_digits):
    app = QApplication.instance() or QApplication([])
    cv2.setNumThreads(1)
    raw = {"dorcha": {"enabled": True, "box": dict(x=20, y=20, w=28, h=23)}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **kw: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **kw: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    monkeypatch.setattr("mabinogi_addon.ui.dpi.to_physical", lambda b: tuple(b[k] for k in ("x", "y", "w", "h")))
    source = image_io.imread(DATA / "스크린샷 2026-10-16 211914.png")
    zero = image_io.imread(DATA / "스크린샷 2026-10-09 185117.png")
    assert source is not None and zero is not None
    ornament = source[931:988, 933:978].copy()
    zero_digits = zero[892:915, 716:744].copy()
    assert read_dorcha(zero_digits) == 0
    desktop = np.zeros((200, 600, 3), np.uint8)
    state = SimpleNamespace(target=(100, 200, 0, 0, 260, 180), target_queries=0, captures=[])

    def target():
        state.target_queries += 1
        return state.target

    def grab(x, y, w, h):
        state.captures.append((x, y, w, h))
        return desktop[y:y+h, x:x+w].copy()

    tab = DorchaTab(SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False))
    tab._timer.stop()
    monkeypatch.setattr(tab, "_search_target", target)
    monkeypatch.setattr(tab, "_grab_rect", grab)
    try:
        desktop[73:130, 142:187] = ornament
        tab._tick()
        finish_search(tab)
        assert tab._live_box == (150, 90, 28, 23) and tab._overlay.value == 15

        # Same game window moves right. Only unrelated glyphs remain at its old position.
        state.target = (100, 200, 300, 0, 260, 180)
        desktop[:] = 0
        desktop[73:130, 442:487] = ornament
        desktop[90:113, 450:478] = zero_digits
        if old_digits:
            desktop[90:113, 150:178] = ornament[17:40, 8:36]
        current_game = desktop[:180, 300:560]
        assert locate_dorcha(current_game) == (150, 90, 28, 23)
        assert read_dorcha(desktop[90:113, 450:478]) == 0
        state.captures.clear()
        state.target_queries = 0
        for _ in range(3):
            tab._tick()
            finish_search(tab)
            wait_events(200)
        print({"unrelated_old_digits": old_digits, "current_game_value": 0,
               "displayed": tab._overlay.value, "live_box": tab._live_box,
               "target_queries": state.target_queries, "captures": state.captures})
        assert tab._overlay.value == 0 and tab._live_box == (450, 90, 28, 23)
    finally:
        tab.shutdown()
        for widget in (tab._overlay, tab):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        app.processEvents()
