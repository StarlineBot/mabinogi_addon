"""사용 준비의 저장 상태, 선택 순서, 승인·취소·종료와 기존 기능 보존."""

from copy import deepcopy
from threading import Event, get_ident
from types import SimpleNamespace
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


@pytest.mark.parametrize("origin", ["guide", "page"])
def test_skip_setting_refresh_is_bidirectional_read_only_and_survives_reopen(app, settings, monkeypatch, origin):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    screens = {"guide": SetupGuide(), "page": SetupPage()}
    other = screens["page" if origin == "guide" else "guide"]
    try:
        for value in (True, False, True):
            screens[origin].skip.setChecked(value)
            assert config.load_general_flag("skipSetup") is value
            before = settings.read_bytes()
            with monkeypatch.context() as patch:
                def unexpected_write(*args, **kwargs):
                    pytest.fail("refresh must not save settings")
                patch.setattr(config, "_write_local_config", unexpected_write)
                other.refresh()
                assert other.skip.isChecked() is value
            assert settings.read_bytes() == before
        reopened = SetupPage() if origin == "guide" else SetupGuide()
        try:
            assert reopened.skip.isChecked()
        finally:
            reopened.close()
    finally:
        for screen in screens.values():
            screen.close()


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
    from mabinogi_addon.ui import screen_grab

    page = SetupPage()
    monitor = {"left": -1500, "top": 50, "width": 1300, "height": 150}
    monkeypatch.setattr(screen_grab, "_mss", lambda: SimpleNamespace(monitors=[monitor]))
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
        assert window._pages.currentWidget() is (window._tabs if skip else window.setup_guide)
        window._open_setup()
        assert window._pages.currentWidget() is window.setup_guide
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
        assert page.selection.height() == 9 * checks[0].height() // 2 + 2 * page.selection.frameWidth()
        assert checks[3].geometry().bottom() < area.height()
        assert checks[4].y() < area.height() < checks[4].geometry().bottom()
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


