"""Independent MVP QA with real settings I/O, detector, approval, and replay."""

from copy import deepcopy
from pathlib import Path
import shutil

import numpy as np
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QMessageBox

from mabinogi_addon import autofind_diagnostics as diag, config, image_io
from mabinogi_addon.autofind_replay import replay
from mabinogi_addon.detect import autofind_anchors
from mabinogi_addon.ui import autofind_confirm as flow, dpi
from mabinogi_addon.ui.skillbar_mirror import group_defs
from mabinogi_addon.ui.skillbar_tab import SkillbarTab
from mabinogi_addon.ui.tuarim_tab import TuarimTab


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tests/data/\uc2a4\ud06c\ub9b0\uc0f7 2026-10-10 190116.png"
OFFSET = (-1920, 120)


@pytest.fixture(scope="session")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def live_pipeline(application, monkeypatch, tmp_path):
    settings = tmp_path / "\uc124\uc815 \uc790\ub8cc" / "settings.json"
    reader, writer = config._read_local_config, config._write_local_config
    chunks = {group.key: {"pos": {"x": 400 + index * 22, "y": 500 + index * 16},
                         "locked": index % 2 == 0, "show": index != 1,
                         "cells": [True, False, True, True]}
              for index, group in enumerate(group_defs())}
    writer({"tuarim": {"enabled": True, "box": {"x": 10, "y": 20, "w": 42, "h": 16},
                       "thresholds": [90, 95], "sounds": [True, False]},
            "skillbar": {"enabled": True, "anchor": {"x": 100, "y": 150},
                         "scale": 130, "centerTopY": 500, "chunks": chunks}}, settings)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: reader(settings))
    monkeypatch.setattr(config, "_write_local_config", lambda value, *a, **k: writer(value, settings))
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "qa-only"})
    monkeypatch.setattr(dpi, "screen_scale", lambda: 1.0)

    class Watcher:
        game = False

        def is_game_active(self):
            return self.game

        def is_self_active(self):
            return False

    watcher = Watcher()
    tabs = {"tuarim": TuarimTab(watcher), "skillbar": SkillbarTab(watcher)}
    frame = image_io.imread(REFERENCE)
    assert frame is not None
    storage = diag.DiagnosticStore(tmp_path / "diagnostics")
    capture = {"frame": frame}
    monkeypatch.setattr(flow, "capture_for_autofind", lambda: (capture["frame"], *OFFSET))
    original_perform = diag.perform_autofind

    def perform(feature, backend, **kwargs):
        return original_perform(feature, backend, storage=storage, **kwargs)

    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    before = deepcopy(reader(settings))
    yield tabs, settings, reader, storage, capture, watcher, before
    for tab in tabs.values():
        tab.shutdown()
        tab.deleteLater()
    storage.io.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
@pytest.mark.parametrize("approve", [True, False])
def test_real_settings_detector_confirmation_zip(live_pipeline, monkeypatch, tmp_path, feature, approve):
    tabs, settings, reader, storage, _capture, _watcher, before = live_pipeline
    tab = tabs[feature]
    if feature == "tuarim":
        tab._tracker._fired = {90, 95}
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k:
                        QMessageBox.StandardButton.Yes if approve else QMessageBox.StandardButton.No)
    tab._on_auto_find()
    storage.io.wait()
    record = storage.recent()[0]
    expected = deepcopy(before)
    if approve:
        expected[feature]["box" if feature == "tuarim" else "anchor"] = (
            {"x": -1178, "y": 1040, "w": 42, "h": 16} if feature == "tuarim"
            else {"x": -1918, "y": 132})
    assert reader(settings) == expected
    assert record.metadata["confirmation"]["status"] == ("applied" if approve else "cancelled")
    assert record.metadata["success"]
    result = replay(storage.export(record, tmp_path / "shared.zip"))
    assert result["replayed"] and result["matches_recorded"]
    assert tab._timer.isActive() and not tab._autofind_busy
    if feature == "tuarim":
        assert tab._tracker._fired == {90, 95}


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
@pytest.mark.parametrize("capture_mode", ["failed", "blank"])
def test_actual_capture_failure_preserves_json(live_pipeline, monkeypatch, feature, capture_mode):
    tabs, settings, reader, storage, capture, _watcher, before = live_pipeline
    capture["frame"] = None if capture_mode == "failed" else np.zeros((400, 1300, 3), np.uint8)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: pytest.fail("No candidate to approve"))
    tabs[feature]._on_auto_find()
    storage.io.wait()
    record = storage.recent()[0]
    assert not record.metadata["success"]
    assert record.metadata["failure_stage"] == ("capture" if capture_mode == "failed" else "detect")
    assert reader(settings) == before
    assert tabs[feature]._timer.isActive()


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_real_atomic_replace_failure_keeps_old_region(live_pipeline, monkeypatch, feature):
    tabs, settings, reader, storage, _capture, _watcher, before = live_pipeline
    original_replace = config.os.replace

    def fail_final_replace(source, target):
        if Path(target) == settings:
            raise PermissionError("independent final replace failure")
        return original_replace(source, target)

    monkeypatch.setattr(config.os, "replace", fail_final_replace)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    tab = tabs[feature]
    original_region = deepcopy(tab._region if feature == "tuarim" else tab._anchor)
    tab._on_auto_find()
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["confirmation"]["status"] == "save_failed"
    assert reader(settings) == before
    assert (tab._region if feature == "tuarim" else tab._anchor) == original_region
    assert tab._timer.isActive()


