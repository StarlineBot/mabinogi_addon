"""사용 준비의 저장 상태, 선택 순서, 승인·취소·종료와 기존 기능 보존."""

from copy import deepcopy
from threading import Event, get_ident
import time

import numpy as np
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from mabinogi_addon import config, setup_state as state, autofind_diagnostics as diag
from mabinogi_addon.ui.setup_page import SetupPage
from mabinogi_addon.ui import setup_flow


BOX = {"x": -1200, "y": 400, "w": 42, "h": 16}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def settings(monkeypatch, tmp_path):
    path = tmp_path / "한글 경로" / "설정.json"
    path.parent.mkdir()
    read, write = config._read_local_config, config._write_local_config
    monkeypatch.setattr(config, "_read_local_config", lambda *a, **k: read(path))
    monkeypatch.setattr(config, "_write_local_config", lambda data, *a, **k: write(data, path))
    raw = {f.section: {"enabled": False} for f in state.FEATURES}
    raw["general"] = {"gameExe": "Client.exe"}
    config._write_local_config(raw)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"})
    return path


def update(section, **values):
    raw = config._read_local_config()
    raw.setdefault(section, {}).update(values)
    config._write_local_config(raw)


@pytest.mark.parametrize("bad", [None, {}, {"x": 0, "y": 0, "w": 0, "h": 10},
                                {"x": True, "y": 0, "w": 10, "h": 10},
                                {"x": 1, "y": 2, "w": 3, "h": "4"}])
def test_broken_region_is_unregistered(bad):
    assert state.missing("tuarim", {"tuarim": {"box": bad}}) == ["tuarim"]


def test_empty_existing_skip_and_unchecked(settings):
    assert state.needs_start_screen()
    state.save_enabled("tuarim", True)
    assert state.needs_start_screen()
    update("tuarim", box=BOX)
    assert not state.pending()
    assert state.needs_start_screen()
    update("general", gameExe=None)
    assert state.needs_start_screen()
    update("general", skipSetup=True)
    assert not state.needs_start_screen()
    assert config.load_tuarim()["box"] == BOX


@pytest.mark.parametrize("skip", [False, True, None, "true", 1])
def test_beta_start_screen_requires_explicit_opt_out(settings, skip):
    update("tuarim", enabled=True, box=BOX)
    update("general", skipSetup=skip)
    assert state.pending() == []
    assert state.needs_start_screen() is (skip is not True)


@pytest.mark.parametrize("value", [True, False, None, "false", 0, 1, []])
def test_enabled_interpretation_matches_existing_tabs(settings, value):
    for key, loader in (("tuarim", config.load_tuarim), ("boss", config.load_boss_pattern),
                        ("skillbar", config.load_skillbar), ("stat_bars", config.load_stat_bars)):
        update(state.BY_KEY[key].section, enabled=value)
        assert state.enabled(key) == loader()["enabled"]


def test_selection_order_and_disabled_items(settings):
    for key in ("skillbar", "tuarim", "buff"):
        state.save_enabled(key, True)
        state.remember_order(key, True)
    assert state.pending(automatic_only=True) == ["skillbar", "tuarim", "buff"]
    state.save_enabled("tuarim", False)
    state.remember_order("tuarim", False)
    state.save_enabled("tuarim", True)
    state.remember_order("tuarim", True)
    assert state.pending(automatic_only=True) == ["skillbar", "buff", "tuarim"]
    update("skillbar", anchor={"x": -1000, "y": 20})
    assert state.pending(automatic_only=True) == ["buff", "tuarim"]


def test_manual_areas_and_shared_prerequisites(settings):
    update("debuffTracker", enabled=True, captureRegion=BOX)
    update("general", debuffGateMode="percent")
    assert state.pending(automatic_only=True) == ["boss"]
    update("bossPattern", box=BOX)
    assert state.pending() == []
    update("customOverlay", enabled=True, overlays=[BOX])
    update("memo", enabled=True)
    assert state.pending() == ["memo"]
    assert state.pending(automatic_only=True) == []
    update("memoTracker", captureRegion=BOX)
    assert state.pending() == []
    update("statBars", enabled=True, box=BOX, bars={"hp": {"alert": {"on": True}}})
    update("bossPattern", box=None)
    assert state.missing("stat_bars") == ["boss"]


