"""해외(영문 제목) 클라이언트에서 게임 프로세스를 열지 않는 모드(사용자 결정 11-18) — Windows API는 가짜.

NA 사용자가 애드온만 켠 채 두 번 NA 보안 프로그램에 게임이 끊김 → 가장 유력한 후보인 '게임 프로세스 열기'(OpenProcess)를
해외 게임 창에는 하지 않는다. 한국('마비노기' 제목)은 지금 경로 그대로."""
import ctypes
import os
import sys
from types import SimpleNamespace

import pytest

from mabinogi_addon.system import overseas_guard as og
from mabinogi_addon.system import window_watcher as ww

NA = (101, "Mabinogi", "Mabinogi", 4242)          # (hwnd, 제목, 창 클래스, pid)
CHROME = (102, "Mabinogi", "Chrome_WidgetWin_1", 5555)  # 제목이 딱 'Mabinogi'인 유튜브 탭(크롬)
KR = (103, "마비노기", "Mabinogi", 7777)


@pytest.fixture(autouse=True)
def _reset():
    og.reset_for_tests()
    yield
    og.reset_for_tests()


def _scan(*rows):
    og.scan(lambda: list(rows))


class FakeKernel:
    """ctypes.windll.kernel32 가짜 — OpenProcess 호출을 기록."""

    def __init__(self):
        self.opened = []

    def OpenProcess(self, access, inherit, pid):
        self.opened.append(pid)
        return 0  # 실패로 돌려 나머지 호출 없음


@pytest.fixture
def kernel(monkeypatch):
    k = FakeKernel()
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=k), raising=False)
    return k


# ---- 판정(순수) ----
@pytest.mark.parametrize("title,cls,ok", [
    ("Mabinogi", "Mabinogi", True), ("Mabinogi", "", True),
    ("Mabinogi - YouTube - Chrome", "Chrome_WidgetWin_1", False),  # 유튜브 'Mabinogi' 영상 탭
    ("Mabinogi", "MozillaWindowClass", False), ("Mabinogi", "CabinetWClass", False),
    ("마비노기", "Mabinogi", False), ("마비노기 Mabinogi", "", False),
    # QA 5fbb5f09 ②: 한국 사용자의 다른 프로그램 — 창 클래스와 상관없이 제목이 'Mabinogi'만이 아니면 아님
    ("mabinogi_2026_11_18_123456.jpg - 꿀뷰", "HoneyviewClass", False), ("Mabinogi 길드", "EVA_Window_Dblclk", False),
    ("OBS 31.0.0 - Profile: Mabinogi - Scenes: 기본", "Qt663QWindowIcon", False),
    ("Mabinogi - 다음 팟플레이어", "PotPlayer64", False),
])
def test_overseas_game_window(title, cls, ok):
    assert og.is_overseas_game_window(title, cls) is ok


def test_scan_protects_only_overseas_game_pid():
    _scan(NA, CHROME, KR)
    assert og.active() and og.game_window() == (101, 4242)
    assert og.is_protected_pid(4242)
    assert not og.is_protected_pid(5555) and not og.is_protected_pid(7777)


def test_korean_client_only_changes_nothing():
    _scan(KR, CHROME)
    assert not og.active() and og.game_window() is None and not og.is_protected_pid(7777)


def test_closed_window_keeps_protection_for_the_run():
    _scan(NA)
    _scan(KR)  # NA 창이 닫힘
    assert og.game_window() is None and og.active() and og.is_protected_pid(4242)


# ---- 프로세스를 여는 곳 ----
def test_exe_lookup_never_opens_na_game(kernel):
    _scan(NA, KR)
    assert ww._exe_basename_of_pid(4242) == "" and kernel.opened == []
    ww._exe_basename_of_pid(7777)  # 한국 게임은 지금처럼 연다
    assert kernel.opened == [7777]


