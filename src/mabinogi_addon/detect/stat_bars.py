"""하단 체력/마나/스태미나 바 판독.

게임 하단 좌측의 세 가로 바(위→아래로 HP·MP·스태미나)를 감싸는 영역을 받아, 각 바의
**채움 비율(0~1)**을 돌려준다. (미러링이 아니라 값만 읽어 우리 오버레이로 새로 그린다.)

원리 — 바 '채움'과 '소모(빈 구간)'는 **같은 색조**지만 **밝기(V)가 다르다**(채움은 밝고
소모는 어둡다). 그래서 색조만으론 못 가르고, 각 바 띠에서 '그 색조에 해당하며 밝은'
픽셀이 가로로 어디까지 이어지는지(밝기 절벽)로 비율을 잰다. 숫자가 바 위에 겹쳐도,
숫자는 색조가 달라(흰색) 제외되므로 비율 측정에는 영향이 적다.

세 바는 게임에서 항상 HP→MP→스태미나 순으로 쌓이므로, 영역에서 찾은 띠를 **위에서
아래 순서**로 그 이름에 매핑한다(색조로 가르지 않아 색이 달라도 안정적). 영역 아래의
파란 '경험치(lv) 바'는 포함하면 네 번째 띠로 잡혀 매핑이 어긋나니, 영역 지정 시 제외한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

STAT_IDS = ("hp", "mp", "sta")  # 위 → 아래 순서

# 띠(바) 판정: '유채색(S 높음) + 어둡지 않음(V>_V_MIN)' 픽셀이 한 행에서 이 비율 이상이면
# '바다운 행'. 그런 행이 세로로 _MIN_ROWS개 이어지면 하나의 바 띠로 본다.
_SAT_MIN = 70
_V_MIN = 45
_ROW_RATIO = 0.30
_MIN_ROWS = 3
# 채움/소모 구분: 그 바 색조(±_HUE_TOL)이며 밝기 V가 _FILL_V 이상이면 '채움'.
_HUE_TOL = 16
_FILL_V = 120


@dataclass
class StatReading:
    stat_id: str  # "hp" | "mp" | "sta"
    ratio: float  # 0.0 ~ 1.0 채움 비율
    hue: int  # 바 색조(그리기용 참고)


def _bands(region: np.ndarray) -> list[tuple[int, int]]:
    """영역에서 '바다운 행'이 세로로 이어지는 구간(띠)들을 위에서 아래 순으로."""
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    barrow = ((s > _SAT_MIN) & (v > _V_MIN)).mean(axis=1) > _ROW_RATIO
    bands: list[tuple[int, int]] = []
    y = 0
    h = region.shape[0]
    while y < h:
        if barrow[y]:
            y0 = y
            while y < h and barrow[y]:
                y += 1
            if y - y0 >= _MIN_ROWS:
                bands.append((y0, y))
        else:
            y += 1
    return bands


def _ratio(region: np.ndarray, r0: int, r1: int) -> tuple[float, int]:
    """한 띠(r0:r1)의 채움 비율과 대표 색조."""
    band = region[r0:r1]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    bh, bs, bv = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2]
    colored = (bs > _SAT_MIN) & (bv > _V_MIN)
    if not colored.any():
        return 0.0, -1
    hue = int(np.median(bh[colored]))
    # 그 색조에 해당하는(채움/소모 둘 다) 픽셀 → 바의 가로 범위.
    huematch = (np.abs(bh - hue) <= _HUE_TOL) & (bs > _SAT_MIN - 10)
    cols = np.where(huematch.any(axis=0))[0]
    if cols.size == 0:
        return 0.0, hue
    left, right = int(cols.min()), int(cols.max())
    span = right - left + 1
    if span <= 1:
        return 0.0, hue
    # 각 열에서 '그 색조 + 밝음' 픽셀의 최대 V → 채움 열 판정(소모 구간은 어두워 탈락).
    colmax = np.where(huematch, bv, 0).max(axis=0)
    filled = np.where(colmax >= _FILL_V)[0]
    if filled.size == 0:
        return 0.0, hue
    fill_right = int(filled.max())
    ratio = (fill_right - left + 1) / span
    return float(max(0.0, min(1.0, ratio))), hue


def read_stat_bars(region: np.ndarray) -> list[StatReading]:
    """영역(BGR)에서 위→아래 순으로 최대 3개 바를 읽어 [HP, MP, STA] 순 반환.

    띠가 3개 미만이면 찾은 수만큼(순서대로 hp, mp, sta) 돌려준다 — 영역이 덜 맞은 것.
    """
    if region is None or region.shape[0] < 6 or region.shape[1] < 20:
        return []
    bands = _bands(region)[:3]
    out: list[StatReading] = []
    for i, (r0, r1) in enumerate(bands):
        ratio, hue = _ratio(region, r0, r1)
        out.append(StatReading(STAT_IDS[i], ratio, hue))
    return out