@pytest.fixture
def flow(app, settings, monkeypatch, tmp_path):
    page = SetupPage()
    storage = diag.DiagnosticStore(tmp_path / "진단")
    monkeypatch.setattr(diag, "store", lambda: storage)
    capture_threads = []
    def capture(**kwargs):
        assert kwargs["require_game"] is True and kwargs["restore_allowed"]()
        capture_threads.append(get_ident())
        return np.zeros((150, 1300, 3), np.uint8), -1500, 50
    monkeypatch.setattr(setup_flow, "capture_for_autofind", capture)
    monkeypatch.setattr(setup_flow, "to_logical", lambda *box: box)
    detections = []
    def detector(key, frame, assets, trace):
        detections.append((key, get_ident()))
        trace["input_shape"] = list(frame.shape)
        return (10, 20, 1168, 89) if key == "skillbar" else (10, 20, 42, 16)
    monkeypatch.setattr(setup_flow, "run_detector", detector)
    applied = []
    def apply(key, box):
        applied.append((key, box, get_ident()))
        if key in ("buff", "debuff"):
            config.save_capture_region(*box, state.BY_KEY[key].section)
        elif key == "skillbar":
            config.save_skillbar({"anchor": {"x": box[0], "y": box[1]}})
        else:
            update(state.BY_KEY[key].section, box=dict(zip(("x", "y", "w", "h"), box)))
    flow = setup_flow.SetupFlow(page, apply)
    monkeypatch.setattr(flow, "_approve", lambda key, box: box)
    notices = []
    monkeypatch.setattr(flow, "_notice", lambda *args: notices.append(args))
    yield flow, page, applied, detections, capture_threads, storage, notices
    flow.shutdown()
    if flow.future is not None:
        flow.future.result(timeout=5)
    page.close()
    storage.io.close()


def test_batch_order_real_json_approval_worker_and_diagnostics(flow):
    run, page, applied, detections, captures, storage, notices = flow
    for key in ("skillbar", "tuarim", "boss"):
        state.save_enabled(key, True)
        state.remember_order(key, True)
    before = config._read_local_config()
    update("tuarim", thresholds=[92, 97], sounds=[False, True])
    run.run()
    assert [item[0] for item in applied] == ["skillbar", "tuarim", "boss"]
    assert all(item[2] == get_ident() for item in applied)
    assert all(thread != get_ident() for _, thread in detections)
    assert captures == [get_ident()] * 3
    assert applied[1][1] == (-1490, 70, 42, 16)
    assert config.load_tuarim()["thresholds"] == [92, 97]
    assert config.load_tuarim()["sounds"] == [False, True]
    assert before["skillbar"]["enabled"] == config.load_skillbar()["enabled"]
    assert not page.busy
    assert "등록 완료 3" in page.progress.text()
    storage.io.wait()
    records = storage.recent()
    assert len(records) == 3
    assert all(r.metadata["confirmation"]["status"] == "applied" for r in records)
    assert len({r.id for r in records}) == 3
    run.run()
    assert len(detections) == 3  # re-run never overwrites registered regions


def test_decline_keeps_settings_and_moves_to_next(flow, monkeypatch):
    run, page, applied, detections, _, storage, _ = flow
    update("tuarim", enabled=True, thresholds=[90, 95])
    update("skillbar", enabled=True, scale=175)
    before = deepcopy(config._read_local_config())
    monkeypatch.setattr(run, "_approve", lambda key, box: None if key == "tuarim" else box)
    run.run()
    assert config._read_local_config()["tuarim"] == before["tuarim"]
    assert [a[0] for a in applied] == ["skillbar"]
    assert config.load_skillbar()["scale"] == 175
    assert "등록하지 않음 1" in page.progress.text()
    assert [a[0] for a in detections] == ["tuarim", "skillbar"]
    storage.io.wait()
    assert {r.metadata["confirmation"]["status"] for r in storage.recent()} == {"applied", "cancelled"}


@pytest.mark.parametrize("failure", ["capture", "detect", "save", "grid"])
def test_failures_report_and_restore_controls(flow, monkeypatch, failure):
    run, page, applied, _, _, _, notices = flow
    key = "skillbar" if failure == "grid" else "tuarim"
    state.save_enabled(key, True)
    if failure == "capture":
        monkeypatch.setattr(setup_flow, "capture_for_autofind", lambda **kw: (None, 0, 0))
    elif failure == "detect":
        monkeypatch.setattr(setup_flow, "run_detector", lambda *a: None)
    elif failure == "grid":
        monkeypatch.setattr(setup_flow, "run_detector", lambda *a: (10, 20, 600, 60))
    else:
        def denied(*a):
            raise PermissionError("read-only")
        run.apply = denied
    run.run()
    assert not applied
    assert state.missing(key) == [key]
    assert not page.busy and page.run_btn.isEnabled()
    assert ("저장 실패 1" if failure == "save" else "찾지 못함 1") in page.progress.text()
    assert notices


