"""0.38.0 도르카 화면 스레드 정체 수정 — 대상 확인·캡처·판독·전체 탐색은 작업 스레드에서, 화면 스레드는 결과 반영만.

사용자 실측(0.37.1): 도르카를 켜면 '마우스 커서 틱'이 1초에 2~3번 0.1~0.24초 늦었다. 원인은 200ms 판독 틱이
화면 스레드에서 설정 파일 읽기·프로세스 조회·mss 캡처·판독, 못 읽으면 게임 창 전체 BitBlt까지 하던 것.
(다른 테스트는 conftest가 같은 계산을 동기로 돌려 판정 로직만 본다 — 여기서는 실제 스레드로 돈다.)
"""
import logging
import threading
from time import monotonic

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from mabinogi_addon import config
from mabinogi_addon.system import window_capture
from mabinogi_addon.ui import dorcha_search, dorcha_tab
from test_dorcha_tracking import moving, place  # noqa: F401  (픽스처)


@pytest.fixture
def threaded(moving, monkeypatch):
    app, tab, state, writes = moving
    monkeypatch.setattr(dorcha_tab.DorchaTab, "INLINE_JOBS", False)
    calls = []
    grab, target = tab._grab_rect, tab._search_target

    def grab_on(x, y, w, h):
        calls.append(("grab", threading.current_thread() is threading.main_thread(), (x, y, w, h)))
        return grab(x, y, w, h)

    def target_on():
        calls.append(("target", threading.current_thread() is threading.main_thread(), None))
        return target()

    monkeypatch.setattr(tab, "_grab_rect", grab_on)
    monkeypatch.setattr(tab, "_search_target", target_on)
    located = []
    original = dorcha_search.locate_dorcha

    def locate(frame, *a, **k):
        located.append(threading.current_thread() is threading.main_thread())
        return original(frame, *a, **k)
    monkeypatch.setattr(dorcha_search, "locate_dorcha", locate)
    return app, tab, state, calls, located


def settle(tab):
    """작업이 끝나 화면 스레드에 결과가 반영될 때까지(진짜 이벤트 루프로) 기다린다."""
    deadline = monotonic() + 5
    while monotonic() < deadline and any(
            getattr(tab, name, None) is not None for name in ("_tick_job", "_reread_job", "_search_worker")):
        loop = QEventLoop()
        QTimer.singleShot(5, loop.quit)
        loop.exec()
    assert tab._tick_job is None and tab._search_worker is None


def test_screen_thread_never_captures_looks_up_or_searches(threaded):
    app, tab, state, calls, located = threaded
    place(state, 20, 20)
    tab._tick()
    assert calls == []  # 틱 자체(화면 스레드)는 아무것도 캡처·조회하지 않고 작업만 건다
    settle(tab)
    assert tab._overlay.value == 15
    # 장식이 옮겨 가면: 못 읽음 → 전체 탐색(창 전체 캡처 포함) → 찾은 자리 다시 읽기 — 전부 작업 스레드
    calls.clear()
    place(state, 150, 90)
    tab._tick()
    settle(tab)
    settle(tab)
    assert tab._overlay.value == 15 and tab._live_box == (150, 90, 28, 23)
    assert (0, 0, 260, 180) in [c[2] for c in calls]  # 창 전체 캡처가 실제로 있었고
    assert located and not any(located)               # 전체 탐색도
    assert calls and not any(on_main for _, on_main, _ in calls), calls  # 어느 것도 화면 스레드가 아님


def test_ticks_do_not_pile_up_while_a_job_runs(threaded, monkeypatch):
    app, tab, state, calls, _ = threaded
    place(state, 20, 20)
    gate = threading.Event()
    grab = tab._grab_rect

    def slow(*box):
        gate.wait(2)
        return grab(*box)
    monkeypatch.setattr(tab, "_grab_rect", slow)
    tab._tick()
    job = tab._tick_job
    for _ in range(20):
        tab._tick()  # 지난 계산이 도는 중이면 쌓지 않고 건너뜀
        assert tab._tick_job is job
    gate.set()
    settle(tab)
    assert tab._overlay.value == 15


def test_slow_tick_logs_step_timings_once_a_minute(moving, caplog):
    _, tab, state, _ = moving
    caplog.set_level(logging.INFO, logger=dorcha_tab.__name__)
    steps = {"대상 확인": 1.0, "캡처": 25.0, "판독": 9.0}
    tab._log_slow("판독 틱", {"캡처": 10.0})  # 30ms 미만은 남기지 않음
    tab._log_slow("판독 틱", steps)
    tab._log_slow("판독 틱", steps)
    lines = [r.getMessage() for r in caplog.records if "느림" in r.getMessage()]
    assert lines == ["도르카 판독 틱 느림(작업 스레드) 35ms: 대상 확인 1ms · 캡처 25ms · 판독 9ms"]
    state.now += 61
    tab._log_slow("전체 탐색", {"창 전체 캡처": 40.0})
    assert len([r for r in caplog.records if "느림" in r.getMessage()]) == 2


def test_game_exe_and_owner_lookups_are_cached(monkeypatch):
    import sys
    from types import SimpleNamespace
    from mabinogi_addon.system import dwm_thumbnail, window_watcher
    monkeypatch.setattr(window_capture, "sys", SimpleNamespace(platform="win32"))
    reads, owners = [], []
    monkeypatch.setattr(config, "load_game_exe", lambda: reads.append(1) or "Client.exe")
    monkeypatch.setattr(window_watcher, "_exe_basename_of_pid", lambda pid: owners.append(pid) or "client.exe")
    monkeypatch.setattr(dwm_thumbnail, "find_game_window", lambda *a: pytest.fail("창 전체 나열 금지"))
    monkeypatch.setattr(dwm_thumbnail, "window_rect", lambda hwnd: (0, 0, 800, 600))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(IsWindow=lambda h: True, IsWindowVisible=lambda h: True))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 7)))
    for _ in range(50):  # 초당 5번 × 10초
        assert window_capture.registered_game_target((5, 7, 0, 0, 1, 1)) == (5, 7, 0, 0, 800, 600)
    assert reads == [1] and owners == [7]  # 설정 파일·프로세스 조회는 캐시 시간 동안 한 번
    config.save_game_exe("Client.exe")  # 설정에서 게임 실행 파일을 바꾸면 캐시를 바로 비운다
    window_capture.registered_game_target((5, 7, 0, 0, 1, 1))
    assert reads == [1, 1]
