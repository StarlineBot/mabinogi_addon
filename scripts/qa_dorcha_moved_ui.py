"""Explicit QA: live screenshot localization and moving source UI."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from mabinogi_addon import config, image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.ui.dorcha_tab import DorchaTab


DATA = Path(__file__).resolve().parents[1] / "tests/data"
NEW = DATA / "스크린샷 2026-10-16 234015.png"


@pytest.fixture(scope="module", autouse=True)
def single_cv_thread():
    previous = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(previous)


def new_frame():
    frame = image_io.imread(NEW)
    assert frame is not None and frame.shape == (1440, 2560, 3)
    return frame


@pytest.mark.parametrize("neighborhood", [False, True], ids=["full-screenshot", "unobscured-neighborhood"])
def test_new_visible_ui_must_be_located(neighborhood):
    frame = new_frame()
    expected = (577, 123, 28, 23)
    if neighborhood:
        frame = frame[80:200, 540:690].copy()
        expected = (37, 43, 28, 23)
    trace = {}
    actual = run_detector("dorcha", frame, detector_assets("dorcha"), trace)
    assert actual == expected, {"actual": actual, "expected": expected, "trace": trace}


def test_actual_new_number_is_readable():
    frame = new_frame()
    assert read_dorcha(frame[123:146, 577:605]) == 15


def test_prior_fifteen_scene_still_locates_and_reads():
    frame = image_io.imread(DATA / "스크린샷 2026-10-16 211914.png")
    assert frame is not None
    box = run_detector("dorcha", frame, detector_assets("dorcha"), {})
    assert box == (941, 948, 28, 23)
    x, y, w, h = box
    assert read_dorcha(frame[y:y+h, x:x+w]) == 15


def test_moving_source_must_be_reacquired_for_new_requirement(monkeypatch):
    app = QApplication.instance() or QApplication([])
    raw = {"dorcha": {"enabled": True, "box": dict(x=20, y=20, w=28, h=23)}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **kw: deepcopy(raw))
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **kw: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    monkeypatch.setattr("mabinogi_addon.ui.dpi.to_physical", lambda b: (b["x"], b["y"], b["w"], b["h"]))
    # Use a known-locatable ornament to separate motion from the new scene's anchor failure.
    control = image_io.imread(DATA / "스크린샷 2026-10-16 211914.png")
    assert control is not None
    ornament = control[931:988, 933:978].copy()
    frame = np.zeros((180, 260, 3), np.uint8)
    frame[3:60, 12:57] = ornament
    captures = []

    def grab(x, y, w, h):
        captures.append((x, y, w, h))
        return frame[y:y+h, x:x+w].copy()

    tab = DorchaTab(SimpleNamespace(is_game_active=lambda: True, is_self_active=lambda: False))
    tab._timer.stop()
    monkeypatch.setattr(tab, "_grab_rect", grab)
    try:
        tab._tick()
        assert tab._overlay.value == 15
        frame[:] = 0
        frame[73:130, 142:187] = ornament
        assert read_dorcha(frame[90:113, 150:178]) == 15
        assert run_detector("dorcha", frame, detector_assets("dorcha"), {}) == (150, 90, 28, 23)
        for _ in range(10):
            QTest.qWait(200)
            tab._tick()
        assert tab._overlay.value == 15, {
            "after_move": tab._overlay.value,
            "captures": captures,
            "saved_region": tab._region,
        }
    finally:
        tab.shutdown()
        for widget in (tab._overlay, tab):
            if widget is not None:
                widget.close()
                widget.deleteLater()
        app.processEvents()
