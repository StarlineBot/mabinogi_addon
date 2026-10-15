"""Native-screen regressions; explicit pytest invocation, not default collection."""

from pathlib import Path

import cv2
import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config, image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.tracker.tuarim import REARM_FRAMES, TuarimTracker
from mabinogi_addon.ui.tuarim_tab import TuarimTab


DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
PREFIX = "\uc2a4\ud06c\ub9b0\uc0f7 "


def screen(stamp):
    frame = image_io.imread(DATA / f"{PREFIX}{stamp}.png")
    assert frame is not None
    return frame


def auto_crop(frame):
    cv2.setNumThreads(1)
    box = run_detector("tuarim", frame, detector_assets("tuarim"), {})
    assert box is not None
    x, y, w, h = box
    return box, frame[y:y+h, x:x+w]


def test_native_55_crop_control():
    frame = screen("2026-10-12 000512")
    # Same original pixels, no glyph scaling, pasting, brightness adjustment or mocks.
    assert read_percent(frame[919:932, 740:782]) == 55


def test_autofind_preserves_native_55_reading():
    box, crop = auto_crop(screen("2026-10-12 000512"))
    assert box == (740, 918, 42, 16)
    assert read_percent(crop) == 55


@pytest.mark.parametrize("stamp,expected", [
    ("2026-10-09 185117", (742, 920, 42, 16)),
    ("2026-10-14 000646", (967, 976, 42, 16)),
])
def test_full_native_100_is_not_reset_evidence(stamp, expected):
    box, crop = auto_crop(screen(stamp))
    assert box == expected
    assert read_percent(crop) in (100, None)


def test_tab_native_100_hold_keeps_fired_state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    monkeypatch.setattr(config, "_write_local_config", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa"})
    from mabinogi_addon.ui import dpi
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)

    class Watcher:
        def is_game_active(self):
            return True

        def is_self_active(self):
            return False

    frame = screen("2026-10-09 185117")
    box, _crop = auto_crop(frame)
    tab = TuarimTab(Watcher())
    tab._timer.stop()
    try:
        tab.enable.setChecked(True)
        tab._tracker = TuarimTracker([90, 95])
        assert tab._tracker.observe(98) == []
        assert tab._tracker.observe(98) == [90, 95]
        tab._apply_region(*box)
        assert tab._tracker._fired == {90, 95}
        captures = []

        def grab(x, y, w, h):
            captures.append((x, y, w, h))
            return frame[y:y+h, x:x+w].copy()

        tab._grab_rect = grab
        sounds = []
        tab._play = sounds.append
        for _ in range(REARM_FRAMES + 1):
            tab._tick()
        assert captures == [box] * (REARM_FRAMES + 1)
        assert sounds == []
        # Only capture/audio boundaries are substituted; real reader, stabilizer and
        # tracker consume identical native 100% pixels, with no actual gauge reset.
        assert tab._tracker._fired == {90, 95}
    finally:
        tab.shutdown()
        tab.close()
        tab.deleteLater()
        app.processEvents()
