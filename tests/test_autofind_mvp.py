"""Reference screenshots, structural negatives, approval and diagnostic replay."""

from copy import deepcopy

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QCoreApplication, QEvent, QRect
from PySide6.QtGui import QImage

from mabinogi_addon import autofind_diagnostics as diag, config, image_io
from mabinogi_addon.autofind_replay import detector_assets, replay, run_detector
from mabinogi_addon.detect.tuarim_reader import read_percent
from mabinogi_addon.ui import autofind_confirm as flow
from mabinogi_addon.ui.skillbar_tab import SkillbarTab
from mabinogi_addon.ui.tuarim_tab import TuarimTab
from mabinogi_addon.ui.skillbar_mirror import group_defs, slice_group


SHOTS = ("스크린샷 2026-10-10 190116.png", "스크린샷 2026-10-12 200511.png")


@pytest.fixture(scope="module", autouse=True)
def application():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(scope="module")
def frames():
    images = [image_io.imread(f"tests/data/{name}") for name in SHOTS]
    assert all(image is not None for image in images)
    return images


@pytest.mark.parametrize("feature,expected", [
    ("tuarim", [(742, 920, 42, 16), (965, 974, 42, 16)]),
    ("skillbar", [(2, 12, 1168, 89), (0, 10, 1168, 89)]),
])
def test_real_screen_reference_positions(frames, feature, expected):
    for frame, box in zip(frames, expected):
        trace = {}
        assert run_detector(feature, frame, detector_assets(feature), trace) == box
        assert trace["result"] == list(box)
        assert trace["candidates"]


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_no_anchor_on_blank_or_purple_background(feature):
    for color in ((0, 0, 0), (130, 20, 130)):
        frame = np.full((400, 1300, 3), color, np.uint8)
        assert run_detector(feature, frame, detector_assets(feature), {}) is None


def test_tuarim_movable_inner_number_independent_and_ambiguous(frames):
    patch = frames[0][875:943, 708:802].copy()
    patch[18:38, 14:30] = 0
    frame = np.zeros((500, 700, 3), np.uint8)
    frame[180:248, 210:304] = patch
    assets = detector_assets("tuarim")
    assert run_detector("tuarim", frame, assets, {}) == (244, 225, 42, 16)
    frame[350:418, 450:544] = patch
    trace = {}
    assert run_detector("tuarim", frame, assets, trace) is None
    assert trace["rejection"] == "ambiguous_candidates"


def test_tuarim_button_occlusion_rejected(frames):
    frame = frames[0].copy()
    frame[908:921, 755:779] = 0
    assert run_detector("tuarim", frame, detector_assets("tuarim"), {}) is None


def test_skillbar_moves_and_does_not_depend_on_skills(frames):
    patch = frames[0][:115, :1235].copy()
    for bx in (2, 622):
        for y in (12, 61):
            for group in (0, 188, 376):
                for cell in range(4):
                    x = bx + group + cell * 44
                    patch[y + 5:y + 35, x + 5:x + 35] = 60
    frame = np.zeros((450, 1600, 3), np.uint8)
    frame[220:335, 160:1395] = patch
    assert run_detector("skillbar", frame, detector_assets("skillbar"), {}) == (162, 232, 1168, 89)


def test_skillbar_mirror_only_and_partial_grid_rejected(frames):
    frame = frames[0].copy()
    frame[:140, :1250] = 0
    assert run_detector("skillbar", frame, detector_assets("skillbar"), {}) is None
    frame = frames[0].copy()
    frame[61:101, 998:1170] = 0
    trace = {}
    assert run_detector("skillbar", frame, detector_assets("skillbar"), trace) is None
    assert any(c.get("rejection") == "unsupported_grid" for c in trace["candidates"])


