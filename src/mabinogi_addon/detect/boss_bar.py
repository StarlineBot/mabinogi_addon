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


def make_validator():
    """박스가 진짜 보스바인지 검증하는 콜백 — 그 안에서 HP% 판독과 이름 식별이 둘 다
    성공할 때만 True. (테두리 포함·채팅 글자 붙음·아래 바 합쳐짐 등 잘못 잡힌 박스를 거름.)"""
    from .boss_hp_reader import read_percent
    from .boss_name_matcher import identify, load_name_templates

    name_templates = load_name_templates()

    def validate(sub: np.ndarray) -> bool:
        if sub is None or sub.size == 0 or sub.shape[1] < 20:
            return False
        w = sub.shape[1]
        if read_percent(sub) is None:
            return False
        return identify(sub[:, : int(w * 0.60)], name_templates) is not None

    return validate


def locate_boss_bar(
    frame: np.ndarray, validate=None
) -> tuple[int, int, int, int] | None:
    """전체 화면에서 보스 체력바 영역 (x,y,w,h)를 찾는다(없으면 None).

    색·HP에 의존하지 않고 '연속 솔리드 가로 바' 구조로 찾는다. 보스바가 안 보이면 None.
    validate(sub_bgr)->bool 을 주면, 그 박스 안에서 검증(퍼센트·이름 판독)이 통과한 후보만
    채택한다(테두리 포함·채팅 글자 붙음·아래 바 합쳐짐 등 잘못 잡힌 박스를 거른다).
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
    cands: list[tuple[int, int, int, int]] = []
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
        box = _trim_rows(sat, x, y, w, h)  # 위/아래 테두리 등 비채움 행 제거
        if box is not None:
            cands.append(box)
    cands.sort(key=lambda b: -b[2])  # 넓은 것부터
    if validate is not None:
        for bx, by, bw, bh in cands:
            if validate(frame[by : by + bh, bx : bx + bw]):
                return (bx, by, bw, bh)
        return None  # 판독 검증을 통과한 후보가 없음
    return cands[0] if cands else None


def _trim_rows(
    sat: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[int, int, int, int] | None:
    """밴드에서 '채움 행'(그 행의 채도 비율이 충분)만 남도록 위/아래를 다듬는다.

    바 위 테두리나 글자 안티앨리어싱이 컴포넌트에 섞여 높이가 부풀면(예: 36→45px) 퍼센트
    판독이 어긋난다. 채움 비율이 임계 이상인 연속 행 구간으로 좁힌다.
    """
    rows = sat[y : y + h, x : x + w].mean(axis=1)
    filled = rows >= 0.45
    idx = np.flatnonzero(filled)
    if idx.size == 0:
        return (x, y, w, h)
    top, bot = int(idx[0]), int(idx[-1])
    nh = bot - top + 1
    if nh < 4:
        return None
    return (x, y + top, w, nh)
