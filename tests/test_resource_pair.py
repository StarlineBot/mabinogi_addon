import numpy as np
import pytest
from mabinogi_addon import image_io,autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import detector_assets,run_detector,replay
from mabinogi_addon.detect import resource_pair


@pytest.fixture
def panel():
    image = image_io.imread("tests/data/스크린샷 2026-10-18 124011.png")
    assert image is not None
    return image[34:109,1225:1332].copy()


def test_same_panel_yields_two_independently_validated_regions(panel):
    trace = {}
    assert run_detector("resources",panel,detector_assets("resources"),trace) == (14,23,68,44)
    assert trace["regions"] == {"dorcha":[14,23,28,23],"tuarim":[40,51,42,16]}


def test_multiple_panels_are_not_paired(panel):
    image = np.hstack([panel,np.zeros((75,20,3),np.uint8),panel])
    trace = {}
    assert run_detector("resources",image,detector_assets("resources"),trace) is None
    assert trace["rejection"] == "ambiguous_candidates"


def test_independent_detectors_cannot_pair_different_ornaments(panel,monkeypatch):
    monkeypatch.setattr(resource_pair.dorcha_anchor,"locate_dorcha",lambda *args:(14,23,28,23))
    monkeypatch.setattr(resource_pair.tuarim_anchor,"locate_tuarim",lambda *args:(140,51,42,16))
    trace = {}
    assert resource_pair.locate_resources(panel,{},trace) is None
    assert trace["rejection"] == "different_ornaments"


def test_missing_dorcha_word_models_allow_independent_percent_success(panel):
    assets = {key:image for key,image in detector_assets("resources").items() if not key.startswith("dorcha_word_")}
    trace = {}
    assert run_detector("resources",panel,assets,trace) is not None
    assert set(trace["regions"]) == {"tuarim"}


def test_missing_right_button_can_still_offer_only_dorcha(panel):
    panel = panel.copy()
    panel[39:52,53:80] = 0
    trace = {}
    assert run_detector("resources",panel,detector_assets("resources"),trace) is not None
    assert set(trace["regions"]) == {"dorcha"}


def test_common_zip_contains_both_models_and_replays_without_installed_assets(panel,tmp_path,monkeypatch):
    store = diag.DiagnosticStore(tmp_path/"공통 진단")
    try:
        _,_,_,box = diag.perform_autofind("resources",lambda:(panel,-300,40),storage=store)
        assert box == (14,23,68,44)
        store.io.wait()
        archive = store.export(store.recent()[0],tmp_path/"같은 입력.zip")
        monkeypatch.setattr(resource_pair,"assets",lambda:pytest.fail("installed models loaded"))
        result = replay(archive)
        assert result["matches_recorded"] and result["result"] == list(box)
    finally:
        store.io.close()
