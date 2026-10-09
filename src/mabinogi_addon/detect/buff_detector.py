"""버프 디텍터 (기획서 2.1 / 4.2).

등록 아이콘들을 캡처 영역의 '아이콘 열'(x 고정, 세로 띠)에서 검색한다.
버프가 추가/제거되면 목록이 당겨져 y가 바뀌므로, 위치를 캐시하지 않고
매 프레임 세로 띠 전체를 다시 검색한다. x를 좁혀 성능을 확보한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .icon_matcher import DEFAULT_THRESHOLD, match_icon


def _gray(img: np.ndarray) -> np.ndarray:
    """BGR이면 그레이스케일로. 이미 1채널이면 그대로."""
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img


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
    # 아이콘 '존재' 판정엔 색이 거의 불필요하고, 그레이스케일 매칭이 BGR 3채널보다
    # ~3배 빠르다(실측상 등록 아이콘은 그레이에서도 ~1.0, 오탐은 <임계로 분리). 매칭을
    # 가볍게 해 더 짧은 주기로 아이콘 생성/소멸을 빠르게 캐치하기 위함.
    strip = _gray(region[:, x0:x1])

    detections: list[Detection] = []
    for buff_id, template in templates.items():
        result = match_icon(strip, _gray(template))
        if result.present(threshold):
            detections.append(Detection(buff_id, result.score, result.y))

    detections.sort(key=lambda d: d.y)
    return detections
