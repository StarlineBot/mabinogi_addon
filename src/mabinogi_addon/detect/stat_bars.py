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
# 색조 전환 분리: 바들이 '어두운 간격 없이 붙어' 있을 때(간격만으론 못 가름), 행 대표
# 색조가 현재 바 색조에서 이 값 넘게 바뀌면 새 바로 본다. 인접 바 색조 차(분홍↔파랑 ≈49,
# 파랑↔노랑 ≈91, 분홍↔노랑 ≈40)보다 충분히 작고, 한 바 내부 색조 흔들림(±5)보다 크다.
_HUE_SPLIT = 20
# 채움/소모 구분: 그 바 색조(±_HUE_TOL)이며 밝기 V가 _FILL_V 이상이면 '채움'.
_HUE_TOL = 16
_FILL_V = 120
# 꽉 참 스냅: 오른쪽 소모(어두운) 구간이 이 px(또는 폭 비율) 이하면 100%로 본다.
# (바 오른쪽 끝 둥근 캡·안티앨리어싱으로 꽉 찬 바가 99%로 읽히던 것 방지)
_FULL_SNAP_PX = 2
_FULL_SNAP_RATIO = 0.02


@dataclass
class StatReading:
    stat_id: str  # "hp" | "mp" | "sta"
    ratio: float  # 0.0 ~ 1.0 채움 비율
    hue: int  # 바 색조(그리기용 참고)


def _hue_dist(a: int, b: int) -> int:
    """색조(0~180) 원형 거리."""
    d = abs(a - b) % 180
    return min(d, 180 - d)


def _bands(region: np.ndarray) -> list[tuple[int, int]]:
    """영역에서 바 띠 구간들을 위에서 아래 순으로.

    바 경계는 둘 중 하나로 나눈다: (1) 어두운 간격 행(바다운 행이 끊김), 또는 (2) **색조
    전환**(간격 없이 붙은 바라도 위 바와 색이 달라지면 새 바). 생/마/스 3바가 간격 없이
    맞붙어 있으면 (1)만으론 한 덩어리로 병합돼 1개만 읽히던 문제를 (2)로 해결한다.
    매핑은 색조 '값'이 아니라 '전환'만 쓰므로 위→아래 순서 매핑은 그대로다(색 무관).
    """
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    colored = (s > _SAT_MIN) & (v > _V_MIN)
    barrow = colored.mean(axis=1) > _ROW_RATIO
    h = region.shape[0]
    bands: list[tuple[int, int]] = []
    start: int | None = None
    rep = -1  # 현재 바의 대표 색조
    for y in range(h):
        row_hue = int(np.median(hue[y][colored[y]])) if (barrow[y] and colored[y].any()) else -1
        if row_hue < 0:  # 어두운/무채색 행 → 바 끊김
            if start is not None and y - start >= _MIN_ROWS:
                bands.append((start, y))
            start, rep = None, -1
        elif start is None:  # 새 바 시작
            start, rep = y, row_hue
        elif _hue_dist(row_hue, rep) > _HUE_SPLIT:  # 색조 전환 → 붙은 새 바
            if y - start >= _MIN_ROWS:
                bands.append((start, y))
            start, rep = y, row_hue
    if start is not None and h - start >= _MIN_ROWS:
        bands.append((start, h))
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
    # 오른쪽 '소모(어두운) 구간'이 거의 없으면 꽉 참(100%)으로 스냅한다. 바 오른쪽 끝의
    # 둥근 캡·안티앨리어싱 때문에 마지막 1~2px가 덜 밝게 잡혀, 꽉 찬 바가 99%로 읽히던
    # 것을 막는다(_FULL_SNAP_PX, 또는 폭의 _FULL_SNAP_RATIO 중 큰 값 이내면 100%).
    depleted = right - fill_right
    if depleted <= max(_FULL_SNAP_PX, int(span * _FULL_SNAP_RATIO)):
        return 1.0, hue
    ratio = (fill_right - left + 1) / span
    return float(max(0.0, min(1.0, ratio))), hue


# ---- 체력바 영역 자동 찾기 (전체 화면에서 위치 검출) ----
# 체력바는 사용자가 옮길 수 있고 UI 배율에 따라 크기가 변하므로 고정 좌표를 안 쓴다.
# 색(마젠타 HP / 파랑 MP / 노랑 STA) + 기하(가로로 긴 바가 세로로 근접 스택)로 찾는다.
# 바 위에 current/max 숫자가 겹쳐 색이 조각나므로, 가로 모폴로지 클로즈로 이어붙인 뒤 찾는다.
# 보통 꽉 차 있는 MP(파랑)·STA(노랑) 쌍을 앵커로 잡고 HP는 한 피치 위로 유도(HP가 비어도 OK).
_LOC_HUE = {"hp": (150, 172), "mp": (98, 118), "sta": (16, 34)}  # OpenCV H(0~180)
_LOC_SAT_MIN = 90
_LOC_VAL_MIN = 90


def _color_bars(
    hsv: np.ndarray, lo: int, hi: int, min_w: int, close_w: int, max_h: int
) -> list[tuple[int, int, int, int]]:
    """주어진 색조대의 '가로로 긴 바' 블롭들(x,y,w,h). 숫자로 끊긴 색은 가로로 이어붙인다."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (h >= lo) & (h <= hi) & (s > _LOC_SAT_MIN) & (v > _LOC_VAL_MIN)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_w, 1))
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, hh, _ = stats[i]
        if w >= min_w and 2 <= hh <= max_h and w > hh * 1.8:
            out.append((int(x), int(y), int(w), int(hh)))
    return out


def locate_stat_bars(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """전체 화면에서 체력바(생/마/스 3색 스택) 영역을 찾아 (x,y,w,h)로 반환(없으면 None).

    여러 후보가 있으면 화면 **맨 아래** 스택을 고른다(게임 원본 바는 하단 메뉴바에 붙어
    있다; 앱이 띄운 오버레이는 게임 창 캡처엔 안 잡히지만, 전체 데스크톱 캡처 등에서 섞여도
    맨 아래가 원본이다). 바가 안 보이면(메뉴바 최소화 등) None → 호출 측은 수동 지정/안내로 폴백.
    """
    if frame is None or frame.size == 0 or frame.shape[0] < 20 or frame.shape[1] < 40:
        return None
    H, W = frame.shape[:2]
    min_w = max(12, int(W * 0.012))
    close_w = max(8, int(W * 0.012))
    max_h = max(14, int(H * 0.03))
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mps = _color_bars(hsv, *_LOC_HUE["mp"], min_w, close_w, max_h)
    stas = _color_bars(hsv, *_LOC_HUE["sta"], min_w, close_w, max_h)
    best: tuple[int, int, int, int] | None = None
    for bx, by, bw, bh in mps:  # MP(파랑) 위
        for cx, cy, cw, ch in stas:  # STA(노랑) 아래
            gap = cy - by
            if abs(bx - cx) > max(20, int(W * 0.01)) or not (0 < gap < max_h + 20):
                continue
            x = min(bx, cx)
            top = max(0, by - gap)  # HP는 MP 한 피치 위
            w = max(bx + bw, cx + cw) - x
            box = (x, top, w, cy + ch - top)
            if best is None or box[1] > best[1]:  # 더 아래(맨 아래=원본)
                best = box
    if best is None:
        return None
    # 검증: 그 박스에서 실제로 3개 바를 읽어야 진짜 체력바(디버프 아이콘 줄 오탐 제거).
    bx, by, bw, bh = best
    if len(read_stat_bars(frame[by : by + bh, bx : bx + bw])) < 3:
        return None
    return best


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
