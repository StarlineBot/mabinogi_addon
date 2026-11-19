"""요리창 자동 찾기 실행부(docs/cooking-spec.md 7절, 0.54.0) — 캡처·찾기는 작업 스레드 1개, 화면 반영은 화면 스레드.

- 요리 탭이 `게임 위에 이 바 띄우기`를 켠 동안 + 게임이 앞일 때만 1초마다 tick(). 꺼져 있으면 캡처·찾기 0.
- 캡처 대상: 등록된 게임 창(registered_game_target, 자동 찾기와 같은 경로) → 없으면 주 모니터. 좌표는 물리 픽셀.
- mss는 작업 스레드 것 하나를 재사용하고, 끝낼 때 그 스레드에서 닫는다(GDI 반납 — 도르카와 같은 방식).
- 바 오버레이는 판독 캡처에서 빠져 있어(overlay_capture.watch) 자기 바를 다시 찾지 않는다.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from ..detect.cooking_window import CookingFinder, State

_log = logging.getLogger("mabinogi_addon.cooking")


def _target_rect() -> tuple[int, int, int, int] | None:
    """게임 창(left, top, width, height) 물리 픽셀 — 등록 창 우선, 없으면 주 모니터."""
    try:
        from ..system.window_capture import registered_game_target
        target = registered_game_target()
        if target is not None:
            return tuple(int(v) for v in target[2:6])
    except Exception:  # noqa: BLE001
        _log.debug("게임 창 조회 실패 — 주 모니터로", exc_info=True)
    try:
        from .screen_grab import _mss
        mon = _mss().monitors[1]
        return int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"])
    except Exception:  # noqa: BLE001
        return None


class CookingAutoFind:
    """tick()을 화면 스레드에서 부르면, 끝난 작업 결과를 돌려주고(없으면 None) 다음 작업을 건다."""

    def __init__(self, target=_target_rect) -> None:
        self.finder = CookingFinder()
        self._target = target
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future | None = None
        self._local = threading.local()
        self.origin = (0, 0)  # 마지막 작업의 게임 창 왼쪽 위(물리)

    # ---- 작업 스레드 ----
    def _grab(self, left: int, top: int):
        def grab(x, y, w, h):
            try:
                sct = getattr(self._local, "sct", None)
                if sct is None:
                    import mss
                    sct = self._local.sct = mss.mss()
                shot = sct.grab({"left": left + x, "top": top + y, "width": w, "height": h})
                return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3]
            except Exception:  # noqa: BLE001
                return None
        return grab

    def _job(self):
        rect = self._target()
        if rect is None:
            return None
        left, top, width, height = rect
        state = self.finder.step(self._grab(left, top), width, height)
        return state, (left, top)

    def _close_thread_mss(self) -> None:
        sct = getattr(self._local, "sct", None)
        self._local.sct = None
        if sct is not None:
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                _log.debug("mss 닫기 실패", exc_info=True)

    def submit(self, fn) -> Future:
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cooking-find")
        return self._executor.submit(fn)

    # ---- 화면 스레드 ----
    def tick(self, run: bool) -> State | None:
        """끝난 결과(State, 없으면 None). run이 참일 때만 다음 찾기를 건다(하나씩)."""
        result = None
        if self._future is not None and self._future.done():
            try:
                done = self._future.result()
            except Exception:  # noqa: BLE001
                _log.warning("요리창 찾기 실패", exc_info=True)
                done = None
            self._future = None
            if done is not None:
                result, self.origin = done
        if run and self._future is None:
            self._future = self.submit(self._job)
        return result

    def reset(self) -> None:
        self.finder.reset()

    def shutdown(self) -> None:
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.submit(self._close_thread_mss)  # 작업 스레드의 mss는 그 스레드에서 닫는다
            executor.shutdown(wait=False, cancel_futures=False)
        self._future = None
