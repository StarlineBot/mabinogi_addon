"""단축바 공유 캡처(쿨타임 명세 9.1-1·9.1-4) — 미러와 쿨타임이 같은 단축바를 따로 찍지 않게, 작업 스레드 하나가 찍어 나눠 준다.

- 요청(이름 → 물리 픽셀 사각형·주기·처리 함수)을 받아, 지금 필요한 요청들을 덮는 **사각형 하나**만 mss로 찍는다.
- 각 요청의 처리 함수는 **작업 스레드에서** 자기 부분(잘라 낸 numpy)을 받아 결과를 돌려준다(None이면 보낼 것 없음).
- 결과는 Qt 신호로 화면 스레드에 넘긴다 — 화면 스레드는 캡처·크기 조정·판정을 하지 않는다(커서 꼬리 끊김 대책).
- 테스트는 `INLINE = True`(conftest)로 같은 일을 바로(동기로) 한다.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np
from PySide6.QtCore import QObject, Signal

_log = logging.getLogger(__name__)


class SkillbarCapture(QObject):
    INLINE = False
    delivered = Signal(str, object)  # (요청 이름, 처리 결과) — 화면 스레드로(대기열 연결)

    def __init__(self, grab=None, parent=None) -> None:
        super().__init__(parent)
        self._grab_override = grab
        self._lock = threading.Lock()
        self._requests: dict[str, dict] = {}
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._local = threading.local()

    # ---- 요청 -------------------------------------------------------------------------------
    def set_request(self, name: str, rect, interval: float, handler, grab=None) -> None:
        """rect = 물리 픽셀 (x, y, w, h) 또는 None(그만). handler(frame)->결과(작업 스레드)."""
        if rect is None or rect[2] <= 0 or rect[3] <= 0:
            self.clear(name)
            return
        rect = tuple(int(v) for v in rect)
        if self.INLINE:  # 테스트: 바로 찍어 처리·전달
            frame = (grab or self._grab)(*rect)
            if frame is not None:
                result = handler(frame)
                if result is not None:
                    self.delivered.emit(name, result)
            return
        with self._lock:
            old = self._requests.get(name)
            due = old["due"] if old is not None and old["rect"] == rect else 0.0
            self._requests[name] = {"rect": rect, "interval": float(interval), "handler": handler, "due": due}
        self._ensure_thread()
        self._wake.set()

    def clear(self, name: str) -> None:
        with self._lock:
            self._requests.pop(name, None)

    def active(self, name: str) -> bool:
        with self._lock:
            return name in self._requests

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(2.0)
        self._thread = None

    # ---- 작업 스레드 ----------------------------------------------------------------------------
    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="skillbar-capture", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                with self._lock:
                    due = {n: dict(r) for n, r in self._requests.items() if r["due"] <= now}
                    nxt = min((r["due"] for r in self._requests.values()), default=None)
                if not due:
                    wait = 0.5 if nxt is None else max(0.005, min(0.5, nxt - now))
                    self._wake.wait(wait)
                    self._wake.clear()
                    continue
                self._capture_once(due, now)
        finally:
            sct = getattr(self._local, "sct", None)
            if sct is not None:
                try:
                    sct.close()
                except Exception:  # noqa: BLE001
                    pass

    def _capture_once(self, due: dict, now: float) -> None:
        x0 = min(r["rect"][0] for r in due.values())
        y0 = min(r["rect"][1] for r in due.values())
        x1 = max(r["rect"][0] + r["rect"][2] for r in due.values())
        y1 = max(r["rect"][1] + r["rect"][3] for r in due.values())
        frame = self._grab(x0, y0, x1 - x0, y1 - y0)  # 사각형 하나만 찍는다(요청들이 나눠 씀)
        for name, req in due.items():
            with self._lock:
                live = self._requests.get(name)
                if live is not None and live["rect"] == req["rect"]:
                    live["due"] = now + live["interval"]
            if frame is None:
                continue
            x, y, w, h = req["rect"]
            part = frame[y - y0:y - y0 + h, x - x0:x - x0 + w]
            try:
                result = req["handler"](part)
            except Exception:  # noqa: BLE001 — 처리 하나가 실패해도 다른 요청은 계속
                _log.warning("단축바 공유 캡처 처리 실패(%s)", name, exc_info=True)
                continue
            if result is not None:
                self.delivered.emit(name, result)

    def _grab(self, x, y, w, h) -> np.ndarray | None:
        if self._grab_override is not None:
            return self._grab_override(x, y, w, h)
        try:
            sct = getattr(self._local, "sct", None)
            if sct is None:
                import mss
                sct = self._local.sct = mss.mss()  # 스레드마다 따로(스레드 사이 공유 불가)
            shot = sct.grab({"left": x, "top": y, "width": w, "height": h})
            return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3].copy()
        except Exception:  # noqa: BLE001 — 캡처 불가 → 이번 회차 건너뜀
            return None


_shared: SkillbarCapture | None = None


def shared() -> SkillbarCapture:
    """앱 전체에서 하나(미러·쿨타임이 같은 것을 쓴다)."""
    global _shared
    from shiboken6 import isValid
    if _shared is None or not isValid(_shared):
        _shared = SkillbarCapture()
    return _shared
