"""설정 초기화·가져오기·서버 설정 불러오기 뒤 앱이 바로 다시 켜진다(0.46.0, 사용자 결정 11-11).

- 적용 → 정상 종료 정리 → 자기 자신 다시 실행 1번, 종료 때 설정 저장·동기화 올리기 0회
- 취소·X·Esc → 적용 0회, 다시 실행 0회
- 다시 켜기 표시가 있는 새 프로세스는 단일 인스턴스 자리를 기다렸다 잡고, 없으면 바로 꺼짐
- 다시 실행 실패 → 직접 다시 켜 달라는 안내
"""
import json
import sys
import uuid
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from mabinogi_addon import config
from mabinogi_addon.system import single_instance, updater
from mabinogi_addon.ui import main_window
from mabinogi_addon.ui.settings_tab import RESTART_NOTICE, SettingsTab
from test_main_shutdown import window  # noqa: F401  (픽스처)


def _spin(app, done, ms=3000):
    import time
    end = time.monotonic() + ms / 1000
    while not done() and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)


@pytest.fixture
def relaunch(monkeypatch):
    calls, infos = [], []
    monkeypatch.setattr(updater, "can_relaunch_self", lambda: True)
    monkeypatch.setattr(updater, "relaunch_self", lambda: calls.append("relaunch"))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: infos.append(a[-1]) or QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: pytest.fail(f"경고 창: {a[-1]}"))
    return calls, infos


def _guard_close(monkeypatch, w):
    """종료 정리 중 설정 쓰기·동기화 올리기를 센다."""
    writes, flushes = [], []
    original = config._write_local_config
    monkeypatch.setattr(config, "_write_local_config",
                        lambda data, *a, **k: (writes.append(1), original(data, *a, **k)))
    monkeypatch.setattr(w._account, "shutdown", lambda flush=True: flushes.append(flush))
    return writes, flushes


def _bundle(tmp_path):
    import zipfile
    raw = config._read_local_config()
    raw["buffTracker"] = {"scale": 77}
    dest = tmp_path / "백업.zip"
    with zipfile.ZipFile(dest, "w") as z:
        z.writestr("config.json", json.dumps(raw, ensure_ascii=False))
    return dest


@pytest.mark.parametrize("action", ["reset", "import", "load"])
def test_apply_then_cleanup_then_relaunch_once_without_saving(window, relaunch, monkeypatch, tmp_path, action):  # noqa: F811
    w, _ = window
    app = QApplication.instance()
    calls, infos = relaunch
    monkeypatch.setattr(SettingsTab, "_confirm_restart", lambda *a, **k: True)
    if action == "import":
        bundle = _bundle(tmp_path)
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(bundle), ""))
        w.settings_tab._on_import_config()
    elif action == "reset":
        w.settings_tab._on_reset_config()
    else:  # 서버 설정을 받아 적용한 직후(AccountController.applied)
        w._on_account_applied(True)
    assert w._config_pending_restart and calls == []  # 정리 전엔 아직 실행 안 함
    applied = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None
    writes, flushes = _guard_close(monkeypatch, w)
    _spin(app, lambda: w._closing)
    assert w._closing and calls == ["relaunch"] and infos == []
    assert writes == [] and flushes == [False]  # 종료 때 설정 저장 0회·동기화 올리기 0회
    observed = config.LOCAL_CONFIG_PATH.read_bytes() if config.LOCAL_CONFIG_PATH.exists() else None
    assert observed == applied
    if action == "import":
        assert config._read_local_config()["buffTracker"] == {"scale": 77}


