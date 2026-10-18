"""Real input regression plus conservative ornament/number controls."""

import cv2
import numpy as np
import pytest

from scripts.qa_dorcha_visible_seven_20261018 import (
    original, one_thread, moving,
    test_the_exact_numeric_roi_reads_seven,
    test_visible_seven_is_found_in_the_original_frame,
    test_correct_saved_region_is_revalidated_by_the_actual_controller,
    test_alt_tab_returns_to_reading_the_same_visible_seven,
    test_alt_tab_known_ornament_control_still_recovers_fifteen,
)
from mabinogi_addon import autofind_diagnostics as diag, image_io
from mabinogi_addon.autofind_replay import detector_assets, replay, run_detector
from mabinogi_addon.detect import resource_anchor
from mabinogi_addon.detect.dorcha_anchor import locate_dorcha
from mabinogi_addon.detect.dorcha_reader import read_dorcha


def test_new_template_is_an_exact_grayscale_crop_and_excludes_inner_digits(original):
    data = resource_anchor.assets()
    gray = cv2.cvtColor(original[38:95,1229:1274], cv2.COLOR_BGR2GRAY)
    np.testing.assert_array_equal(data["anchor_seven"], cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    assert not np.any(data["mask"][22:36,14:30])


def test_shared_ornament_keeps_the_percent_region_separate(original):
    frame = original[32:107,1223:1330].copy()
    assert run_detector("dorcha", frame, detector_assets("dorcha"), {}) == (14,23,28,23)
    assert run_detector("tuarim", frame, detector_assets("tuarim"), {}) == (40,51,42,16)


def test_later_night_scene_finds_seven_without_another_reference():
    frame = image_io.imread("tests/data/스크린샷 2026-10-18 124011.png")
    assert frame is not None
    box = locate_dorcha(frame)
    assert box == (1239,57,28,23)
    x,y,w,h = box
    assert read_dorcha(frame[y:y+h,x:x+w]) == 7


def test_two_new_ornaments_are_ambiguous(original):
    panel = original[32:107,1223:1303]
    image = np.hstack([panel, np.zeros((75,20,3),np.uint8), panel])
    trace = {}
    assert locate_dorcha(image, diagnostics=trace) is None
    assert trace["rejection"] == "ambiguous_candidates"


def test_missing_ornament_in_actual_scene_is_not_a_numeric_fallback(original):
    image = original.copy()
    image[25:105,1220:1280] = 0
    assert locate_dorcha(image) is None


def test_matching_ornament_with_missing_inner_word_is_rejected(original):
    image = original[32:107,1223:1303].copy()
    image[28:42,20:36] = 0
    trace = {}
    assert locate_dorcha(image, diagnostics=trace) is None
    assert trace["rejection"] == "unreadable_digits"


def test_new_ornament_zip_replays_without_installed_templates(original, tmp_path, monkeypatch):
    store = diag.DiagnosticStore(tmp_path / "도르카 진단")
    try:
        frame = original[32:107,1223:1303].copy()
        _, _, _, box = diag.perform_autofind("dorcha", lambda: (frame,0,0), storage=store)
        assert box == (14,23,28,23)
        store.io.wait()
        record = store.recent()[0]
        assert "anchor_seven" in record.metadata["asset_names"]
        path = store.export(record, tmp_path / "재현.zip")
        monkeypatch.setattr(resource_anchor, "assets", lambda: pytest.fail("loaded installed assets"))
        result = replay(path)
        assert result["matches_recorded"] and result["result"] == list(box)
    finally:
        store.io.close()
