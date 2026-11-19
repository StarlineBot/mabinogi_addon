"""요리창 자동 찾기 실행부(docs/cooking-spec.md 7절, 0.54.0) — 캡처·찾기는 작업 스레드 1개, 화면 반영은 화면 스레드.

- 요리 탭이 `게임 위에 이 바 띄우기`를 켠 동안 + 게임이 앞일 때만 1초마다 tick(). 꺼져 있으면 캡처·찾기 0.
- 캡처(QA 반려 11-19 뒤): 버프·체력바 판독과 같은 공유 라이브 카메라(dxcam, 주 모니터 전체 프레임)에서 잘라 쓴다.
  대상 사각형은 등록된 게임 창(registered_game_target) → 없으면 주 모니터 전체. 게임 창이 주 모니터 밖이거나
  라이브 카메라를 못 쓰면 작업 스레드의 mss로(그 스레드 인스턴스 재사용, 종료 때 그 스레드에서 닫음).
- 진단 로그(INFO, QA 반려 11-19 두 번째 뒤): '신호' 기준 — 꺼짐↔켜짐이 바뀔 때 한 줄, 켜져 있는 동안은 매 step 한 줄
  (띠 검은 비율·전체 찾기 여부·최고 점수·자리·못 찾은 횟수·결과 상태), 꺼져 있는 동안은 30초에 한 줄.
- 실패 프레임 저장(logs/cooking-find/, 실행당): 신호가 켜졌는데 못 찾은 전체 프레임 최대 3장 + 신호 꺼짐 판정 프레임
  30초 간격 최대 2장(띠 자리 확인용). 로그 줄에 파일 이름.
- 바 오버레이는 판독 캡처에서 빠져 있어(overlay_capture.watch) 자기 바를 다시 찾지 않는다.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np

from ..detect.cooking_window import SIGNAL_RATIO, CookingFinder, State

_log = logging.getLogger("mabinogi_addon.cooking")
LOG_EVERY = 30.0  # 신호가 꺼져 있는 동안 이 간격(초)마다 한 줄
MAX_MISS_SHOTS = 3   # 신호 켜짐 + 못 찾음 프레임(실행당)
MAX_OFF_SHOTS = 2    # 신호 꺼짐 판정 프레임(실행당, 30초 간격)


def shot_dir():
    from .. import paths
    return paths.user_data_dir() / "logs" / "cooking-find"


def _registered_rect() -> tuple[int, int, int, int] | None:
    """등록 게임 창(left, top, width, height) 물리 픽셀. 없거나 실패면 None."""
    from ..system.window_capture import registered_game_target
    target = registered_game_target()
    return None if target is None else tuple(int(v) for v in target[2:6])


def _open_camera():
    """공유 라이브 카메라(버프·체력바와 같은 것). 못 쓰면 None(맥·CI·dxcam/mss 모두 실패)."""
    from ..capture.shared_live import _SharedLiveCamera
    return _SharedLiveCamera.acquire()


class CookingAutoFind:
    """tick()을 화면 스레드에서 부르면, 끝난 작업 결과를 돌려주고(없으면 None) 다음 작업을 건다."""

    def __init__(self, registered=_registered_rect, camera=_open_camera) -> None:
        self.finder = CookingFinder()
        self._registered = registered
        self._open_camera = camera
        self._camera = None
        self._camera_failed = False
        self._executor: ThreadPoolExecutor | None = None
        self._future: Future | None = None
        self._local = threading.local()
        self.origin = (0, 0)  # 마지막 작업의 대상 왼쪽 위(물리)
        self.source = ""      # 마지막 작업의 대상·캡처 경로(진단)
        self._last_log = -LOG_EVERY
        self._signal_on: bool | None = None
        self._miss_shots = 0
        self._off_shots = 0
        self._no_target_logged = False

    # ---- 작업 스레드: 캡처 ----
    def _thread_mss(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss
            sct = self._local.sct = mss.mss()
        return sct

    def _live_frame(self):
        """공유 카메라 전체 프레임(주 모니터, BGR). 못 쓰면 None — 한 번 실패하면 이후 mss."""
        if self._camera is None and not self._camera_failed:
            try:
                self._camera = self._open_camera()
            except Exception:  # noqa: BLE001
                self._camera_failed = True
                _log.info("요리창 찾기: 라이브 카메라를 못 써서 mss로 캡처", exc_info=True)
        if self._camera is None:
            return None
        try:
            return self._camera.full_frame()
        except Exception:  # noqa: BLE001
            _log.warning("요리창 찾기: 라이브 프레임 실패", exc_info=True)
            return None

    def _mss_grab(self, left: int, top: int):
        def grab(x, y, w, h):
            try:
                shot = self._thread_mss().grab({"left": left + x, "top": top + y, "width": w, "height": h})
                return np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)[:, :, :3]
            except Exception:  # noqa: BLE001
                _log.debug("요리창 찾기: mss 캡처 실패", exc_info=True)
                return None
        return grab

    @staticmethod
    def _frame_grab(frame, left: int, top: int):
        def grab(x, y, w, h):
            x0, y0 = left + x, top + y
            if x0 < 0 or y0 < 0 or x0 + w > frame.shape[1] or y0 + h > frame.shape[0]:
                return None
            return frame[y0:y0 + h, x0:x0 + w]
        return grab

    def _source(self):
        """(left, top, width, height, grab, 설명) — 대상 사각형과 캡처 함수. 대상이 없으면 None."""
        try:
            rect = self._registered()
            where = "등록 게임 창"
        except Exception:  # noqa: BLE001
            _log.warning("요리창 찾기: 게임 창 조회 실패", exc_info=True)
            rect, where = None, "게임 창 조회 실패"
        frame = self._live_frame()
        if rect is None:
            if frame is not None:
                rect, where = (0, 0, frame.shape[1], frame.shape[0]), "주 모니터(게임 창 미등록)"
            else:
                try:
                    mon = self._thread_mss().monitors[1]
                    rect = (int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"]))
                    where = "주 모니터(게임 창 미등록)"
                except Exception:  # noqa: BLE001
                    _log.warning("요리창 찾기: 모니터 조회 실패", exc_info=True)
                    return None
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            return None
        inside = (frame is not None and left >= 0 and top >= 0
                  and left + width <= frame.shape[1] and top + height <= frame.shape[0])
        if inside:
            return left, top, width, height, self._frame_grab(frame, left, top), f"{where}·라이브"
        return left, top, width, height, self._mss_grab(left, top), f"{where}·mss"

    def _job(self):
        source = self._source()
        if source is None:
            return None
        left, top, width, height, grab, where = source
        state = self.finder.step(grab, width, height)
        where = f"{where} ({left},{top},{width}x{height})"
        self._diagnose(state, where, grab, width, height, time.monotonic())
        return state, (left, top), where

    # ---- 작업 스레드: 진단(로그·실패 프레임) ----
    def _save_shot(self, kind: str, frame) -> str:
        if frame is None:
            return "-"
        from ..image_io import imwrite
        folder = shot_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            return "저장 실패"
        name = f"{time.strftime('%Y%m%d_%H%M%S')}_{kind}{self._miss_shots if kind == 'miss' else self._off_shots}.png"
        return name if imwrite(folder / name, np.ascontiguousarray(frame)) else "저장 실패"

    def _diagnose(self, state: State, where: str, grab, width: int, height: int, now: float) -> None:
        f = self.finder
        on = f.last_ratio is not None and f.last_ratio >= SIGNAL_RATIO
        changed = on != self._signal_on
        self._signal_on = on
        if not on and not changed and now - self._last_log < LOG_EVERY:
            return
        self._last_log = now
        shot = ""
        if on and state.kind != "found" and f.last_frame is not None and self._miss_shots < MAX_MISS_SHOTS:
            self._miss_shots += 1  # 신호는 켜졌는데 못 찾은 프레임
            shot = f" 저장={self._save_shot('miss', f.last_frame)}"
        elif not on and self._off_shots < MAX_OFF_SHOTS and f.last_ratio is not None:
            self._off_shots += 1   # 신호 꺼짐 판정 프레임(띠 자리 확인용) — 30초 간격
            shot = f" 저장={self._save_shot('off', grab(0, 0, width, height))}"
        best = f.last_best
        _log.info("요리창 찾기: %s상태=%s 대상=%s 띠검은비율=%s 신호=%s 전체찾기=%s 최고점수=%s 자리=%s "
                  "못찾음=%d 전체찾기수=%d 캡처실패=%d%s",
                  ("신호 바뀜 " if changed else ""), state.kind, where,
                  "-" if f.last_ratio is None else f"{f.last_ratio:.2f}",
                  "켜짐" if on else "꺼짐", "예" if f.last_full else "아니오",
                  "-" if best is None else f"{best.score:.3f}",
                  "-" if best is None else f"{best.bar[0]},{best.bar[1]}",
                  f.misses, f.full_searches, f.capture_failures, shot)

    def _close_thread_resources(self) -> None:
        sct = getattr(self._local, "sct", None)
        self._local.sct = None
        if sct is not None:
            try:
                sct.close()
            except Exception:  # noqa: BLE001
                _log.debug("mss 닫기 실패", exc_info=True)
        camera, self._camera = self._camera, None
        if camera is not None:
            camera.release()

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
                _log.warning("요리창 찾기 실패(예외)", exc_info=True)
                done = False
            self._future = None
            if done:
                result, self.origin, self.source = done
                self._no_target_logged = False
            elif done is None and not self._no_target_logged:
                self._no_target_logged = True
                _log.info("요리창 찾기: 상태=대상 없음(게임 창·모니터를 못 얻음)")
        if run and self._future is None:
            self._future = self.submit(self._job)
        return result

    def reset(self) -> None:
        self.finder.reset()
        self._signal_on = None

    def release(self) -> None:
        """바를 끄면 라이브 카메라·mss를 놓는다(작업 스레드에서)."""
        if self._executor is not None or self._camera is not None:
            self.submit(self._close_thread_resources)

    def shutdown(self) -> None:
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.submit(self._close_thread_resources)  # 작업 스레드의 자원은 그 스레드에서 닫는다
            executor.shutdown(wait=False, cancel_futures=False)
        self._future = None
