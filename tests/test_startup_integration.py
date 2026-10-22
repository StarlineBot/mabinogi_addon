"""Actual startup flow, with external update/window work replaced at its boundary."""

import importlib.util
import logging
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QProgressBar

import mabinogi_addon
from mabinogi_addon import config, paths
from mabinogi_addon.system import startup, updater
from mabinogi_addon.ui import splash


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def bridge(monkeypatch):
    events = []
    connection = SimpleNamespace(
        is_alive=lambda: True,
        update_text=lambda message: events.append(message),
        close=lambda: events.append("close"),
    )
    monkeypatch.setitem(sys.modules, "pyi_splash", connection)
    return connection, events


def test_frozen_screen_keeps_its_bridge_and_never_creates_a_qt_replacement(
    bridge, monkeypatch
):
    connection, events = bridge
    monkeypatch.setattr(splash, "Splash", lambda: pytest.fail("second loading window"))
    screen = startup.StartupScreen()
    screen.configure(start_in_tray=False)
    screen.step(45)
    screen.step(60, "실제 다운로드 37%")
    screen.step(95)
    screen.close()
    screen.close()
    screen.step(100, "late callback")
    screen.configure(start_in_tray=False)
    assert events == ["@resume", "@status:실제 다운로드 37%", "@resume", "close"]


@pytest.mark.parametrize("failure", ["not_alive", "send_error"])
def test_bootloader_failure_does_not_create_a_second_window(
    app, bridge, monkeypatch, failure
):
    connection, events = bridge
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(splash, "Splash", lambda: pytest.fail("second loading window"))
    if failure == "not_alive":
        connection.is_alive = lambda: False
    else:

        def broken(message):
            raise OSError("broken IPC")

        connection.update_text = broken
    screen = startup.StartupScreen()
    screen.configure(start_in_tray=False)
    screen.step(12, "확인 중")
    screen.step(45)
    screen.close()
    assert events == ([] if failure == "not_alive" else ["close"])


@pytest.mark.parametrize(
    "case",
    [
        "normal",
        "tray",
        "duplicate",
        "update",
        "check_failure",
        "construct_failure",
        "start_failure",
    ],
)
def test_real_main_startup_lifetime_and_existing_entry_policy(
    app, bridge, monkeypatch, case
):
    from mabinogi_addon import logbuffer
    from mabinogi_addon.system import single_instance
    from mabinogi_addon.ui import main_window, theme
    import faulthandler
    import PySide6.QtWidgets as widgets

    connection, events = bridge
    handlers = set(logging.getLogger().handlers)
    level = logging.getLogger().level
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logbuffer, "install", lambda: None)
    monkeypatch.setattr(faulthandler, "enable", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "QApplication", lambda args: app)
    monkeypatch.setattr(app, "exec", lambda: events.append("exec") or 0)
    monkeypatch.setattr(theme, "apply_theme", lambda value: None)
    monkeypatch.setattr(main_window, "app_icon", QIcon)
    monkeypatch.setattr(
        config, "load_general_flag", lambda key, default: case == "tray"
    )
    monkeypatch.setattr(updater, "cleanup_old", lambda: None)
    monkeypatch.setattr(updater, "can_update", lambda: True)
    monkeypatch.setattr(
        single_instance,
        "SingleInstance",
        lambda: SimpleNamespace(already_running=case == "duplicate"),
    )
    monkeypatch.setattr(splash, "Splash", lambda: pytest.fail("second loading window"))

    def check():
        events.append("check")
        if case == "check_failure":
            raise OSError("offline")
        return {"version": "0.8.0"} if case == "update" else None

    def download(info, progress_cb):
        progress_cb(37)
        events.append("download")
        return Path("new.exe")

    monkeypatch.setattr(updater, "check_latest", check)
    monkeypatch.setattr(updater, "download", download)
    monkeypatch.setattr(updater, "apply_update", lambda p: events.append("apply"))

    class Window:
        def __init__(self):
            events.append("construct")
            if case == "construct_failure":
                raise RuntimeError("construct failed")

        def start(self):
            events.append("start")
            if case == "start_failure":
                raise RuntimeError("start failed")

        def show(self):
            events.append("show")

    monkeypatch.setattr(main_window, "MainWindow", Window)
    try:
        if case in ("construct_failure", "start_failure"):
            with pytest.raises(RuntimeError):
                mabinogi_addon.main()
        elif case in ("duplicate", "update"):
            mabinogi_addon.main()
        else:
            with pytest.raises(SystemExit) as exit:
                mabinogi_addon.main()
            assert exit.value.code == 0
    finally:
        for handler in set(logging.getLogger().handlers) - handlers:
            logging.getLogger().removeHandler(handler)
            handler.close()
        logging.getLogger().setLevel(level)

    assert events.count("close") == 1
    if case == "tray":
        assert "check" not in events and "show" not in events
        assert events.index("close") < events.index("construct")
    elif case == "duplicate":
        assert "construct" not in events and "exec" not in events
    elif case == "update":
        assert "construct" not in events
        assert "@status:새 버전 v0.8.0 받는 중 37%" in events
        assert events.index("apply") < events.index("close")
    else:
        assert events.index("construct") < events.index("close")
        if case not in ("construct_failure", "start_failure"):
            assert events.index("start") < events.index("close") < events.index("show")
    if case == "check_failure":
        assert (
            events.index("check") < events.index("@resume") < events.index("construct")
        )