def test_shutdown_during_detection_never_applies_late_result(flow, monkeypatch):
    run, page, applied, _, _, storage, _ = flow
    state.save_enabled("tuarim", True)
    release = Event()
    monkeypatch.setattr(setup_flow, "run_detector", lambda *a: (release.wait(2), (10, 20, 42, 16))[1])
    QTimer.singleShot(20, run.shutdown)
    started = time.monotonic()
    run.run()
    assert time.monotonic() - started < 1
    assert not applied
    release.set()
    run.future.result(timeout=3)
    assert state.missing("tuarim") == ["tuarim"]


def test_cancel_approval_does_not_save_and_restores(flow, monkeypatch):
    run, page, applied, _, _, _, _ = flow
    state.save_enabled("tuarim", True)
    def approve(*args):
        run.cancel()
        return args[1]
    monkeypatch.setattr(run, "_approve", approve)
    run.run()
    assert not applied
    assert not page.busy
    assert "중단" in page.progress.text()


def test_login_and_game_registration_required(flow, monkeypatch):
    run, page, applied, detections, _, _, _ = flow
    state.save_enabled("tuarim", True)
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    run.run()
    assert "Discord" in page.progress.text()
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test"})
    update("general", gameExe=None)
    run.run()
    assert "게임창" in page.progress.text()
    assert not applied and not detections


@pytest.mark.parametrize("skip", [False, True])
def test_main_window_setup_navigation_and_bidirectional_use(app, settings, monkeypatch, skip):
    from mabinogi_addon.ui.main_window import MainWindow
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    update("general", skipSetup=skip)
    window = MainWindow()
    try:
        assert window._tabs.count() == 4
        assert window._pages.currentWidget() is (window._tabs if skip else window.setup_page)
        window._open_setup()
        assert not window.setup_page.busy
        window.setup_page.feature_changed.emit("buff", True)
        assert window.buff_tab.enable.isChecked()
        assert state.enabled("buff")
        window.buff_tab.enable.setChecked(False)
        assert not window.setup_page.checks["buff"].isChecked()
        assert not state.enabled("buff")
        window._open_setup_feature("skillbar")
        assert window._pages.currentWidget() is window._tabs
        assert window._convenience_tabs.currentIndex() == 1
        window._open_setup()
        window._leave_setup()
        assert window._tracker_tabs.currentIndex() == 0
        assert not window._paused
        assert not window._setup_flow.closed
    finally:
        window._force_quit = True
        window.close()


@pytest.mark.parametrize("answer", [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No])
def test_actual_popup_decision_and_highlight_cleanup(flow, answer):
    run, page, *_ = flow
    QTimer.singleShot(0, lambda: run.dialog.done(int(answer)))
    result = setup_flow.SetupFlow._approve(run, "tuarim", (-100, 20, 42, 16))
    assert result == ((-100, 20, 42, 16) if answer == QMessageBox.StandardButton.Yes else None)
    assert run.dialog is None
    assert not any(w.isVisible() and type(w).__name__ == "RegionHighlight" for w in QApplication.topLevelWidgets())


def test_actual_buff_top_edge_completion(flow):
    run, *_ = flow
    QTimer.singleShot(0, lambda: run.selector.selected.emit(30, 40, 250, 500))
    assert setup_flow.SetupFlow._approve(run, "buff", (30, 20, 250, 520)) == (30, 40, 250, 500)
    assert run.selector is None


def test_actual_popup_shutdown_never_approves(flow):
    run, *_ = flow
    QTimer.singleShot(0, run.shutdown)
    assert setup_flow.SetupFlow._approve(run, "tuarim", (30, 20, 42, 16)) is None
    assert run.dialog is None


def test_native_input_batch_zip_replay_and_separate_runs(flow, monkeypatch, tmp_path):
    from mabinogi_addon import image_io
    from mabinogi_addon.autofind_replay import run_detector, replay
    from zipfile import ZipFile
    import cv2

    run, _, applied, *_rest = flow
    storage = flow[5]
    originals = [image_io.imread("tests/data/스크린샷 2026-10-12 000512.png"),
                 image_io.imread("tests/data/스크린샷 2026-10-10 190116.png")]
    monkeypatch.setattr(setup_flow, "run_detector", run_detector)
    for original in originals:
        update("tuarim", enabled=True, box=None)
        monkeypatch.setattr(setup_flow, "capture_for_autofind", lambda **kw: (original, 0, 0))
        run.run()
        storage.io.wait()
        record = storage.recent()[0]
        destination = tmp_path / (record.id + ".zip")
        storage.export(record, destination)
        assert replay(destination)["matches_recorded"]
        with ZipFile(destination) as archive:
            frame = cv2.imdecode(np.frombuffer(archive.read("input.png"), np.uint8), cv2.IMREAD_COLOR)
            assert np.array_equal(original, frame)
    assert len(applied) == 2
    records = storage.recent()
    assert len(records) == 2 and len({r.id for r in records}) == 2
    assert records[0].metadata["result"] != records[1].metadata["result"]