def test_new_user_selection_is_seeded_once_before_main_window_tabs(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow

    settings.unlink()
    monkeypatch.setattr(config, "LOCAL_CONFIG_PATH", settings)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window = MainWindow()
    try:
        assert all(not check.isChecked() for check in window._feature_checks.values())
        assert window._pages.currentWidget() is window.setup_guide
        assert window.setup_guide.game_status.text() == "게임창 등록 필요"
        assert all(not check.isChecked() for check in window.setup_guide.checks.values())
        assert all(not check.isChecked() for check in window.setup_page.checks.values())
        assert state.pending() == []
        assert window.setup_page.progress.text() == "사용할 기능을 선택하세요."
        window.setup_page.feature_changed.emit("buff", True)
        before = deepcopy(config._read_local_config())
        state.initialize_new_user()
        assert config._read_local_config() == before
        assert state.pending(automatic_only=True) == ["buff"]
    finally:
        window._force_quit = True
        window.close()


@pytest.mark.parametrize("raw", [{}, {"general": {"theme": "dark"}},
                                {"memo": {"text": "기존 메모", "locked": True}},
                                {"buffTracker": {"captureRegion": BOX}}])
def test_existing_file_without_enabled_keeps_legacy_defaults(settings, raw):
    config._write_local_config(raw)
    before = settings.read_bytes()
    state.initialize_new_user(settings)
    assert settings.read_bytes() == before
    assert state.enabled("buff") and state.enabled("debuff")
    assert state.enabled("memo") and state.enabled("custom")


def test_new_user_initialization_uses_supplied_path_only(tmp_path):
    path = tmp_path / "한글 새 설정" / "설정.json"
    state.initialize_new_user(path)
    raw = config._read_local_config(path)
    assert set(raw) == {feature.section for feature in state.FEATURES}
    assert all(not state.enabled(feature.key, raw) for feature in state.FEATURES)


@pytest.mark.parametrize("backup_only", [False, True])
def test_corrupt_or_backup_config_is_not_treated_as_new(settings, backup_only):
    backup = settings.with_name(settings.name + ".bak")
    settings.rename(backup)
    if not backup_only:
        settings.write_text("{broken", encoding="utf-8")
    before = backup.read_bytes()
    state.initialize_new_user(settings)
    assert backup.read_bytes() == before
    assert settings.exists() is (not backup_only)
    assert not state.enabled("buff")


@pytest.mark.parametrize("logged_in", [False, True])
def test_empty_selection_does_not_capture_or_save(flow, monkeypatch, logged_in):
    run, page, applied, detections, captures, _, _ = flow
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test"} if logged_in else None)
    before = deepcopy(config._read_local_config())
    run.run()
    assert page.progress.text() == "사용할 기능을 선택하세요."
    assert config._read_local_config() == before
    assert not captures and not detections and not applied


@pytest.mark.parametrize("logged_in", [False, True])
def test_selection_copy_and_beta_guidance_fit_current_window(app, settings, monkeypatch, logged_in):
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test"} if logged_in else None)
    update("buffTracker", enabled=True, captureRegion=BOX)
    update("tuarim", enabled=True)
    page = SetupPage()
    page.resize(790, 744)
    page.show()
    try:
        app.processEvents()
        for feature in state.FEATURES:
            check = page.checks[feature.key]
            assert " - " + feature.name in check.text()
            assert "\n" not in check.text()
            assert check.sizeHint().width() <= check.width()
        assert page.selection.horizontalScrollBar().maximum() == 0
        assert page.height() == 744
        assert page.skip.geometry().bottom() < page.height()
        assert "테스트 중인 베타" in page.beta_note.text()
        assert page.login_btn.isVisible() is (not logged_in)
        assert page.checks["stat_bars"].isEnabled() is logged_in
        page.set_busy(True)
        assert not page.login_btn.isEnabled()
    finally:
        page.close()


def test_setup_login_opens_existing_account_without_starting_auth(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: None)
    window = MainWindow()
    try:
        window.show()
        app.processEvents()
        expected_height = min(864, window.screen().availableGeometry().height() - 32)
        assert window.width() == 790 and window.height() == expected_height
        assert window._pages.currentWidget() is window._tabs
        window._open_setup()
        assert window._pages.currentWidget() is window._tabs
        before = deepcopy(config._read_local_config())
        window.setup_page.login_btn.click()
        app.processEvents()
        assert window._pages.currentWidget() is window._tabs
        assert window._tabs.currentIndex() == 3
        viewport = window._tabs.currentWidget().viewport()
        button = window.settings_tab._login_btn
        assert viewport.rect().contains(button.mapTo(viewport, button.rect().center()))
        assert window.settings_tab._login_thread is None
        assert config._read_local_config() == before
    finally:
        window._force_quit = True
        window.close()


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


@pytest.mark.parametrize("hide", [False, True])
def test_capture_cancellation_restores_other_widgets_but_respects_tray_hide(flow, monkeypatch, hide):
    from mabinogi_addon.ui import screen_grab

    run, page, applied, *_ = flow
    state.save_enabled("tuarim", True)
    other = SetupPage()
    page.show()
    other.show()
    monkeypatch.setattr(QApplication, "topLevelWidgets", lambda: [page, other])
    monkeypatch.setattr(screen_grab, "_grab_game_window", lambda: (np.zeros((100, 200, 3), np.uint8), 0, 0))
    monkeypatch.setattr(screen_grab, "_save_debug_frame", lambda *a: None)
    monkeypatch.setattr(time, "sleep", lambda *a: None)
    monkeypatch.setattr(setup_flow, "capture_for_autofind", screen_grab.capture_for_autofind)
    QTimer.singleShot(0, lambda: run.cancel(hide=hide))
    try:
        run.run()
        assert run.cancelled
        assert not run.closed
        assert page.isVisible() is not hide
        assert other.isVisible()
        assert not applied
        page.show()
        run.run()
        assert page.isVisible()
        assert not run.cancelled
        assert len(applied) == 1
    finally:
        other.close()


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("logged_in", [False, True])
def test_settings_replay_opens_app_tour_without_changing_configuration(app, settings, monkeypatch, skip, logged_in):
    from mabinogi_addon import version
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a, **k: None)
    monkeypatch.setattr(version, "__version__", "0.0.0")
    monkeypatch.setattr(config, "load_discord_user", lambda:
                        {"id": "test", "name": "테스트"} if logged_in else None)
    update("general", skipSetup=skip, tourShown=True)
    window = MainWindow()
    window._booting = False
    try:
        window.show()
        app.processEvents()
        window._leave_setup()
        window._tabs.setCurrentIndex(3)
        before = deepcopy(config._read_local_config())
        window.settings_tab.replay_tour.emit()
        tour = window._tour
        assert tour.isVisible()
        assert window._pages.currentWidget() is window._tabs
        assert tour._steps[0].target is window._tracker_tabs.tabBar()
        assert len(tour._steps) == 7
        assert all(step.target not in (window.setup_page.run_btn, window.buff_tab.add_btn)
                   for step in tour._steps)
        settings_step = tour._steps[-2]
        settings_step.before()
        assert settings_step.target is (window.settings_tab.setup_btn if logged_in else window.settings_tab.tour_btn)
        assert settings_step.target.isVisible()
        tour._finish()
        assert config._read_local_config() == before
        assert not window.setup_page.busy
    finally:
        tour = getattr(window, "_tour", None)
        if tour is not None:
            tour.close()
        window._force_quit = True
        window.close()