@pytest.mark.parametrize("action", ["reset", "import_confirm", "import_pick", "load_x"])
def test_cancel_applies_nothing_and_does_not_relaunch(window, relaunch, monkeypatch, tmp_path, action):  # noqa: F811
    w, _ = window
    app = QApplication.instance()
    calls, infos = relaunch
    for name in ("reset_config", "import_bundle"):
        monkeypatch.setattr(config, name, lambda *a, **k: pytest.fail("취소했는데 적용함"))
    monkeypatch.setattr(SettingsTab, "_confirm_restart", lambda *a, **k: False)
    if action == "reset":
        w.settings_tab._on_reset_config()
    elif action == "import_confirm":
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "x.zip"), ""))
        w.settings_tab._on_import_config()
    elif action == "import_pick":
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))
        monkeypatch.setattr(SettingsTab, "_confirm_restart", lambda *a, **k: pytest.fail("고르기 취소 뒤 확인 창"))
        w.settings_tab._on_import_config()
    else:  # 서버 설정 물음 창 X → 아무것도 안 함(866817b)
        chosen = []
        monkeypatch.setattr(w._account, "resolve", chosen.append)

        def close_box():
            box = next(b for b in QApplication.topLevelWidgets() if isinstance(b, QMessageBox) and b.isVisible())
            box.close()
        QTimer.singleShot(50, close_box)
        w._on_account_ask({"rev": 5, "updated": "2026-11-11T01:02:03Z", "device": "노트북"}, "new_pc")
        assert chosen == [None]
    QTest.qWait(50)
    app.processEvents()
    assert not w._config_pending_restart and not w._closing and calls == [] and infos == []


@pytest.mark.parametrize("how", ["esc", "x", "cancel", "ok"])
def test_confirm_dialog_buttons(window, how):  # noqa: F811
    w, _ = window

    def act():
        box = next(b for b in QApplication.topLevelWidgets() if isinstance(b, QMessageBox) and b.isVisible())
        if how == "esc":
            QTest.keyClick(box, Qt.Key.Key_Escape)
        elif how == "x":
            box.close()
        else:
            next(b for b in box.buttons() if b.text() == {"cancel": "취소", "ok": "초기화하고 다시 켜기"}[how]).click()
    QTimer.singleShot(50, act)
    assert w.settings_tab._confirm_restart("설정 초기화", "본문", "초기화하고 다시 켜기") is (how == "ok")


def test_relaunch_failure_shows_manual_restart_notice(window, relaunch, monkeypatch):  # noqa: F811
    w, _ = window
    calls, infos = relaunch

    def fail():
        raise OSError(1223, "The operation was canceled by the user")
    monkeypatch.setattr(updater, "relaunch_self", fail)
    monkeypatch.setattr(SettingsTab, "_confirm_restart", lambda *a, **k: True)
    w.settings_tab._on_reset_config()
    _spin(QApplication.instance(), lambda: w._closing)
    assert infos == [main_window.RELAUNCH_FAILED_TEXT] and "다시 실행해 주세요" in infos[0]


def test_dev_run_shows_notice_instead_of_restarting(window, relaunch, monkeypatch):  # noqa: F811
    w, _ = window
    calls, infos = relaunch
    monkeypatch.setattr(updater, "can_relaunch_self", lambda: False)
    monkeypatch.setattr(SettingsTab, "_confirm_restart", lambda *a, **k: True)
    w.settings_tab._on_reset_config()
    QTest.qWait(50)
    assert calls == [] and not w._closing and w._config_pending_restart and "다시 실행" in infos[0]


def test_texts_announce_restart():
    from mabinogi_addon.ui.main_window import account_ask_text
    text = account_ask_text({"updated": "2026-11-11T01:02:03Z", "device": "노트북"}, "new_pc")
    assert text.endswith("불러오면 앱이 바로 다시 켜져요.") and RESTART_NOTICE["reset"] == "적용하려고 앱이 바로 다시 켜져요."


# ---- 다시 실행(업데이트와 같은 길) ----

def test_relaunch_self_passes_restart_flag_and_strips_mei(monkeypatch, tmp_path):
    import subprocess
    seen = {}
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app.exe"))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(updater, "_is_admin", lambda: True)  # 관리자 → 권한 이어받기(UAC 다시 안 뜸)
    monkeypatch.setattr(updater, "_launch_elevated", lambda *a: pytest.fail("관리자인데 UAC 승격"))
    monkeypatch.setenv("_MEIPASS2", "old")
    monkeypatch.setattr(subprocess, "Popen", lambda args, **k: seen.update(args=args, env=k["env"]))
    updater.relaunch_self()
    assert seen["args"] == [str(tmp_path / "app.exe"), updater.RESTART_ARG] and "_MEIPASS2" not in seen["env"]
    elevated = []
    monkeypatch.setattr(updater, "_is_admin", lambda: False)
    monkeypatch.setattr(updater, "_launch_elevated", lambda *a: elevated.append(a))
    updater.relaunch_self()
    assert elevated == [(tmp_path / "app.exe", (updater.RESTART_ARG,))]


