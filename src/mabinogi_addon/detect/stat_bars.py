"""하단 체력/마나/스태미나 바 판독.

게임 하단 좌측의 세 가로 바(위→아래로 HP·MP·스태미나)를 감싸는 영역을 받아, 각 바의
**채움 비율(0~1)**을 돌려준다. (미러링이 아니라 값만 읽어 우리 오버레이로 새로 그린다.)

원리 — 바 '채움'과 '소모(빈 구간)'는 **같은 색조**지만 **밝기(V)가 다르다**(채움은 밝고
소모는 어둡다). 그래서 색조만으론 못 가르고, 각 바 띠에서 '그 색조에 해당하며 밝은'
픽셀이 가로로 어디까지 이어지는지(밝기 절벽)로 비율을 잰다. 숫자가 바 위에 겹쳐도,
숫자는 색조가 달라(흰색) 제외되므로 비율 측정에는 영향이 적다.

띠 이름은 **색조**로 정한다(0.49.0, 하늘색 인터페이스 — 사용자 제보 11-14): HP ~163(분홍), MP ~114(파랑),
스태미나 ~23(노랑)에 가장 가까운 것, 어느 바에도 안 맞는 띠(인터페이스 테두리·경험치 바 등)는 버린다.
예전엔 위→아래 순서로 붙였는데, 테두리가 띠 하나로 잡히면 배정이 한 칸씩 밀렸다.
MP는 **채도 110 이상**만 바로 인정한다 — 하늘색 인터페이스 테두리(H 92~99·S 89~100·밝음)가 MP 색조 허용을 통과해
MP를 100%로 읽혔다. 기존 스크린샷 114장의 MP 바는 H 114·S 127~128로 일정하다.
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
_ROW_RATIO_STRICT = 0.15
# 같은 바 색조면 채도가 이만큼만 돼도 바로 이어 본다(흐린 화면에서 숫자 글자가 번져 채도가 떨어진 부분 — 행 판정·가로 범위)
_RELAX_SAT = 30
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
# 바마다 색조 중심 ±_BAR_HUE_TOL + 채도 하한(0.49.1 — 인터페이스 색별 테두리 제외, 사용자 제보 11-14·15).
# 기존 118장 실측: HP H163~167·S126~176, MP H113~114·S125~132, STA H22~23·S179~220.
# 테두리: 하늘 H92~99·S89~100, 빨강 H1~2·S145~154, 노랑 H21~25·S103~114, 베이지 H15~18·S33~93 — 모두 어느 바에도 안 맞음.
_BAR_HUE = {"hp": 165, "mp": 114, "sta": 23}  # 채움 색 중심(띠 이름·그리기용 대표)
_BAR_HUE_TOL = 8
_BAR_SAT_MIN = {"hp": 110, "mp": 110, "sta": 140}
_MP_SAT_MIN = _BAR_SAT_MIN["mp"]
# 바마다 인정하는 색 (색조 중심, 채도 하한) — 채움 색 + 소모(빈 부분) 색(0.49.1 QA 5ece564: 마나 덜 찬 화면에서 MP 띠를 못 찾음).
# 소모 실측: HP H171·S178·V119(채움 ±8 안), MP H126·S170·V78(남색 — 채움 114 ±8 밖이라 따로), STA 소모는 아직 자료 없음.
_DEPLETED_HUE = {"hp": 171, "mp": 126}  # 소모 색조(STA는 자료 대기 — 사용자에게 스태미나 덜 찬 스크린샷 요청 중)
_DEPLETED_SAT_MIN = 140
_BAR_COLOURS = {k: ((_BAR_HUE[k], _BAR_SAT_MIN[k]),) + (((_DEPLETED_HUE[k], _DEPLETED_SAT_MIN),) if k in _DEPLETED_HUE else ())
                for k in _BAR_HUE}


def _bar_mask(h, s, stat: str, slack: int = 0) -> np.ndarray:
    """그 바의 채움·소모 색(각 색조 ±_BAR_HUE_TOL·채도 하한 − slack) 픽셀."""
    hh = h.astype(int)
    out = np.zeros(hh.shape, dtype=bool)
    for c, sat in _BAR_COLOURS[stat]:
        d = np.abs(hh - c)
        d = np.minimum(d, 180 - d)
        out |= (d <= _BAR_HUE_TOL) & (s >= sat - slack)
    return out


def _bar_pixels(h, s, v, sat_min: int = _SAT_MIN) -> np.ndarray:
    """바로 볼 유채색 픽셀 — 세 바 중 하나의 색조·채도에 맞는 것만(인터페이스 테두리 제외). sat_min은 예전 인자 호환."""
    any_bar = _bar_mask(h, s, "hp") | _bar_mask(h, s, "mp") | _bar_mask(h, s, "sta")
    return any_bar & (v > _V_MIN)


def _stat_of(hue: int) -> str | None:
    """띠 대표 색조 → 바 이름(채움·소모 색 중 가장 가까운 것, ±_BAR_HUE_TOL 밖이면 None)."""
    dist, best = min((_hue_dist(hue, c), k) for k, cs in _BAR_COLOURS.items() for c, _ in cs)
    return best if dist <= _BAR_HUE_TOL else None


def _stat_dist(hue: int, stat: str) -> int:
    return min(_hue_dist(hue, c) for c, _ in _BAR_COLOURS[stat])


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
    """
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    hue, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    colored = _bar_pixels(hue, s, v)
    # 흐린 화면(195115): 숫자 글자가 번져 바 왼쪽 채도가 떨어지면 확실한 픽셀만으론 한 행의 30%가 안 된다 →
    # 확실한 픽셀이 _ROW_RATIO_STRICT 이상이고 '같은 바 색조·낮은 채도'까지 치면 _ROW_RATIO를 넘어도 바 행.
    # 인터페이스 테두리 행은 확실한 픽셀이 거의 없어(채도 하한 미달) 여기 안 걸린다.
    hh = hue.astype(int)
    relaxed = np.zeros(hh.shape, dtype=bool)
    for cs in _BAR_COLOURS.values():
        for c, _ in cs:
            d = np.abs(hh - c)
            relaxed |= np.minimum(d, 180 - d) <= _BAR_HUE_TOL
    relaxed = (relaxed & (s >= _RELAX_SAT) & (v > _V_MIN)) | colored
    strict_ratio = colored.mean(axis=1)
    barrow = (strict_ratio > _ROW_RATIO) | ((strict_ratio > _ROW_RATIO_STRICT) & (relaxed.mean(axis=1) > _ROW_RATIO))
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


