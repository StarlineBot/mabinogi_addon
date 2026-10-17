"""New live evidence: visible Dorcha zero and manually labelled Tuarim samples."""

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.detect.tuarim_reader import read_percent

ROOT = Path(__file__).resolve().parents[1]
DORCHA = ROOT / "tests/data/autofind_20261016T192204168176Z_e70b6c5c.zip"
SAMPLES = ROOT / "tests/data/투아림게이지 샘플 모음.zip"


@pytest.fixture(scope="module", autouse=True)
def one_opencv_thread():
    before = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(before)


def decode(data):
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    return image


@pytest.fixture(scope="module")
def dorcha_input():
    with ZipFile(DORCHA) as archive:
        return decode(archive.read("input.png"))


def test_current_dorcha_autofind_must_locate_visible_zero(dorcha_input):
    trace = {}
    box = run_detector("dorcha", dorcha_input, detector_assets("dorcha"), trace)
    assert box is not None, trace
    x, y, w, h = box
    # Human-inspected zero at the ornament, not a number elsewhere in the scene.
    assert x <= 548 < x + w and y <= 136 < y + h, box
    assert 16 <= h <= 30 and 19 <= w <= 38, box
    assert read_dorcha(dorcha_input[y:y + h, x:x + w]) == 0


@pytest.mark.parametrize("name,expected", [
    ("v04_3995.png", 0),
    ("v04_4805.png", 39),
    ("v04_5789.png", 95),
    ("v04_5832.png", 99),
    ("v04_5845.png", None),
])
def test_manually_read_percent_must_not_become_four(name, expected):
    # Labels come from visual inspection, never from the v04 filename prefix.
    with ZipFile(SAMPLES) as archive:
        image = decode(archive.read("새 폴더 (2)/" + name))
    assert image.shape == (28, 58, 3)
    assert read_percent(image) == expected


def test_original_diagnostic_png_integrity_and_recorded_failure():
    with ZipFile(DORCHA) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        assert metadata["feature"] == "dorcha"
        assert metadata["app_version"] == "0.4.81"
        assert metadata["failure_stage"] == "detect" and metadata["result"] is None
        assert not metadata["missing_required_assets"]
        for name, digest in metadata["files_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
