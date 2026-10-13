"""자동 찾기용 전체 화면 1회 캡처 헬퍼 (mss).

자동 찾기는 '영역이 아직 없을 때' 화면 전체를 한 번 떠서 검출기에 넘긴다. 주 모니터를
캡처하고, 검출 좌표를 전역 좌표로 바꿀 오프셋(left, top)을 함께 돌려준다.
"""

from __future__ import annotations

import numpy as np

_sct = None


def grab_primary() -> tuple[np.ndarray | None, int, int]:
    """주 모니터를 BGR로 캡처하고 (이미지, left, top)을 반환. 실패 시 (None, 0, 0)."""
    global _sct
    try:
        if _sct is None:
            import mss

            _sct = mss.mss()
        mon = _sct.monitors[1]  # 주 모니터
        shot = _sct.grab(mon)
        img = np.frombuffer(shot.bgra, np.uint8).reshape(shot.height, shot.width, 4)
        return np.ascontiguousarray(img[:, :, :3]), int(mon["left"]), int(mon["top"])
    except Exception:  # noqa: BLE001 — 캡처 실패 시 호출 측이 안내
        return None, 0, 0
