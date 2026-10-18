"""Shared ornament localization must not couple the two resource readers."""

import cv2
import numpy as np
import pytest

from mabinogi_addon import config, image_io, autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import detector_assets, run_detector, replay
from mabinogi_addon.detect import resource_anchor, dorcha_anchor, dorcha_reader, tuarim_anchor, tuarim_reader
from scripts.qa_tuarim_coarse_candidate_miss import (
    frame,
    test_original_full_frame_must_find_visible_tuarim,
    test_unobscured_neighborhood_locates_and_reads_ninety_eight,
    test_single_pixel_translation_does_not_change_scene_identity,
    test_same_full_frame_dorcha_anchor_corresponds_to_correct_percent_region,
    test_unreadable_dorcha_digits_must_not_block_percent_location,
)
from test_dorcha_reader import NEW, DATA


def test_tuarim_does_not_require_dorcha_words_reader_or_settings(monkeypatch):
    monkeypatch.setattr(dorcha_reader,"_REFS",None)
    def forbidden(*a,**k):
        pytest.fail("Tuarim depended on Dorcha reader/settings")
    monkeypatch.setattr(dorcha_anchor,"locate_dorcha",forbidden)
    monkeypatch.setattr(dorcha_reader,"read_dorcha",forbidden)
    monkeypatch.setattr(config,"load_dorcha",forbidden)
    data = detector_assets("tuarim")
    assert not any(key.startswith("word_") for key in data)
    image = frame()
    image[127:142,580:602] = 0
    assert run_detector("tuarim",image,data,{}) == (603,151,42,16)
    assert tuarim_reader.read_percent(image[151:167,603:645]) == 98


def test_percent_reader_is_not_a_localization_requirement(monkeypatch):
    monkeypatch.setattr(tuarim_reader,"read_percent",lambda *a,**k:pytest.fail("locator called percent reader"))
    assert run_detector("tuarim",frame(),detector_assets("tuarim"),{}) == (603,151,42,16)


def test_two_actual_resource_panels_are_ambiguous():
    panel = frame()[75:210,535:725].copy()
    image = np.hstack([panel,np.zeros((135,20,3),np.uint8),panel])
    trace = {}
    assert run_detector("tuarim",image,detector_assets("tuarim"),trace) is None
    assert trace["rejection"] == "ambiguous_candidates"


def test_circle_alone_does_not_replace_right_button_structure_validation():
    image = frame()[75:210,535:725].copy()
    image[:,79:] = 0
    assert len(resource_anchor.ornament_candidates(image,resource_anchor.assets(),{})) == 1
    assert run_detector("tuarim",image,detector_assets("tuarim"),{}) is None


def test_legacy_full_anchor_assets_still_locate_native_percent():
    from mabinogi_addon.detect.autofind_anchors import assets
    image = image_io.imread("tests/data/스크린샷 2026-10-12 000512.png")
    assert image is not None
    assert run_detector("tuarim",image,assets("tuarim"),{}) is not None


def test_new_zip_replays_shared_ornament_without_installed_assets(tmp_path,monkeypatch):
    store = diag.DiagnosticStore(tmp_path/"투아림 진단")
    image = frame()
    try:
        _,_,_,box = diag.perform_autofind("tuarim",lambda:(image,-300,120),storage=store)
        assert box == (603,151,42,16)
        store.io.wait()
        record = store.recent()[0]
        np.testing.assert_array_equal(image_io.imread(record.directory/"input.png"),image)
        path = store.export(record,tmp_path/"실패 재현.zip")
        def forbidden(*a,**k):
            pytest.fail("replay read installed assets")
        monkeypatch.setattr(resource_anchor,"assets",forbidden)
        monkeypatch.setattr(tuarim_anchor,"assets",forbidden)
        monkeypatch.setattr(dorcha_reader,"_REFS",None)
        result = replay(path)
        assert result["matches_recorded"] and result["result"] == list(box)
    finally:
        store.io.close()


@pytest.mark.parametrize("bad", [None,np.zeros((20,20),np.uint8),np.zeros((20,20,4),np.uint8),
                                np.zeros((20,20,3),np.float32)])
def test_invalid_frame_does_not_enter_template_matching(bad):
    assert run_detector("tuarim",bad,detector_assets("tuarim"),{}) is None


def test_native_fallback_can_be_cancelled_between_scales():
    calls = []
    trace = {}
    def cancelled():
        if "native grayscale fallback; unchanged acceptance score" in trace.get("transforms", ()):
            calls.append(1)
        return len(calls) == 3
    assert resource_anchor.ornament_candidates(np.zeros((180,260,3),np.uint8),resource_anchor.assets(),trace,cancelled) == []
    assert len(calls) == 3
    assert trace["rejection"] == "cancelled"
    assert "native grayscale fallback; unchanged acceptance score" in trace["transforms"]


@pytest.mark.parametrize("_value,stamp",NEW)
def test_shared_circle_locations_in_existing_dorcha_scenes_keep_percent_geometry(_value,stamp):
    image = image_io.imread(DATA/f"스크린샷 2026-10-16 {stamp}.png")
    assert image is not None
    x,y = (931,929) if image.shape[0] == 1436 else (933,931)
    assert run_detector("tuarim",image,detector_assets("tuarim"),{}) == (x+34,y+45,42,16)


def test_percent_region_below_visible_panel_is_rejected():
    image = frame()[75:165,535:725].copy()
    assert run_detector("tuarim",image,detector_assets("tuarim"),{}) is None


def test_shared_search_does_not_mutate_diagnostic_models():
    data = detector_assets("tuarim")
    before = {key:image.copy() for key,image in data.items()}
    assert run_detector("tuarim",frame(),data,{}) == (603,151,42,16)
    for key,image in before.items():
        np.testing.assert_array_equal(data[key],image)


@pytest.mark.parametrize("bad", [np.zeros((1,1),np.uint8),np.zeros((57,74),np.uint8),np.zeros(5,np.uint8)])
def test_invalid_full_structure_mask_is_rejected_without_cv_exception(bad):
    data = detector_assets("tuarim")
    data["mask"] = bad
    assert run_detector("tuarim",frame(),data,{}) is None
