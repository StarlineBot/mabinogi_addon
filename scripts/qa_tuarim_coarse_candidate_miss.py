"""Explicit QA: full-frame coarse top-three selection misses a valid Tuarim UI."""

from pathlib import Path

import cv2
import numpy as np
import pytest

from mabinogi_addon import image_io
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon.detect.tuarim_reader import read_percent


SOURCE = Path(__file__).resolve().parents[1] / "tests/data/스크린샷 2026-10-17 012459.png"


@pytest.fixture(scope="module", autouse=True)
def one_cv_thread():
    old = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(old)


def frame():
    result = image_io.imread(SOURCE)
    assert result is not None and result.shape == (1440, 2560, 3)
    return result


def test_original_full_frame_must_find_visible_tuarim():
    trace = {}
    actual = run_detector("tuarim", frame(), detector_assets("tuarim"), trace)
    assert actual == (603, 151, 42, 16), {"actual": actual, "trace": trace}


def test_unobscured_neighborhood_locates_and_reads_ninety_eight():
    image = frame()[75:210, 535:725].copy()
    actual = run_detector("tuarim", image, detector_assets("tuarim"), {})
    assert actual == (68, 76, 42, 16)
    x, y, w, h = actual
    assert read_percent(image[y:y+h, x:x+w]) == 98


@pytest.mark.parametrize("dx,dy", [(-1,0), (0,-1), (-1,-1), (1,0), (0,1), (1,1)])
def test_single_pixel_translation_does_not_change_scene_identity(dx, dy):
    image = frame()
    shifted = cv2.warpAffine(image, np.float32([[1,0,dx],[0,1,dy]]),
                             (image.shape[1], image.shape[0]), flags=cv2.INTER_NEAREST)
    actual = run_detector("tuarim", shifted, detector_assets("tuarim"), {})
    assert actual == (603+dx, 151+dy, 42, 16)
    x, y, w, h = actual
    assert read_percent(shifted[y:y+h, x:x+w]) == 98


def test_same_full_frame_dorcha_anchor_corresponds_to_correct_percent_region():
    image = frame()
    actual = run_detector("dorcha", image, detector_assets("dorcha"), {})
    assert actual == (577, 123, 28, 23)
    # Scale=1 in this native screenshot. This is correspondence evidence, not a product fix.
    x, y = actual[0] + 26, actual[1] + 28
    assert (x, y) == (603, 151)
    assert read_percent(image[y:y+16, x:x+42]) == 98


def test_unreadable_dorcha_digits_must_not_block_percent_location():
    image = frame()[75:210, 535:725].copy()
    # Only the masked inner word changes; ornament and percentage pixels stay intact.
    image[52:67, 45:67] = 0
    actual = run_detector("tuarim", image, detector_assets("tuarim"), {})
    assert actual == (68, 76, 42, 16)
    assert read_percent(image[76:92, 68:110]) == 98
    trace = {}
    assert run_detector("dorcha", image, detector_assets("dorcha"), trace) is None
    assert trace["rejection"] == "unreadable_digits"