def _watcher(monkeypatch, title, pid, registered=None, cls="Mabinogi"):
    w = object.__new__(ww.WindowsWatcher)
    w._titles = ww.DEFAULT_GAME_TITLES
    w._game_exe = registered
    w._own_pid = os.getpid()
    monkeypatch.setattr(w, "_foreground", lambda: (title, pid), raising=False)
    monkeypatch.setattr(w, "_foreground_class", lambda: cls, raising=False)
    return w


@pytest.mark.parametrize("registered", [None, "client.exe"])
def test_classify_na_by_title_without_opening(monkeypatch, kernel, registered):
    _scan(NA, CHROME)
    w = _watcher(monkeypatch, "Mabinogi", 4242, registered)
    assert w._classify() == "game" and w.foreground_info() == ("Mabinogi", "")
    w = _watcher(monkeypatch, "Mabinogi", 5555, registered, "Chrome_WidgetWin_1")
    assert w._classify() == "other"
    assert kernel.opened == []  # 해외 제목이면 등록된 실행 파일이 있어도 열지 않음


def test_classify_korean_uses_existing_path(monkeypatch):
    _scan(NA)
    calls = []
    monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: calls.append(pid) or "client.exe")
    w = _watcher(monkeypatch, "마비노기", 7777)
    assert w._classify() == "game" and calls == [7777]
    w = _watcher(monkeypatch, "아무 창", 8888, "client.exe")
    assert w._classify() == "game" and calls == [7777, 8888]


def test_find_game_window_picks_na_by_title(monkeypatch):
    from mabinogi_addon.system import dwm_thumbnail
    rows = {201: ("Mabinogi", "Chrome_WidgetWin_1", 5555), 202: ("Mabinogi", "Mabinogi", 4242)}
    monkeypatch.setattr(dwm_thumbnail, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        IsWindowVisible=lambda h: True, GetWindowText=lambda h: rows[h][0], GetClassName=lambda h: rows[h][1],
        EnumWindows=lambda cb, extra: [cb(h, extra) for h in rows]))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, rows[h][2])))
    monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: pytest.fail("실행 파일 확인 금지"))
    assert dwm_thumbnail.find_game_window("client.exe", ww.DEFAULT_GAME_TITLES) == 202


def test_game_target_uses_na_window_without_exe(monkeypatch):
    from mabinogi_addon import config
    from mabinogi_addon.system import dwm_thumbnail, window_capture
    _scan(NA)
    monkeypatch.setattr(window_capture, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(config, "load_game_exe", lambda: None)  # 등록 안 해도
    monkeypatch.setattr(dwm_thumbnail, "find_game_window", lambda *a: pytest.fail("실행 파일로 찾기 금지"))
    monkeypatch.setattr(dwm_thumbnail, "window_rect", lambda hwnd: (0, 0, 1280, 720))
    monkeypatch.setattr(ww, "_exe_basename_of_pid", lambda pid: pytest.fail("실행 파일 확인 금지"))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242)))
    assert window_capture.registered_game_target() == (101, 4242, 0, 0, 1280, 720)  # 판독 기능은 그대로 이 창으로


# ---- 해외면 끔: 최적화·FPS·블랙박스·잡담 진단·우선순위 ----
def test_optimization_and_fps_do_not_start(monkeypatch):
    from mabinogi_addon.system.optimization import WindowsOptimization
    _scan(NA)
    backend = object.__new__(WindowsOptimization)
    monkeypatch.setattr("mabinogi_addon.system.window_capture.registered_game_target",
                        lambda *a: pytest.fail("게임 찾기 금지"))
    assert backend.game() is None  # 최적화 엔진·FPS 측정(같은 game())은 '게임 없음'으로 시작 안 함
    monkeypatch.setattr(backend, "_windows", lambda: None)
    monkeypatch.setattr(WindowsOptimization, "_kernel", staticmethod(lambda: pytest.fail("OpenProcess 금지")))
    with pytest.raises(ProcessLookupError), backend._process({"pid": 4242}):
        pass
    assert backend.alive({"pid": 4242}) is False


