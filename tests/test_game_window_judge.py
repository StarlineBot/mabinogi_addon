"""'게임 창인지' 판단(0.46.0, #221) — 제목 폴백에서 브라우저·탐색기·메신저·앱 자신 제외, 게임창 등록 개선."""
import os

import pytest
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config
from mabinogi_addon.system import window_watcher as ww


@pytest.mark.parametrize("title,exe,game", [
    ("마비노기 - 나무위키 - Chrome", "chrome.exe", False),
    ("마비노기 공략 - Microsoft Edge", "msedge.exe", False),
    ("마비노기", "explorer.exe", False),            # 탐색기 '마비노기' 폴더
    ("마비노기 길드 - Discord", "Discord.exe", False),
    ("마비노기", "KakaoTalk.exe", False),
    ("마비노기", "mabinogi-addon.exe", False),       # 앱 자신
    ("마비노기", "client.exe", True),
    ("Mabinogi", "client.exe", True),
    ("메모장", "notepad.exe", False),
    ("마비노기", "", True),                          # 실행파일을 못 읽으면 예전처럼 제목만
])
def test_is_game_title(title, exe, game):
    assert ww.is_game_title(title, exe) is game


def test_is_game_window_excludes_own_process_and_needs_exe():
    assert ww.is_game_window("마비노기", "client.exe", pid=7, own_pid=8)
    assert not ww.is_game_window("마비노기", "client.exe", pid=8, own_pid=8)
    assert not ww.is_game_window("마비노기", "", pid=7, own_pid=8)


@pytest.mark.parametrize("windows,found", [
    ([("마비노기 - 나무위키 - Chrome", "chrome.exe"), ("마비노기", "client.exe")], "client.exe"),
    ([("마비노기", "Client.exe"), ("마비노기", "client.exe")], "client.exe"),  # 같은 실행파일 두 창 → 하나
    ([("마비노기 - 나무위키 - Chrome", "chrome.exe"), ("메모장", "notepad.exe")], None),  # 0개
    ([("마비노기", "client.exe"), ("Mabinogi", "client_test.exe")], None),             # 2개
])
def test_find_running_game(windows, found):
    assert ww.find_running_game(windows) == found


class _FakeWatcherProcess:
    """WindowsWatcher._classify 폴백을 맥에서: 포그라운드 창·실행파일을 가짜로."""


@pytest.mark.parametrize("title,exe,registered,expected", [
    ("마비노기 - 나무위키 - Chrome", "chrome.exe", None, "other"),
    ("마비노기", "client.exe", None, "game"),
    ("마비노기", "explorer.exe", None, "other"),
    ("마비노기 - 나무위키 - Chrome", "chrome.exe", "chrome.exe", "game"),  # 등록돼 있으면 지금처럼 실행파일로만
    ("아무 제목", "client.exe", "client.exe", "game"),
    ("마비노기", "client.exe", "other.exe", "other"),
])
def test_windows_watcher_classify_fallback(monkeypatch, title, exe, registered, expected):
    w = object.__new__(ww.WindowsWatcher)
    w._titles = ww.DEFAULT_GAME_TITLES
    w._game_exe = registered
    w._own_pid = os.getpid()
    monkeypatch.setattr(w, "_foreground", lambda: (title, 4242), raising=False)
    monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: exe)
    assert w._classify() == expected


def test_first_run_dialog_preselects_game_not_browser(monkeypatch):
    QApplication.instance() or QApplication([])
    import mabinogi_addon.ui.game_window_dialog as gwd
    wins = [("마비노기 - 나무위키 - Chrome", "chrome.exe"), ("마비노기", "client.exe")]
    monkeypatch.setattr(gwd, "list_windows", lambda: wins)

    class W:
        def set_game_exe(self, exe):
            pass
    dlg = gwd.GameWindowDialog(W())
    assert dlg._combo.currentData() == "client.exe"
    dlg.deleteLater()


# ---- 설정 › 게임창 등록 ----

class _Watcher:
    def __init__(self):
        self.fg = ("", "")
        self.own = False
        self.exe = None

    def foreground_info(self):
        return self.fg

    def is_self_active(self):
        return self.own

    def set_game_exe(self, exe):
        self.exe = exe

    def __getattr__(self, name):  # 설정 탭이 쓰는 다른 질의는 기본값
        return lambda *a, **k: False


@pytest.fixture
def tab(monkeypatch):
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui.settings_tab import SettingsTab
    watcher = _Watcher()
    t = SettingsTab(watcher)
    now = [0.0]
    t._detect_clock = lambda: now[0]
    monkeypatch.setattr(ww, "list_windows", lambda: [])
    config.save_game_exe("before.exe")
    t._update_game_label()
    results = []
    t.game_registration_finished.connect(results.append)
    yield t, watcher, now, results
    t._stop_detect()
    t.deleteLater()


def _tick(t, now, seconds):
    now[0] += seconds
    t._tick_detect()


