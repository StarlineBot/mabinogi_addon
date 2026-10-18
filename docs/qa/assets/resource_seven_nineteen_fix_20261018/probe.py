"""Fresh focus cycles on both real scenes; synthetic 91 is labeled separately."""

from pathlib import Path
import sys

import pytest
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import _isolated_runtime, _no_leaked_qthreads  # noqa: E402,F401
from test_dorcha_tracking import moving, one_cv_thread  # noqa: E402,F401
from docs.qa.assets.dorcha_startup_20261018.probe import drain  # noqa: E402
from mabinogi_addon import image_io  # noqa: E402
from mabinogi_addon.detect.tuarim_reader import read_percent  # noqa: E402


@pytest.mark.parametrize("stamp, box", [
    ("122605", (1237, 55, 28, 23)),
    ("124011", (1239, 57, 28, 23)),
])
def test_visible_seven_first_validates_and_recovers_after_focus_cycle(moving, stamp, box):
    app, tab, state, writes = moving
    frame = image_io.imread(ROOT / f"tests/data/스크린샷 2026-10-18 {stamp}.png")
    assert frame is not None
    state.frame = frame
    state.target = (1, 2, 0, 0, frame.shape[1], frame.shape[0])
    tab._region = dict(zip(("x", "y", "w", "h"), box))
    tab._tick()
    assert tab._overlay.value == 7 and tab._live_box == box
    state.game = False
    tab._tick()
    assert tab._overlay.value is None and tab._live_box is None
    state.game = True
    tab._tick()
    drain(app, tab)
    assert tab._overlay.value == 7 and tab._live_box == box
    assert not tab._tracking_lost and not writes


def test_synthetic_swapped_night_glyphs_keep_ninety_one():
    frame = image_io.imread(ROOT / "tests/data/스크린샷 2026-10-18 124011.png")
    assert frame is not None
    native = frame[85:101, 1265:1307].copy()
    assert read_percent(native) == 19
    # Swap native digit cells without changing percent alignment or surrounding pixels.
    swapped = native.copy()
    swapped[1:14, 9:17] = native[1:14, 17:25]
    swapped[1:14, 17:25] = native[1:14, 9:17]
    assert read_percent(swapped) == 91
    for gain in (0.4, 0.6, 0.8, 1.0, 1.1, 1.2, 1.4):
        changed_nineteen = np.clip(native.astype(float) * gain, 0, 255).astype(np.uint8)
        changed_ninety_one = np.clip(swapped.astype(float) * gain, 0, 255).astype(np.uint8)
        assert read_percent(changed_nineteen) in (None, 19)
        assert read_percent(changed_ninety_one) == 91