_MIN_BAR_WIDTH = 40


def _band_span(region: np.ndarray, r0: int, r1: int) -> tuple[str, int, int] | None:
    """한 띠의 (바 이름, 왼쪽, 오른쪽) — 채움·소모를 합친 가로 범위. 바 색이 아니면 None."""
    hsv = cv2.cvtColor(region[r0:r1], cv2.COLOR_BGR2HSV)
    bh, bs, bv = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2]
    colored = _bar_pixels(bh, bs, bv)
    if not colored.any():
        return None
    hue = int(np.median(bh[colored]))
    stat = _stat_of(hue)
    if stat is None:
        return None
    span = _span(bh, bs, bv, stat, hue)
    return None if span is None else (stat, span[0], span[1])


_RUN_GAP = 3


def _span(bh, bs, bv, stat: str, hue: int) -> tuple[int, int] | None:
    """띠의 가로 범위(왼쪽, 오른쪽). ① 확실한 픽셀(띠 색조 ±_HUE_TOL·그 바 채도 하한)의 가장 긴 연속 구간 —
    바 옆 테두리 이음새(빨강 H177~179 등)가 떨어져 붙어도 안 넣는다. ② 그 구간에서 양옆으로 '그 바 색(채움·소모) ±_BAR_HUE_TOL,
    채도 _RELAX_SAT 이상'인 열이 이어지는 만큼 넓힌다 — 흐린 화면(195115)에서 글자 번짐으로 채도가 낮아진 바 왼쪽."""
    strict = ((np.abs(bh - hue) <= _HUE_TOL) & (bs >= _BAR_SAT_MIN[stat])).any(axis=0)
    cols = np.where(strict)[0]
    if not cols.size:
        return None
    runs = np.split(cols, np.where(np.diff(cols) > _RUN_GAP)[0] + 1)
    best = max(runs, key=lambda r: (r[-1] - r[0], r.size))
    left, right = int(best[0]), int(best[-1])
    relaxed = np.zeros(bh.shape, dtype=bool)
    for c, _ in _BAR_COLOURS[stat]:
        d = np.abs(bh - c)
        relaxed |= np.minimum(d, 180 - d) <= _BAR_HUE_TOL
    # 바 열은 위아래로 차 있다 — 띠 높이의 1/3 이상이 그 색이어야(흐린 테두리 가장자리 번짐은 몇 행뿐)
    rcol = (relaxed & (bs >= _RELAX_SAT) & (bv > _V_MIN)).sum(axis=0) * 3 >= bh.shape[0]
    rcol |= strict
    n = rcol.size
    while left > 0 and rcol[max(0, left - 1 - _RUN_GAP):left].any():
        left = max(0, left - 1 - _RUN_GAP) + int(np.argmax(rcol[max(0, left - 1 - _RUN_GAP):left]))
    while right < n - 1 and rcol[right + 1:right + 2 + _RUN_GAP].any():
        right = right + 1 + int(np.where(rcol[right + 1:right + 2 + _RUN_GAP])[0][-1])
    return left, right