def test_rejects_app_browser_explorer_then_registers_game(tab):
    t, w, now, results = tab
    t._start_detect()
    assert not t._detect_btn.isEnabled() and "(15초)" in t._detect_btn.text()
    w.own = True  # 버튼 누른 직후: 앱 자신이 앞 → 아무것도 안 함
    w.fg = ("섯다라인", "mabinogi-addon.exe")
    _tick(t, now, 0.3)
    assert config.load_game_exe() == "before.exe" and not t._detect_status.text()
    w.own = False
    for fg in (("마비노기 - 나무위키 - Chrome", "chrome.exe"), ("마비노기", "explorer.exe"), ("x", "mabinogi-addon.exe")):
        w.fg = fg
        _tick(t, now, 0.3)
        assert config.load_game_exe() == "before.exe" and t._detect_status.text().startswith("마비노기 창이 아니에요")
        assert t._detect_timer is not None  # 거절 뒤 계속 기다림
    w.fg = ("마비노기", "client.exe")  # 2초쯤 뒤 게임이 앞으로
    _tick(t, now, 1.0)
    assert config.load_game_exe() == "client.exe" and w.exe == "client.exe" and results == [True]
    assert t._detect_timer is None and t._detect_btn.isEnabled() and "client.exe" in t._game_hint.text()


def test_timeout_keeps_previous_value(tab):
    t, w, now, results = tab
    t._start_detect()
    w.own = True
    for _ in range(50):
        _tick(t, now, 0.3)
        if t._detect_timer is None:
            break
    assert 14.9 <= now[0] <= 15.3
    assert config.load_game_exe() == "before.exe" and results == [False]
    assert t._detect_status.text() == "시간이 지났어요. 다시 눌러 주세요."


@pytest.mark.parametrize("windows,registered", [
    ([("마비노기", "client.exe"), ("마비노기 - 나무위키 - Chrome", "chrome.exe")], True),
    ([], False),
    ([("마비노기", "client.exe"), ("Mabinogi", "other.exe")], False),
])
def test_running_game_found_registers_at_once(tab, monkeypatch, windows, registered):
    t, w, now, results = tab
    monkeypatch.setattr(ww, "list_windows", lambda: windows)
    t._start_detect()
    if registered:
        assert config.load_game_exe() == "client.exe" and results == [True]
        assert t._detect_status.text() == "찾았어요: client.exe" and t._detect_timer is None
    else:
        assert config.load_game_exe() == "before.exe" and t._detect_timer is not None and results == []


# ---- 0.48.0: 저장된 잘못된 게임창 등록 값(앱 자신·브라우저 등)은 읽을 때 무시 ----

@pytest.mark.parametrize("bad", ["mabinogi-addon.exe", "chrome.exe"])
def test_saved_bad_game_exe_is_ignored_with_warning_once(bad, caplog, monkeypatch):
    import logging
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(config, "_bad_game_exe_logged", set())
    caplog.set_level(logging.WARNING, logger="mabinogi_addon.config")
    config.save_game_exe(bad)
    assert config.load_game_exe() is None and config.load_game_exe() is None  # 미등록처럼 → 제목 폴백
    assert config.load_game_exe_raw() == bad  # 저장값은 지우지 않음
    lines = [r.getMessage() for r in caplog.records if "[게임창]" in r.getMessage()]
    assert lines == [f"[게임창] 등록된 값 {bad}는 게임이 아니라 무시 — 다시 등록 필요"]
    from mabinogi_addon.ui.settings_tab import SettingsTab
    t = SettingsTab(_Watcher())
    assert t._game_hint.text() == f"등록된 값({bad})은 게임이 아니에요. '게임창 등록 시작'으로 다시 등록해 주세요."
    t.deleteLater()


def test_saved_good_game_exe_is_kept():
    config.save_game_exe("client.exe")
    assert config.load_game_exe() == "client.exe" and config.invalid_game_exe() is None


@pytest.mark.parametrize("local", ["client.exe", None])
def test_import_bundle_keeps_this_pc_game_exe_when_incoming_is_bad(tmp_path, local):
    import json
    import zipfile
    raw = {"general": {"theme": "dark"}}
    if local:
        raw["general"]["gameExe"] = local
    config._write_local_config(raw)
    bundle = tmp_path / "b.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("config.json", json.dumps({"general": {"theme": "light", "gameExe": "mabinogi-addon.exe"}}))
    config.import_bundle(bundle, path=config.LOCAL_CONFIG_PATH, user_dir=tmp_path / "u")
    general = config._read_local_config()["general"]
    assert general["theme"] == "light" and general.get("gameExe") == local
    with zipfile.ZipFile(bundle, "w") as z:  # 올바른 값은 들어옴
        z.writestr("config.json", json.dumps({"general": {"gameExe": "client2.exe"}}))
    config.import_bundle(bundle, path=config.LOCAL_CONFIG_PATH, user_dir=tmp_path / "u")
    assert config._read_local_config()["general"]["gameExe"] == "client2.exe"