# ---- 단일 인스턴스: 다시 켜기 표시가 있으면 기다렸다 잡음 ----

def test_acquire_waits_for_old_process_only_when_restarting():
    QApplication.instance() or QApplication([])
    key = "test_" + uuid.uuid4().hex
    old = single_instance.SingleInstance(key)
    assert not old.already_running
    sleeps = []
    assert single_instance.acquire(key=key, sleep=sleeps.append) is None and sleeps == []  # 평소 두 번째 실행: 바로 꺼짐
    holder = [old]

    def sleep(seconds):  # 기다리는 동안 옛 프로세스가 끝남
        sleeps.append(seconds)
        if len(sleeps) == 3:
            holder.pop()._shm.detach()
    guard = single_instance.acquire(key=key, wait=15.0, sleep=sleep)
    assert guard is not None and not guard.already_running and len(sleeps) == 3
    t = [0.0]
    other = single_instance.acquire(key=key, wait=15.0, interval=0.25, clock=lambda: t[0],
                                    sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert other is None and t[0] == pytest.approx(15.0, abs=0.3)  # 끝까지 안 비면 최대 15초 뒤 포기


@pytest.mark.parametrize("restarted", [True, False])
def test_main_restart_flag_waits_for_slot_and_shows_window_even_in_tray(monkeypatch, restarted):
    """`--restart`: 자리를 15초까지 기다리고, '트레이로 시작'이어도 창을 보여 줌·업데이트 확인 건너뜀."""
    import faulthandler
    import logging

    import PySide6.QtWidgets as widgets

    import mabinogi_addon
    from mabinogi_addon import logbuffer
    from mabinogi_addon.system import startup
    from mabinogi_addon.ui import theme
    from PySide6.QtGui import QIcon
    app = QApplication.instance() or QApplication([])
    events = []
    handlers, level = set(logging.getLogger().handlers), logging.getLogger().level
    monkeypatch.setattr(sys, "argv", ["app.exe"] + (["--restart"] if restarted else []))
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    import threading
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(logbuffer, "install", lambda: None)
    monkeypatch.setattr(faulthandler, "enable", lambda *a, **k: None)
    monkeypatch.setattr(widgets, "QApplication", lambda args: app)
    monkeypatch.setattr(app, "exec", lambda: 0)
    monkeypatch.setattr(theme, "apply_theme", lambda value: None)
    monkeypatch.setattr(main_window, "app_icon", QIcon)
    monkeypatch.setattr(config, "load_general_flag", lambda key, default: key == "startInTray")
    monkeypatch.setattr(updater, "cleanup_old", lambda: None)
    monkeypatch.setattr(updater, "can_update", lambda: True)
    monkeypatch.setattr(updater, "check_latest", lambda: events.append("update-check"))
    monkeypatch.setattr(startup.StartupScreen, "step", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(single_instance, "acquire", lambda wait=0.0, **k: events.append(("acquire", wait)) or SimpleNamespace())

    class Window:
        def start(self):
            events.append("start")

        def show(self):
            events.append("show")
    monkeypatch.setattr(main_window, "MainWindow", Window)
    try:
        with pytest.raises(SystemExit):
            mabinogi_addon.main()
    finally:
        for handler in set(logging.getLogger().handlers) - handlers:
            logging.getLogger().removeHandler(handler)
            handler.close()
        logging.getLogger().setLevel(level)
    assert ("acquire", mabinogi_addon.RESTART_WAIT if restarted else 0.0) in events
    assert ("show" in events) is restarted  # 평소엔 '트레이로 시작'이라 창 없음
    assert "update-check" not in events  # 트레이 시작은 원래 확인 안 함, 다시 켜기도 건너뜀
    assert mabinogi_addon.RESTART_WAIT == 15.0

