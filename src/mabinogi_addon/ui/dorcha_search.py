"""Bounded, cancellable background jobs for Dorcha. Widget updates stay on the UI thread.

0.38.0: 게임 창 전체 캡처·찾은 자리 다시 읽기도 탐색 스레드에서 한다(화면 스레드는 결과 반영만).
"""

import time

from PySide6.QtCore import QThread

from ..detect.dorcha_anchor import locate_dorcha


class DorchaJob(QThread):
    """판독 틱 계산 하나(대상 확인·캡처·판독) — 결과는 result, 반영은 화면 스레드가."""

    def __init__(self, work):
        super().__init__()
        self._work = work
        self.result = None

    def run(self):
        try:
            self.result = self._work()
        finally:
            self._work = None


class DorchaSearch(QThread):
    def __init__(self, frame, target, epoch, grab=None, read=None, target_fn=None):
        super().__init__()
        self.frame = frame
        self.target = target
        self.epoch = epoch
        self._grab, self._read, self._target_fn = grab, read, target_fn
        self.box = None
        self.error = None
        self.elapsed = 0.0
        self.steps = {}
        # 찾은 자리 다시 읽기(탐색 스레드) 결과
        self.read_done = False
        self.value = None
        self.read_frame = None
        self.current_target = None

    def _timed(self, name, fn, *args):
        started = time.perf_counter()
        try:
            return fn(*args)
        finally:
            self.steps[name] = self.steps.get(name, 0.0) + (time.perf_counter() - started) * 1000

    def run(self):
        started = time.monotonic()
        try:
            if self.frame is None and self._grab is not None:
                _, _, x, y, w, h = self.target
                frame = self._timed("창 전체 캡처", self._grab, x, y, w, h)
                if frame is None or self.isInterruptionRequested():
                    return
                self.frame = frame
            self.box = self._timed("전체 탐색", lambda: locate_dorcha(self.frame, cancelled=self.isInterruptionRequested))
            self.frame = None
            if (self.box is not None and self._grab is not None and self._read is not None
                    and not self.isInterruptionRequested()):
                _, _, ox, oy, _, _ = self.target
                bx, by, bw, bh = self.box
                frame = self._timed("다시 캡처", self._grab, bx+ox, by+oy, bw, bh)
                self.value = self._timed("판독", self._read, frame) if frame is not None else None
                self.read_frame = frame
                self.current_target = self._timed("대상 확인", self._target_fn) if self._target_fn else self.target
                self.read_done = True
        except Exception as exc:
            self.error = type(exc).__name__
        finally:
            self.frame = None
            self._grab = self._read = self._target_fn = None
            self.elapsed = time.monotonic() - started
