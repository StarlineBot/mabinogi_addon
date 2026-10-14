"""실제 원본 PNG, ZIP 재실행, 실패 격리와 비동기 수명 회귀 테스트."""

import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
from zipfile import ZipFile

import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from PySide6.QtCore import QTimer

from mabinogi_addon import autofind_diagnostics as diag, config, image_io
from mabinogi_addon.autofind_replay import replay, run_detector
from mabinogi_addon.system.window_watcher import AlwaysActiveWatcher
from mabinogi_addon.ui import diag_capture, screen_grab
from mabinogi_addon.ui.settings_tab import SettingsTab


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def storage(tmp_path, monkeypatch):
    store = diag.DiagnosticStore(tmp_path / "사용자 자료" / "진단")
    monkeypatch.setattr(diag, "_store", store)
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: {})
    yield store
    store.io.close()
    assert not store.io._thread.is_alive()


@pytest.fixture
def regions(tmp_path, monkeypatch):
    monkeypatch.setattr(diag_capture.paths, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(diag_capture, "to_physical", lambda r: tuple(r[k] for k in ("x", "y", "w", "h")))
    monkeypatch.setattr(config, "load_capture_region", lambda *a: {"x": -100, "y": 20, "w": 30, "h": 20})
    monkeypatch.setattr(config, "load_tuarim", lambda: {"box": None})
    monkeypatch.setattr(diag_capture, "_grab_pixels", lambda r: np.full((r[3], r[2], 3), 73, np.uint8))


def _capture(frame, offset=(-1920, 100)):
    def grab():
        info = diag.capture_info.get()
        info.update(backend="fake-mss", target="game_window", frame_size=[frame.shape[1], frame.shape[0]],
                    qt_screens=[{"device_pixel_ratio": 1.0}, {"device_pixel_ratio": 1.5}])
        return frame, *offset
    return grab


def _failed(frame, storage, marker="run-only"):
    def detect(image, trace, assets):
        logging.getLogger("mabinogi_addon.repro").warning(marker)
        trace["rejection"] = "test-no-match"
        return None
    return diag.perform_autofind("test", _capture(frame), detect=detect, assets={}, storage=storage)


def test_diagnostic_directory_permission_is_result(regions, monkeypatch):
    original = Path.mkdir
    def denied(self, *a, **k):
        if self.name == "debug":
            raise PermissionError("read-only diagnostic directory")
        return original(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", denied)
    result = diag_capture.save_diagnostic()
    assert not result.saved
    assert "PermissionError" in result.error
    assert [r.status for r in result.regions] == ["save_failed", "save_failed", "unconfigured"]
    assert "영역 미지정" in result.message() and "저장 폴더 오류" in result.message()


def test_user_directory_creation_permission_is_result(regions, monkeypatch):
    def denied():
        raise PermissionError("user data creation")
    monkeypatch.setattr(diag_capture.paths, "user_data_dir", denied)
    assert "PermissionError" in diag_capture.save_diagnostic().error


@pytest.mark.parametrize("bad", [
    {"x": 0, "y": 0, "w": 30}, {}, {"x": "0", "y": 0, "w": 30, "h": 20},
    {"x": True, "y": 0, "w": 30, "h": 20}, {"x": 0, "y": 0, "w": -1, "h": 20},
    {"x": 0, "y": 0, "w": 30, "h": 0}, {"x": 0, "y": 0, "w": 10**9, "h": 20},
])
def test_corrupt_buff_does_not_stop_debuff(regions, monkeypatch, bad):
    monkeypatch.setattr(config, "load_capture_region", lambda name: bad if name == "buffTracker" else {"x": 0, "y": 0, "w": 30, "h": 20})
    result = diag_capture.save_diagnostic()
    assert [r.status for r in result.regions] == ["invalid_region", "saved", "unconfigured"]
    assert len(result.saved) == 1


@pytest.mark.parametrize("mode", ["none", "exception", "write_false", "write_exception"])
def test_capture_and_png_errors_are_distinct(regions, monkeypatch, mode):
    def fail(*args):
        raise OSError("injected failure")
    if mode in ("none", "exception"):
        monkeypatch.setattr(diag_capture, "_grab_pixels", (lambda r: None) if mode == "none" else fail)
    else:
        monkeypatch.setattr(image_io, "imwrite", (lambda *a: False) if mode == "write_false" else fail)
    result = diag_capture.save_diagnostic()
    expected = "capture_failed" if mode in ("none", "exception") else "save_failed"
    assert result.regions[0].status == expected
    assert ("캡처 실패" if expected == "capture_failed" else "PNG 저장 실패") in result.message()


def test_partial_png_failure_keeps_other_region(regions, monkeypatch):
    write = image_io.imwrite
    monkeypatch.setattr(image_io, "imwrite", lambda p, f: False if p.name.startswith("buffTracker") else write(p, f))
    result = diag_capture.save_diagnostic()
    assert result.regions[0].status == "save_failed"
    assert result.regions[1].status == "saved"
    assert "1개 저장" in result.message() and "버프: PNG 저장 실패" in result.message()


def test_snapshot_pixels_unchanged(regions):
    result = diag_capture.save_diagnostic()
    for filename in result.saved:
        assert np.array_equal(image_io.imread(result.directory / filename), np.full((20, 30, 3), 73, np.uint8))


def test_input_pixels_and_zip_bytes_unchanged(storage, tmp_path):
    frame = np.random.default_rng(11).integers(0, 256, (40, 70, 3), np.uint8)[:, ::2]
    original = frame.copy()
    _failed(frame, storage)
    frame[:] = 0
    storage.io.wait()
    record = storage.recent()[0]
    png = (record.directory / "input.png").read_bytes()
    assert np.array_equal(image_io.imread(record.directory / "input.png"), original)
    archive = storage.export(record, tmp_path / "한글 공백 !" / "공유.zip")
    with ZipFile(archive) as z:
        assert z.read("input.png") == png
        extracted = Path(z.extract("input.png", tmp_path / "압축 해제"))
        assert extracted.read_bytes() == png
        meta = json.loads(z.read("metadata.json"))
        assert meta["capture"]["offset_physical"] == [-1920, 100]
        assert meta["capture"]["qt_screens"][1]["device_pixel_ratio"] == 1.5


def test_detector_mutation_does_not_change_recorded_input(storage):
    frame = np.full((40, 70, 3), 123, np.uint8)
    def mutate(image, trace, assets):
        image[:] = 9
        return None
    diag.perform_autofind("test", _capture(frame), detect=mutate, assets={}, storage=storage)
    storage.io.wait()
    saved = image_io.imread(storage.recent()[0].directory / "input.png")
    assert np.all(saved == 123)


def test_repeated_runs_do_not_mix_images_or_logs(storage):
    for i in range(8):
        _failed(np.full((40, 70, 3), i + 20, np.uint8), storage, f"unique-execution-{i}")
        storage.io.wait()
    records = list(reversed(storage.recent()))
    assert len(records) == 8 and len({r.id for r in records}) == 8
    for i, record in enumerate(records):
        assert np.all(image_io.imread(record.directory / "input.png") == i + 20)
        logs = (record.directory / "logs.txt").read_text()
        assert f"unique-execution-{i}" in logs
        assert all(f"unique-execution-{j}" not in logs for j in range(8) if i != j)


@pytest.mark.parametrize("raises", [False, True])
def test_capture_failure_can_export_without_png(storage, tmp_path, raises):
    def fail():
        if raises:
            raise RuntimeError("capture unavailable")
        return None, 0, 0
    result = diag.perform_autofind("buff", fail, storage=storage)
    assert result == (None, 0, 0, None)
    storage.io.wait()
    record = storage.recent()[0]
    archive = storage.export(record, tmp_path / "capture-failed.zip")
    with ZipFile(archive) as z:
        assert "input.png" not in z.namelist()
        assert {"metadata.json", "logs.txt"} <= set(z.namelist())
    result = replay(archive)
    assert not result["replayed"] and result["failure_stage"] == "capture"


def test_png_write_failure_leaves_metadata_and_logs(storage, monkeypatch, tmp_path):
    monkeypatch.setattr(image_io, "imwrite", lambda *args: False)
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["image_errors"]
    with ZipFile(storage.export(record, tmp_path / "png-failed.zip")) as z:
        assert "input.png" not in z.namelist()
        assert json.loads(z.read("metadata.json"))["image_errors"]


def test_storage_permission_can_export_original_from_memory(storage, monkeypatch, tmp_path):
    def denied():
        raise PermissionError("injected storage permission")
    monkeypatch.setattr(storage, "_root", denied)
    frame = np.full((40, 70, 3), 83, np.uint8)
    _failed(frame, storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert "PermissionError" in record.storage_error and record.directory is None
    with ZipFile(storage.export(record, tmp_path / "permission.zip")) as z:
        saved = cv2.imdecode(np.frombuffer(z.read("input.png"), np.uint8), cv2.IMREAD_UNCHANGED)
        assert np.array_equal(saved, frame)
        assert "PermissionError" in json.loads(z.read("metadata.json"))["storage_error"]


def test_replay_does_not_claim_success_with_missing_template(storage, monkeypatch, tmp_path):
    write = image_io.imwrite
    monkeypatch.setattr(image_io, "imwrite", lambda p, f: False if p.name == "anchor.png" else write(p, f))
    diag.perform_autofind("buff", _capture(np.zeros((100, 180, 3), np.uint8)), storage=storage)
    storage.io.wait()
    path = storage.export(storage.recent()[0], tmp_path / "missing-template.zip")
    result = replay(path)
    assert not result["replayed"] and result["failure_stage"] == "diagnostic_assets"


@pytest.mark.parametrize("feature", ["buff", "boss", "debuff"])
def test_initial_missing_templates_are_setup_failure(storage, monkeypatch, tmp_path, feature):
    from unittest.mock import Mock
    from mabinogi_addon import autofind_replay
    from mabinogi_addon.detect import status_panel, boss_hp_reader
    if feature == "buff":
        monkeypatch.setattr(status_panel, "anchor_template", lambda: None)
    else:
        monkeypatch.setattr(boss_hp_reader, "_DIGITS", {})
    detector = Mock()
    monkeypatch.setattr(autofind_replay, "run_detector", detector)
    frame = np.full((100, 180, 3), 73, np.uint8)
    diag.perform_autofind(feature, _capture(frame), storage=storage)
    detector.assert_not_called()
    storage.io.wait()
    record = storage.recent()[0]
    assert not record.metadata["success"]
    assert record.metadata["failure_stage"] == "detector_setup"
    assert record.metadata["missing_required_assets"]
    assert "필수 검출 템플릿 없음" in record.metadata["error"]
    np.testing.assert_array_equal(image_io.imread(record.directory / "input.png"), frame)
    result = replay(storage.export(record, tmp_path / "initially-missing.zip"))
    assert not result["replayed"] and result["failure_stage"] == "detector_setup"
    assert result["missing_assets"] == record.metadata["missing_required_assets"]
    detector.assert_not_called()


@pytest.mark.parametrize("feature", ["buff", "boss", "debuff"])
def test_legacy_empty_asset_list_does_not_bypass_requirements(storage, tmp_path, feature):
    metadata = {"schema": 1, "run_id": "legacy-empty-assets", "feature": feature,
                "started_at": "2026-10-14T00:00:00+00:00", "app_version": "0.0.0",
                "success": False, "failure_stage": "detect", "result": None, "asset_names": []}
    storage.add(diag.RunRecord(metadata, np.zeros((100, 180, 3), np.uint8)))
    storage.io.wait()
    result = replay(storage.export(storage.recent()[0], tmp_path / "legacy.zip"))
    assert not result["replayed"] and result["failure_stage"] == "detector_setup"
    assert result["missing_assets"]


@pytest.mark.parametrize("feature", ["boss", "debuff"])
def test_missing_single_digit_template_is_setup_failure(storage, monkeypatch, tmp_path, feature):
    from mabinogi_addon.detect import boss_hp_reader
    digits = {k: v for k, v in boss_hp_reader._DIGITS.items() if k != "9"}
    monkeypatch.setattr(boss_hp_reader, "_DIGITS", digits)
    diag.perform_autofind(feature, _capture(np.zeros((100, 180, 3), np.uint8)), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["failure_stage"] == "detector_setup"
    assert record.metadata["missing_required_assets"] == ["digit_9"]
    result = replay(storage.export(record, tmp_path / "missing-digit.zip"))
    assert not result["replayed"] and result["missing_assets"] == ["digit_9"]


@pytest.mark.parametrize("feature", ["boss", "debuff"])
def test_loaded_digit_png_failure_is_not_setup_failure(storage, monkeypatch, tmp_path, feature):
    write = image_io.imwrite
    monkeypatch.setattr(image_io, "imwrite", lambda p, f: False if p.name.startswith("digit_9_") else write(p, f))
    diag.perform_autofind(feature, _capture(np.zeros((100, 180, 3), np.uint8)), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["failure_stage"] == "detect"
    assert record.metadata["missing_required_assets"] == []
    assert record.metadata["image_errors"]
    result = replay(storage.export(record, tmp_path / "digit-png-failure.zip"))
    assert not result["replayed"] and result["failure_stage"] == "diagnostic_assets"


@pytest.mark.parametrize("feature", ["buff", "boss", "debuff", "stat_bars"])
def test_failed_zip_alone_replays_all_detectors(storage, tmp_path, monkeypatch, feature):
    frame = np.zeros((100, 180, 3), np.uint8)
    diag.perform_autofind(feature, _capture(frame), storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert not record.metadata["success"] and record.metadata["failure_stage"] == "detect"
    path = storage.export(record, tmp_path / f"{feature}.zip")
    from mabinogi_addon.detect import status_panel, boss_hp_reader
    monkeypatch.setattr(status_panel, "anchor_template", lambda: None)
    monkeypatch.setattr(boss_hp_reader, "_DIGITS", {})
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: pytest.fail("replay must not read local config"))
    result = replay(path)
    assert result["replayed"] and result["matches_recorded"]


@pytest.mark.parametrize("feature", ["buff", "boss", "debuff", "stat_bars"])
def test_real_screenshot_zip_replays_same_result(storage, tmp_path, feature):
    from mabinogi_addon.autofind_replay import detector_assets
    frame = image_io.imread(Path(__file__).parent / "data" / "스크린샷 2026-10-09 190901.png")
    assert frame is not None
    expected = run_detector(feature, frame, detector_assets(feature), {})
    _, _, _, found = diag.perform_autofind(feature, _capture(frame), storage=storage)
    assert found == expected
    storage.io.wait()
    path = storage.export(storage.recent()[0], tmp_path / f"real-{feature}.zip")
    assert replay(path)["matches_recorded"]


def test_secrets_removed_from_config_logs_and_errors(storage, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "_read_local_config", lambda: {
        "nexonApiKey": "private-value-9943", "general": {"apiKey": "nested-private-1212", "gameExe": "client.exe"},
        "discord": {"accessToken": "access-private-5566"}, "inquiryWebhookUrl": "https://discord.com/api/webhooks/1/secret",
    })
    def capture():
        raise RuntimeError("private-value-9943 nested-private-1212 access-private-5566 token=unknown-token-007 https://discord.com/api/webhooks/1/secret")
    diag.perform_autofind("buff", capture, storage=storage)
    storage.io.wait()
    path = storage.export(storage.recent()[0], tmp_path / "sanitized.zip")
    with ZipFile(path) as z:
        text = z.read("metadata.json").decode() + z.read("logs.txt").decode()
        for secret in ("private-value-9943", "nested-private-1212", "access-private-5566", "unknown-token-007", "/webhooks/1/secret"):
            assert secret not in text
        assert "client.exe" in text and "[REDACTED]" in text


def test_retention_count_and_bytes(storage):
    storage.max_runs = 3
    for i in range(8):
        _failed(np.full((40, 70, 3), i, np.uint8), storage)
        storage.io.wait()
    assert len(storage.recent()) == 3
    assert len([p for p in storage.root.iterdir() if not p.name.startswith(".")]) == 3
    storage.max_bytes = 1
    storage.refresh()
    assert not storage.recent()
    assert not list(storage.root.iterdir())


def test_memory_and_queue_bounds_do_not_wait_for_writer(storage):
    storage.max_memory = 1000
    release, started = threading.Event(), threading.Event()
    def slow():
        started.set()
        release.wait(10)
    storage.io.submit(slow)
    assert started.wait(2)
    try:
        for i in range(10):
            _failed(np.zeros((40, 70, 3), np.uint8), storage, f"bounded-{i}")
        assert sum(r.memory_bytes for r in storage.recent()) <= 1000
        assert storage.io._queue.qsize() <= 3
        assert any(r.storage_error for r in storage.recent())
    finally:
        release.set()
        storage.io.wait()


def test_zip_error_preserves_existing_file_and_cleans_tmp(storage, monkeypatch, tmp_path):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    dest = tmp_path / "existing.zip"
    dest.write_bytes(b"previous-backup")
    def denied(*a, **k):
        raise PermissionError("zip write denied")
    monkeypatch.setattr(ZipFile, "write", denied)
    with pytest.raises(PermissionError):
        storage.export(storage.recent()[0], dest)
    assert dest.read_bytes() == b"previous-backup"
    assert not list(tmp_path.glob("*.tmp"))


def test_export_inside_run_folder_includes_only_manifest(storage):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    record = storage.recent()[0]
    (record.directory / "config.local.json.bak").write_text('{"token":"never-share-this"}')
    path = storage.export(record, record.directory / "shared.zip")
    with ZipFile(path) as z:
        assert set(z.namelist()) == {"metadata.json", "logs.txt", "input.png"}
    storage.export(record, path)
    with ZipFile(path) as z:
        assert "shared.zip" not in z.namelist()


def test_export_refuses_original_file_overwrite(storage):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    record = storage.recent()[0]
    original = (record.directory / "input.png").read_bytes()
    with pytest.raises(ValueError, match="덮어쓸"):
        storage.export(record, record.directory / "input.png")
    assert (record.directory / "input.png").read_bytes() == original


def test_export_refuses_corrupted_png(storage, tmp_path):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    record = storage.recent()[0]
    (record.directory / "input.png").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="무결성"):
        storage.export(record, tmp_path / "bad.zip")


def test_invalid_asset_name_does_not_touch_file_outside_run(storage):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    record = storage.recent()[0]
    outside = storage.root / "keep.png"
    outside.write_bytes(b"do-not-delete")
    record.assets = {"../keep": np.zeros((5, 5), np.uint8)}
    metadata = storage._write(record, storage.root / "temporary-test")
    assert metadata["image_errors"] and outside.read_bytes() == b"do-not-delete"


@pytest.mark.parametrize("unhandled", [True, False])
def test_snapshot_restores_window_on_permission_error(app, storage, regions, monkeypatch, unhandled):
    widget = SettingsTab(AlwaysActiveWatcher())
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))
    def denied(*a):
        raise PermissionError("injected collector exception")
    if unhandled:
        monkeypatch.setattr(diag_capture, "save_diagnostic", denied)
    else:
        monkeypatch.setattr(diag_capture.paths, "user_data_dir", denied)
    widget._diag_minimized = True
    widget.showMinimized()
    try:
        widget._do_diag_capture()
        storage.io.wait()
        widget._poll_diagnostic()
        assert not widget.isMinimized()
        assert warnings and "PermissionError" in warnings[0]
    finally:
        widget.shutdown()
        widget.close()


def test_zip_worker_keeps_ui_responsive_and_shutdown_stops_callbacks(app, storage):
    widget = SettingsTab(AlwaysActiveWatcher())
    release, started = threading.Event(), threading.Event()
    callbacks = []
    def slow():
        started.set()
        release.wait(10)
    try:
        widget._diagnostic_job(slow, (), lambda *args: callbacks.append(args))
        assert started.wait(2)
        heartbeat = []
        QTimer.singleShot(0, lambda: heartbeat.append(True))
        app.processEvents()
        assert heartbeat == [True]
        assert widget._diag_poll.isActive() and not widget._diag_future.done()
        widget.shutdown()
        release.set()
        storage.io.wait()
        app.processEvents()
        assert not callbacks and not widget._diag_poll.isActive()
    finally:
        release.set()
        widget.shutdown()
        widget.close()


def test_partial_collection_restores_window_and_reports_missing_region(app, storage, regions, monkeypatch):
    monkeypatch.setattr(config, "load_capture_region", lambda name: {"x": 0, "y": 0, "w": 30} if name == "buffTracker" else {"x": 0, "y": 0, "w": 30, "h": 20})
    widget = SettingsTab(AlwaysActiveWatcher())
    messages = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: messages.append(box.text()))
    widget._diag_minimized = True
    widget.showMinimized()
    try:
        widget._do_diag_capture()
        storage.io.wait()
        widget._poll_diagnostic()
        assert not widget.isMinimized()
        assert messages and "1개 저장" in messages[0] and "버프: 영역 오류" in messages[0]
        assert widget._diag_status.text() != "처리 중..."
    finally:
        widget.shutdown()
        widget.close()


def test_shutdown_cancels_snapshot_countdown(app, storage, monkeypatch):
    widget = SettingsTab(AlwaysActiveWatcher())
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Ok)
    try:
        widget._on_diag_snapshot()
        assert widget._diag_countdown.isActive()
        widget.shutdown()
        assert not widget._diag_countdown.isActive()
        app.processEvents()
        assert widget._diag_future is None
    finally:
        widget.shutdown()
        widget.close()


