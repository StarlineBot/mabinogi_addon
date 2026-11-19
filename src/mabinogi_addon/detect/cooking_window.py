"""요리창 자동 찾기(docs/cooking-spec.md 7절, 0.54.0) — Qt 없는 순수 로직.

- 시작 신호(가벼움): 요리창이 뜨면 게임 화면 아래쪽이 검게 가려진다 → 게임 창 높이 80~88% 띠의 검은 픽셀(밝기 < 8)
  비율이 0.7 이상이면 '요리창이 떠 있음'. 측정: 요리 화면 0.82~1.0, 요리창 없는 화면 최고 0.42.
- 찾기: 요리창의 '농도 조절 버튼 줄 + 게이지 바'(기준 그림 tests/data/11image.png의 247×42)를 경계선(Canny 40/120)으로
  만들어 TM_CCOEFF_NORMED. 기준 0.6 — tests/data 요리 화면 5장 0.765~0.860, 요리창 없는 화면 136장 최고 0.496(11-19 측정).
  UI 크기는 해상도와 무관하게 같아(4K도 바 245px) 배율 탐색 없음.
- 추적(CookingFinder): 1초마다 신호 → 지난 자리 둘레(max(32px, 템플릿 높이))만 대조 → 없으면 전체 다시 찾기.
  신호가 사라지거나 두 번 연속 못 찾으면 '닫힘'. 한 번도 못 찾았으면 '손으로'(0.53.0 손으로 맞추기 대체).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from .. import paths

cv2.setNumThreads(1)

BAND = (0.80, 0.88)        # 신호 띠(게임 창 높이 비율)
BLACK_LEVEL = 8            # 이보다 어두우면 검은 픽셀
SIGNAL_RATIO = 0.7
MATCH_MIN = 0.6
BAR_OFFSET = (1, 32)       # 템플릿 왼쪽 위 → 게이지 바(테두리 포함) 왼쪽 위
BAR_SIZE = (245, 10)       # 게이지 바(테두리 포함, 물리 픽셀)
MISSES_TO_CLOSE = 2
_CANNY = (40, 120)


@lru_cache(maxsize=1)
def template() -> np.ndarray:
    """경계선 템플릿(uint8, 42×247)."""
    gray = cv2.imread(str(paths.detect_templates_dir() / "cooking" / "gauge_row.png"), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError("cooking/gauge_row.png")
    return cv2.Canny(gray, *_CANNY)


def to_gray(frame: np.ndarray) -> np.ndarray:
    if frame.ndim == 2:
        return frame
    return cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY)


def band_rect(width: int, height: int) -> tuple[int, int, int, int]:
    """신호 띠(x, y, w, h) — 게임 창 기준."""
    y0, y1 = int(height * BAND[0]), int(height * BAND[1])
    return 0, y0, width, max(1, y1 - y0)


def black_ratio(band: np.ndarray, step: int = 4) -> float:
    """띠의 검은 픽셀 비율(줄여 읽기 — step 간격)."""
    gray = to_gray(band)[::step, ::step]
    return float((gray < BLACK_LEVEL).mean()) if gray.size else 0.0


def signal(band: np.ndarray) -> bool:
    return black_ratio(band) >= SIGNAL_RATIO


@dataclass(frozen=True)
class Match:
    bar: tuple[int, int, int, int]   # 게이지 바(x, y, w, h) — 넘긴 이미지 기준(+offset)
    score: float


def locate(frame: np.ndarray, offset: tuple[int, int] = (0, 0)) -> Match | None:
    """이미지 안에서 요리창 게이지 줄을 찾는다(기준 미만이면 None)."""
    tpl = template()
    gray = to_gray(frame)
    if gray.shape[0] < tpl.shape[0] or gray.shape[1] < tpl.shape[1]:
        return None
    result = cv2.matchTemplate(cv2.Canny(gray, *_CANNY), tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(result)
    if not np.isfinite(score) or score < MATCH_MIN:
        return None
    return Match((offset[0] + x + BAR_OFFSET[0], offset[1] + y + BAR_OFFSET[1], *BAR_SIZE), float(score))


@dataclass(frozen=True)
class State:
    """found: 바 자리(게임 창 기준 x, y, w, h) / closed: 요리창 꺼짐(숨김) / manual: 한 번도 못 찾음(손으로 맞추기)."""
    kind: str
    bar: tuple[int, int, int, int] | None = None


class CookingFinder:
    """1초마다 step() — grab(x, y, w, h)는 게임 창 기준 사각형을 BGR/회색 이미지로(실패면 None)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.bar: tuple[int, int, int, int] | None = None
        self.seen = False
        self.misses = 0
        self.full_searches = 0
        self.state = State("manual")

    def _lost(self) -> State:
        self.bar = None
        self.state = State("closed" if self.seen else "manual")
        return self.state

    def step(self, grab, width: int, height: int) -> State:
        band = grab(*band_rect(width, height))
        if band is None or not signal(band):
            self.misses = 0
            return self._lost()
        match = None
        if self.bar is not None:  # 지난 자리 둘레만
            th, tw = template().shape
            margin = max(32, th)
            tx, ty = self.bar[0] - BAR_OFFSET[0], self.bar[1] - BAR_OFFSET[1]
            x0, y0 = max(0, tx - margin), max(0, ty - margin)
            x1, y1 = min(width, tx + tw + margin), min(height, ty + th + margin)
            roi = grab(x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None
            match = locate(roi, (x0, y0)) if roi is not None else None
        if match is None:  # 처음이거나 창을 옮김 → 전체
            self.full_searches += 1
            frame = grab(0, 0, width, height)
            match = locate(frame) if frame is not None else None
        if match is None:
            self.misses += 1
            if self.misses >= MISSES_TO_CLOSE:
                return self._lost()
            return self.state  # 한 번 못 찾음은 지난 상태 유지
        self.misses = 0
        self.seen = True
        self.bar = match.bar
        self.state = State("found", match.bar)
        return self.state