@pytest.mark.parametrize("blocked", ["busy", "restart", "closing"])
def test_settings_replay_does_not_interrupt_work_or_shutdown(app, settings, monkeypatch, blocked):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window = MainWindow()
    window._leave_setup()
    before = deepcopy(config._read_local_config())
    if blocked == "busy":
        window.setup_page.set_busy(True)
    elif blocked == "restart":
        window._config_pending_restart = True
    else:
        window._setup_flow.shutdown()
    try:
        window.settings_tab.replay_tour.emit()
        assert window._pages.currentWidget() is window._tabs
        assert getattr(window, "_tour", None) is None
        assert config._read_local_config() == before
    finally:
        window._force_quit = True
        window.close()


@pytest.mark.parametrize("stage, expected", [(1, ["boss", "buff", "debuff"]),
                                            (2, ["skillbar", "tuarim", "stat_bars"])])
def test_guide_scopes_existing_flow_and_preserves_check_order(flow, stage, expected):
    from mabinogi_addon.ui.setup_guide import SetupGuide, GUIDE_KEYS

    run, home, applied, detections, _, storage, _ = flow
    for key in ("skillbar", "boss", "buff", "tuarim", "debuff", "stat_bars"):
        state.save_enabled(key, True)
        state.remember_order(key, True)
    page = SetupGuide()
    page.reset()
    page.stage = stage
    page.refresh()
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert [key for key, _ in detections] == expected
        assert [item[0] for item in applied] == expected
        assert page.outcomes == {key: "등록됨" for key in expected}
        assert all(state.missing(key) for key in GUIDE_KEYS if key not in expected)
        assert not run.running and not page.busy and run.page is home
        assert page.run_btn.text() == "자동설정"
        storage.io.wait()
        assert {r.metadata["feature"] for r in storage.recent()} == set(expected)
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert len(detections) == 3
    finally:
        page.close()


def test_guide_shared_boss_dependency_does_not_enable_boss_feature(flow):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, detections, _, _, _ = flow
    update("statBars", enabled=True, bars={"hp": {"alert": {"on": True}}})
    update("tuarim", enabled=True)
    page = SetupGuide()
    page.stage = 2
    page.refresh()
    try:
        assert "보스 체력바" in page.status_text("stat_bars", config._read_local_config())
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert [key for key, _ in detections] == ["tuarim", "stat_bars", "boss"]
        assert not state.enabled("boss")
        assert not state.missing("stat_bars")
        assert [item[0] for item in applied] == ["tuarim", "stat_bars", "boss"]
    finally:
        page.close()


def test_empty_current_stage_does_not_search_other_selected_stage(flow):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, detections, captures, _, _ = flow
    state.save_enabled("tuarim", True)
    page = SetupGuide()
    page.stage = 1
    before = deepcopy(config._read_local_config())
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert page.progress.text() == "사용할 기능을 선택하세요."
        assert not applied and not detections and not captures and not page.outcomes
        assert config._read_local_config() == before
        page.move(1)
        assert page.stage == 2
    finally:
        page.close()