def _refine(frame: np.ndarray, box) -> tuple[int, int, int, int] | None:
    """후보 사각형 → 세 바 띠만 딱 감싸는 사각형(0.49.1). 좌우는 세 바 범위의 가운데 값 — 바 옆 인터페이스 장식(바와 같은 색)이
    한 바에만 붙어 넓어져도 끌려가지 않는다. 세 바(HP·MP·STA)가 다 없으면 None."""
    H, W = frame.shape[:2]
    x, y, w, h = (int(v) for v in box)
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w < 20 or h < 6:
        return None
    region = frame[y:y + h, x:x + w]
    found = {}
    for r0, r1 in _bands(region):
        got = _band_span(region, r0, r1)
        if got is not None and got[0] not in found:
            found[got[0]] = (r0, r1, got[1], got[2])
    if len(found) != 3:
        return None
    tops = [v[0] for v in found.values()]
    bottoms = [v[1] for v in found.values()]
    left = int(np.median([v[2] for v in found.values()]))
    right = int(np.median([v[3] for v in found.values()]))
    if right - left < _MIN_BAR_WIDTH:  # 체력바는 해상도와 무관하게 약 100px — 아이콘 속 작은 색 띠 오탐 제외
        return None
    return (x + left, y + min(tops), right - left + 1, max(bottoms) - min(tops))


def _ratio(region: np.ndarray, r0: int, r1: int) -> tuple[float, int]:
    """한 띠(r0:r1)의 채움 비율과 대표 색조."""
    band = region[r0:r1]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    bh, bs, bv = hsv[:, :, 0].astype(int), hsv[:, :, 1].astype(int), hsv[:, :, 2]
    colored = _bar_pixels(bh, bs, bv)
    if not colored.any():
        return 0.0, -1
    hue = int(np.median(bh[colored]))
    # 그 색조에 해당하는(채움/소모 둘 다) 픽셀 → 바의 가로 범위. MP는 테두리(채도 ≤ 100)를 빼고.
    # 채움/소모의 가로 범위는 그 띠 색조 ±_HUE_TOL(소모 쪽은 색조가 조금 다름 — MP 소모 H126) + 그 바의 채도 하한(테두리 제외).
    stat = _stat_of(hue)
    sat_floor = _BAR_SAT_MIN[stat] if stat is not None else _SAT_MIN - 10
    huematch = (np.abs(bh - hue) <= _HUE_TOL) & (bs >= sat_floor)
    cols = np.where(huematch.any(axis=0))[0]
    if cols.size == 0:
        return 0.0, hue
    left, right = int(cols.min()), int(cols.max())
    span = right - left + 1
    if span <= 1:
        return 0.0, hue
    # 각 열에서 '그 색조 + 밝음' 픽셀의 최대 V → 채움 열 판정(소모 구간은 어두워 탈락).
    colmax = np.where(huematch, bv, 0).max(axis=0)
    fill_cols = colmax >= _FILL_V
    if stat in _DEPLETED_HUE:
        # 채움·소모 색조가 다른 바(HP 165↔171, MP 114↔126)는 색조로도 가른다 — 바 위에 반투명 어두운 것이 덮여
        # 채움이 어두워진 화면(001541: MP 채움 H114·V68)에서 밝기만으론 채움이 짧게 읽혔다.
        df = np.abs(bh - _BAR_HUE[stat])
        df = np.minimum(df, 180 - df)
        dd = np.abs(bh - _DEPLETED_HUE[stat])
        dd = np.minimum(dd, 180 - dd)
        # 열마다 채움 색 픽셀이 소모 색 픽셀보다 많고 띠 높이의 1/4 이상이어야 채움 — 흰 숫자 글자는 어느 쪽도 아니라 빠지고,
        # 소모 구간 위 글자 둘레 번짐(200614: 남색 바탕에 H117 몇 픽셀)은 소모 색이 더 많아 채움으로 안 친다.
        fillpix = (bs >= _BAR_SAT_MIN[stat]) & (df <= _BAR_HUE_TOL) & (df < dd)
        deplpix = (bs >= _DEPLETED_SAT_MIN) & (dd <= _BAR_HUE_TOL) & (dd < df)
        nf, nd = fillpix.sum(axis=0), deplpix.sum(axis=0)
        hue_cols = np.where((nf * 4 >= (r1 - r0)) & (nf > nd))[0]
        hue_cols = hue_cols[hue_cols >= left]
        # 채움은 바 왼쪽 끝부터 이어진다 — 왼쪽에 붙은 구간만(글자 획 틈 _RUN_GAP까지). 바 오른쪽 끝 둥근 캡(H119·S130)은 안 침.
        if hue_cols.size and hue_cols[0] - left <= _RUN_GAP:
            run = np.split(hue_cols, np.where(np.diff(hue_cols) > _RUN_GAP)[0] + 1)[0]
            fill_cols[run] = True
    filled = np.where(fill_cols)[0]
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
_LOC_HUE = {k: (_BAR_HUE[k] - _BAR_HUE_TOL, _BAR_HUE[k] + _BAR_HUE_TOL) for k in _BAR_HUE}  # OpenCV H(0~180) — 읽기와 같은 기준
_LOC_SAT_MIN = 90
_LOC_SAT = dict(_BAR_SAT_MIN)  # 바마다 채도 하한(인터페이스 테두리가 바에 붙어 한 덩어리가 되던 것)
_LOC_VAL_MIN = 90
# 체력바는 게임 화면 '하단'에 붙어 있다. 프레임 위쪽(상단 스킬바·버프 아이콘 줄)에서 파랑/
# 노랑 아이콘이 MP/STA 쌍처럼 잡혀 엉뚱한 곳(예: (765,36))을 체력바로 오검출하던 것을 막기
# 위해, 바 후보를 프레임 하단 구역(top ≥ H×_LOC_BOTTOM_FRAC)으로만 제한한다.
_LOC_BOTTOM_FRAC = 0.5


