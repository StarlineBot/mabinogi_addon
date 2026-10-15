"""Independent V2 guide probes; run explicitly with the headless audio boundary."""

from copy import deepcopy
from pathlib import Path
from threading import Event
import time

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QPushButton

from mabinogi_addon import config, setup_state as state, autofind_diagnostics as diag
from mabinogi_addon.ui import main_window, setup_flow
from scripts.qa_setup_first_user import app, isolated, close


@pytest.fixture
def scene(app, isolated, monkeypatch, tmp_path):
    account = {"logged_in": True}
    monkeypatch.setattr(config, "load_discord_user", lambda:
                        {"id": "qa", "name": "QA"} if account["logged_in"] else None)
    # Region persistence is real; native game capture is a separate boundary.
    def no_live(region):
        raise ImportError("no Windows capture backend in this probe")
    monkeypatch.setattr(main_window, "create_live_source", no_live)
    storage = diag.DiagnosticStore(tmp_path / "diagnostics")
    monkeypatch.setattr(diag, "store", lambda: storage)
    window = main_window.MainWindow()
    monkeypatch.setattr(window.party_tab, "start_polling", lambda: None)
    window.start()
    captures, detections, notices = [], [], []

    def capture(**kwargs):
        assert kwargs["require_game"]
        captures.append(True)
        return np.zeros((300, 1400, 3), dtype=np.uint8), 0, 0

    def detect(key, frame, assets, trace):
        detections.append(key)
        return (10, 20, 1168, 89) if key == "skillbar" else (10, 20, 42, 16)

    monkeypatch.setattr(setup_flow, "capture_for_autofind", capture)
    monkeypatch.setattr(setup_flow, "run_detector", detect)
    monkeypatch.setattr(setup_flow, "to_logical", lambda *box: box)
    monkeypatch.setattr(window._setup_flow, "_approve", lambda key, box: box)
    monkeypatch.setattr(window._setup_flow, "_notice", lambda *args: notices.append(args))
    yield window, account, captures, detections, notices, isolated, storage
    close(window)
    storage.io.wait()
    storage.io.close()


def game():
    raw = config._read_local_config()
    raw.setdefault("general", {})["gameExe"] = "Client.exe"
    config._write_local_config(raw)


def test_actual_first_show_stages_and_tour_are_not_registration(app, scene):
    window, _, captures, detections, _, path, _ = scene
    window.move(0, 0)
    window.show()
    app.processEvents()
    guide = window.setup_guide
    assert window._pages.currentWidget() is guide and guide.stage == 0
    assert not any(check.isChecked() for check in guide.checks.values())
    assert not config.load_general_flag("firstUseGuideShown")
    out = Path("/tmp/setup-v2-qa")
    out.mkdir(exist_ok=True)
    for stage in range(3):
        assert guide.stage == stage
        app.processEvents()
        app.processEvents()
        assert window.rect().contains(guide.next_btn.mapTo(window, guide.next_btn.rect().bottomRight()))
        assert window.rect().contains(guide.later_btn.mapTo(window, guide.later_btn.rect().bottomRight()))
        assert guide.selection.horizontalScrollBar().maximum() == 0
        assert not any(button.isVisible() and button.text() in ("Discord 로그인", "개별 설정", "앱으로 이동")
                       for button in guide.findChildren(QPushButton))
        assert {key for key, check in guide.checks.items() if check.isVisible()} == set(guide.feature_keys)
        window.grab().save(str(out / f"stage-{stage + 1}.png"))
        guide.later_btn.click()
    tour = window._tour
    assert tour.isVisible() and "4 / 4" in tour._step_lbl.text()
    scene_image = QPixmap(tour.size())
    scene_image.fill(Qt.GlobalColor.white)
    painter = QPainter(scene_image)
    painter.drawPixmap(window.mapToGlobal(QPoint()) - tour.pos(), window.grab())
    painter.drawPixmap(0, 0, tour.grab())
    painter.end()
    scene_image.save(str(out / "stage-4.png"))
    for _ in range(len(tour._steps)):
        tour._next.click()
        app.processEvents()
    assert window._tour is None and config.load_general_flag("tourShown")
    assert not captures and not detections and state.pending() == []
    raw = config._read_local_config()
    assert all(not state.enabled(feature.key, raw) for feature in state.FEATURES)


def test_nonlogged_entry_and_scope_are_inert(app, scene):
    window, account, captures, detections, _, path, _ = scene
    account["logged_in"] = False
    window.settings_tab.login_changed.emit()
    before = path.read_bytes()
    window.show()
    app.processEvents()
    window._open_guide()
    window._resume_guide()
    window._run_guide_setup()
    assert window._pages.currentWidget() is not window.setup_guide
    assert window.settings_tab.guide_btn.isHidden()
    assert not captures and not detections and path.read_bytes() == before