def test_approved_anchor_drives_real_mirror_tick(live_pipeline, monkeypatch):
    tabs, settings, reader, _storage, capture, watcher, before = live_pipeline
    tab = tabs["skillbar"]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    tab._on_auto_find()
    watcher.game = True
    calls = []
    frame = capture["frame"]

    def grab(x, y, w, h):
        calls.append((x, y, w, h))
        return frame[12:101, 2:1170].copy()

    monkeypatch.setattr(tab, "_grab_rect", grab)
    tab._tick()
    assert calls == [(-1918, 132, 1168, 89)]
    assert reader(settings)["skillbar"]["chunks"] == before["skillbar"]["chunks"]
    checked = 0
    for group in group_defs():
        overlay = tab._overlays[group.key]
        if not before["skillbar"]["chunks"][group.key]["show"]:
            assert not overlay.isVisible()
            continue
        for index, pixmap in enumerate(overlay._cells):
            if not before["skillbar"]["chunks"][group.key]["cells"][index]:
                assert pixmap is None
                continue
            image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
            pixels = np.frombuffer(image.bits(), np.uint8).reshape(40, image.bytesPerLine())
            actual = pixels[:, :120].reshape(40, 40, 3)[:, :, ::-1]
            x = 2 + (620 if group.block else 0) + (0, 188, 376)[group.col] + 44 * index
            y = 12 + (49 if group.row else 0)
            np.testing.assert_array_equal(actual, frame[y:y + 40, x:x + 40])
            checked += 1
    assert checked == 33


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_fifty_declines_leave_no_owned_highlights(live_pipeline, monkeypatch, feature):
    tabs, settings, reader, _storage, _capture, _watcher, before = live_pipeline
    tab = tabs[feature]
    box = (30, 40, 42, 16) if feature == "tuarim" else (30, 40, 1168, 89)

    def perform(_feature, _backend, **kwargs):
        kwargs["confirm"](box, 0, 0)
        return np.zeros((1, 1, 3), np.uint8), 0, 0, box

    monkeypatch.setattr(flow, "perform_autofind", perform)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.No)
    for _attempt in range(50):
        tab._on_auto_find()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert tab._autofind_highlight is None
        assert not tab._autofind_busy
        assert tab._timer.isActive()
        assert not any(isinstance(w, flow.RegionHighlight) for w in QApplication.topLevelWidgets())
    assert reader(settings) == before


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_assets_load_from_declared_bundle_layout(monkeypatch, tmp_path, feature):
    expected = autofind_anchors.assets(feature)
    target = tmp_path / "frozen bundle" / "mabinogi_addon/detect/templates/autofind"
    target.mkdir(parents=True)
    for name in ("anchor", "mask"):
        source = ROOT / "src/mabinogi_addon/detect/templates/autofind" / f"{feature}_{name}.png"
        shutil.copyfile(source, target / source.name)
    monkeypatch.setattr(autofind_anchors, "__file__",
                        str(target.parent.parent / "autofind_anchors.py"))
    actual = autofind_anchors.assets(feature)
    assert set(actual) == {"anchor", "mask"}
    for name in actual:
        np.testing.assert_array_equal(actual[name], expected[name])