def test_detected_source_still_slices_all_48_original_cells(frames):
    frame = frames[0]
    x, y, w, h = run_detector("skillbar", frame, detector_assets("skillbar"), {})
    source = frame[y:y + h, x:x + w]
    for group in group_defs():
        cells = slice_group(source, group, [True] * 4)
        for index, cell in enumerate(cells):
            cx = x + (620 if group.block else 0) + (0, 188, 376)[group.col] + 44 * index
            cy = y + (49 if group.row else 0)
            image = cell.toImage().convertToFormat(QImage.Format.Format_RGB888)
            pixels = np.frombuffer(image.bits(), np.uint8).reshape(40, image.bytesPerLine())
            bgr = pixels[:, :120].reshape(40, 40, 3)[:, :, ::-1]
            np.testing.assert_array_equal(bgr, frame[cy:cy + 40, cx:cx + 40])


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_synthetic_150_percent_structure(frames, feature):
    source = frames[0]
    if feature == "tuarim":
        patch = source[875:943, 708:802]
        expected = (251, 138, 63, 24)
    else:
        patch = source[:115, :1235]
        expected = (203, 88, 1752, 134)
    scaled = cv2.resize(patch, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_AREA)
    frame = np.zeros((400, 2200, 3), np.uint8)
    frame[70:70 + scaled.shape[0], 200:200 + scaled.shape[1]] = scaled
    result = run_detector(feature, frame, detector_assets(feature), {})
    assert result is not None
    assert all(abs(a - b) <= 1 for a, b in zip(result, expected))


def test_reference_percentage_crop_reads_seven_and_does_not_reset_at_100(frames):
    patches = []
    for frame in frames:
        x, y, w, h = run_detector("tuarim", frame, detector_assets("tuarim"), {})
        patches.append(frame[y:y + h, x:x + w])
    assert read_percent(patches[0]) == 7
    for gain in (0.6, 0.8, 1.0, 1.1, 1.2, 1.4):
        altered = np.clip(patches[1].astype(float) * gain, 0, 255).astype(np.uint8)
        assert read_percent(altered) is None


@pytest.mark.parametrize("value", [90, 95, 98, 99])
def test_existing_high_glyphs_in_autofind_region_geometry(frames, value):
    reference = image_io.imread(f"tests/data/tuarim_hi/{value:02d}.png")
    assert reference is not None
    patch = frames[0][875:943, 708:802].copy()
    patch[45:61, 34:76] = 0
    patch[45:61, 42:76] = cv2.resize(reference, (34, 16), interpolation=cv2.INTER_AREA)
    frame = np.zeros((300, 600, 3), np.uint8)
    frame[100:168, 200:294] = patch
    box = run_detector("tuarim", frame, detector_assets("tuarim"), {})
    assert box is not None
    x, y, w, h = box
    assert read_percent(frame[y:y + h, x:x + w]) == value


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_new_detectors_roundtrip_original_zip(frames, tmp_path, monkeypatch, feature):
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    storage = diag.DiagnosticStore(tmp_path / "진단 자료")
    try:
        frame = frames[0]
        _, ox, oy, box = diag.perform_autofind(feature, lambda: (frame, -1920, 120), storage=storage)
        assert (ox, oy) == (-1920, 120) and box is not None
        storage.io.wait()
        record = storage.recent()[0]
        expected = {"anchor", "mask"}
        if feature == "tuarim":
            expected |= {"circle_anchor", "circle_mask", "circle_anchor_alt"}
        assert set(record.metadata["asset_names"]) == expected
        np.testing.assert_array_equal(image_io.imread(record.directory / "input.png"), frame)
        result = replay(storage.export(record, tmp_path / "공유.zip"))
        assert result["replayed"] and result["matches_recorded"]
    finally:
        storage.io.close()


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_confirmation_cancel_does_not_change_detector_result(frames, tmp_path, monkeypatch, feature):
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    storage = diag.DiagnosticStore(tmp_path / feature)
    try:
        frame = frames[0]
        outcome = {"status": "cancelled", "region_logical": [-200, 100, 60, 20]}
        diag.perform_autofind(feature, lambda: (frame, -1920, 120), storage=storage,
                              confirm=lambda *a: outcome)
        storage.io.wait()
        record = storage.recent()[0]
        assert record.metadata["success"] and record.metadata["confirmation"] == outcome
        assert replay(storage.export(record, tmp_path / f"{feature}.zip"))["matches_recorded"]
    finally:
        storage.io.close()


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_missing_mask_is_setup_failure_not_normal_no_match(frames, tmp_path, monkeypatch, feature):
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    storage = diag.DiagnosticStore(tmp_path / feature)
    assets = detector_assets(feature)
    assets.pop("mask")
    try:
        diag.perform_autofind(feature, lambda: (frames[0], 0, 0), storage=storage, assets=assets)
        storage.io.wait()
        record = storage.recent()[0]
        assert record.metadata["failure_stage"] == "detector_setup"
        assert record.metadata["missing_required_assets"] == ["mask"]
        assert not replay(storage.export(record, tmp_path / f"{feature}.zip"))["replayed"]
    finally:
        storage.io.close()