def test_blackbox_does_not_start(monkeypatch):
    from mabinogi_addon.system import blackbox_capture, blackbox_events
    _scan(NA)
    monkeypatch.setattr("mabinogi_addon.system.window_capture.registered_game_target",
                        lambda *a: pytest.fail("게임 찾기 금지"))
    events = object.__new__(blackbox_events.WindowsEvents)
    assert events.sample() == (None, False)  # 녹화 대상 없음 → 블랙박스 시작 안 함
    monkeypatch.setattr(blackbox_capture, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(PermissionError):
        blackbox_capture.target_identity(101, 4242)


def test_perf_dialogue_priority_skip_na_process(monkeypatch):
    from mabinogi_addon.system import (
        dialogue_visibility,
        perf_metrics,
        process_priority,
    )
    _scan(NA)
    fake = SimpleNamespace(OpenProcess=lambda *a: pytest.fail("OpenProcess 금지"))
    monkeypatch.setitem(sys.modules, "win32api", fake)
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(PROCESS_QUERY_LIMITED_INFORMATION=0x1000))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242)))
    assert perf_metrics.process_private_bytes(4242) is None
    assert perf_metrics.process_state(4242) is None
    detail = {}
    dialogue_visibility._blocker_identity(None, 101, detail)
    assert detail == {"blocker_pid": 4242, "blocker_exe": "overseas-game"}
    monkeypatch.setattr(process_priority, "_kernel", lambda: pytest.fail("OpenProcess 금지"))
    assert process_priority.api_priority(4242)[0] is None
    with pytest.raises(PermissionError):
        process_priority.write(4242, next(iter(process_priority.WRITABLE)))


def test_game_identity_without_opening(monkeypatch):
    from mabinogi_addon.system import game_process
    _scan(NA)
    probe = object.__new__(game_process.GameProcessProbe)
    probe._backend = SimpleNamespace(game=lambda: pytest.fail("프로세스 조회 금지"))
    probe._last = None
    monkeypatch.setattr(game_process, "sys", SimpleNamespace(platform="win32"))
    assert probe.identity() == (4242, 0)  # 창의 pid만 — 게임 재시작 감지는 pid로


