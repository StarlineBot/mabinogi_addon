"""Independent held-out native pixels and one-shot moved-panel regression."""

from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.detect.tuarim_reader import read_percent

ROOT = Path(__file__).resolve().parents[4]
SAMPLES = ROOT / "tests/data/투아림게이지 샘플 모음.zip"
DORCHA = ROOT / "tests/data/autofind_20261016T192204168176Z_e70b6c5c.zip"


@pytest.fixture(scope="module", autouse=True)
def one_opencv_thread():
    previous = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(previous)


def decode(data):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


# Labels were read from enlarged originals, not the v04 filename prefix.
@pytest.mark.parametrize("stamp,value", [
    (4061, 2), (4107, 3), (4148, 5), (4185, 6), (4217, 8),
    (4250, 12), (4380, 14), (4459, 21), (4501, 22), (4541, 26),
    (4573, 28), (4620, 30), (4691, 33), (4725, 35), (4760, 36),
    (4792, 38), (4824, 40), (4857, 44), (4954, 49), (5037, 52),
    (5136, 56), (5185, 58), (5227, 60), (5264, 62), (5297, 64),
    (5331, 66), (5363, 68), (5395, 70), (5427, 71), (5525, 75),
    (5655, 86), (5711, 89), (5783, 95), (5820, 97),
    (5830, 98), (5831, 98),
])
def test_additional_visually_labelled_native_frames(stamp, value):
    with ZipFile(SAMPLES) as archive:
        image = decode(archive.read(f"새 폴더 (2)/v04_{stamp}.png"))
    assert read_percent(image) == value


@pytest.mark.parametrize("feature", ["dorcha", "tuarim"])
@pytest.mark.parametrize("origin", [(5, 5), (450, 230), (120, 100)])
def test_one_shot_search_finds_native_panel_at_new_positions(feature, origin):
    with ZipFile(DORCHA) as archive:
        panel = decode(archive.read("input.png"))[90:180, 510:615].copy()
    frame = np.zeros((360, 640, 3), np.uint8)
    x, y = origin
    frame[y:y + panel.shape[0], x:x + panel.shape[1]] = panel
    trace = {}
    box = run_detector(feature, frame, detector_assets(feature), trace)
    relative = (24, 32, 28, 23) if feature == "dorcha" else (50, 60, 42, 16)
    expected = (x + relative[0], y + relative[1], relative[2], relative[3])
    assert box == expected, trace
    left, top, width, height = box
    crop = frame[top:top + height, left:left + width]
    reader = read_dorcha if feature == "dorcha" else read_percent
    assert reader(crop) == 0