def test_feature_switch_save_error_restores_previous_state(app, settings, monkeypatch):
    from mabinogi_addon.ui.widgets import feature_checkbox
    check = feature_checkbox("buff", "버프 트래커 사용")
    warnings = []
    def denied(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(config, "_write_local_config", denied)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: warnings.append(a))
    check.setChecked(True)
    assert not check.isChecked()
    assert not state.enabled("buff")
    assert len(warnings) == 1
    check.close()


def test_four_visible_feature_rows_and_independent_scroll_boxes(app, settings):
    page = SetupPage()
    page.resize(790, 744)
    page.show()
    try:
        app.processEvents()
        area = page.selection.viewport()
        checks = list(page.checks.values())
        assert page.selection.height() == 4 * checks[0].height() + 2 * page.selection.frameWidth()
        assert page.run_btn.width() == page.selection.width()
        assert len({id(group[0]) for group in page.groups.values()}) == 3
        state.save_enabled("tuarim", True)
        page.refresh()
        assert page.feature_rows["tuarim"][0].parentWidget() is page.groups["need"][0].widget()
        update("tuarim", box=BOX)
        page.refresh()
        assert page.feature_rows["tuarim"][0].parentWidget() is page.groups["done"][0].widget()
        assert page.selection.verticalScrollBar().maximum() > 0
    finally:
        page.close()


def test_batch_capture_never_falls_back_to_desktop(app, monkeypatch):
    from mabinogi_addon.ui import screen_grab
    monkeypatch.setattr(screen_grab, "_grab_game_window", lambda: (None, 0, 0))
    monkeypatch.setattr(screen_grab, "_save_debug_frame", lambda *a: None)
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    def forbidden():
        raise AssertionError("must not capture desktop in batch setup")
    monkeypatch.setattr(screen_grab, "grab_primary", forbidden)
    assert screen_grab.capture_for_autofind(require_game=True) == (None, 0, 0)


def test_stat_bar_save_failure_keeps_memory_region(app, settings, monkeypatch):
    from mabinogi_addon.ui.stat_bars_tab import StatBarsTab
    class Watcher:
        def is_game_active(self):
            return False
        def is_self_active(self):
            return False
    tab = StatBarsTab(Watcher())
    previous = deepcopy(tab._region)
    def denied(*args, **kwargs):
        raise PermissionError("read-only")
    monkeypatch.setattr(config, "save_stat_bars", denied)
    try:
        with pytest.raises(PermissionError):
            tab._on_selected(10, 20, 300, 50)
        assert tab._region == previous
    finally:
        tab.shutdown()


def test_capture_shutdown_does_not_restore_closed_windows(app, monkeypatch):
    from mabinogi_addon.ui import screen_grab
    class Top:
        def isVisible(self):
            return True
        def hide(self):
            pass
        def show(self):
            raise AssertionError("closed application must not be shown again")
    monkeypatch.setattr(QApplication, "topLevelWidgets", lambda: [Top()])
    monkeypatch.setattr(screen_grab, "_grab_game_window", lambda: (None, 0, 0))
    monkeypatch.setattr(screen_grab, "_save_debug_frame", lambda *a: None)
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    screen_grab.capture_for_autofind(require_game=True, restore_allowed=lambda: False)


def test_logout_during_approval_never_saves(flow, monkeypatch):
    run, page, applied, *_ = flow
    state.save_enabled("tuarim", True)
    def approve(key, box):
        monkeypatch.setattr(config, "load_discord_user", lambda: None)
        return box
    monkeypatch.setattr(run, "_approve", approve)
    run.run()
    assert not applied
    assert not page.busy


@pytest.mark.parametrize("failure", ["window", "save", None])
def test_game_countdown_reports_result_and_releases_timer(app, settings, monkeypatch, failure):
    from mabinogi_addon.ui.settings_tab import SettingsTab
    class Watcher:
        def foreground_info(self):
            if failure == "window":
                raise OSError("window exited")
            return "Game", "NewClient.exe"
        def set_game_exe(self, exe):
            self.exe = exe
    tab = SettingsTab(Watcher())
    results = []
    tab.game_registration_finished.connect(results.append)
    if failure == "save":
        def denied(*args, **kwargs):
            raise PermissionError("read-only")
        monkeypatch.setattr(config, "save_game_exe", denied)
    try:
        tab._start_detect()
        timer = tab._detect_timer
        tab._start_detect()
        assert tab._detect_timer is timer
        for _ in range(3):
            tab._tick_detect()
        assert results == [failure is None]
        assert tab._detect_timer is None
        assert tab._detect_btn.isEnabled()
    finally:
        tab.shutdown()
