"""진단용 캡처 (문제 신고 보조).

저장된 추적 영역(버프/디버프/투아림)을 '지금' 그대로 캡처해 PNG로 저장한다.
해상도·게임 UI 배율이 다른 사용자의 시간/% 판독 오류를 재현·확정하려면, 앱이 실제로
어떤 픽셀을 읽는지 봐야 한다. mss로 물리픽셀을 잡아(DPI 변환 포함) 저장만 한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np

from .. import config, image_io, paths
from .dpi import to_physical


def _grab_physical(region: dict) -> np.ndarray | None:
    """저장된 논리좌표 영역을 물리픽셀로 변환해 mss로 캡처(BGR). 실패 시 None."""
    px, py, pw, ph = to_physical(region)
    if pw < 1 or ph < 1:
        return None
    try:
        import mss

        with mss.mss() as sct:
            shot = sct.grab({"left": px, "top": py, "width": pw, "height": ph})
        return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
            shot.height, shot.width, 4
        )[:, :, :3]
    except Exception:  # noqa: BLE001 — 캡처 불가 환경이면 조용히 건너뜀
        return None


def save_diagnostic() -> tuple[Path, list[str]]:
    """설정된 영역들을 캡처해 debug 폴더에 저장. (폴더, 저장된 파일명들) 반환."""
    out = paths.user_data_dir() / "debug"
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 — 파일명용 로컬시간
    saved: list[str] = []

    # 버프·디버프: config의 캡처 영역.
    for name in ("buffTracker", "debuffTracker"):
        region = config.load_capture_region(name)
        if not region:
            continue
        frame = _grab_physical(region)
        if frame is None:
            continue
        fname = f"{name}_{ts}.png"
        if image_io.imwrite(out / fname, frame):
            saved.append(fname)

    # 투아림: 별도 저장 구조(box).
    box = config.load_tuarim().get("box")
    if box:
        frame = _grab_physical(box)
        if frame is not None:
            fname = f"tuarim_{ts}.png"
            if image_io.imwrite(out / fname, frame):
                saved.append(fname)

    return out, saved
