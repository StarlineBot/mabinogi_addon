"""Independent native-screen coverage and legacy/padded reader comparison."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.tuarim_reader import read_percent


DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
PREFIX = "\uc2a4\ud06c\ub9b0\uc0f7 "
CASES = [
    ("2026-10-06 223724", (740, 918, 42, 16), 0),
    ("2026-10-07 013118", (742, 920, 42, 16), 13),
    ("2026-10-09 185117", (742, 920, 42, 16), None),
    ("2026-10-09 185152", (740, 918, 42, 16), None),
    ("2026-10-09 185217", (742, 920, 42, 16), None),
    ("2026-10-09 185247", (742, 920, 42, 16), None),
    ("2026-10-09 200715", (742, 920, 42, 16), None),
    ("2026-10-09 200724", (742, 920, 42, 16), None),
    ("2026-10-10 190116", (742, 920, 42, 16), 7),
    ("2026-10-11 095841", (740, 918, 42, 16), 0),
    ("2026-10-12 000512", (740, 918, 42, 16), 55),
    ("2026-10-12 200511", (965, 974, 42, 16), None),
    ("2026-10-14 000646", (967, 976, 42, 16), None),
]


@pytest.mark.parametrize("stamp,expected_box,expected_value", CASES)
def test_native_full_screen_detect_then_read(stamp, expected_box, expected_value):
    cv2.setNumThreads(1)
    frame = image_io.imread(DATA / f"{PREFIX}{stamp}.png")
    assert frame is not None
    box = run_detector("tuarim", frame, detector_assets("tuarim"), {})
    assert box == expected_box
    x, y, w, h = box
    assert read_percent(frame[y:y+h, x:x+w]) == expected_value


@pytest.mark.parametrize("value", [85, 89, *range(90, 100)])
@pytest.mark.parametrize("gain", [0.6, 0.8, 1.0, 1.1, 1.2, 1.4])
def test_padding_does_not_worsen_existing_high_glyph_reading(value, gain):
    image = image_io.imread(DATA / "tuarim_hi" / f"{value:02d}.png")
    assert image is not None and image.shape[:2] == (13, 28)
    assert read_percent(image) == value
    altered = np.clip(image.astype(float) * gain, 0, 255).astype(np.uint8)
    baseline = read_percent(altered)
    padded = np.pad(altered, ((1, 2), (14, 0), (0, 0)))
    # Glyph pixels and scale are unchanged. This is a synthetic padding contract,
    # not proof of live high-value auto ROIs or accuracy under all combat effects.
    assert read_percent(padded) == baseline
