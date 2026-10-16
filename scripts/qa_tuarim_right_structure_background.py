"""Live v0.4.80 ZIP: valid ornament rejected by right-structure background."""

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
ZIP = ROOT / "tests/data/autofind_20261016T172504548267Z_2887b867.zip"
EXPECTED = (603, 151, 42, 16)


@pytest.fixture(scope="module", autouse=True)
def single_opencv_thread():
    before = cv2.getNumThreads()
    cv2.setNumThreads(1)
    yield
    cv2.setNumThreads(before)


@pytest.fixture(scope="module")
def diagnostic():
    with ZipFile(ZIP) as archive:
        metadata = json.loads(archive.read("metadata.json"))
        def image(name):
            result = cv2.imdecode(np.frombuffer(archive.read(name + ".png"), np.uint8),
                                  cv2.IMREAD_UNCHANGED)
            assert result is not None, name
            return result
        return metadata, image("input"), {name: image(name) for name in metadata["asset_names"]}


def right_mask(assets):
    mask = assets["mask"].copy()
    mask[:, :45] = 0
    return mask


def test_live_original_must_locate_visible_tuarim(diagnostic):
    _, frame, assets = diagnostic
    trace = {}
    result = run_detector("tuarim", frame, assets, trace)
    assert result == EXPECTED, trace


def test_saved_failure_records_current_assets_and_right_structure_rejection(diagnostic):
    metadata, _, assets = diagnostic
    assert metadata["app_version"] == "0.4.80"
    assert metadata["failure_stage"] == "detect"
    assert not metadata["missing_required_assets"]
    current = detector_assets("tuarim")
    assert assets.keys() == current.keys()
    for name, image in assets.items():
        np.testing.assert_array_equal(image, current[name])
    assert metadata["result"] is None
    assert metadata["detector"]["trace"]["rejection"] == "anchor_not_found"
    candidate = metadata["detector"]["trace"]["candidates"][-1]
    assert candidate["anchor"][:2] == [569, 106]
    assert candidate["ornament_score"] > 0.99
    assert candidate["structure_score"] < 0.97


def test_opaque_button_pixels_are_exact_and_score_one(diagnostic):
    _, frame, assets = diagnostic
    actual = frame[106:163, 569:643]
    np.testing.assert_array_equal(actual[33:44, 47:71], assets["anchor"][33:44, 47:71])
    mask = np.zeros_like(assets["mask"])
    mask[33:44, 47:71] = 255
    assert int(np.count_nonzero(mask)) == 264
    score = float(cv2.matchTemplate(actual, assets["anchor"], cv2.TM_CCORR_NORMED, mask=mask)[0, 0])
    assert score == pytest.approx(1.0, abs=1e-6)


def test_only_38_outside_pixels_change_rejection_to_acceptance(diagnostic):
    _, frame, assets = diagnostic
    mask = right_mask(assets)
    outside = mask > 0
    outside[33:45, 47:71] = False
    assert int(np.count_nonzero(mask)) == 326
    assert int(np.count_nonzero(outside)) == 38
    changed = frame.copy()
    region = changed[106:163, 569:643]
    region[outside] = assets["anchor"][outside]
    # Counterfactual only: the top ROI row is background, not the numeric glyph.
    np.testing.assert_array_equal(changed[152:167, 603:645], frame[152:167, 603:645])
    assert read_percent(changed[151:167, 603:645]) == 0
    np.testing.assert_array_equal(region[33:45, 47:71], frame[139:151, 616:640])
    trace = {}
    assert run_detector("tuarim", changed, assets, trace) == EXPECTED
    assert trace["candidates"][-1]["structure_score"] > 0.99


def test_visible_zero_percent_is_independently_readable(diagnostic):
    _, frame, _ = diagnostic
    assert read_percent(frame[151:167, 603:645]) == 0


def test_same_original_dorcha_locates_and_reads_five(diagnostic):
    _, frame, _ = diagnostic
    assert run_detector("dorcha", frame, detector_assets("dorcha"), {}) == (577, 123, 28, 23)
    assert read_dorcha(frame[123:146, 577:605]) == 5


def test_missing_right_button_is_still_rejected(diagnostic):
    _, frame, assets = diagnostic
    changed = frame.copy()
    changed[139:151, 616:640] = 0
    trace = {}
    assert run_detector("tuarim", changed, assets, trace) is None
    assert any(item.get("ornament_score", 0) > 0.99 for item in trace["candidates"])
