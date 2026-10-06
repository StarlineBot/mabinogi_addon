"""유니코드 경로 안전 이미지 로더.

Windows에서 cv2.imread(str(path))는 한글 등 비ASCII 경로를 못 읽고 None을 반환한다
(ANSI 코드페이지 한계). 디버프 아이콘 파일명이 한글이라 이 문제로 템플릿이 안 잡혔다.
Python으로 바이트를 읽어 cv2.imdecode로 디코딩하면 경로 인코딩과 무관하게 동작한다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread(path: Path | str, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    """경로 인코딩과 무관하게 이미지를 읽는다. 실패 시 None."""
    try:
        data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, flags)