@pytest.mark.parametrize("failure", ["capture", "decline", "save", "detect"])
def test_guide_failures_keep_unattempted_separate_and_allow_next_stage(flow, monkeypatch, failure):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, detections, _, _, _ = flow
    for key in ("buff", "debuff", "boss"):
        state.save_enabled(key, True)
    page = SetupGuide()
    page.stage = 1
    page.refresh()
    if failure == "capture":
        monkeypatch.setattr(setup_flow, "capture_for_autofind", lambda **kw: (None, 0, 0))
    elif failure == "decline":
        monkeypatch.setattr(run, "_approve", lambda key, box: None if key == "buff" else box)
    elif failure == "save":
        original = run.apply
        def apply(key, box):
            if key == "buff":
                raise PermissionError("read-only")
            original(key, box)
        run.apply = apply
    else:
        original = setup_flow.run_detector
        monkeypatch.setattr(setup_flow, "run_detector", lambda key, *args:
                            None if key == "buff" else original(key, *args))
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        expected = {"capture": "게임창 미발견 또는 캡처 실패", "decline": "등록하지 않음",
                    "save": "저장 실패", "detect": "찾지 못함"}[failure]
        assert page.outcomes["buff"] == expected
        assert state.missing("buff")
        if failure == "capture":
            assert page.outcomes == {"buff": expected}
            assert page.status_text("debuff", config._read_local_config()) == "아직 시도하지 않음"
            assert not applied and not detections
        else:
            assert [item[0] for item in applied] == ["debuff", "boss"]
        assert not page.busy
        page.move(1)
        assert page.stage == 2
    finally:
        page.close()


def test_guide_defer_back_and_reset_never_change_saved_configuration(app, settings):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    update("buffTracker", enabled=True, captureRegion=BOX)
    update("bossPattern", enabled=True)
    before = deepcopy(config._read_local_config())
    page = SetupGuide()
    try:
        page.reset()
        page.move(1)
        page.defer()
        assert page.stage == 2
        page.move(-1)
        assert page.status_text("buff", before) == "등록됨"
        assert page.status_text("boss", before) == "나중에 설정"
        page.reset()
        assert page.stage == 0 and not page.outcomes
        assert config._read_local_config() == before
        assert set(page.checks) == {"buff", "debuff", "boss", "tuarim", "stat_bars", "skillbar"}
    finally:
        page.close()


@pytest.mark.parametrize("logged_in", [False, True])
def test_guide_actual_window_navigation_and_resume_preserve_step(app, settings, monkeypatch, logged_in):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "테스트"} if logged_in else None)
    window = MainWindow()
    window.show()
    try:
        window.settings_tab.reopen_guide.emit()
        guide = window.setup_guide
        if not logged_in:
            before = deepcopy(config._read_local_config())
            window._resume_guide()
            window._run_guide_setup()
            assert window._pages.currentWidget() is not guide
            assert not guide.active and window.settings_tab.guide_btn.isHidden()
            assert window._setup_flow.future is None
            assert config._read_local_config() == before
            return
        assert window._pages.currentWidget() is guide and guide.stage == 0
        guide.move(1)
        guide.feature_changed.emit("buff", True)
        assert window.buff_tab.enable.isChecked() and guide.checks["buff"].isChecked()
        window._open_setup_feature("buff")
        assert window._guide_return_btn.isVisible()
        update("buffTracker", captureRegion=BOX)
        window._guide_return_btn.click()
        assert window._pages.currentWidget() is guide and guide.stage == 1
        assert guide.statuses["buff"].text() == "등록됨"
        assert not config.load_general_flag("firstUseGuideShown")
        window._open_setup_login()
        assert window._tabs.currentIndex() == 3
        assert window.settings_tab._login_thread is None
        window._guide_return_btn.click()
        assert guide.stage == 1
        guide.move(1)
        guide.feature_changed.emit("stat_bars", True)
        assert state.enabled("stat_bars") is logged_in
        for stage in range(3):
            guide.stage = stage
            guide.refresh()
            app.processEvents()
            app.processEvents()
            expected_height = min(800, window.screen().availableGeometry().height() - 32)
            assert window.width() == 790 and window.height() == expected_height
            assert window.rect().contains(guide.next_btn.mapTo(window, guide.next_btn.rect().bottomRight()))
            assert guide.selection.horizontalScrollBar().maximum() == 0
            for key in guide.feature_keys:
                assert guide.checks[key].width() >= guide.checks[key].sizeHint().width()
            assert not hasattr(guide, "beta_note") and not hasattr(guide, "login_btn")
            for key, widget in guide.feature_rows.items():
                assert widget.isVisible() is (key in guide.feature_keys and stage in (1, 2))
            assert not any(button.text() == "개별 설정" for button in guide.findChildren(type(guide.next_btn)))
            assert not any(button.text() in ("앱으로 이동", "Discord 로그인")
                           for button in guide.findChildren(type(guide.next_btn)))
            assert not hasattr(guide, "result")
        guide.next_btn.click()
        assert config.load_general_flag("firstUseGuideShown")
        assert not guide.active and not window._guide_return_btn.isVisible()
        assert window._tour.isVisible()
        assert "4 / 4" in window._tour._step_lbl.text()
        window._tour._finish()
        window.settings_tab.reopen_setup.emit()
        assert window._pages.currentWidget() is guide
        window.settings_tab.reopen_guide.emit()
        assert guide.stage == 0
        assert state.missing("buff") == []
    finally:
        window._force_quit = True
        window.close()


