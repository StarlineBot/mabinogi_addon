"""아이콘 템플릿 매칭 (기획서 4.2).

지정 영역(버프 상태창 캡처) 안에서 등록 아이콘을 cv2.matchTemplate +
TM_CCOEFF_NORMED로 검색한다. 밝기·대비의 선형 변화에 강해 반투명·단색 배경에 대응.
행 간격을 하드코딩하지 않고 영역 전체를 2D 검색하므로 그룹 여백에 영향받지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# 실데이터 기준 튜닝: 실제 버프는 1.00, 오탐은 ≤0.67로 명확히 갈림(아이콘 불투명).
# 0.8이면 양쪽에 여유를 두고 분리된다.
DEFAULT_THRESHOLD = 0.8


@dataclass(frozen=True)
class MatchResult:
    score: float  # TM_CCOEFF_NORMED 최고 점수 (-1~1)
    x: int  # 영역 내 매칭 위치(템플릿 좌상단)
    y: int

    def present(self, threshold: float = DEFAULT_THRESHOLD) -> bool:
        return self.score >= threshold


def match_icon(region: np.ndarray, template: np.ndarray) -> MatchResult:
    """region 안에서 template의 최고 매칭 위치·점수. template이 region보다 크면 점수 -1."""
    if (
        template.shape[0] > region.shape[0]
        or template.shape[1] > region.shape[1]
    ):
        return MatchResult(-1.0, 0, 0)
    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _min_v, max_v, _min_l, max_l = cv2.minMaxLoc(result)
    return MatchResult(float(max_v), int(max_l[0]), int(max_l[1]))