@pytest.fixture
def tabs(monkeypatch):
    app = QApplication.instance() or QApplication([])
    data = {"tuarim": {"enabled": False, "box": {"x": 10, "y": 20, "w": 58, "h": 28},
                       "thresholds": [90, 95], "sounds": [True, False]},
            "skillbar": {"enabled": False, "anchor": {"x": 1, "y": 2}, "scale": 130,
                         "centerTopY": 500, "chunks": {"b0r0c0": {
                             "pos": {"x": 400, "y": 500}, "locked": True,
                             "show": False, "cells": [False, True, True, False]}}}}
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: deepcopy(data))
    def write(value, *a, **k):
        data.clear()
        data.update(deepcopy(value))
    monkeypatch.setattr(config, "_write_local_config", write)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test"})
    class Watcher:
        def is_game_active(self): return False
        def is_self_active(self): return False
    tuarim, skillbar = TuarimTab(Watcher()), SkillbarTab(Watcher())
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: notices.append(a))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: notices.append(a))
    yield tuarim, skillbar, data, notices
    tuarim.shutdown()
    skillbar.shutdown()
    tuarim.deleteLater()
    skillbar.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("index,feature,box", [(0, "tuarim", (30, 40, 60, 20)),
                                               (1, "skillbar", (30, 40, 1168, 89))])
@pytest.mark.parametrize("mode", ["approve", "cancel", "no_match", "capture_failed", "raises"])
def test_approval_only_preserves_other_settings(tabs, monkeypatch, index, feature, box, mode):
    tab, data = tabs[index], tabs[2]
    before = deepcopy(data)
    def perform(*a, **k):
        if mode == "raises": raise RuntimeError("injected")
        if mode not in ("capture_failed", "no_match"):
            k["confirm"](box, -100, 50)
        return (None if mode == "capture_failed" else np.zeros((10, 10, 3), np.uint8),
                -100, 50, None if mode == "no_match" else box)
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(flow, "to_logical", lambda *coords: coords)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k:
                        QMessageBox.StandardButton.Yes if mode == "approve" else QMessageBox.StandardButton.No)
    tab._on_auto_find()
    assert tab._timer.isActive() and not tab._autofind_busy
    assert tab._autofind_highlight is None
    if mode == "approve":
        field = "box" if index == 0 else "anchor"
        expected = {"x": box[0] - 100, "y": box[1] + 50}
        if index == 0: expected.update(w=box[2], h=box[3])
        before[feature][field] = expected
    assert data == before


def test_tuarim_new_region_clears_evidence_but_keeps_fired_policy(tabs):
    tab = tabs[0]
    tab._tracker._fired = {90, 95}
    tab._tracker._low = 19
    tab._tracker._hi = {90: 1, 95: 1}
    tab._prev_raw = tab._stable_value = 5
    tab._apply_region(100, 200, 60, 20)
    assert tab._tracker._fired == {90, 95}
    assert tab._tracker._low == 0 and not any(tab._tracker._hi.values())
    assert tab._prev_raw is None and tab._stable_value is None


