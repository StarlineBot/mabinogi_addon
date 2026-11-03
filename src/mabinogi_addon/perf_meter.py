"""기능별 처리 시간 계측(앱 CPU 절감 1단계 — 측정만, 동작 변경 없음).

각 기능의 주기 작업(틱)을 `measure("버프")`로 감싸면 경과 시간(perf_counter)과 그 스레드의 CPU 시간(thread_time)을
기능·스레드별로 더해 두고, 1분마다 app.log에 한 줄로 남긴다:

    기능별 처리 시간(60초, 앱 CPU 5.1% · 코어 8개): 버프 22.0ms/s CPU 20.1(작업) · 보스 3.1ms/s CPU 2.9(화면) · …

- ms/s = 1초당 그 기능이 쓴 경과 시간(1000이면 코어 하나를 계속 씀). CPU = 같은 구간의 스레드 CPU 시간(ms/s).
  Windows의 스레드 CPU 시간은 약 15.6ms 단위로 올라가므로 짧은 틱은 개별로는 0/15.6이지만 1분 합계로는 근사가 맞는다.
- 앱 CPU = 이 프로세스 전체 CPU 시간 ÷ 경과 ÷ 코어 수(작업 관리자와 같은 기준). 기능 합과의 차이는 그리기·Qt·기타 스레드.
- 비용: 호출마다 시계 두 번·잠금 한 번(수 µs). 기록이 없으면 로그도 없다.
"""
from __future__ import annotations

from contextlib import contextmanager
import functools
import logging
import os
import threading
import time

_log = logging.getLogger("mabinogi_addon.perf")
_lock = threading.Lock()
_acc: dict[tuple[str, str], list[float]] = {}  # (기능, 스레드) -> [경과 s, CPU s, 횟수]
REPORT_SECONDS = 60


def _thread_label() -> str:
    return "화면" if threading.current_thread() is threading.main_thread() else "작업"


def add(name: str, wall: float, cpu: float, thread: str | None = None) -> None:
    key = (name, thread or _thread_label())
    with _lock:
        row = _acc.get(key)
        if row is None:
            _acc[key] = [wall, cpu, 1]
        else:
            row[0] += wall
            row[1] += cpu
            row[2] += 1


@contextmanager
def measure(name: str):
    wall0, cpu0 = time.perf_counter(), time.thread_time()
    try:
        yield
    finally:
        add(name, time.perf_counter() - wall0, time.thread_time() - cpu0)


def timed(name: str):
    """메서드·함수 데코레이터 버전."""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            with measure(name):
                return fn(*args, **kwargs)
        return inner
    return wrap


def take() -> dict[tuple[str, str], list[float]]:
    """지금까지 모은 값을 꺼내고 비운다."""
    global _acc
    with _lock:
        snapshot, _acc = _acc, {}
    return snapshot


def format_line(snapshot, elapsed: float, process_cpu: float, cores: int | None = None) -> str | None:
    """한 줄 요약(경과 ms/s 큰 순). 기록이 없으면 None."""
    if not snapshot or elapsed <= 0:
        return None
    cores = cores or os.cpu_count() or 1
    rows = sorted(snapshot.items(), key=lambda item: -item[1][0])
    parts = [f"{name} {wall / elapsed * 1000:.1f}ms/s CPU {cpu / elapsed * 1000:.1f}({thread}·{int(calls)}회)"
             for (name, thread), (wall, cpu, calls) in rows]
    app = process_cpu / elapsed / cores * 100
    return (f"기능별 처리 시간({elapsed:.0f}초, 앱 CPU {app:.1f}% · 코어 {cores}개 · 코어 1개 기준 "
            f"{process_cpu / elapsed * 1000:.0f}ms/s): " + " · ".join(parts))


class Reporter:
    """화면 스레드 QTimer로 1분마다 한 줄. start()/stop()."""

    def __init__(self, parent=None, seconds: int = REPORT_SECONDS):
        from PySide6.QtCore import QTimer
        self._timer = QTimer(parent)
        self._timer.setInterval(seconds * 1000)
        self._timer.timeout.connect(self.report)
        self._wall = self._cpu = None

    def start(self) -> None:
        take()  # 시작 전 기록은 버린다
        self._wall, self._cpu = time.perf_counter(), time.process_time()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def report(self) -> str | None:
        wall, cpu = time.perf_counter(), time.process_time()
        if self._wall is None:
            self._wall, self._cpu = wall, cpu
            return None
        line = format_line(take(), wall - self._wall, cpu - self._cpu)
        self._wall, self._cpu = wall, cpu
        if line:
            _log.info(line)
        return line
