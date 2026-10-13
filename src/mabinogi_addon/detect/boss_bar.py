"""보스 체력바 영역 자동 찾기 (전체 화면에서 위치 검출).

보스바는 채움 색이 HP 단계별로 바뀌고(보라>파랑>노랑>빨강 …) 보스마다 이름·폭이 달라서
'색'으로는 못 잡는다. 대신 **구조**로 구분한다 — 화면 하단 메뉴바 위에 뜨는,
**하나의 연속된 솔리드 가로 바**(스킬 아이콘 그리드와 달리 내부 세로 경계가 적다)이고
채도로 꽉 차 있다. 자동 찾기는 설정 시 1회만, 보스 첫 노출(고HP) 때 쓰므로 그걸로 충분하다.

판별:
- 넓은 가로 밴드(폭 ≥ 화면폭 18%, 납작: w > h*6), 화면 하단(y > 72%).
- **솔리드**: 내부 세로 경계 밀도가 낮다(스킬 그리드는 아이콘 경계로 높다).
- **꽉 참**: 밴드 내부 채도 채움 비율이 높다(매끈한 배경 바닥 오탐 제거).
여러 개면 가장 넓은 것을 고른다. 없으면 None(→ 호출 측은 "보스바가 노출됐는지 확인" 안내).
"""

from __future__ import annotations

import cv2
import numpy as np

_SAT_MIN = 90
_VAL_MIN = 80
_MIN_W_FRAC = 0.18  # 화면 폭 대비 최소 바 폭
_MIN_H_FRAC = 0.014  # 화면 높이 대비 최소 바 높이
_MAX_H_FRAC = 0.06  # 최대(너무 두꺼운 건 바 아님)
_FLAT_RATIO = 6  # w > h * 이것 (납작한 가로 바)
_BOTTOM_FRAC = 0.72  # 이 아래(하단)에서만
_EDGE_DENSITY_MAX = 0.25  # 내부 세로 경계 밀도 상한(솔리드 바; 그리드는 ↑)
_FILL_MIN = 0.5  # 밴드 내부 채도 채움 하한(바닥 오탐 제거)


def locate_boss_bar(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """전체 화면에서 보스 체력바 영역 (x,y,w,h)를 찾는다(없으면 None).

    색·HP에 의존하지 않고 '연속 솔리드 가로 바' 구조로 찾는다. 보스바가 안 보이면 None.
    """
    if frame is None or frame.size == 0 or frame.shape[0] < 40 or frame.shape[1] < 80:
        return None
    H, W = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    sat = ((hsv[:, :, 1] > _SAT_MIN) & (hsv[:, :, 2] > _VAL_MIN)).astype(np.uint8)
    closed = cv2.morphologyEx(
        sat, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (35, 1))
    )
    n, _, stats, _ = cv2.connectedComponentsWithStats(closed, 8)
    min_w = int(W * _MIN_W_FRAC)
    min_h, max_h = int(H * _MIN_H_FRAC), int(H * _MAX_H_FRAC)
    best: tuple[int, int, int, int] | None = None
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        if not (w >= min_w and min_h <= h <= max_h and w > h * _FLAT_RATIO):
            continue
        if y <= H * _BOTTOM_FRAC:
            continue
        fill = float(sat[y : y + h, x : x + w].mean())
        if fill < _FILL_MIN:  # 바닥 등 꽉 안 찬 밴드 제외
            continue
        gray = cv2.cvtColor(frame[y : y + h, x : x + w], cv2.COLOR_BGR2GRAY)
        edges = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
        if float((edges > 60).mean()) >= _EDGE_DENSITY_MAX:  # 그리드(스킬 줄) 제외
            continue
        if best is None or w > best[2]:
            best = (int(x), int(y), int(w), int(h))
    return best