def test_reentry_shutdown_and_beta_gate(tabs, monkeypatch):
    tab = tabs[0]
    calls = []
    def perform(*a, **k):
        calls.append(a)
        tab._on_auto_find()
        k["confirm"]((30, 40, 60, 20), 0, 0)
        return np.zeros((10, 10, 3), np.uint8), 0, 0, (30, 40, 60, 20)
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k:
                        (tab.shutdown(), QMessageBox.StandardButton.Yes)[1])
    before = deepcopy(tabs[2])
    tab._on_auto_find()
    assert len(calls) == 1 and tabs[2] == before
    assert not tab._timer.isActive()
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    tabs[1]._on_auto_find()
    assert len(calls) == 1


def test_unsupported_mirror_size_keeps_anchor(tabs, monkeypatch):
    def perform(*a, **k):
        k["confirm"]((30, 40, 584, 45), 0, 0)
        return np.zeros((10, 10, 3), np.uint8), 0, 0, (30, 40, 584, 45)
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(flow, "to_logical", lambda *coords: coords)
    before = deepcopy(tabs[2])
    tabs[1]._on_auto_find()
    assert tabs[2] == before and tabs[3]


@pytest.mark.parametrize("index,feature,box", [(0, "tuarim", (30, 40, 60, 20)),
                                               (1, "skillbar", (30, 40, 1168, 89))])
def test_save_failure_restores_timer_and_in_memory_region(tabs, monkeypatch, index, feature, box):
    tab = tabs[index]
    def denied(*a, **k): raise PermissionError("read-only")
    monkeypatch.setattr(config, f"save_{feature}", denied)
    statuses = []
    def perform(*a, **k):
        statuses.append(k["confirm"](box, 0, 0))
        return np.zeros((10, 10, 3), np.uint8), 0, 0, box
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(flow, "to_logical", lambda *coords: coords)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    old = deepcopy(tab._region if index == 0 else tab._anchor)
    tab._on_auto_find()
    assert (tab._region if index == 0 else tab._anchor) == old
    assert statuses[0]["status"] == "save_failed"
    assert tab._timer.isActive() and tabs[3]


def test_skillbar_physical_scale_converts_to_existing_logical_grid(tabs, monkeypatch):
    def perform(*a, **k):
        k["confirm"]((90, 120, 1752, 134), -1920, 300)
        return np.zeros((10, 10, 3), np.uint8), -1920, 300, (90, 120, 1752, 134)
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(flow, "to_logical", lambda x, y, w, h: (-1220, 280, 1168, 89))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    tabs[1]._on_auto_find()
    assert tabs[2]["skillbar"]["anchor"] == {"x": -1220, "y": 280}


def test_repeated_cancel_closes_owned_highlights(tabs, monkeypatch):
    tab = tabs[0]
    def perform(*a, **k):
        k["confirm"]((30, 40, 42, 16), 0, 0)
        return np.zeros((10, 10, 3), np.uint8), 0, 0, (30, 40, 42, 16)
    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    for _ in range(20):
        tab._on_auto_find()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert tab._autofind_highlight is None
        assert not any(isinstance(w, flow.RegionHighlight) for w in QApplication.topLevelWidgets())


def test_highlight_covers_negative_virtual_desktop(tabs, monkeypatch):
    from mabinogi_addon.ui import region_highlight as mod
    class Screen:
        def virtualGeometry(self): return QRect(-1920, -100, 3840, 1180)
    monkeypatch.setattr(mod.QGuiApplication, "primaryScreen", lambda: Screen())
    highlight = mod.RegionHighlight()
    try:
        highlight.flash(-100, 50, 42, 16, "test", msec=0)
        assert highlight.geometry() == QRect(-1920, -100, 3840, 1180)
        assert highlight._rect.topLeft().x() == 1820
        assert not highlight._timer.isActive()
    finally:
        highlight.close()
        highlight.deleteLater()