def _color_bars(
    hsv: np.ndarray, lo: int, hi: int, min_w: int, close_w: int, max_h: int, sat_min: int = _LOC_SAT_MIN
) -> list[tuple[int, int, int, int]]:
    """주어진 색조대의 '가로로 긴 바' 블롭들(x,y,w,h). 숫자로 끊긴 색은 가로로 이어붙인다."""
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    mask = (h >= lo) & (h <= hi) & (s > sat_min) & (v > _LOC_VAL_MIN)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (close_w, 1))
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, hh, _ = stats[i]
        if w >= min_w and 2 <= hh <= max_h and w > hh * 1.8:
            out.append((int(x), int(y), int(w), int(hh)))
    return out


def locate_stat_bars(frame: np.ndarray, *, diagnostics: dict | None = None) -> tuple[int, int, int, int] | None:
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
    y_min = int(H * _LOC_BOTTOM_FRAC)  # 하단 구역만(상단 스킬바 아이콘 오검출 방지)
    mps = [b for b in _color_bars(hsv, *_LOC_HUE["mp"], min_w, close_w, max_h, _LOC_SAT["mp"]) if b[1] >= y_min]
    stas = [b for b in _color_bars(hsv, *_LOC_HUE["sta"], min_w, close_w, max_h, _LOC_SAT["sta"]) if b[1] >= y_min]
    if diagnostics is not None:
        diagnostics.update(transforms=["BGR to HSV", "hue mask", "horizontal morphology close", "connected components"],
                           search_region=[0, y_min, W, H - y_min],
                           thresholds={"hue": _LOC_HUE, "saturation_min": _LOC_SAT_MIN, "bar_saturation_min": _LOC_SAT,
                                       "value_min": _LOC_VAL_MIN, "min_width": min_w,
                                       "close_width": close_w, "max_height": max_h},
                           mp_candidates=mps, sta_candidates=stas, rejection="no_matching_stack")
    candidates: list[tuple[int, int, int, int]] = []
    for bx, by, bw, bh in mps:  # MP(파랑) 위
        for cx, cy, cw, ch in stas:  # STA(노랑) 아래
            gap = cy - by
            if abs(bx - cx) > max(20, int(W * 0.01)) or not (0 < gap < max_h + 20):
                continue
            x = min(bx, cx)
            top = max(0, by - gap)  # HP는 MP 한 피치 위
            candidates.append((x, top, max(bx + bw, cx + cw) - x, cy + ch - top))
    # 0.49.1: MP 바 둘레 창도 후보로 — 인터페이스 장식(바와 같은 색)이 STA·HP 쪽에 붙어 짝이 안 맞는 화면(빨강·노랑)
    for bx, by, bw, bh in mps:
        pad = max(4, bw // 4)
        candidates.append((bx - pad, by - 2 * bh - 8, bw + 2 * pad, 5 * bh + 16))
    # 대신 HP(분홍)·STA(노랑) 쌍으로(0.49.0): 하늘색 인터페이스에선 MP 바가 주변 파란 테두리와 붙어 한 덩어리가 돼
    # MP 후보로 안 잡힌다. HP 위·STA 아래(MP 한 칸 사이)면 그 사이가 MP.
    hps = [b for b in _color_bars(hsv, *_LOC_HUE["hp"], min_w, close_w, max_h, _LOC_SAT["hp"]) if b[1] >= y_min]
    if diagnostics is not None:
        diagnostics["hp_candidates"] = hps
    for ax, ay, aw, ah in hps:
        for cx, cy, cw, ch in stas:
            gap = cy - ay
            if abs(ax - cx) > max(20, int(W * 0.01)) or not (ah < gap < 2 * (max_h + 20)):
                continue
            x = min(ax, cx)
            candidates.append((x, ay, max(ax + aw, cx + cw) - x, cy + ch - ay))
    if not candidates:
        return None
    # 검증: 세 바만 딱 감싸게 다듬은 사각형에서 실제로 3개 바를 읽어야 진짜 체력바(디버프 아이콘 줄 오탐 제거).
    # 여럿이면 맨 아래(게임 원본 바는 하단 메뉴바에 붙어 있다).
    best = None
    for cand in candidates:
        box = _refine(frame, cand)
        if box is None or box[1] + box[3] // 2 < y_min:  # 가운데(MP 줄)가 하단 구역 — HP 줄은 경계 위에 걸쳐도 된다
            continue
        bx, by, bw, bh = box
        if len(read_stat_bars(frame[by:by + bh, bx:bx + bw], require_complete=True)) < 3:
            continue
        # 맨 아래 우선, 높이가 거의 같으면(±4px) 넓은 쪽 — 짧은 MP 덩어리 둘레 창이 바를 잘라 만든 좁은 사각형보다 HP·STA 쌍 쪽(195115)
        if best is None or box[1] > best[1] + 4 or (abs(box[1] - best[1]) <= 4 and box[2] > best[2]):
            best = box
    if best is None:
        if diagnostics is not None:
            diagnostics["rejection"] = "fewer_than_three_readable_bars"
        return None
    if diagnostics is not None:
        diagnostics["rejection"] = None
    return best


def read_stat_bars(region: np.ndarray, *, require_complete: bool = False) -> list[StatReading]:
    """영역(BGR)에서 띠를 찾아 색조로 이름을 붙여 [HP, MP, STA] 순(찾은 것만) 반환.

    어느 바 색조에도 안 맞는 띠(인터페이스 테두리·경험치 바 등)는 버리고, 같은 바로 보이는 띠가 둘이면 기준 색조에 더
    가까운 것. 표시/알림/자동찾기는 require_complete=True로 세 바가 모두 있을 때만 쓴다.
    """
    if region is None or region.shape[0] < 6 or region.shape[1] < 20:
        return []
    found: dict[str, tuple[int, StatReading]] = {}
    duplicate = False
    for r0, r1 in _bands(region):
        ratio, hue = _ratio(region, r0, r1)
        stat = _stat_of(hue) if hue >= 0 else None
        if stat is None:
            continue
        dist = _stat_dist(hue, stat)
        duplicate = duplicate or stat in found
        if stat not in found or dist < found[stat][0]:
            found[stat] = (dist, StatReading(stat, ratio, hue))
    if require_complete and (len(found) != 3 or duplicate):
        return []  # 같은 바 색 띠가 둘이면 어느 쪽이 진짜인지 모름 — 표시·알림엔 쓰지 않는다
    return [found[k][1] for k in STAT_IDS if k in found]
