"""Native full-screen pixels must remain compatible with the percentage reader."""

import numpy as np
import cv2
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect import tuarim_reader as reader
from mabinogi_addon.tracker.tuarim import REARM_FRAMES, TuarimTracker
from mabinogi_addon.ui.tuarim_tab import TuarimTab


CASES = [
    ("2026-10-12 000512", 55),
    ("2026-10-10 190116", 7),
    ("2026-10-09 185117", None),
    ("2026-10-14 000646", None),
    ("2026-10-12 200511", None),
]


@pytest.fixture(scope="module")
def native_crops():
    crops = {}
    for stamp, _expected in CASES:
        frame = image_io.imread(f"tests/data/스크린샷 {stamp}.png")
        assert frame is not None
        box = run_detector("tuarim", frame, detector_assets("tuarim"), {})
        assert box is not None
        x, y, w, h = box
        crops[stamp] = box, frame[y:y + h, x:x + w].copy()
    return crops


@pytest.mark.parametrize("stamp,expected", CASES)
def test_native_auto_region_is_correct_or_safely_held(native_crops, stamp, expected):
    _box, crop = native_crops[stamp]
    assert reader.read_percent(crop) == expected


@pytest.mark.parametrize("stamp", ["2026-10-09 185117", "2026-10-14 000646"])
def test_native_hundred_brightness_does_not_become_reset(native_crops, stamp):
    _box, crop = native_crops[stamp]
    for gain in (0.6, 0.8, 1.0, 1.1, 1.2, 1.4):
        image = np.clip(crop.astype(float) * gain, 0, 255).astype(np.uint8)
        assert reader.read_percent(image) is None


@pytest.mark.parametrize("stamp,expected", [CASES[0], CASES[2], CASES[3]])
@pytest.mark.parametrize("scale", [1.5, 2.0])
def test_scaled_native_crop_keeps_reading_contract(native_crops, stamp, expected, scale):
    image = cv2.resize(native_crops[stamp][1], None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_LINEAR)
    assert reader.read_percent(image) == expected


@pytest.mark.parametrize("value", [0, 3, 5, 7])
def test_real_low_glyphs_keep_reading_with_added_padding(value):
    image = image_io.imread(f"tests/data/tuarim_samples/{value:02d}.png")
    assert image is not None
    for margins in (((0, 0), (14, 0), (0, 0)), ((1, 2), (14, 0), (0, 0))):
        assert reader.read_percent(np.pad(image, margins)) == value


def test_missing_or_corrupt_percent_assets_hold_wide_input(native_crops, monkeypatch):
    monkeypatch.setattr(reader, "_PERCENT", None)
    monkeypatch.setattr(reader, "_PERCENT_PLAIN", np.zeros((1, 1), np.uint8))
    assert reader.read_percent(native_crops["2026-10-09 185117"][1]) is None
    legacy = image_io.imread("tests/data/tuarim_hi/95.png")
    assert legacy is not None and reader.read_percent(legacy) == 95
    assert reader.read_percent(np.zeros((1, 42, 3), np.uint8)) is None


def test_native_hold_then_real_reset_rearms_once(native_crops, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test"})
    from mabinogi_addon.ui import dpi
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)
    class Watcher:
        def is_game_active(self): return True
        def is_self_active(self): return False
    tab = TuarimTab(Watcher())
    tab._timer.stop()
    box, frame = native_crops["2026-10-09 185117"]
    sounds = []
    tab._play = sounds.append
    tab._grab_rect = lambda *coords: frame.copy()
    try:
        tab.enable.setChecked(True)
        tab._tracker = TuarimTracker([90, 95])
        tab._tracker.observe(98)
        assert tab._tracker.observe(98) == [90, 95]
        tab._apply_region(*box)
        for _ in range(REARM_FRAMES * 3):
            tab._tick()
        assert tab._tracker._fired == {90, 95} and not sounds
        low = image_io.imread("tests/data/tuarim_samples/00.png")
        high = image_io.imread("tests/data/tuarim_hi/98.png")
        assert low is not None and high is not None
        frame = np.pad(low, ((1, 2), (14, 0), (0, 0)))
        for _ in range(REARM_FRAMES + 1):
            tab._tick()
        assert not tab._tracker._fired
        frame = np.pad(high, ((1, 2), (14, 0), (0, 0)))
        for _ in range(4):
            tab._tick()
        assert sounds == [90, 95]
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()