# ---- QA 5fbb5f09 ①: 마지막 훑기 0.1초 뒤 북미 창이 떠도(다음 훑기 2초 전) 그 pid를 열지 않음 ----
def _fresh_na_window(monkeypatch, scan_rows=(KR,)):
    """창 목록 훑기는 방금(북미 창 없음) — 그 뒤 북미 창이 뜬 화면을 가짜 Win32로."""
    from mabinogi_addon import config
    from mabinogi_addon.system import dwm_thumbnail, window_capture
    og.scan(lambda: list(scan_rows))  # 막 훑음 → 2초 동안 다시 안 훑음
    assert not og.active()
    rows = {103: ("마비노기 - 나무위키 - Chrome", "Chrome_WidgetWin_1", 5555), 101: ("Mabinogi", "Mabinogi", 4242)}
    gui = SimpleNamespace(IsWindowVisible=lambda h: True, IsWindow=lambda h: True,
                          GetWindowText=lambda h: rows[h][0], GetClassName=lambda h: rows[h][1],
                          EnumWindows=lambda cb, extra: [cb(h, extra) for h in rows],
                          GetForegroundWindow=lambda: 0, IsIconic=lambda h: False)
    proc = SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, rows[h][2]))
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", proc)
    monkeypatch.setattr(window_capture, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(dwm_thumbnail, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(dwm_thumbnail, "window_rect", lambda hwnd: (0, 0, 1280, 720))
    monkeypatch.setattr(config, "load_game_exe", lambda: "client.exe")  # 등록된 실행 파일 경로
    window_capture.clear_target_cache()
    return rows


def _no_open(monkeypatch, kernel):
    from mabinogi_addon.system.optimization import WindowsOptimization
    monkeypatch.setattr(WindowsOptimization, "_kernel", staticmethod(lambda: pytest.fail("OpenProcess 금지(최적화)")))
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(OpenProcess=lambda *a: pytest.fail("OpenProcess 금지")))
    monkeypatch.setitem(sys.modules, "win32con", SimpleNamespace(PROCESS_QUERY_LIMITED_INFORMATION=0x1000))


def test_gap_optimization_game_does_not_open_new_na_window(monkeypatch, kernel):
    from mabinogi_addon.system.optimization import WindowsOptimization
    _fresh_na_window(monkeypatch)
    _no_open(monkeypatch, kernel)
    backend = object.__new__(WindowsOptimization)
    backend._game_window = None
    monkeypatch.setattr(backend, "_windows", lambda: None)
    assert backend.game() is None
    assert og.is_protected_pid(4242) and 4242 not in kernel.opened  # 찾는 순간 보호 등록, 북미 게임은 열지 않음
    # (한국 브라우저 창 5555는 지금처럼 실행 파일 확인 — 한국 경로 그대로)


def test_gap_previous_window_turned_na(monkeypatch, kernel):
    """이전에 잡아 둔 창(같은 hwnd·pid)이 북미 제목이 된 경우도 그 창 제목만 보고 열지 않음."""
    from mabinogi_addon.system import window_capture
    _fresh_na_window(monkeypatch)
    _no_open(monkeypatch, kernel)
    assert window_capture.registered_game_target((101, 4242, 0, 0, 1, 1)) == (101, 4242, 0, 0, 1280, 720)
    assert og.is_protected_pid(4242) and kernel.opened == []


def test_gap_game_identity_and_blackbox_and_perf(monkeypatch, kernel):
    from mabinogi_addon.system import blackbox_events, game_process, perf_metrics
    from mabinogi_addon.system.optimization import WindowsOptimization
    _fresh_na_window(monkeypatch)
    _no_open(monkeypatch, kernel)
    events = object.__new__(blackbox_events.WindowsEvents)
    assert events.sample() == (None, False)  # 블랙박스: 그 창을 찾는 순간 보호 → 시작 안 함
    og.reset_for_tests()
    _fresh_na_window(monkeypatch)
    backend = object.__new__(WindowsOptimization)
    backend._game_window = None
    monkeypatch.setattr(backend, "_windows", lambda: None)
    probe = object.__new__(game_process.GameProcessProbe)
    probe._backend, probe._last = backend, None
    monkeypatch.setattr(game_process, "sys", SimpleNamespace(platform="win32"))
    assert probe.identity() is None  # 첫 조회: 게임 프로세스 조회 없이 없음
    assert probe.identity() == (4242, 0)  # 다음 조회부터 창 pid만
    assert perf_metrics.process_state(4242) is None and perf_metrics.process_private_bytes(4242) is None
    assert 4242 not in kernel.opened


def test_gap_foreground_classify_registers_immediately(monkeypatch, kernel):
    og.scan(lambda: [KR])  # 방금 훑음(북미 창 없음)
    w = _watcher(monkeypatch, "Mabinogi", 4242, "client.exe")
    assert w._classify() == "game" and og.is_protected_pid(4242)
    assert ww._exe_basename_of_pid(4242) == "" and kernel.opened == []


def test_gap_dialogue_diagnostics_registers_immediately(monkeypatch):
    from mabinogi_addon.system import dialogue_visibility
    og.scan(lambda: [KR])
    gui = SimpleNamespace(GetWindowText=lambda h: "Mabinogi", GetClassName=lambda h: "Mabinogi")
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 4242)))
    monkeypatch.setitem(sys.modules, "win32api", SimpleNamespace(OpenProcess=lambda *a: pytest.fail("OpenProcess 금지")))
    detail = {}
    dialogue_visibility._blocker_identity(gui, 101, detail)
    assert detail == {"blocker_pid": 4242, "blocker_exe": "overseas-game"} and og.is_protected_pid(4242)