@pytest.mark.parametrize("skip", [False, True])
@pytest.mark.parametrize("seen", [False, True])
@pytest.mark.parametrize("guide_seen", [False, True])
@pytest.mark.parametrize("registered", [False, True])
@pytest.mark.parametrize("logged_in", [False, True])
def test_first_show_guide_ignores_seen_and_registered_but_respects_skip_and_login(
        app, settings, monkeypatch, skip, seen, guide_seen, registered, logged_in):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    notes = []
    def show_notes(self):
        assert not self.setup_guide.active
        assert self._pages.currentWidget() is not self.setup_page
        notes.append(True)
    monkeypatch.setattr(MainWindow, "_maybe_show_release_notes", show_notes)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *a, **k: None)
    monkeypatch.setattr(config, "load_discord_user", lambda: {"id": "test", "name": "QA"} if logged_in else None)
    update("general", skipSetup=skip, tourShown=seen, firstUseGuideShown=guide_seen)
    if registered:
        for name in ("buffTracker", "debuffTracker"):
            update(name, captureRegion=BOX)
        for name in ("tuarim", "bossPattern", "statBars"):
            update(name, box=BOX)
        update("skillbar", anchor={"x": 10, "y": 20})
    window = MainWindow()
    window._booting = False
    try:
        before = deepcopy(config._read_local_config())
        pages = []
        window._pages.currentChanged.connect(lambda _: pages.append(window._pages.currentWidget()))
        window.show()
        app.processEvents()
        expected = logged_in and not skip
        assert (window._pages.currentWidget() is window.setup_guide) is expected
        assert window.setup_page not in pages
        assert window.setup_guide.active is expected
        assert window.setup_guide.stage == 0
        assert notes == [True]
        assert getattr(window, "_tour", None) is None
        assert config._read_local_config() == before
        window._leave_setup()
        window._tabs.setCurrentIndex(3)
        assert window.settings_tab.setup_btn is window.settings_tab.guide_btn
        assert window.settings_tab.setup_btn.isHidden() is (not logged_in)
        window.settings_tab.setup_btn.click()
        assert (window._pages.currentWidget() is window.setup_guide) is logged_in
        assert window._pages.currentWidget() is not window.setup_page
        assert config._read_local_config() == before
    finally:
        window._force_quit = True
        window.close()


