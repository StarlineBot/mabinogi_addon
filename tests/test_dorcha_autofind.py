from pathlib import Path

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox

from mabinogi_addon import image_io, autofind_diagnostics as diag
from mabinogi_addon.autofind_replay import detector_assets, run_detector, replay
from mabinogi_addon.detect.dorcha_reader import read_dorcha
from mabinogi_addon.ui import autofind_confirm as confirm
from test_dorcha_reader import DATA, NEW
from test_dorcha_tab import runtime


@pytest.mark.parametrize("value,stamp",NEW)
def test_native_autofind_returns_inner_number_not_percent(value,stamp):
    cv2.setNumThreads(1)
    frame = image_io.imread(DATA/f"스크린샷 2026-10-16 {stamp}.png")
    assert frame is not None
    trace = {}
    box = run_detector("dorcha",frame,detector_assets("dorcha"),trace)
    x,y = (931,929) if frame.shape[0] == 1436 else (933,931)
    assert box == (x+8,y+17,28,23)
    x,y,w,h = box
    assert read_dorcha(frame[y:y+h,x:x+w]) == value
    assert trace["accept_score"] == .97


def small_scene():
    frame = image_io.imread(DATA/"스크린샷 2026-10-16 210734.png")
    return frame[925:1000,920:1020].copy()


def test_multiple_or_missing_circles_are_not_silently_selected():
    frame = small_scene()
    both = np.hstack([frame,np.zeros((frame.shape[0],20,3),np.uint8),frame])
    assert run_detector("dorcha",both,detector_assets("dorcha"),{}) is None
    assert run_detector("dorcha",np.zeros_like(frame),detector_assets("dorcha"),{}) is None
    trace = {}
    assert run_detector("dorcha",frame,{},trace) is None
    assert trace["rejection"] == "missing_required_templates"


@pytest.mark.parametrize("accept",[False,True])
def test_confirmation_only_saves_after_approval(runtime,monkeypatch,accept):
    tab,_,_ = runtime
    previous = dict(tab._region)
    monkeypatch.setattr(confirm,"to_logical",lambda *box:box)
    class Highlight:
        def flash(self,*a,**k): pass
        def close(self): pass
        def deleteLater(self): pass
    monkeypatch.setattr(confirm,"RegionHighlight",Highlight)
    monkeypatch.setattr(QMessageBox,"question",lambda *a,**k: QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.No)
    def perform(feature,capture,**kwargs):
        assert feature == "dorcha"
        result = kwargs["confirm"]((20,30,28,23),0,0)
        assert result["status"] == ("applied" if accept else "cancelled")
        return np.zeros((80,80,3),np.uint8),0,0,(20,30,28,23)
    monkeypatch.setattr(confirm,"perform_autofind",perform)
    tab._on_auto_find()
    assert tab._region == (dict(x=20,y=30,w=28,h=23) if accept else previous)


def test_diagnostic_zip_replays_same_inputs_and_assets(tmp_path):
    store = diag.DiagnosticStore(tmp_path/"진단")
    try:
        frame = small_scene()
        _,_,_,box = diag.perform_autofind("dorcha",lambda:(frame,0,0),storage=store)
        assert box is not None
        store.io.wait()
        record = store.recent()[0]
        zip_path = store.export(record,tmp_path/"도르카.zip")
        result = replay(zip_path)
        assert result["matches_recorded"] and result["result"] == list(box)
    finally:
        store.io.close()
