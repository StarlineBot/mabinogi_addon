"""실시간 캡처 (Windows, dxcam).

지정 영역만 캡처한다. dxcam은 새 프레임이 없으면 None을 돌려주는데, 그건 "변화 없음"
이므로 호출측에서 직전 상태를 유지하면 된다. Windows 전용이라 import도 지연시킨다.
"""

from __future__ import annotations

import numpy as np

from .base import FrameSource, Region


class LiveCaptureSource(FrameSource):
    def __init__(self, region: Region) -> None:
        import dxcam  # Windows 전용 의존성 (지연 import)

        self._region = region
        # cv2와 색 순서를 맞추려고 BGR로 받는다(FileFrameSource의 imread와 동일).
        self._camera = dxcam.create(output_color="BGR")

    def grab(self) -> np.ndarray | None:
        return self._camera.grab(region=self._region.ltrb)

    def close(self) -> None:
        if getattr(self, "_camera", None) is not None:
            self._camera.release()
            self._camera = None
