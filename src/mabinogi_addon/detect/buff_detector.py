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


# 4K(0.33.0 QA): 4K 화면의 버프 아이콘은 미세하게 흐려 실제 버프 점수가 0.83~0.87(2560·창·1080은 1.0)로 기준 0.8에 붙는다.
# 기준을 낮추면 비슷한 아이콘(마기그래프·마법 공격력 강화/증가 등 0.70~0.77)이 '있음'이 되므로 기준은 그대로 두고
#  ① 첫 검출 구제: 점수가 기준 바로 아래(RESCUE_MIN~기준)면 양쪽을 살짝 흐려 다시 비교해 RESCUE_BLUR 이상일 때만 인정
#    (tests/data: 4K 123333 행진곡 0.786→0.912 / 비슷한 아이콘 최고 0.771·0.758 → 원 점수에서 탈락)
#  ② 유지 이력: 직전 프레임에 있던 버프는 같은 줄(±HOLD_ROWS)에서 HOLD_THRESHOLD 이상이면 계속 '있음'
#    (점수가 0.8 근처에서 흔들려 '있음→3초 없음'이 반복 → 사라짐 경고가 계속 울리던 것. 디버프 0.68/0.58 이력과 같은 방식)
RESCUE_MIN = 0.78
RESCUE_BLUR = 0.9
HOLD_THRESHOLD = 0.75
HOLD_ROWS = 3


def _soft(img: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(img, (3, 3), 0.6)


def detect_buffs(
    region: np.ndarray,
    templates: dict[str, np.ndarray],
    icon_column: tuple[int, int],
    threshold: float = DEFAULT_THRESHOLD,
    held: dict[str, int] | None = None,
) -> list[Detection]:
    """영역 안에서 등록 아이콘들을 찾아 present인 것만 y 오름차순으로 반환.

    icon_column: 영역 기준 (x0, x1) — 아이콘이 있는 세로 띠. 이 폭 안에서만 검색.
    held: 직전 프레임에 있던 버프 {id: 아이콘 y} — 그 줄에서는 유지 이력 기준(HOLD_THRESHOLD)으로 본다.
    """
    x0, x1 = icon_column
    # 아이콘 '존재' 판정엔 색이 거의 불필요하고, 그레이스케일 매칭이 BGR 3채널보다
    # ~3배 빠르다(실측상 등록 아이콘은 그레이에서도 ~1.0, 오탐은 <임계로 분리). 매칭을
    # 가볍게 해 더 짧은 주기로 아이콘 생성/소멸을 빠르게 캐치하기 위함.
    strip = _gray(region[:, x0:x1])
    soft_strip = None

    detections: list[Detection] = []
    for buff_id, template in templates.items():
        t = _gray(template)
        if t.shape[0] > strip.shape[0] or t.shape[1] > strip.shape[1]:
            continue
        scores = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED)
        _lo, score, _lo_at, at = cv2.minMaxLoc(scores)
        y = int(at[1])
        if score >= threshold:
            detections.append(Detection(buff_id, float(score), y))
            continue
        if score >= RESCUE_MIN:
            if soft_strip is None:
                soft_strip = _soft(strip)
            window = soft_strip[y:y + t.shape[0], at[0]:at[0] + t.shape[1]]
            if window.shape == t.shape and match_icon(window, _soft(t)).score >= RESCUE_BLUR:
                detections.append(Detection(buff_id, float(score), y))
                continue
        if held and buff_id in held:
            hy = held[buff_id]
            band = scores[max(0, hy - HOLD_ROWS):hy + HOLD_ROWS + 1]
            if band.size:
                _lo, kept, _lo_at, kept_at = cv2.minMaxLoc(band)
                if kept >= HOLD_THRESHOLD:
                    detections.append(Detection(buff_id, float(kept), max(0, hy - HOLD_ROWS) + int(kept_at[1])))

    detections.sort(key=lambda d: d.y)
    return detections
