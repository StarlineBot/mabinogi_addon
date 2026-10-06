"""버프 디텍터 (기획서 2.1 / 4.2).

등록 아이콘들을 캡처 영역의 '아이콘 열'(x 고정, 세로 띠)에서 검색한다.
버프가 추가/제거되면 목록이 당겨져 y가 바뀌므로, 위치를 캐시하지 않고
매 프레임 세로 띠 전체를 다시 검색한다. x를 좁혀 성능을 확보한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .icon_matcher import DEFAULT_THRESHOLD, match_icon


@dataclass(frozen=True)
class Detection:
    buff_id: str
    score: float
    y: int  # 영역 기준 아이콘 상단 y (시간 판독 시 이 행을 쓴다)


def detect_buffs(
    region: np.ndarray,
    templates: dict[str, np.ndarray],
    icon_column: tuple[int, int],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Detection]:
    """영역 안에서 등록 아이콘들을 찾아 present인 것만 y 오름차순으로 반환.

    icon_column: 영역 기준 (x0, x1) — 아이콘이 있는 세로 띠. 이 폭 안에서만 검색.
    """
    x0, x1 = icon_column
    strip = region[:, x0:x1]

    detections: list[Detection] = []
    for buff_id, template in templates.items():
        result = match_icon(strip, template)
        if result.present(threshold):
            detections.append(Detection(buff_id, result.score, result.y))

    detections.sort(key=lambda d: d.y)
    return detections
