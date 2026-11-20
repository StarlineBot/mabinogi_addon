"""요리창 자동 찾기(docs/cooking-spec.md 7절, 0.54.0) — Qt 없는 순수 로직.

- 시작 신호(가벼움): 요리창이 뜨면 게임 화면 아래쪽이 검게 가려진다 → 게임 창 높이 80~88% 띠의 검은 픽셀(밝기 < 8)
  비율이 0.7 이상이면 '요리창이 떠 있음'. 측정: 요리 화면 0.82~1.0, 요리창 없는 화면 최고 0.42.
- 찾기: 요리창의 '농도 조절 버튼 줄 + 게이지 바'(기준 그림 tests/data/11image.png의 247×42)를 경계선(Canny 40/120)으로
  만들어 TM_CCOEFF_NORMED. 11-20부터 밝은 반투명 스킨 그림을 더해 두 점수 맵 평균, 기준 0.47(아래 MATCH_MIN).
  UI 크기는 해상도와 무관하게 같아(4K도 바 245px) 배율 탐색 없음.
- 추적(CookingFinder): 1초마다 신호 → 지난 자리 둘레(max(32px, 템플릿 높이))만 대조 → 없으면 전체 다시 찾기.
  신호가 사라지면 '닫힘'(찾은 적 있을 때), 신호는 있는데 두 번 연속 못 찾으면 '손으로'(사용자 결정 11-20), 한 번도 못 찾았으면 '손으로'.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from .. import paths
from ..image_io import imread

cv2.setNumThreads(1)

BAND = (0.80, 0.88)        # 신호 띠(게임 창 높이 비율)
BLACK_LEVEL = 8            # 이보다 어두우면 검은 픽셀
SIGNAL_RATIO = 0.7
MATCH_MIN = 0.47  # 두 기준 그림 점수 맵 평균 기준(11-20 QA): 요리 7장 최저 0.565, 요리창 없는 135장 최고 0.371
BAR_OFFSET = (1, 32)       # 템플릿 왼쪽 위 → 게이지 바(테두리 포함) 왼쪽 위
BAR_SIZE = (245, 10)       # 게이지 바(테두리 포함, 물리 픽셀)
MISSES_TO_CLOSE = 2
_CANNY = (40, 120)


# 기준 그림(둘 다 247×42, 바 = +(1,32) 245×10): 어두운 불투명 스킨(11image) + 밝은 반투명 스킨(스크린샷 2026-11-20 174704 (346,812)).
# 반투명 스킨은 버튼 가운데 줄이 없고 바 테두리가 흐리며 뒤 배경 무늬가 섞여, 한 그림만으로는 0.47~0.52(QA 반려 11-20) →
# 두 그림 각각의 점수 맵을 평균해 최댓값을 쓴다.
TEMPLATE_FILES = ("gauge_row.png", "gauge_row_light.png")


@lru_cache(maxsize=1)
def templates() -> tuple[np.ndarray, ...]:
    """경계선 템플릿들(uint8, 42×247)."""
    out = []
    for name in TEMPLATE_FILES:
        # image_io.imread: cv2.imread는 Windows에서 한글 등 비ASCII 경로(사용자 폴더 아래 exe 풀림 자리)를 못 읽는다(QA 반려 11-19)
        gray = imread(paths.detect_templates_dir() / "cooking" / name, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise FileNotFoundError(f"cooking/{name}")
        out.append(cv2.Canny(gray, *_CANNY))
    return tuple(out)


def template() -> np.ndarray:
    """첫 기준 그림(크기 기준 — 모든 기준 그림은 같은 크기)."""
    return templates()[0]


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


def best(frame: np.ndarray, offset: tuple[int, int] = (0, 0)) -> Match | None:
    """기준과 무관하게 가장 비슷한 자리(진단 로그용). 이미지가 템플릿보다 작으면 None."""
    tpls = templates()
    gray = to_gray(frame)
    if gray.shape[0] < tpls[0].shape[0] or gray.shape[1] < tpls[0].shape[1]:
        return None
    edges = cv2.Canny(gray, *_CANNY)
    result = cv2.matchTemplate(edges, tpls[0], cv2.TM_CCOEFF_NORMED)
    for tpl in tpls[1:]:
        result += cv2.matchTemplate(edges, tpl, cv2.TM_CCOEFF_NORMED)
    result /= len(tpls)
    _, score, _, (x, y) = cv2.minMaxLoc(result)
    if not np.isfinite(score):
        return None
    return Match((offset[0] + x + BAR_OFFSET[0], offset[1] + y + BAR_OFFSET[1], *BAR_SIZE), float(score))


def locate(frame: np.ndarray, offset: tuple[int, int] = (0, 0)) -> Match | None:
    """이미지 안에서 요리창 게이지 줄을 찾는다(기준 미만이면 None)."""
    match = best(frame, offset)
    return match if match is not None and match.score >= MATCH_MIN else None


@dataclass(frozen=True)
class State:
    """found: 바 자리(게임 창 기준 x, y, w, h) / closed: 찾은 적 있고 신호가 사라짐 = 요리창 꺼짐(숨김) /
    manual: 손으로 맞추기 — 한 번도 못 찾았거나, 신호는 있는데 2회 연속 못 알아봄(사용자 결정 11-20)."""
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
        # 진단(마지막 step): 띠 검은 비율(None = 띠 캡처 실패), 가장 비슷한 자리·점수, 캡처 실패 횟수
        self.last_ratio: float | None = None
        self.last_best: Match | None = None
        self.last_full = False                    # 이번 step에서 전체 찾기를 했는지
        self.last_frame: np.ndarray | None = None  # 이번 step의 전체 프레임(전체 찾기 때만 — 실패 프레임 저장용)
        self.capture_failures = 0

    def _signal_gone(self) -> State:
        """신호 사라짐(띠 캡처 실패 포함): 찾은 적 있으면 요리창 꺼짐(closed), 아니면 손으로(manual)."""
        self.bar = None
        self.state = State("closed" if self.seen else "manual")
        return self.state

    def _not_recognized(self) -> State:
        """신호는 있는데 2회 연속 못 알아봄: 요리창은 떠 있으니 숨기지 않고 손으로 맞춘 자리로(seen과 무관)."""
        self.bar = None
        self.state = State("manual")
        return self.state

    def _find(self, image, offset) -> Match | None:
        if image is None:
            return None
        candidate = best(image, offset)
        if candidate is not None and (self.last_best is None or candidate.score > self.last_best.score):
            self.last_best = candidate
        return candidate if candidate is not None and candidate.score >= MATCH_MIN else None

    def step(self, grab, width: int, height: int) -> State:
        band = grab(*band_rect(width, height))
        self.last_ratio = None if band is None else black_ratio(band)
        self.last_best = None
        self.last_full = False
        self.last_frame = None
        if band is None:
            self.capture_failures += 1
        if band is None or self.last_ratio < SIGNAL_RATIO:
            self.misses = 0
            return self._signal_gone()
        match = None
        if self.bar is not None:  # 지난 자리 둘레만
            th, tw = template().shape
            margin = max(32, th)
            tx, ty = self.bar[0] - BAR_OFFSET[0], self.bar[1] - BAR_OFFSET[1]
            x0, y0 = max(0, tx - margin), max(0, ty - margin)
            x1, y1 = min(width, tx + tw + margin), min(height, ty + th + margin)
            roi = grab(x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None
            match = self._find(roi, (x0, y0))
        if match is None:  # 처음이거나 창을 옮김 → 전체
            self.full_searches += 1
            self.last_full = True
            frame = self.last_frame = grab(0, 0, width, height)
            if frame is None:
                self.capture_failures += 1
            match = self._find(frame, (0, 0))
        if match is None:
            self.misses += 1
            if self.misses >= MISSES_TO_CLOSE:
                return self._not_recognized()
            return self.state  # 한 번 못 찾음은 지난 상태 유지
        self.misses = 0
        self.seen = True
        self.bar = match.bar
        self.state = State("found", match.bar)
        return self.state
