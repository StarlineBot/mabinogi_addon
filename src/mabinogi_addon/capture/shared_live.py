"""공유 라이브 카메라 (Windows, dxcam).

dxcam은 한 모니터(출력)에 카메라 1개만 허용하고, grab()은 새 프레임이 없으면
None을 돌려준다. 버프·디버프처럼 서로 다른 두 영역을 각각 잡으면 한쪽이 프레임을
굶게 된다. 그래서 전체 프레임을 한 번만 잡아(짧은 캐시) 각 영역이 잘라 쓰게 한다.

- _SharedLiveCamera: dxcam 카메라 1개를 참조카운트로 공유. full_frame()은 최대
  max_age마다 한 번만 실제 grab(변화 없으면 직전 프레임 유지)해 두 영역이 같은
  프레임을 쓰게 한다.
- RegionView(FrameSource): 특정 영역을 전체 프레임에서 잘라 돌려준다.

Windows 전용이라 dxcam import는 지연한다(맥/CI에선 create_region_view 미호출).
"""

from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .base import FrameSource, Region

_log = logging.getLogger("mabinogi_addon.capture")

# 전체 프레임을 다시 잡는 최소 간격(초). 두 영역이 한 틱 안에서 같은 프레임을 쓰게 한다.
_MAX_AGE = 0.08


class _SharedLiveCamera:
    _instance: _SharedLiveCamera | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        import dxcam  # Windows 전용 (지연 import)

        t = time.perf_counter()
        self._camera = dxcam.create(output_color="BGR")
        _log.info("dxcam.create %.0fms", (time.perf_counter() - t) * 1000)
        # dxcam.create()는 실패 시 예외가 아니라 None을 돌려준다(멀티모니터·하이브리드
        # GPU 등). 그대로 두면 grab이 영원히 None → '라이브 캡처가 조용히 안 됨'이
        # 된다. 여기서 명시적으로 에러를 내 호출부가 알 수 있게 하고, 진단용으로
        # dxcam이 본 출력 목록을 로그에 남긴다.
        if self._camera is None:
            try:
                info = dxcam.output_info()
            except Exception as exc:  # noqa: BLE001 — 진단 로그용
                info = f"(output_info 실패: {exc})"
            _log.error("dxcam.create() 실패(None 반환). 출력 목록:\n%s", info)
            raise RuntimeError(
                "dxcam 라이브 캡처 카메라를 만들 수 없습니다. "
                "게임을 '테두리 없는 창(전체 창)' 모드로 두거나, 그래픽 드라이버/"
                "모니터 설정을 확인하세요."
            )
        self._frame_lock = threading.Lock()
        self._last_frame: np.ndarray | None = None
        self._last_ts = 0.0
        self._refs = 0

    @classmethod
    def acquire(cls) -> _SharedLiveCamera:
        with cls._lock:
            if cls._instance is None:
                cls._instance = _SharedLiveCamera()
            cls._instance._refs += 1
            return cls._instance

    def release(self) -> None:
        camera = None
        with _SharedLiveCamera._lock:
            self._refs -= 1
            if self._refs <= 0:
                camera = self._camera
                self._camera = None
                _SharedLiveCamera._instance = None
        # dxcam 해제(DXGI)는 느릴 수 있어 데몬 스레드로 → 종료/재시작을 막지 않는다.
        if camera is not None:
            def _rel() -> None:
                t = time.perf_counter()
                camera.release()
                _log.info("dxcam release %.0fms", (time.perf_counter() - t) * 1000)

            threading.Thread(target=_rel, daemon=True).start()

    def full_frame(self) -> np.ndarray | None:
        """전체 프레임. max_age 안에선 캐시 재사용, 새 프레임 없으면 직전 유지."""
        with self._frame_lock:
            now = time.monotonic()
            if self._camera is not None and now - self._last_ts >= _MAX_AGE:
                t = time.perf_counter()
                frame = self._camera.grab()  # 변화 없으면 None
                dt = (time.perf_counter() - t) * 1000
                if dt > 50:  # grab이 오래 걸리면(블로킹 의심) 경고
                    _log.warning("dxcam grab %.0fms (느림)", dt)
                self._last_ts = now
                if frame is not None:
                    self._last_frame = frame
            return self._last_frame


class RegionView(FrameSource):
    """공유 카메라의 전체 프레임에서 지정 영역만 잘라 돌려준다."""

    def __init__(self, region: Region) -> None:
        self._region = region
        self._camera = _SharedLiveCamera.acquire()

    def grab(self) -> np.ndarray | None:
        frame = self._camera.full_frame()
        if frame is None:
            return None
        left, top, right, bottom = self._region.ltrb
        h, w = frame.shape[:2]
        # 화면 경계로 클램프(영역이 화면 밖으로 조금 나가도 안전)
        left, top = max(0, left), max(0, top)
        right, bottom = min(w, right), min(h, bottom)
        if right <= left or bottom <= top:
            return None
        return frame[top:bottom, left:right]

    def close(self) -> None:
        if self._camera is not None:
            self._camera.release()
            self._camera = None