def test_stage_scope_real_persistence_and_shared_dependency(scene):
    window, _, captures, detections, _, _, _ = scene
    game()
    window._open_guide()
    guide = window.setup_guide
    guide.next_btn.click()
    for key in ("boss", "buff", "tuarim", "stat_bars"):
        window._set_feature_enabled(key, True)
        if key == "stat_bars":
            raw = config._read_local_config()
            raw["statBars"]["bars"] = {"hp": {"alert": {"on": True}}}
            config._write_local_config(raw)
    guide.run_btn.click()
    assert detections == ["boss", "buff"]
    assert state.missing("tuarim") and state.missing("stat_bars")
    assert not state.missing("boss") and not state.missing("buff")
    before = deepcopy(config._read_local_config())
    guide.run_btn.click()
    assert len(captures) == 2 and config._read_local_config() == before
    guide.next_btn.click()
    guide.run_btn.click()
    assert detections == ["boss", "buff", "tuarim", "stat_bars"]
    assert all(not state.missing(key) for key in ("boss", "buff", "tuarim", "stat_bars"))


@pytest.mark.parametrize("failure", ["decline", "missing", "save", "capture"])
def test_failures_are_not_success_and_do_not_trap_navigation(scene, monkeypatch, failure):
    window, _, captures, detections, notices, _, _ = scene
    game()
    window._open_guide()
    guide = window.setup_guide
    guide.move(1)
    for key in ("buff", "boss"):
        guide.feature_changed.emit(key, True)
    if failure == "decline":
        monkeypatch.setattr(window._setup_flow, "_approve", lambda key, box: None if key == "buff" else box)
    elif failure == "missing":
        detector = setup_flow.run_detector
        monkeypatch.setattr(setup_flow, "run_detector", lambda key, *args: None if key == "buff" else detector(key, *args))
    elif failure == "save":
        def deny(*args, **kwargs):
            raise PermissionError("qa storage failure")
        monkeypatch.setattr(config, "save_capture_region", deny)
    else:
        monkeypatch.setattr(setup_flow, "capture_for_autofind", lambda **kwargs: (None, 0, 0))
    guide.run_btn.click()
    expected = {"decline": "등록하지 않음", "missing": "찾지 못함",
                "save": "저장 실패", "capture": "게임창 미발견 또는 캡처 실패"}[failure]
    assert guide.statuses["buff"].text() == expected
    assert state.missing("buff") == ["buff"]
    if failure == "capture":
        assert guide.statuses["boss"].text() == "아직 시도하지 않음"
        assert not detections
    else:
        assert not state.missing("boss")
    assert not guide.busy and guide.next_btn.isEnabled()
    guide.next_btn.click()
    assert guide.stage == 2


def test_logout_during_worker_discards_pending_result(scene, monkeypatch):
    window, account, _, _, _, _, _ = scene
    game()
    window._open_guide()
    guide = window.setup_guide
    guide.move(1)
    guide.feature_changed.emit("buff", True)
    started = Event()

    def slow(*args):
        started.set()
        time.sleep(0.15)
        return (10, 20, 42, 16)

    def logout():
        account["logged_in"] = False
        window.settings_tab.login_changed.emit()

    monkeypatch.setattr(setup_flow, "run_detector", slow)
    QTimer.singleShot(25, logout)
    guide.run_btn.click()
    assert started.is_set() and window._setup_flow.cancelled
    window._setup_flow.future.result(timeout=2)
    assert state.missing("buff") == ["buff"]
    assert not guide.active and window._pages.currentWidget() is not guide
    assert not guide.busy and not window._setup_flow.running


def test_skip_checkbox_is_synchronized_when_returning_to_existing_setup(app, scene):
    window, _, _, _, _, _, _ = scene
    window.show()
    app.processEvents()
    assert window._pages.currentWidget() is window.setup_guide
    window.setup_guide.skip.click()
    assert config.load_general_flag("skipSetup")
    out = Path("/tmp/setup-v2-qa")
    out.mkdir(exist_ok=True)
    window.grab().save(str(out / "skip-in-guide.png"))
    for _ in range(3):
        window.setup_guide.next_btn.click()
        app.processEvents()
    window._tour._skip.click()
    app.processEvents()
    window._tabs.setCurrentIndex(3)
    window._tabs.currentWidget().ensureWidgetVisible(window.settings_tab.setup_btn)
    window.settings_tab.setup_btn.click()
    app.processEvents()
    assert window._pages.currentWidget() is window.setup_page
    window.grab().save(str(out / "skip-in-existing-setup.png"))
    assert window.setup_page.skip.isChecked() == config.load_general_flag("skipSetup")


def test_existing_area_survives_back_reopen_and_next_process(scene):
    window, _, _, _, _, path, _ = scene
    game()
    window._open_guide()
    guide = window.setup_guide
    guide.move(1)
    guide.feature_changed.emit("boss", True)
    guide.run_btn.click()
    saved = deepcopy(config.load_boss_bar_region())
    guide.move(1)
    guide.move(-1)
    window.settings_tab.reopen_guide.emit()
    assert guide.stage == 0 and config.load_boss_bar_region() == saved
    window._force_quit = True
    window.close()
    second = main_window.MainWindow()
    try:
        second._open_guide()
        assert second.setup_guide.stage == 0
        assert second.setup_guide.status_text("boss", config._read_local_config()) == "등록됨"
        assert config.load_boss_bar_region() == saved
    finally:
        close(second)