def test_fatal_error_before_qapplication_still_closes_bootloader(bridge, monkeypatch):
    def failed(screen):
        raise ImportError("Qt cannot load")

    monkeypatch.setattr(mabinogi_addon, "_main", failed)
    with pytest.raises(ImportError):
        mabinogi_addon.main()
    assert bridge[1] == ["close"]


@pytest.mark.parametrize("phase", ["check_latest", "download", "apply_update"])
def test_update_failure_remains_nonfatal_and_records_real_status(phase, monkeypatch):
    messages = []
    screen = SimpleNamespace(step=lambda pct, msg: messages.append(msg))
    monkeypatch.setattr(updater, "can_update", lambda: True)
    monkeypatch.setattr(updater, "check_latest", lambda: {"version": "0.8.0"})
    monkeypatch.setattr(
        updater,
        "download",
        lambda info, progress_cb: (progress_cb(41), Path("new.exe"))[1],
    )
    monkeypatch.setattr(updater, "apply_update", lambda path: None)

    def fail(*a, **k):
        raise OSError("offline or file locked")

    monkeypatch.setattr(updater, phase, fail)
    assert mabinogi_addon._apply_update_before_launch(screen) is False
    if phase == "apply_update":
        assert messages[-2:] == ["새 버전 v0.8.0 받는 중 41%", "업데이트 적용 중"]


def test_qt_fallback_has_fixed_slots_and_one_cancelled_timer(app, monkeypatch):
    monkeypatch.setattr(splash, "MESSAGES", ["한글", "다음 대사"])
    window = splash.Splash()
    window.show()
    assert window.size().width() == 440 and window.size().height() == 240
    assert not window.findChildren(QProgressBar)
    window._timer.stop()
    window._tick()
    first = window.msg.text()
    assert first in ("한", "다")
    window.step(45)
    assert window.msg.text() == first
    window.step(60, "업데이트 37%")
    window._tick()
    assert window.msg.text() == "업데이트 37%"
    assert not window._timer.isActive()
    window.step(95)
    assert window.msg.text() == "" and window._timer.isActive()
    window.close()
    window._tick()
    window.step(100, "late")
    assert not window._timer.isActive() and window.msg.text() == ""


def test_source_controller_uses_one_fallback_and_tray_uses_none(app, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyi_splash", None)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)
    screen = startup.StartupScreen()
    screen.configure(start_in_tray=False)
    window = screen._fallback
    assert window is not None and window.isVisible()
    screen.configure(start_in_tray=False)
    assert screen._fallback is window
    screen.close()
    assert not window.isVisible() and not window._timer.isActive()
    tray = startup.StartupScreen()
    tray.configure(start_in_tray=True)
    assert tray._fallback is None


def test_empty_fallback_content_and_effect_failure_do_not_schedule_more_work(
    app, monkeypatch
):
    monkeypatch.setattr(splash, "MESSAGES", [])
    empty = splash.Splash()
    assert empty.msg.text() == "시작하는 중" and not empty._timer.isActive()
    empty.close()
    monkeypatch.setattr(splash, "MESSAGES", ["대사"])
    monkeypatch.setattr(
        splash.Splash,
        "_show_text",
        lambda *a: (_ for _ in ()).throw(ValueError("effect")),
    )
    failed = splash.Splash()
    assert failed._mode == "fallback" and not failed._timer.isActive()
    failed.close()


def test_fallback_display_and_cleanup_failure_cannot_block_startup(app, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyi_splash", None)
    monkeypatch.setattr(paths, "is_frozen", lambda: False)

    def fail():
        raise RuntimeError("display unavailable")

    monkeypatch.setattr(
        splash, "Splash", lambda: SimpleNamespace(center_on_screen=fail, close=fail)
    )
    screen = startup.StartupScreen()
    screen.configure(start_in_tray=False)
    screen.step(45)
    screen.close()
    assert screen._fallback is None


def test_installed_update_with_failed_relaunch_asks_restart_instead_of_running_old(monkeypatch):
    import mabinogi_addon
    from PySide6.QtWidgets import QMessageBox
    from mabinogi_addon.system import updater
    shown = []
    screen = type("Splash", (), {"step": lambda *a: None, "close": lambda self: shown.append("close")})()
    monkeypatch.setattr(updater, "can_update", lambda: True)
    monkeypatch.setattr(updater, "check_latest", lambda: {"version": "9.9.9"})
    monkeypatch.setattr(updater, "download", lambda info, progress_cb=None: "new.exe")
    def relaunch_failed(path):
        raise updater.RelaunchError("새 버전을 자동으로 시작하지 못했어요(취소).")
    monkeypatch.setattr(updater, "apply_update", relaunch_failed)
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.append(text))
    assert mabinogi_addon._apply_update_before_launch(screen) is True  # 옛 버전으로 계속 띄우지 않음
    assert shown[0] == "close" and "앱을 다시 실행해 주세요" in shown[1]
