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
    try:
        tab._tick()
        tab._tick()
        lines = [r.getMessage() for r in caplog.records if "보스 틱 느림" in r.getMessage()]
        assert len(lines) == 1  # 분당 1번
        assert "캡처 40ms" in lines[0] and "이름 식별 40ms" in lines[0] and "보스바 확인 40ms" in lines[0]
    finally:
        tab.shutdown()


def test_fast_tick_is_not_logged(monkeypatch, caplog):
    bt, tab = _tab(monkeypatch)
    caplog.set_level(logging.INFO, logger="mabinogi_addon.ui.boss_tab")
    tab._log_slow({"캡처": 3.0, "이름 식별": 4.0, "HP 판독": 2.0})
    assert not [r for r in caplog.records if "보스 틱 느림" in r.getMessage()]
    tab.shutdown()
