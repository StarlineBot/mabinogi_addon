"""Padded readers must not turn uncertain tens into a confident single digit."""

import numpy as np
import pytest
import cv2

from scripts.qa_tuarim_visible_nineteen_20261018 import (
    nineteen, pipeline, sample, hundred,
    test_native_registered_nineteen_keeps_its_tens,
    test_actual_reader_and_stabilizer_display_nineteen,
    test_prior_bright_scene_reads_the_same_nineteen,
    test_prior_narrow_low_range_controls_still_read,
    test_full_hundred_is_still_held_as_unreadable,
)
from mabinogi_addon import image_io
from mabinogi_addon.detect import tuarim_reader as reader


def padded(frame):
    height = frame.shape[0]+3
    image = np.zeros((height,max(round(height*2.7),frame.shape[1]+14),3),np.uint8)
    image[1:1+frame.shape[0],7:7+frame.shape[1]] = frame
    return image


def test_thin_reference_is_the_original_native_cell():
    frame = image_io.imread("tests/data/스크린샷 2026-10-18 124011.png")
    assert frame is not None
    np.testing.assert_array_equal(reader._THIN_ONE, frame[86:99,1274:1282].max(axis=2))


@pytest.mark.parametrize("reference", [None, np.zeros((13,8),np.uint8), np.zeros((12,8),np.uint8)])
def test_uncertain_tens_without_matching_reference_are_held(nineteen, monkeypatch, reference):
    monkeypatch.setattr(reader, "_THIN_ONE", reference)
    assert reader.read_percent(nineteen) is None


def test_faint_tens_does_not_invent_a_high_digit(nineteen, monkeypatch):
    classify = reader._classify
    def wrong_tens(vec, refs, labels):
        if refs is reader._REFS[2]:
            return 9, 0.99
        return classify(vec, refs, labels)
    monkeypatch.setattr(reader, "_classify", wrong_tens)
    assert reader.read_percent(nineteen) == 19


def test_reference_does_not_override_uncertain_ones(nineteen, monkeypatch):
    classify = reader._classify
    def weak_ones(vec, refs, labels):
        digit, score = classify(vec, refs, labels)
        if refs is reader._REFS[0]:
            return digit, min(score,0.84)
        return digit, score
    monkeypatch.setattr(reader, "_classify", weak_ones)
    assert reader.read_percent(nineteen) is None


def test_sustained_nineteen_is_not_reset_evidence(nineteen):
    from mabinogi_addon.tracker import TuarimTracker
    from mabinogi_addon.tracker.tuarim import REARM_FRAMES
    tracker = TuarimTracker([90,95])
    assert tracker.observe(95) == []
    assert tracker.observe(95) == [90,95]
    for _ in range(REARM_FRAMES+2):
        assert tracker.observe(reader.read_percent(nineteen)) == []
    assert tracker.observe(98) == []
    assert tracker.observe(98) == []


@pytest.mark.parametrize("name,value", [("v01_124.png",1),("v01_151.png",4),
    ("v05_155.png",5),("v08_172.png",8),("v00_113.png",0),("v06_159.png",6)])
def test_real_single_digits_do_not_acquire_tens_when_padded(name, value):
    assert reader.read_percent(padded(sample(name))) in (None,value)


@pytest.mark.parametrize("value", range(90,100))
def test_padded_high_range_keeps_both_digits(value):
    frame = image_io.imread(f"tests/data/tuarim_hi/{value:02d}.png")
    assert frame is not None
    assert reader.read_percent(padded(frame)) == value


def test_full_session_in_padded_boxes_still_fires_exactly_twice():
    import re
    import zipfile
    from mabinogi_addon.tracker import TuarimTracker
    tracker = TuarimTracker([90,95])
    fired = []
    with zipfile.ZipFile("tests/data/raw_7603.zip") as archive:
        names = [name for name in archive.namelist() if re.fullmatch(r"(raw|v\d+)_\d+\.png",name)]
        names.sort(key=lambda name:int(re.search(r"_(\d+)\.png",name).group(1)))
        assert len(names) == 2926
        for name in names:
            frame = cv2.imdecode(np.frombuffer(archive.read(name),np.uint8),cv2.IMREAD_COLOR)
            assert frame is not None
            value = reader.read_percent(padded(frame))
            for _ in range(2):
                fired.extend(tracker.observe(value))
    assert fired == [90,95]
