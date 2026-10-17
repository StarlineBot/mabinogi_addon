"""New source pixels, independent manual labels and reset safety."""

from zipfile import ZipFile
import cv2
import numpy as np
import pytest

from scripts.qa_new_resource_samples import (
    SAMPLES, decode, dorcha_input, one_opencv_thread,
    test_current_dorcha_autofind_must_locate_visible_zero,
    test_manually_read_percent_must_not_become_four,
    test_original_diagnostic_png_integrity_and_recorded_failure,
)
from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.tracker.tuarim import TuarimTracker, REARM_FRAMES
from mabinogi_addon.autofind_replay import detector_assets, run_detector
from mabinogi_addon import autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import replay


def sample(name):
    with ZipFile(SAMPLES) as archive:
        return decode(archive.read('새 폴더 (2)/v04_'+name+'.png'))


@pytest.mark.parametrize('name,value',[('4318',14),('4778',38),('4869',45),('4973',49),('4563',28)])
def test_visually_read_holdouts_not_used_as_glyph_sources(name,value):
    assert read_percent(sample(name)) == value


def test_hundred_hold_cannot_rearm_but_true_zero_can():
    tracker = TuarimTracker([90,95])
    fired = []
    for name in ['5789']*3+['5845']*(REARM_FRAMES+3)+['5832']*3:
        fired.extend(tracker.observe(read_percent(sample(name))))
    assert fired == [90,95]
    for name in ['3995']*(REARM_FRAMES+2)+['5832']*3:
        fired.extend(tracker.observe(read_percent(sample(name))))
    assert fired == [90,95,90,95]


@pytest.mark.parametrize('value',[0,130,255])
def test_blank_manual_box_does_not_become_four(value):
    assert read_percent(np.full((28,58,3),value,np.uint8)) is None


def test_corrupt_or_occluded_small_words_do_not_fall_back_to_four():
    image = sample('5845')
    image[:, :19] = 0
    assert read_percent(image) is None  # the visible 00% is not a reset
    image = sample('5789')
    image[8:16,27:32] = 0
    assert read_percent(image) is None


def test_new_dorcha_without_digits_and_two_panels_still_rejected(dorcha_input):
    data = detector_assets('dorcha')
    crop = dorcha_input[90:180,510:615].copy()
    crop[32:55,24:52] = 0
    assert run_detector('dorcha',crop,data,{}) is None
    crop = dorcha_input[90:180,510:615].copy()
    doubled = np.hstack([crop,np.zeros((90,20,3),np.uint8),crop])
    assert run_detector('dorcha',doubled,data,{}) is None


def test_new_frame_tuarim_autofind_reads_zero_and_requires_right_button(dorcha_input):
    data = detector_assets('tuarim')
    trace = {}
    box = run_detector('tuarim',dorcha_input,data,trace)
    assert box == (560,150,42,16), trace
    x,y,w,h = box
    assert read_percent(dorcha_input[y:y+h,x:x+w]) == 0
    missing = dorcha_input.copy()
    missing[138:149,573:597] = 0
    assert run_detector('tuarim',missing,data,{}) is None


@pytest.mark.parametrize('feature,expected', [('dorcha',(534,122,28,23)),('tuarim',(560,150,42,16))])
def test_new_models_replay_from_zip_without_installed_assets(feature,expected,dorcha_input,tmp_path,monkeypatch):
    from mabinogi_addon.detect import dorcha_anchor, tuarim_anchor, resource_anchor
    store = diag.DiagnosticStore(tmp_path/'한글 진단 폴더')
    try:
        _,_,_,box = diag.perform_autofind(feature,lambda:(dorcha_input,-2560,120),
                                         storage=store,assets=detector_assets(feature))
        assert box == expected
        store.io.wait()
        path = store.export(store.recent()[0],tmp_path/'재현 자료.zip')
        def forbidden(*a,**k):
            pytest.fail('replay loaded installed assets')
        for module in (dorcha_anchor,tuarim_anchor,resource_anchor):
            monkeypatch.setattr(module,'assets',forbidden)
        result = replay(path)
        assert result['replayed'] and result['matches_recorded']
        assert result['result'] == list(expected)
    finally:
        store.io.close()
