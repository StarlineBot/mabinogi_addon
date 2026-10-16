"""Independent missing-button negatives across scale, background and pixel phase."""

from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from mabinogi_addon.autofind_replay import detector_assets, run_detector


@pytest.fixture(scope="module")
def panel():
    root = Path(__file__).resolve().parents[4]
    with ZipFile(root / "tests/data/autofind_20261016T172504548267Z_2887b867.zip") as archive:
        frame = cv2.imdecode(np.frombuffer(archive.read("input.png"), np.uint8), cv2.IMREAD_COLOR)
    assert frame is not None
    return frame[106:167, 569:645].copy()


@pytest.fixture(scope="module")
def assets():
    return detector_assets("tuarim")


@pytest.mark.parametrize("scale", [0.75, 1.0, 1.25, 1.5, 2.0])
@pytest.mark.parametrize("background", [0, 255])
@pytest.mark.parametrize("shift", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_absent_button_is_rejected(panel, assets, scale, background, shift):
    native = panel.copy()
    keep = np.zeros(native.shape[:2], bool)
    keep[:57, :45] = True
    keep[46:61, 34:76] = True
    native[~keep] = background
    native = cv2.resize(native, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    image = np.full((240, 320, 3), background, np.uint8)
    x, y = 60 + shift[0], 40 + shift[1]
    image[y:y + native.shape[0], x:x + native.shape[1]] = native
    trace = {}
    assert run_detector("tuarim", image, assets, trace) is None, trace
    # The circle remains detectable; the negative must exercise button validation.
    assert any(item.get("ornament_score", 0) >= 0.97 for item in trace["candidates"]), trace
