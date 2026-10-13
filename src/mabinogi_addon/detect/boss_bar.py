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
# 이름 글자(흰색) 판정: 채도 낮고 밝은 픽셀. 바 채움은 고채도라 제외된다.
_NAME_SAT_MAX = 90
_NAME_VAL_MIN = 170
_NAME_COV_MIN = 0.012  # 박스 왼쪽 60%에서 흰 글자 최소 비율(실제 보스 ≥0.027, 여유 둠)


def _has_name_text(sub: np.ndarray) -> bool:
    """보스바 박스 왼쪽에 이름 글자(흰 텍스트)가 있는지 — '누구'인지는 보지 않는다."""
    w = sub.shape[1]
    left = sub[:, : int(w * 0.60)]
    hsv = cv2.cvtColor(left, cv2.COLOR_BGR2HSV)
    glyph = (hsv[:, :, 1] < _NAME_SAT_MAX) & (hsv[:, :, 2] > _NAME_VAL_MIN)
    return float(glyph.mean()) >= _NAME_COV_MIN


def make_validator():
    """박스가 진짜 보스바인지 검증하는 콜백 — HP% 판독이 되고(오른쪽에 'XXX.XX%'),
    왼쪽에 **이름 글자가 있을 때**만 True. (지난 커밋은 등록된 5개 보스만 식별(identify)해
    통과시켜, 글라스 기브넨 등 미등록 보스에선 자동 찾기가 안 됐다. 디버프 트래커는 모든
    보스에서 써야 하므로, '누구인지'가 아니라 '이름 글자 + %가 있는 바'인지로 바꾼다.)

    이걸로 거르는 것: 펠롬 2단 바 등 % 판독 실패(read_percent None), 글자 없는 솔리드 밴드.
    """
    from .boss_hp_reader import read_percent

    def validate(sub: np.ndarray) -> bool:
        if sub is None or sub.size == 0 or sub.shape[1] < 20:
            return False
        if read_percent(sub) is None:
            return False
        return _has_name_text(sub)

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
            box = _trim_cols(sat, *box)  # 좌/우 비채움 열 제거(채팅 글자 붙음 등)
        if box is not None:
            cands.append(_normalize_height(box, H))  # 높이 정규화(세로 중심 유지)
    cands.sort(key=lambda b: -b[2])  # 넓은 것부터
    if validate is not None:
        for bx, by, bw, bh in cands:
            if validate(frame[by : by + bh, bx : bx + bw]):
                return (bx, by, bw, bh)
        return None  # 판독 검증을 통과한 후보가 없음
    return cands[0] if cands else None


# 보스바 높이는 보스마다 다르지만(레넨 37px, 글라스 기브넨 45px) **세로 중심과 이름·% 글자
# 크기·위치는 같다**. read_percent는 박스 높이(h/36)로 글자 크기를 스케일하므로, 높이가 큰
# 박스를 '공유 보스바 영역'에 저장하면 **다른 보스 HP가 1/10로 읽혀** 패턴 알림이 오작동한다.
# 그래서 찾은 바의 세로 중심만 쓰고 높이는 고정 비율로 정규화한다. (기준 2560×1440 → 37px.
# 비율이라 4K도 비례하나, 4K 보스 스샷이 없어 미검증 — 확보 시 확인할 것.)
_HEIGHT_FRAC = 0.0257


def _normalize_height(
    box: tuple[int, int, int, int], H: int
) -> tuple[int, int, int, int]:
    """박스의 세로 중심은 유지하고 높이를 고정 비율(H×_HEIGHT_FRAC)로 맞춘다. x·w는 그대로."""
    x, y, w, h = box
    cy = y + h / 2
    nh = round(H * _HEIGHT_FRAC)
    ny = round(cy - nh / 2)
    ny = max(0, min(ny, H - nh))
    return (int(x), int(ny), int(w), int(nh))


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
    # 맨 위 연속 채움 구간만 남긴다. 보스 HP바 밑에 별도 바(예: 펠롬의 '어둠의 에르그')가
    # 붙어 한 컴포넌트로 잡히면, 둘 사이 얇은 빈 행(채움 급감)에서 끊어 위=보스 HP바만 취한다.
    # 정상 단일 바는 중간 글자 구간도 ≥0.45라 끊기지 않는다(한 덩어리 그대로).
    top = int(idx[0])
    bot = top
    while bot + 1 < h and filled[bot + 1]:
        bot += 1
    nh = bot - top + 1
    if nh < 4:
        return None
    return (x, y + top, w, nh)


def _trim_cols(
    sat: np.ndarray, x: int, y: int, w: int, h: int
) -> tuple[int, int, int, int] | None:
    """밴드에서 '채움 열'(그 열의 채도 비율이 충분)만 남도록 좌/우를 다듬는다.

    morphology close가 바 왼쪽 채팅 글자를 바에 가로로 이어붙이면 박스가 왼쪽으로
    과하게 늘어난다(예: x=890 폭 649, 실제 바 x≈1018 폭 521). 실제 바 열은 채움 비율이
    높고(이름·숫자가 겹쳐도 뒤 채움이 남아 ≥0.6), 채팅/배경 열은 낮다. 채움 비율이 임계
    이상인 첫/마지막 열로 좁힌다. (실제 바는 첫 열부터 채워져 트림이 거의 없다.)
    """
    cols = sat[y : y + h, x : x + w].mean(axis=0)
    filled = np.flatnonzero(cols >= 0.6)
    if filled.size == 0:
        return (x, y, w, h)
    left, right = int(filled[0]), int(filled[-1])
    nw = right - left + 1
    if nw < max(20, int(w * 0.4)):  # 너무 많이 잘리면(진짜 바가 아님) 원본 유지
        return (x, y, w, h)
    # 이름·숫자 글자가 겹쳐도 그 뒤 채움이 남아 바 본체 열은 ≥0.6으로 유지된다. 바 바깥
    # 채팅/배경 열은 채움이 낮아 잘린다. (모폴로지로 바에 바짝 붙어 이어진 몇 px 채팅은
    # 남을 수 있으나, 큰 과잉 포함은 제거된다 — 예: x890 폭649 → x1000 폭539.)
    return (x + left, y, nw, h)