def test_tray_restore_and_relogin_never_reveal_legacy_setup(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow

    account = {"logged_in": True}
    monkeypatch.setattr(config, "load_discord_user", lambda:
                        {"id": "test", "name": "테스트"} if account["logged_in"] else None)
    monkeypatch.setattr(QApplication, "quit", lambda: None)
    monkeypatch.setattr(MainWindow, "_maybe_check_update", lambda *args: None)
    notes = []
    monkeypatch.setattr(MainWindow, "_maybe_show_release_notes", lambda self: notes.append(True))
    update("general", skipSetup=False, tourShown=True, firstUseGuideShown=True, startInTray=True)
    window = MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    try:
        window.start()
        before = deepcopy(config._read_local_config())
        app.processEvents()
        assert not window.isVisible() and not notes
        assert not window.setup_guide.active
        window.show()
        app.processEvents()
        assert notes == [True]
        assert window._pages.currentWidget() is window.setup_guide
        assert window.setup_guide.stage == 0 and window.setup_guide.active
        window.setup_guide.move(1)
        monkeypatch.setattr(window, "_minimize_to_tray_enabled", lambda: True)
        before["general"]["windowPos"] = {"x": window.pos().x(), "y": window.pos().y()}
        window.close()
        assert not window.isVisible() and not window._closing
        window.show()
        app.processEvents()
        assert window.setup_guide.stage == 1 and notes == [True]
        account["logged_in"] = False
        window.settings_tab.login_changed.emit()
        window._open_setup()
        window._resume_guide()
        assert window._pages.currentWidget() is window._tabs
        assert window.settings_tab.setup_btn.isHidden()
        account["logged_in"] = True
        window.settings_tab.login_changed.emit()
        window._tabs.setCurrentIndex(3)
        assert window.settings_tab.setup_btn.isVisible()
        window.settings_tab.setup_btn.click()
        assert window._pages.currentWidget() is window.setup_guide
        assert window.setup_guide.stage == 0
        assert config._read_local_config() == before
    finally:
        window._force_quit = True
        window.close()


def test_guide_cancel_and_reentrant_navigation_do_not_escape_busy_stage(flow, monkeypatch):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, detections, _, _, _ = flow
    update("tuarim", enabled=True)
    update("skillbar", enabled=True)
    page = SetupGuide()
    page.stage = 2
    def approve(key, box):
        assert run.running and page.busy
        page.move(1)
        page.defer()
        assert page.stage == 2
        run.run(feature_keys=("skillbar",))
        run.cancel()
        return box
    monkeypatch.setattr(run, "_approve", approve)
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert not applied
        assert [key for key, _ in detections] == ["tuarim"]
        assert page.outcomes == {"tuarim": "중단됨"}
        assert page.status_text("skillbar", config._read_local_config()) == "아직 시도하지 않음"
        assert not page.busy and not run.running
        monkeypatch.setattr(run, "_approve", lambda key, box: box)
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert page.outcomes == {"tuarim": "등록됨", "skillbar": "등록됨"}
    finally:
        page.close()


def test_guide_shutdown_discards_worker_result_and_does_not_touch_page_after_shutdown(flow, monkeypatch):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, _, _, _, _ = flow
    page = SetupGuide()
    page.stage = 2
    state.save_enabled("tuarim", True)
    ready = Event()
    def slow(*args):
        ready.set()
        time.sleep(0.1)
        return (10, 20, 42, 16)
    monkeypatch.setattr(setup_flow, "run_detector", slow)
    QTimer.singleShot(20, run.shutdown)
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert ready.is_set() and not applied and not page.outcomes
        assert not run.running and run.closed
        run.future.result(timeout=2)
        assert state.missing("tuarim")
    finally:
        page.close()


def test_guide_restart_restores_saved_areas_but_starts_at_first_step(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow
    from mabinogi_addon.ui import main_window

    class Source:
        closed = False
        def grab(self):
            return np.zeros((BOX["h"], BOX["w"], 3), np.uint8)
        def close(self):
            self.closed = True

    source = Source()
    monkeypatch.setattr(main_window, "create_live_source", lambda region: source)

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    first = MainWindow()
    first._open_guide()
    first.setup_guide.move(1)
    first.setup_guide.feature_changed.emit("buff", True)
    first._apply_setup_region("buff", tuple(BOX[k] for k in ("x", "y", "w", "h")))
    first.setup_guide.move(1)
    first._force_quit = True
    first.close()
    assert source.closed
    second = MainWindow()
    try:
        second._open_guide()
        assert second.setup_guide.stage == 0
        assert config.load_capture_region() == BOX
        assert second.setup_guide.checks["buff"].isChecked()
        assert not config.load_general_flag("firstUseGuideShown")
        assert second.setup_guide.status_text("buff", config._read_local_config()) == "등록됨"
    finally:
        second._force_quit = True
        second.close()


def test_app_tour_can_be_replaced_and_closed_without_marking_registration(app, settings, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window = MainWindow()
    try:
        window.show()
        window._run_tour()
        first = window._tour
        window._open_guide()
        assert not first.isVisible() and window._tour is None
        assert not config.load_general_flag("tourShown")
        window._run_tour()
        tour = window._tour
        for index in range(len(tour._steps)):
            tour._i = index
            tour._show_step()
            app.processEvents()
            step = tour._steps[index]
            if step.target is not None:
                assert step.target.isVisible()
                assert tour._target_rect() is not None
        tour._finish()
        app.processEvents()
        assert window._tour is None and config.load_general_flag("tourShown")
        assert not config.load_general_flag("firstUseGuideShown")
        window._run_tour()
        last = window._tour
        window._force_quit = True
        window.close()
        assert not last.isVisible() and window._tour is None
    finally:
        window._force_quit = True
        window.close()


def test_guide_approval_updates_current_stage_before_next_candidate(flow, monkeypatch):
    from mabinogi_addon.ui.setup_guide import SetupGuide

    run, _, applied, _, _, _, _ = flow
    for key in ("buff", "debuff"):
        state.save_enabled(key, True)
    page = SetupGuide()
    page.stage = 1
    page.refresh()
    seen = []
    def approve(key, box):
        if key == "debuff":
            assert page.statuses["buff"].text() == "등록됨"
            assert page.feature_rows["buff"].parentWidget() is page.groups["done"][1].widget()
            assert page.feature_rows["debuff"].parentWidget() is page.groups["need"][1].widget()
        seen.append(key)
        return box
    monkeypatch.setattr(run, "_approve", approve)
    try:
        run.run(page=page, feature_keys=page.feature_keys, on_result=page.record_result)
        assert seen == ["buff", "debuff"]
        assert len(applied) == 2 and page.stage == 1
        assert page.statuses["debuff"].text() == "등록됨"
    finally:
        page.close()


@pytest.mark.parametrize("during_tour", [False, True])
def test_logout_hides_beta_guide_and_closes_guide_tour(app, settings, monkeypatch, during_tour):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window = MainWindow()
    try:
        window.show()
        window._open_guide()
        if during_tour:
            window.setup_guide.stage = 2
            window.setup_guide.move(1)
            assert window._tour.isVisible()
        before = deepcopy(config._read_local_config())
        monkeypatch.setattr(config, "load_discord_user", lambda: None)
        window.settings_tab.login_changed.emit()
        assert not window.setup_guide.active
        assert not window.setup_guide.isVisible()
        assert window.settings_tab.guide_btn.isHidden()
        assert not window._guide_return_btn.isVisible()
        assert getattr(window, "_tour", None) is None
        window._open_guide()
        window._resume_guide()
        assert window._pages.currentWidget() is not window.setup_guide
        assert config._read_local_config() == before
    finally:
        window._force_quit = True
        window.close()


def test_logout_during_guide_approval_cancels_without_saving(flow, monkeypatch):
    from mabinogi_addon.ui.main_window import MainWindow

    monkeypatch.setattr(QApplication, "quit", lambda: None)
    window = MainWindow()
    try:
        window._open_guide()
        window.setup_guide.move(1)
        window.setup_guide.feature_changed.emit("buff", True)
        def approve(key, box):
            monkeypatch.setattr(config, "load_discord_user", lambda: None)
            window.settings_tab.login_changed.emit()
            return box
        monkeypatch.setattr(window._setup_flow, "_approve", approve)
        window._run_guide_setup()
        assert window._setup_flow.cancelled and not window._setup_flow.running
        assert state.missing("buff") == ["buff"]
        assert not window.setup_guide.active
        assert window._pages.currentWidget() is not window.setup_guide
    finally:
        window._force_quit = True
        window.close()