def test_concurrent_runs_have_separate_context_and_images(storage):
    barrier = threading.Barrier(2)
    def execute(i):
        def detect(frame, trace, assets):
            barrier.wait(timeout=3)
            logging.getLogger("mabinogi_addon.repro").warning(f"parallel-only-{i}")
            return None
        diag.perform_autofind("test", _capture(np.full((40, 70, 3), 30 + i, np.uint8)),
                              detect=detect, assets={}, storage=storage)
    threads = [threading.Thread(target=execute, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    storage.io.wait()
    assert len(storage.recent()) == 2
    for record in storage.recent():
        frame = image_io.imread(record.directory / "input.png")
        i = int(frame[0, 0, 0]) - 30
        logs = (record.directory / "logs.txt").read_text()
        assert f"parallel-only-{i}" in logs and f"parallel-only-{1 - i}" not in logs


def test_restart_ignores_corrupt_records_and_cleans_interrupted_save(storage):
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    completed_id = storage.recent()[0].id
    corrupt = storage.root / "corrupt"
    corrupt.mkdir()
    (corrupt / "metadata.json").write_text('{"run_id":"corrupt", "schema":1}')
    code = '''
import os, sys
from pathlib import Path
import numpy as np
from mabinogi_addon.autofind_diagnostics import DiagnosticStore, RunRecord
s = DiagnosticStore(Path(sys.argv[1]))
write = s._write
def interrupted(record, folder):
    write(record, folder)
    os._exit(9)
s._write = interrupted
s.add(RunRecord({"schema":1, "run_id":"20261014T000000000000Z_deadbeef",
                 "feature":"buff", "started_at":"2026-10-14T00:00:00+00:00",
                 "success":False, "failure_stage":"detect"},
                np.zeros((40,70,3), np.uint8)))
s.io.wait()
'''
    result = subprocess.run([sys.executable, "-c", code, str(storage.root)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=15, capture_output=True)
    assert result.returncode == 9, result.stderr.decode()
    assert (storage.root / ".20261014T000000000000Z_deadbeef").exists()
    records = storage.refresh()
    assert [r.id for r in records] == [completed_id]
    assert not (storage.root / ".20261014T000000000000Z_deadbeef").exists()


def test_eviction_releases_memory_even_if_ui_holds_record(storage, monkeypatch):
    storage.max_runs = 2
    monkeypatch.setattr(storage, "_root", lambda: (_ for _ in ()).throw(PermissionError("storage denied")))
    _failed(np.zeros((40, 70, 3), np.uint8), storage)
    storage.io.wait()
    retained_by_ui = storage.recent()[0]
    for _ in range(3):
        _failed(np.zeros((40, 70, 3), np.uint8), storage)
        storage.io.wait()
    assert len(storage.recent()) == 2
    assert retained_by_ui.memory_bytes == 0
    assert "상한" in retained_by_ui.metadata["input_error"]


@pytest.mark.parametrize("feature", ["tuarim", "skillbar"])
def test_new_detector_can_use_common_recording_api(storage, feature):
    def detector(frame, trace, assets):
        trace.update(search_region=[0, 0, 70, 40], rejection="test-only-no-match")
        return None
    diag.perform_autofind(feature, _capture(np.zeros((40, 70, 3), np.uint8)),
                          detect=detector, assets={}, descriptor={"id": feature, "transforms": []}, storage=storage)
    storage.io.wait()
    record = storage.recent()[0]
    assert record.metadata["feature"] == feature and record.metadata["failure_stage"] == "detect"
    assert (record.directory / "input.png").exists()


def test_screen_capture_restores_widgets_on_capture_exception(app, monkeypatch):
    widget = QWidget()
    widget.show()
    app.processEvents()
    monkeypatch.setattr(screen_grab, "_grab_game_window", lambda: (_ for _ in ()).throw(OSError("capture fail")))
    try:
        with pytest.raises(OSError):
            screen_grab.capture_for_autofind()
        assert widget.isVisible()
    finally:
        widget.close()
