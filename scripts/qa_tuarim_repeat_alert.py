"""Independent Tuarim QA. Run explicitly with pytest; no product changes."""

import re
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.tracker.tuarim import REARM_FRAMES, TuarimTracker
from mabinogi_addon.ui import dpi, tuarim_tab as mod


REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pipeline(application, monkeypatch):
    settings = {
        "enabled": True,
        "box": {"x": 0, "y": 0, "w": 28, "h": 13},
        "thresholds": [90, 95],
        "sounds": [True, True],
    }
    monkeypatch.setattr(mod.config, "load_tuarim", lambda: settings)
    monkeypatch.setattr(mod.config, "load_discord_user", lambda: None)
    monkeypatch.setattr(mod.config, "save_tuarim", lambda _data: None)
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)

    class Watcher:
        def is_game_active(self):
            return True

        def is_self_active(self):
            return False

    tab = mod.TuarimTab(Watcher())
    tab._timer.stop()
    frame = np.zeros((13, 28, 3), np.uint8)
    tab._grab_rect = lambda *args: frame
    tab._show_preview = lambda _frame: None
    events = []
    trace = []

    def record(threshold):
        events.append({
            "tick": len(trace) + 1,
            "threshold": threshold,
            "raw": tab._last_value,
            "stable": tab._stable_value,
        })

    tab._play = record

    def step(value=None, *, image=None):
        nonlocal frame
        if image is None:
            with monkeypatch.context() as local:
                local.setattr(mod, "read_percent", lambda _frame: value)
                tab._tick()
        else:
            frame = image
            tab._tick()
        trace.append({
            "raw": tab._last_value,
            "stable": tab._stable_value,
            "low": tab._tracker._low,
            "fired": sorted(tab._tracker._fired),
        })

    yield step, events, trace
    tab.shutdown()
    tab.deleteLater()
    application.processEvents()


def thresholds(events):
    return [event["threshold"] for event in events]


def reach_high(step):
    for value in (89, 89, 90, 90, 91, 95, 95, 96, 98, 98, 98):
        step(value)


def test_same_cycle_95_to_98_fires_only_once_per_threshold(pipeline):
    step, events, _trace = pipeline
    reach_high(step)
    for value in (95, 95, 97, 98, None, 96, 96, 98, 98) * 10:
        step(value)
    assert thresholds(events) == [90, 95], events


@pytest.mark.parametrize("uncertain", [None, "alternating"])
def test_two_low_reads_then_uncertainty_must_not_confirm_reset(pipeline, uncertain):
    step, events, trace = pipeline
    reach_high(step)
    step(5)
    step(5)
    for index in range(REARM_FRAMES):
        step(None if uncertain is None else (96 if index % 2 else 97))
    low_count = trace[-1]["low"]
    step(98)
    step(98)
    step(98)
    assert thresholds(events) == [90, 95], {
        "low_after_uncertainty": low_count, "events": events,
    }


def test_two_short_misread_episodes_must_not_repeat_at_98(pipeline):
    step, events, _trace = pipeline
    reach_high(step)
    for _episode in range(2):
        step(5)
        step(5)
        for _tick in range(REARM_FRAMES):
            step(None)
        for _tick in range(3):
            step(98)
    assert thresholds(events) == [90, 95], events


def test_real_sustained_reset_allows_next_cycle(pipeline):
    step, events, _trace = pipeline
    reach_high(step)
    for _tick in range(REARM_FRAMES + 1):
        step(5)
    for _tick in range(3):
        step(98)
    assert thresholds(events) == [90, 95, 90, 95], events


def test_existing_session_through_actual_tab_not_only_tracker(pipeline):
    step, events, trace = pipeline
    direct = TuarimTracker([90, 95])
    direct_events = []
    archive = REPO / "tests" / "data" / "raw_7603.zip"
    with ZipFile(archive) as session:
        names = [name for name in session.namelist()
                 if re.fullmatch(r"(?:raw|v\d+)_\d+\.png", name)]
        names.sort(key=lambda name: int(name.rsplit("_", 1)[1][:-4]))
        assert len(names) == 2926
        for name in names:
            image = cv2.imdecode(np.frombuffer(session.read(name), np.uint8), cv2.IMREAD_COLOR)
            assert image is not None, name
            value = read_percent(image)
            for _tick in range(2):
                direct_events.extend(direct.observe(value))
                step(image=image)
    assert direct_events == [90, 95], direct_events
    assert thresholds(events) == [90, 95], {
        "frames": len(names), "ticks": len(trace), "events": events,
    }
