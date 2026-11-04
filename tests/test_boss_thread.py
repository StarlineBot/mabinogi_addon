"""꼬리 끊김 조사(사용자 app.log 11-04): 보스 틱 계산은 작업 스레드, 화면 스레드는 결과 반영만 + 느린 틱 단계별 로그."""
from __future__ import annotations

import logging
import os
import threading
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from mabinogi_addon import config


class _Watcher:
    def is_game_active(self):
        return True

    def is_self_active(self):
        return False


def _wait(cond, seconds=5.0):
    deadline = monotonic() + seconds
    while not cond() and monotonic() < deadline:
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    return cond()


def _tab(monkeypatch):
    QApplication.instance() or QApplication([])
    from mabinogi_addon.ui import boss_tab as bt
    monkeypatch.setattr(config, "load_discord_user", lambda *a, **k: {"name": "x"})
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", False)
    tab = bt.BossTab(_Watcher())
    tab._timer.stop()
    tab._region = {"x": 0, "y": 0, "w": 150, "h": 36}
    monkeypatch.setattr(tab, "_show_preview", lambda *a: None)
    monkeypatch.setattr(tab, "_play", lambda *a: None)
    return bt, tab


def test_capture_and_reading_run_off_the_ui_thread(monkeypatch):
    bt, tab = _tab(monkeypatch)
    threads = {}

    def grab(*_a):
        threads["grab"] = threading.current_thread()
        return np.zeros((36, 150, 3), np.uint8)

    def identify(*_a, **_k):
        threads["identify"] = threading.current_thread()
        return "lenen_miir"

    def read(*_a, **_k):
        threads["hp"] = threading.current_thread()
        return 90

    monkeypatch.setattr(tab, "_grab_worker", grab)
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: (_ for _ in ()).throw(AssertionError("화면 스레드 캡처")))
    monkeypatch.setattr(bt, "identify", identify)
    monkeypatch.setattr(bt, "read_percent", read)
    applied = []
    original = tab._apply_tick
    monkeypatch.setattr(tab, "_apply_tick", lambda out: (applied.append(threading.current_thread()), original(out)))
    try:
        for _ in range(4):
            tab._tick()
            assert tab._tick_job is not None
            tab._tick()  # 계산 중 다음 틱은 쌓지 않고 건너뛴다
            assert _wait(lambda: tab._tick_job is None)
        main = threading.main_thread()
        assert threads["grab"] is not main and threads["identify"] is not main and threads["hp"] is not main
        assert applied and all(t is main for t in applied)  # 반영은 화면 스레드
        assert len(applied) == 4
        assert tab._cur_boss == "lenen_miir" and tab._stable_hp == 90
    finally:
        tab.shutdown()
    assert "_executor" not in tab.__dict__ and tab._tick_job is None


def test_slow_tick_logs_steps_once_per_minute(monkeypatch, caplog):
    bt, tab = _tab(monkeypatch)
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", True)
    clock = iter(x * 0.04 for x in range(1000))  # 단계마다 40ms
    monkeypatch.setattr(bt, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(bt, "identify", lambda *a, **k: None)
    monkeypatch.setattr(tab, "_boss_bar_visible", lambda frame: False)
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.boss_tab")
    tab._bar_absent = 0  # 바가 보이던 중 — 보스바 확인이 매 틱 돈다
    try:
        tab._tick()
        tab._tick()
        lines = [r.getMessage() for r in caplog.records if "보스 틱 느림" in r.getMessage()]
        assert len(lines) == 1  # 분당 1번
        assert "캡처 40ms" in lines[0] and "이름 식별 40ms" in lines[0] and "보스바 확인 40ms" in lines[0]
        # 화면 스레드 쪽(미리보기·헤일로·반영)도 함께, 1분 안 느린 틱 횟수도
        assert "[계산·화면]" in lines[0]  # 테스트는 동기(화면 스레드) 실행
        assert "[반영·화면] 미리보기 40ms · 헤일로 40ms · 반영" in lines[0] and "느린 틱 1회" in lines[0]
    finally:
        tab.shutdown()


def test_fast_tick_is_not_logged(monkeypatch, caplog):
    bt, tab = _tab(monkeypatch)
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.boss_tab")
    tab._log_slow({"캡처": 3.0, "이름 식별": 4.0, "HP 판독": 2.0}, {"미리보기": 1.0, "헤일로": 0.5, "반영": 1.0})  # 16ms 미만
    assert not [r for r in caplog.records if "보스 틱 느림" in r.getMessage()]
    tab.shutdown()


def test_capture_guard_time_is_split_from_capture(monkeypatch, caplog):
    """우리 창이 보스 영역을 덮어 화면 스레드에서 읽는 틱: CaptureGuard(창 빼기)와 실제 캡처를 나눠 적는다."""
    bt, tab = _tab(monkeypatch)
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", True)
    times = iter([0.0, 0.050] + [0.050 + i * 0.001 for i in range(1, 400)])
    monkeypatch.setattr(bt, "perf_counter", lambda: next(times))

    def guarded_grab(*_a):
        tab._raw_ms = 5.0  # 실제 캡처 5ms, 나머지 45ms는 창 빼기
        return np.zeros((36, 150, 3), np.uint8)
    monkeypatch.setattr(tab, "_grab_rect", guarded_grab)
    monkeypatch.setattr(bt, "identify", lambda *a, **k: None)
    monkeypatch.setattr(tab, "_boss_bar_visible", lambda frame: False)
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.boss_tab")
    try:
        tab._tick()
        line = next(r.getMessage() for r in caplog.records if "보스 틱 느림" in r.getMessage())
        assert "[계산·화면] 캡처 5ms · CaptureGuard 45ms" in line
    finally:
        tab.shutdown()


def test_bar_check_is_sparse_only_after_bar_is_gone(monkeypatch):
    """보스바 확인(1회 평균 80ms)은 바가 '없음'으로 확정된 동안 3틱에 1번만, 보이거나 유예 중엔 매 틱."""
    bt, tab = _tab(monkeypatch)
    monkeypatch.setattr(bt.BossTab, "INLINE_JOBS", True)
    monkeypatch.setattr(tab, "_grab_rect", lambda *a: np.zeros((36, 150, 3), np.uint8))
    monkeypatch.setattr(bt, "identify", lambda *a, **k: None)
    visible = [False]
    checks = []
    monkeypatch.setattr(tab, "_boss_bar_visible", lambda frame: checks.append(1) or visible[0])
    try:
        for _ in range(30):  # 바 없음(시작부터 '없음' 확정)
            tab._tick()
        assert len(checks) == 10 and not tab.is_boss_present()
        visible[0] = True
        for _ in range(3):
            tab._tick()
        assert tab.is_boss_present()  # 3틱(약 0.9초) 안에 다시 잡힘
        checks.clear()
        visible[0] = False
        for _ in range(tab._UPCOMING_GONE_FRAMES + 1):
            tab._tick()
        assert len(checks) == tab._UPCOMING_GONE_FRAMES + 1  # 유예 중엔 매 틱
        assert not tab.is_boss_present()
    finally:
        tab.shutdown()
